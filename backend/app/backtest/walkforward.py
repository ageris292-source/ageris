"""Walk-forward training with purging, embargo and isotonic calibration
(spec §22-§26). Pure functions over a pooled dataset: rows = (date, ticker).

Leakage controls:
- A training row is used for a test fold only if its label window ENDS
  before the fold starts minus the embargo (purging overlapping labels).
- Calibration data is the most recent slice of the training window, and the
  model fit on the earlier part is purged against it the same way.
- Features are point-in-time by construction (see features.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from app.backtest.features import FEATURES
from app.core.config_file import BacktestRules

TARGETS = ("y_profit", "y_outperform")


class InsufficientDataError(ValueError):
    pass


@dataclass
class CalibratedModel:
    booster: lgb.Booster
    iso_x: list[float]
    iso_y: list[float]

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        raw = self.booster.predict(x[FEATURES].to_numpy(dtype=float))
        return np.clip(np.interp(raw, self.iso_x, self.iso_y), 0.0, 1.0)

    def dump(self) -> dict[str, Any]:
        return {"booster": self.booster.model_to_string(), "iso_x": self.iso_x, "iso_y": self.iso_y}

    @classmethod
    def load(cls, d: dict[str, Any]) -> CalibratedModel:
        return cls(lgb.Booster(model_str=d["booster"]), list(d["iso_x"]), list(d["iso_y"]))


def _params(rules: BacktestRules) -> dict[str, Any]:
    p = rules.lightgbm
    return {
        "objective": "binary",
        "learning_rate": p.learning_rate,
        "num_leaves": p.num_leaves,
        "min_child_samples": p.min_child_samples,
        "subsample": p.subsample,
        "subsample_freq": 1,
        "colsample_bytree": p.colsample_bytree,
        "reg_lambda": p.reg_lambda,
        "seed": rules.seed,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 1,
        "verbosity": -1,
    }


def fit_calibrated(train: pd.DataFrame, target: str, rules: BacktestRules) -> CalibratedModel:
    """Fit on the older part of `train`, calibrate on the newest slice."""
    dates = np.sort(train["date"].unique())
    cut = dates[int(len(dates) * (1 - rules.calibration_fraction))]
    calib = train[train["date"] >= cut]
    fit = train[(train["label_end_date"] < cut)]
    if len(fit) < rules.min_train_samples // 2 or len(calib) < 50:
        raise InsufficientDataError(f"too few rows to fit/calibrate ({len(fit)}/{len(calib)})")
    if fit[target].nunique() < 2 or calib[target].nunique() < 2:
        raise InsufficientDataError("a training slice contains a single class")
    ds = lgb.Dataset(fit[FEATURES].to_numpy(dtype=float), label=fit[target].to_numpy())
    booster = lgb.train(_params(rules), ds, num_boost_round=rules.lightgbm.n_estimators)
    raw = booster.predict(calib[FEATURES].to_numpy(dtype=float))
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
    iso.fit(raw, calib[target].to_numpy())
    return CalibratedModel(
        booster, [float(v) for v in iso.X_thresholds_], [float(v) for v in iso.y_thresholds_]
    )


def ece(p: np.ndarray, y: np.ndarray, bins: int) -> float:
    """Expected calibration error with equal-width bins."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
    return float(total)


def calibration_curve(p: np.ndarray, y: np.ndarray, bins: int) -> list[dict[str, float]]:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append(
                {
                    "bin_low": float(edges[b]),
                    "bin_high": float(edges[b + 1]),
                    "mean_predicted": float(p[m].mean()),
                    "observed_rate": float(y[m].mean()),
                    "count": int(m.sum()),
                }
            )
    return out


def metrics(p: np.ndarray, y: np.ndarray, bins: int) -> dict[str, float | None]:
    both = len(np.unique(y)) == 2
    return {
        "n": float(len(y)),
        "base_rate": float(y.mean()) if len(y) else None,
        "auc": float(roc_auc_score(y, p)) if both else None,
        "brier": float(brier_score_loss(y, p)) if len(y) else None,
        "log_loss": float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1]))
        if len(y)
        else None,
        "ece": ece(p, y, bins) if len(y) else None,
    }


