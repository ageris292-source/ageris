"""System operating modes (spec §5)."""

from enum import StrEnum
from typing import Final

# Build-level switch (spec §5, §32). This build ships NO live broker adapter:
# live orders are impossible whatever the environment says. Enabling live
# trading requires a code change, a real adapter and a new review — never
# configuration alone.
LIVE_TRADING_AVAILABLE: Final[bool] = False


class SystemMode(StrEnum):
    RESEARCH = "research"  # analysis only; can never place orders
    PAPER = "paper"  # simulated orders only; can never reach a live broker
    LIVE = "live"  # live orders possible, but only behind every gate + human approval


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"
