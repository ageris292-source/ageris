"""Configuration must be validated strictly at startup (spec §73)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config_file import ConfigError, load_config

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config" / "aegis.yaml"


def _base() -> dict[str, Any]:
    return yaml.safe_load(REPO_CONFIG.read_text())


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    p = tmp_path / "aegis.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_repository_config_is_valid() -> None:
    cfg = load_config(REPO_CONFIG)
    assert cfg.trade_gates.minimum_probability_of_profit == 0.65
    assert cfg.trade_gates.minimum_reward_risk_ratio == 2.0
    assert "NSE_EQ_DELIVERY" in cfg.transaction_costs


def test_fingerprint_is_stable_and_sensitive(tmp_path: Path) -> None:
    a = load_config(REPO_CONFIG).fingerprint()
    assert a == load_config(REPO_CONFIG).fingerprint()
    data = _base()
    data["trade_gates"]["minimum_reward_risk_ratio"] = 2.5
    assert load_config(_write(tmp_path, data)).fingerprint() != a


def test_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("trade_gates: [unclosed")
    with pytest.raises(ConfigError):
        load_config(p)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("trade_gates", "minimum_probability_of_profit", 0.4),  # below coin-flip
        ("trade_gates", "minimum_probability_of_profit", 1.0),
        ("trade_gates", "minimum_expected_net_return", 0.0),
        ("trade_gates", "minimum_expected_net_return", -0.01),
        ("trade_gates", "minimum_reward_risk_ratio", 0.5),
        ("position_sizing", "kelly_fraction_cap", 1.0),  # unrestricted Kelly forbidden
        ("position_sizing", "risk_per_trade", 0.10),
        ("risk_controls", "max_gross_exposure", 2.0),  # leverage not allowed
        ("execution", "require_human_approval_for_live", False),
        ("freshness", "prices_seconds", 0),
    ],
)
def test_out_of_range_values_rejected(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    data = _base()
    data[section][key] = value
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, data))


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    data = _base()
    data["trade_gates"]["minimum_probabilty_of_profit"] = 0.7  # typo must not be ignored
    with pytest.raises(ConfigError, match="Extra inputs"):
        load_config(_write(tmp_path, data))


def test_missing_section_rejected(tmp_path: Path) -> None:
    data = _base()
    del data["risk_controls"]
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, data))


def test_loss_limits_must_be_nested(tmp_path: Path) -> None:
    data = copy.deepcopy(_base())
    data["risk_controls"]["daily_loss_limit"] = 0.08  # > weekly 0.05
    with pytest.raises(ConfigError, match="daily <= weekly"):
        load_config(_write(tmp_path, data))


def test_position_weight_cannot_exceed_sector_weight(tmp_path: Path) -> None:
    data = _base()
    data["risk_controls"]["max_single_position_weight"] = 0.5
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, data))


def test_empty_cost_schedules_rejected(tmp_path: Path) -> None:
    data = _base()
    data["transaction_costs"] = {}
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, data))