@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame  # OOS rows with p_profit, p_outperform, fold
    folds: list[dict[str, Any]] = field(default_factory=list)
    skipped_folds: list[dict[str, Any]] = field(default_factory=list)


def walk_forward(data: pd.DataFrame, rules: BacktestRules) -> WalkForwardResult:
    """`data`: labelled rows with columns date, ticker, FEATURES, y_*,
    fwd_return, bench_fwd_return, label_end_date."""
    labelled = data.dropna(subset=[*FEATURES, *TARGETS]).sort_values(["date", "ticker"])
    dates = np.sort(labelled["date"].unique())
    if len(dates) <= rules.min_train_sessions + rules.test_fold_sessions:
        raise InsufficientDataError(
            f"{len(dates)} labelled sessions; need more than "
            f"{rules.min_train_sessions + rules.test_fold_sessions}"
        )
    preds: list[pd.DataFrame] = []
    res = WalkForwardResult(pd.DataFrame())
    for k, start in enumerate(
        range(rules.min_train_sessions, len(dates), rules.test_fold_sessions)
    ):
        test_dates = dates[start : start + rules.test_fold_sessions]
        t0 = test_dates[0]
        emb = dates[max(0, start - rules.embargo_sessions)]
        train = labelled[(labelled["label_end_date"] < emb)]
        test = labelled[labelled["date"].isin(test_dates)]
        info: dict[str, Any] = {
            "fold": k,
            "test_start": str(pd.Timestamp(t0).date()),
            "test_end": str(pd.Timestamp(test_dates[-1]).date()),
            "train_rows": len(train),
            "test_rows": len(test),
            "train_last_label_end": str(pd.Timestamp(train["label_end_date"].max()).date())
            if len(train)
            else None,
        }
        if len(train) < rules.min_train_samples:
            res.skipped_folds.append({**info, "reason": "too few training rows"})
            continue
        try:
            models = {t: fit_calibrated(train, t, rules) for t in TARGETS}
        except InsufficientDataError as exc:
            res.skipped_folds.append({**info, "reason": str(exc)})
            continue
        out = test[["date", "ticker", "fwd_return", "bench_fwd_return", *TARGETS]].copy()
        out["p_profit"] = models["y_profit"].predict(test)
        out["p_outperform"] = models["y_outperform"].predict(test)
        out["fold"] = k
        preds.append(out)
        info["profit"] = metrics(
            out["p_profit"].to_numpy(), out["y_profit"].to_numpy(), rules.calibration_bins
        )
        info["outperform"] = metrics(
            out["p_outperform"].to_numpy(), out["y_outperform"].to_numpy(), rules.calibration_bins
        )
        res.folds.append(info)
    if not preds:
        raise InsufficientDataError("no walk-forward fold could be trained")
    res.predictions = pd.concat(preds, ignore_index=True)
    return res


def expected_return_map(
    pred: pd.DataFrame, bins: int, min_count: int = 30
) -> list[dict[str, float]]:
    """Mean realised forward (gross) return per p_profit bin, out of sample.
    Bins with fewer than `min_count` rows are omitted (no estimate there)."""
    edges = np.linspace(0, 1, bins + 1)
    p = pred["p_profit"].to_numpy()
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.sum() >= min_count:
            out.append(
                {
                    "bin_low": float(edges[b]),
                    "bin_high": float(edges[b + 1]),
                    "mean_forward_return": float(pred["fwd_return"].to_numpy()[m].mean()),
                    "count": int(m.sum()),
                }
            )
    return out


def lookup_expected(mapping: list[dict[str, float]], p: float) -> float | None:
    for b in mapping:
        if b["bin_low"] <= p < b["bin_high"] or (p == 1.0 and b["bin_high"] == 1.0):
            return b["mean_forward_return"]
    return None


def last_date(d: pd.Series) -> date:
    return pd.Timestamp(d.max()).date()
