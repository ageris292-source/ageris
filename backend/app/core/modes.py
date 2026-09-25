"""System operating modes (spec §5)."""

from enum import StrEnum


class SystemMode(StrEnum):
    RESEARCH = "research"  # analysis only; can never place orders
    PAPER = "paper"  # simulated orders only; can never reach a live broker
    LIVE = "live"  # live orders possible, but only behind every gate + human approval


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"
