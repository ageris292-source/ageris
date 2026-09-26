"""Live broker adapter interface (spec §29-§31) — scaffolding only.

`BrokerAdapter` is the contract a real Indian-market broker integration
would implement (orders need exchange, side, quantity, a limit price, an
idempotency key and the approving human). This build contains exactly one
implementation, `UnavailableBroker`: it reports itself unavailable (health
UNKNOWN, which fails the engine's execution-mode gate) and refuses every
call. `get_broker()` cannot be pointed at anything else by configuration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol


class BrokerUnavailableError(RuntimeError):
    """No live broker exists in this build; nothing was sent anywhere."""


@dataclass(frozen=True)
class BrokerStatus:
    name: str
    available: bool
    healthy: bool | None  # None = unknown -> never passes a gate
    reason: str


@dataclass(frozen=True)
class LiveOrderRequest:
    decision_id: int
    idempotency_key: str
    approved_by: uuid.UUID
    ticker: str
    exchange: Literal["NSE", "BSE"]
    side: Literal["buy", "sell"]
    quantity: int
    limit_price: Decimal  # limit orders only; market orders are not supported


@dataclass(frozen=True)
class BrokerOrderAck:
    broker_order_id: str
    status: Literal["accepted", "rejected"]
    detail: str


class BrokerAdapter(Protocol):
    name: str

    def status(self) -> BrokerStatus: ...

    def place_order(self, order: LiveOrderRequest) -> BrokerOrderAck: ...

    def cancel_order(self, broker_order_id: str) -> None: ...

    def order_status(self, broker_order_id: str) -> str: ...

    def positions(self) -> dict[str, int]: ...


UNAVAILABLE_REASON = "no live broker adapter exists in this build; live trading is disabled"


class UnavailableBroker:
    """The only adapter in this build. It holds no credentials, opens no
    connections and refuses every call."""

    name = "unavailable"

    def status(self) -> BrokerStatus:
        return BrokerStatus(self.name, available=False, healthy=None, reason=UNAVAILABLE_REASON)

    def place_order(self, order: LiveOrderRequest) -> BrokerOrderAck:
        raise BrokerUnavailableError(UNAVAILABLE_REASON)

    def cancel_order(self, broker_order_id: str) -> None:
        raise BrokerUnavailableError(UNAVAILABLE_REASON)

    def order_status(self, broker_order_id: str) -> str:
        raise BrokerUnavailableError(UNAVAILABLE_REASON)

    def positions(self) -> dict[str, int]:
        raise BrokerUnavailableError(UNAVAILABLE_REASON)


def get_broker() -> BrokerAdapter:
    """Always the unavailable adapter: there is no registry, no environment
    variable and no config key that selects another."""
    return UnavailableBroker()


def readiness_status(adapter: BrokerAdapter) -> Literal["PASS", "FAIL", "UNKNOWN"]:
    h = adapter.status().healthy
    return "UNKNOWN" if h is None else "PASS" if h else "FAIL"
