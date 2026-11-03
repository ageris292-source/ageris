"""Does the model know anything? Baselines, skill scores and validation (audit P1).

A calibrated model can still be useless: if it predicts every stock's base
rate it is perfectly calibrated and has no edge. This module measures the
model against simple baselines on the SAME out-of-sample rows, with
uncertainty, per fold and per market regime, and turns that into an explicit
pass/fail validation that decides whether a model may ever be activated.

Baselines (each fitted on the fold's training rows only, point in time):

* base rate  - always predict the training base rate (no information at all);
* momentum   - logistic regression on the 60-session return alone;
* logistic   - logistic regression on all features (a simple linear model).

Skill is the Brier skill score, 1 - Brier(model) / Brier(baseline): 0 means no
better than the baseline, above 0 means better. Confidence intervals use a
moving-block bootstrap over test dates (blocks of `horizon` sessions), because
overlapping forward labels make neighbouring rows dependent.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.backtest.features import FEATURES

BASELINES = ("base_rate", "momentum", "logistic")
MOMENTUM_FEATURE = "ret_60"
VALIDATION_VERSION = "skill-validation-1"


# ------------------------------------------------------------- baselines --


def fit_baselines(train: pd.DataFrame, test: pd.DataFrame, target: str) -> dict[str, np.ndarray]:
    """Out-of-sample baseline probabilities for `test`, fitted on `train` only."""
    y = train[target].to_numpy().astype(int)
    rate = float(y.mean()) if len(y) else 0.5
    out: dict[str, np.ndarray] = {"base_rate": np.full(len(test), rate)}
    if len(np.unique(y)) < 2:  # nothing to learn: every baseline is the base rate
        out["momentum"] = out["base_rate"].copy()
        out["logistic"] = out["base_rate"].copy()
        return out
    mom = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    mom.fit(train[[MOMENTUM_FEATURE]], y)
    out["momentum"] = mom.predict_proba(test[[MOMENTUM_FEATURE]])[:, 1]
    logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
    logit.fit(train[FEATURES], y)
    out["logistic"] = logit.predict_proba(test[FEATURES])[:, 1]
    return out


# --------------------------------------------------------------- metrics --


def _brier(p: np.ndarray, y: np.ndarray) -> float | None:
    return float(brier_score_loss(y, p)) if len(y) else None


def _auc(p: np.ndarray, y: np.ndarray) -> float | None:
    return float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None


def brier_skill(p: np.ndarray, ref: np.ndarray, y: np.ndarray) -> float | None:
    b_ref = _brier(ref, y)
    b = _brier(p, y)
    if b is None or b_ref is None or b_ref <= 0:
        return None
    return 1.0 - b / b_ref


def _block_indices(
    uniq: np.ndarray, rows: dict[Any, np.ndarray], block: int, rng: np.random.Generator
) -> np.ndarray:
    """Row indices of one moving-block bootstrap resample over unique dates."""
    n = len(uniq)
    block = max(1, min(block, n))
    starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
    chosen = np.concatenate([uniq[s : s + block] for s in starts])[:n]
    return np.concatenate([rows[d] for d in chosen])


def bootstrap_ci(
    pred: pd.DataFrame,
    p_col: str,
    ref_col: str,
    y_col: str,
    block: int,
    samples: int,
    seed: int,
    level: float = 0.90,
) -> dict[str, list[float] | None]:
    """Moving-block bootstrap CIs for AUC and Brier skill vs `ref_col`."""
    rng = np.random.default_rng(seed)
    dates = pred["date"].to_numpy()
    p = pred[p_col].to_numpy()
    ref = pred[ref_col].to_numpy()
    y = pred[y_col].to_numpy().astype(int)
    uniq = np.unique(dates)
    rows = {d: np.flatnonzero(dates == d) for d in uniq}
    aucs: list[float] = []
    skills: list[float] = []
    for _ in range(samples):
        idx = _block_indices(uniq, rows, block, rng)
        a = _auc(p[idx], y[idx])
        s = brier_skill(p[idx], ref[idx], y[idx])
        if a is not None:
            aucs.append(a)
        if s is not None:
            skills.append(s)
    lo, hi = (1 - level) / 2 * 100, (1 + level) / 2 * 100

    def ci(v: list[float]) -> list[float] | None:
        if len(v) < samples // 2:
            return None
        return [float(np.percentile(v, lo)), float(np.percentile(v, hi))]

    return {"auc": ci(aucs), "brier_skill_vs_base_rate": ci(skills)}


def regime_of(pred: pd.DataFrame) -> np.ndarray:
    """Market regime known at each row's date: the benchmark's trailing
    20-session return (a feature, so point in time)."""
    return np.where(pred["bench_ret_20"].to_numpy() >= 0, "rising", "falling")


def evaluate_skill(
    pred: pd.DataFrame, horizon: int, samples: int, seed: int, target: str = "y_profit"
) -> dict[str, Any]:
    """Skill of the model's P(profit) against each baseline on OOS rows.

    `pred` holds, per OOS row: date, fold, the target, `p_profit`,
    `bench_ret_20` and one `b_<baseline>` column per baseline."""
    y = pred[target].to_numpy().astype(int)
    p = pred["p_profit"].to_numpy()
    model = {"brier": _brier(p, y), "auc": _auc(p, y)}
    baselines = {
        b: {
            "brier": _brier(pred[f"b_{b}"].to_numpy(), y),
            "auc": _auc(pred[f"b_{b}"].to_numpy(), y),
        }
        for b in BASELINES
    }
    skill = {b: brier_skill(p, pred[f"b_{b}"].to_numpy(), y) for b in BASELINES}
    folds: list[dict[str, Any]] = []
    for k, g in pred.groupby("fold"):
        gy = g[target].to_numpy().astype(int)
        gp = g["p_profit"].to_numpy()
        folds.append(
            {
                "fold": int(str(k)),
                "rows": len(g),
                "brier_skill": brier_skill(gp, g["b_base_rate"].to_numpy(), gy),
                "auc": _auc(gp, gy),
            }
        )
    scored = [f for f in folds if f["brier_skill"] is not None]
    positive = [f for f in scored if f["brier_skill"] > 0]
    worst = min(scored, key=lambda f: f["brier_skill"]) if scored else None
    regimes: dict[str, Any] = {}
    reg = regime_of(pred)
    for name in ("rising", "falling"):
        m = reg == name
        if m.sum() == 0:
            continue
        ry = y[m]
        regimes[name] = {
            "rows": int(m.sum()),
            "brier_skill": brier_skill(p[m], pred["b_base_rate"].to_numpy()[m], ry),
            "auc": _auc(p[m], ry),
        }
    return {
        "version": VALIDATION_VERSION,
        "target": target,
        "rows": len(pred),
        "model": model,
        "baselines": baselines,
        "brier_skill": {f"vs_{b}": skill[b] for b in BASELINES},
        "ci": bootstrap_ci(pred, "p_profit", "b_base_rate", target, horizon, samples, seed),
        "ci_level": 0.90,
        "bootstrap": {"samples": samples, "block_sessions": horizon, "seed": seed},
        "folds": folds,
        "fold_skill_share": len(positive) / len(scored) if scored else None,
        "worst_fold": worst,
        "regimes": regimes,
    }


# ------------------------------------------------------------ validation --


def validate(
    skill: dict[str, Any] | None,
    *,
    calibration_error: float,
    max_calibration_error: float,
    oos_periods: int,
    min_oos_periods: int,
    survivorship_bias: str,
    min_brier_skill_lower: float,
    min_auc_lower: float,
    min_fold_skill_share: float,
) -> dict[str, Any]:
    """Every activation requirement as a named check. `passed` only if all
    pass; `overridable` lists the checks an admin may waive with a reason
    (only survivorship, which no amount of modelling can fix)."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool | None, value: Any, need: Any, text: str) -> None:
        checks.append(
            {
                "name": name,
                "status": "PASS" if ok else ("UNKNOWN" if ok is None else "FAIL"),
                "value": value,
                "threshold": need,
                "reason": text,
            }
        )

    if skill is None:
        add("skill_measured", None, None, "measured", "Skill against baselines was not measured")
    else:
        lo = (skill.get("ci") or {}).get("brier_skill_vs_base_rate")
        add(
            "beats_base_rate",
            None if lo is None else lo[0] > min_brier_skill_lower,
            None if lo is None else round(lo[0], 4),
            min_brier_skill_lower,
            "Lower 90% bound of Brier skill vs always-predict-the-base-rate"
            + ("" if lo is None else f": {lo[0]:+.3f}"),
        )
        alo = (skill.get("ci") or {}).get("auc")
        add(
            "ranks_better_than_chance",
            None if alo is None else alo[0] > min_auc_lower,
            None if alo is None else round(alo[0], 4),
            min_auc_lower,
            "Lower 90% bound of AUC" + ("" if alo is None else f": {alo[0]:.3f}"),
        )
        share = skill.get("fold_skill_share")
        add(
            "stable_across_folds",
            None if share is None else share >= min_fold_skill_share,
            share,
            min_fold_skill_share,
            "Share of walk-forward folds with positive skill"
            + ("" if share is None else f": {share:.0%}"),
        )
    add(
        "calibrated",
        calibration_error <= max_calibration_error,
        calibration_error,
        max_calibration_error,
        f"Out-of-sample calibration error {calibration_error:.3f}",
    )
    add(
        "enough_out_of_sample",
        oos_periods >= min_oos_periods,
        oos_periods,
        min_oos_periods,
        f"{oos_periods} out-of-sample folds",
    )
    add(
        "survivorship",
        survivorship_bias != "HIGH",
        survivorship_bias,
        "LOW/MEDIUM",
        "Universe excludes delisted stocks (results look better than reality)"
        if survivorship_bias == "HIGH"
        else "Point-in-time universe",
    )
    failed = [c["name"] for c in checks if c["status"] != "PASS"]
    return {
        "version": VALIDATION_VERSION,
        "passed": not failed,
        "failed": failed,
        "overridable": ["survivorship"],
        "checks": checks,
    }


def activation_allowed(validation: dict[str, Any] | None, override_reason: str | None) -> bool:
    """True if the model passed validation, or failed only overridable checks
    and an override reason is given."""
    if not validation:
        return False
    failed = set(validation.get("failed", []))
    if not failed:
        return True
    return bool(override_reason) and failed <= set(validation.get("overridable", []))
