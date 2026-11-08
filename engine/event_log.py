"""Validated append-only command log for deterministic engine replay."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from engine.order import OrderId
from engine.types import OrderType, Side

EventKind = Literal["ORDER_SUBMITTED", "ORDER_CANCELLED"]


@dataclass(frozen=True, slots=True)
class EngineEvent:
    sequence: int
    kind: EventKind
    order_id: OrderId
    side: Side | None = None
    order_type: OrderType | None = None
    quantity: int | None = None
    price: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if isinstance(self.order_id, bool) or not isinstance(self.order_id, (int, str)):
            raise TypeError("order_id must be an int or str")
        if isinstance(self.order_id, int) and self.order_id < 0:
            raise ValueError("integer order_id must be non-negative")
        if isinstance(self.order_id, str) and not self.order_id.strip():
            raise ValueError("string order_id must not be empty or whitespace")
        if self.kind == "ORDER_SUBMITTED":
            if not isinstance(self.side, Side) or not isinstance(
                self.order_type, OrderType
            ):
                raise TypeError("submission event requires valid side and order type")
            if (
                isinstance(self.quantity, bool)
                or not isinstance(self.quantity, int)
                or self.quantity <= 0
            ):
                raise ValueError("submission event quantity must be positive")
            if self.order_type is OrderType.LIMIT:
                if (
                    isinstance(self.price, bool)
                    or not isinstance(self.price, int)
                    or self.price <= 0
                ):
                    raise ValueError("LIMIT event requires a positive price")
            elif self.price is not None:
                raise ValueError("MARKET event must not contain a price")
        elif self.kind == "ORDER_CANCELLED":
            if any(
                v is not None
                for v in (self.side, self.order_type, self.quantity, self.price)
            ):
                raise ValueError("cancellation event cannot contain order details")
        else:
            raise ValueError(f"unsupported event kind: {self.kind!r}")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "sequence": self.sequence,
            "kind": self.kind,
            "order_id": self.order_id,
        }
        if self.kind == "ORDER_SUBMITTED":
            result.update(
                {
                    "side": self.side.value,
                    "order_type": self.order_type.value,
                    "quantity": self.quantity,
                    "price": self.price,
                }
            )
        return result

    @classmethod
    def from_dict(cls, data: object) -> EngineEvent:
        if not isinstance(data, dict):
            raise TypeError("event record must be a JSON object")
        kind = data.get("kind")
        if kind == "ORDER_SUBMITTED":
            required = {
                "sequence",
                "kind",
                "order_id",
                "side",
                "order_type",
                "quantity",
                "price",
            }
            if set(data) != required:
                raise ValueError("submission event has missing or unknown fields")
            return cls(
                sequence=data["sequence"],
                kind=kind,
                order_id=data["order_id"],
                side=Side(data["side"]),
                order_type=OrderType(data["order_type"]),
                quantity=data["quantity"],
                price=data["price"],
            )
        if kind == "ORDER_CANCELLED":
            if set(data) != {"sequence", "kind", "order_id"}:
                raise ValueError("cancellation event has missing or unknown fields")
            return cls(sequence=data["sequence"], kind=kind, order_id=data["order_id"])
        raise ValueError(f"unsupported event kind: {kind!r}")


class EventLog:
    """In-memory event sequence optionally mirrored to JSON Lines.

    File writes are flushed, but are not fsync-backed or transactionally coupled
    to engine state. This is a replay journal, not a crash-safe production WAL.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._events = (
            list(read_events(self.path)) if self.path and self.path.exists() else []
        )

    @property
    def events(self) -> tuple[EngineEvent, ...]:
        return tuple(self._events)

    def append_submission(
        self,
        *,
        order_id: OrderId,
        side: Side,
        order_type: OrderType,
        quantity: int,
        price: int | None,
    ) -> EngineEvent:
        return self._append(
            EngineEvent(
                len(self._events) + 1,
                "ORDER_SUBMITTED",
                order_id,
                side,
                order_type,
                quantity,
                price,
            )
        )

    def append_cancellation(self, order_id: OrderId) -> EngineEvent:
        return self._append(
            EngineEvent(len(self._events) + 1, "ORDER_CANCELLED", order_id)
        )

    def _append(self, event: EngineEvent) -> EngineEvent:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
                    + "\n"
                )
                stream.flush()
        self._events.append(event)
        return event


def read_events(path: str | Path) -> tuple[EngineEvent, ...]:
    events: list[EngineEvent] = []
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"blank event record at line {line_no}")
            try:
                event = EngineEvent.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid event at line {line_no}: {exc}") from exc
            expected = len(events) + 1
            if event.sequence != expected:
                raise ValueError(
                    f"invalid event sequence at line {line_no}: "
                    f"expected {expected}, got {event.sequence}"
                )
            events.append(event)
    return tuple(events)
