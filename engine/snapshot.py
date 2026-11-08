"""Snapshot serialization and deserialization for engine state persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderId, _validate_order_id, _validate_u64
from engine.order_book import OrderBook
from engine.types import OrderType, Side


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """Serializable snapshot of a single resting limit order in the book."""

    order_id: OrderId
    side: Side
    order_type: OrderType
    quantity: int
    price: int
    remaining_quantity: int = -1

    def __post_init__(self) -> None:
        _validate_order_id(self.order_id)
        if not isinstance(self.side, Side):
            raise TypeError("side must be a Side enum value")
        if not isinstance(self.order_type, OrderType):
            raise TypeError("order_type must be an OrderType enum value")
        if self.order_type is not OrderType.LIMIT:
            raise ValueError("only LIMIT orders can rest in an order book snapshot")
        _validate_u64(self.quantity, "quantity")
        _validate_u64(self.price, "price")

        rem = (
            self.quantity if self.remaining_quantity == -1 else self.remaining_quantity
        )
        if rem != self.remaining_quantity:
            object.__setattr__(self, "remaining_quantity", rem)

        _validate_u64(self.remaining_quantity, "remaining_quantity")
        if self.remaining_quantity > self.quantity:
            raise ValueError("remaining_quantity cannot exceed initial quantity")

    @classmethod
    def from_order(cls, order: Order) -> OrderSnapshot:
        if not isinstance(order, Order):
            raise TypeError("order must be an Order instance")
        if order.is_cancelled:
            raise ValueError("cannot snapshot cancelled order")
        if order.is_filled:
            raise ValueError("cannot snapshot filled order")
        if order.order_type is not OrderType.LIMIT or order.price is None:
            raise ValueError("only resting LIMIT orders can be snapshotted")
        return cls(
            order_id=order.order_id,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            price=order.price,
            remaining_quantity=order.remaining_quantity,
        )

    def to_order(self) -> Order:
        order = Order(
            order_id=self.order_id,
            side=self.side,
            order_type=self.order_type,
            quantity=self.quantity,
            price=self.price,
        )
        if self.remaining_quantity < self.quantity:
            order.apply_fill(self.quantity - self.remaining_quantity)
        return order

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "remaining_quantity": self.remaining_quantity,
        }

    @classmethod
    def from_dict(cls, data: Any) -> OrderSnapshot:
        if not isinstance(data, dict):
            raise TypeError("order snapshot record must be a dict")
        required = {
            "order_id",
            "side",
            "order_type",
            "quantity",
            "price",
            "remaining_quantity",
        }
        if set(data) != required:
            raise ValueError("order snapshot record has missing or unknown fields")
        try:
            side = Side(data["side"])
        except ValueError as exc:
            raise ValueError(
                f"invalid side in order snapshot: {data['side']!r}"
            ) from exc
        try:
            order_type = OrderType(data["order_type"])
        except ValueError as exc:
            raise ValueError(
                f"invalid order_type in order snapshot: {data['order_type']!r}"
            ) from exc
        return cls(
            order_id=data["order_id"],
            side=side,
            order_type=order_type,
            quantity=data["quantity"],
            price=data["price"],
            remaining_quantity=data["remaining_quantity"],
        )


@dataclass(frozen=True, slots=True)
class EngineSnapshot:
    """Immutable point-in-time snapshot of the full matching engine state."""

    bids: tuple[OrderSnapshot, ...] = ()
    asks: tuple[OrderSnapshot, ...] = ()
    next_trade_id: int = 1
    last_sequence: int = 0

    def __post_init__(self) -> None:
        bid_list: list[OrderSnapshot] = []
        for item in self.bids:
            if isinstance(item, OrderSnapshot):
                bid_list.append(item)
            elif isinstance(item, dict):
                bid_list.append(OrderSnapshot.from_dict(item))
            else:
                raise TypeError(
                    f"expected OrderSnapshot in bids, got {type(item).__name__}"
                )
        object.__setattr__(self, "bids", tuple(bid_list))

        ask_list: list[OrderSnapshot] = []
        for item in self.asks:
            if isinstance(item, OrderSnapshot):
                ask_list.append(item)
            elif isinstance(item, dict):
                ask_list.append(OrderSnapshot.from_dict(item))
            else:
                raise TypeError(
                    f"expected OrderSnapshot in asks, got {type(item).__name__}"
                )
        object.__setattr__(self, "asks", tuple(ask_list))

        _validate_u64(self.next_trade_id, "next_trade_id")
        _validate_u64(self.last_sequence, "last_sequence", allow_zero=True)

        seen_ids: set[OrderId] = set()
        for order in self.bids:
            if order.side is not Side.BUY:
                raise ValueError(
                    f"order {order.order_id!r} in bids has non-BUY side: {order.side}"
                )
            if order.order_id in seen_ids:
                raise ValueError(f"duplicate order_id in snapshot: {order.order_id!r}")
            seen_ids.add(order.order_id)

        for order in self.asks:
            if order.side is not Side.SELL:
                raise ValueError(
                    f"order {order.order_id!r} in asks has non-SELL side: {order.side}"
                )
            if order.order_id in seen_ids:
                raise ValueError(f"duplicate order_id in snapshot: {order.order_id!r}")
            seen_ids.add(order.order_id)

        for i in range(len(self.bids) - 1):
            if self.bids[i + 1].price > self.bids[i].price:
                raise ValueError(
                    f"bid orders must be in non-ascending price order: "
                    f"{self.bids[i].price} followed by {self.bids[i + 1].price}"
                )

        for i in range(len(self.asks) - 1):
            if self.asks[i + 1].price < self.asks[i].price:
                raise ValueError(
                    f"ask orders must be in non-descending price order: "
                    f"{self.asks[i].price} followed by {self.asks[i + 1].price}"
                )

        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            raise ValueError(
                f"crossed order book in snapshot: best bid {self.bids[0].price} "
                f">= best ask {self.asks[0].price}"
            )

    @classmethod
    def from_engine(
        cls,
        engine: MatchingEngine | Any,
        last_sequence: int | None = None,
    ) -> EngineSnapshot:
        matching_engine = getattr(engine, "matching_engine", engine)
        if not isinstance(matching_engine, MatchingEngine):
            raise TypeError(
                "engine must be a MatchingEngine or RecordingMatchingEngine"
            )

        if last_sequence is None:
            event_log = getattr(engine, "event_log", None)
            if event_log is not None and hasattr(event_log, "events"):
                last_sequence = len(event_log.events)
            else:
                last_sequence = 0

        order_book = matching_engine.order_book
        bid_orders: list[OrderSnapshot] = []
        ask_orders: list[OrderSnapshot] = []

        bid_prices = sorted(order_book._bids.keys(), reverse=True)
        for price in bid_prices:
            level = order_book._bids[price]
            for order in level.orders:
                if not order.is_cancelled and not order.is_filled:
                    bid_orders.append(OrderSnapshot.from_order(order))

        ask_prices = sorted(order_book._asks.keys())
        for price in ask_prices:
            level = order_book._asks[price]
            for order in level.orders:
                if not order.is_cancelled and not order.is_filled:
                    ask_orders.append(OrderSnapshot.from_order(order))

        return cls(
            bids=tuple(bid_orders),
            asks=tuple(ask_orders),
            next_trade_id=matching_engine._next_trade_id,
            last_sequence=last_sequence,
        )

    def restore_engine(self) -> MatchingEngine:
        engine = MatchingEngine()
        engine._next_trade_id = self.next_trade_id
        for order_snap in self.bids:
            engine.order_book.add_order(order_snap.to_order())
        for order_snap in self.asks:
            engine.order_book.add_order(order_snap.to_order())
        engine.order_book.validate_invariants()
        return engine

    def restore_book(self) -> OrderBook:
        return self.restore_engine().order_book

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "last_sequence": self.last_sequence,
            "next_trade_id": self.next_trade_id,
            "bids": [order.to_dict() for order in self.bids],
            "asks": [order.to_dict() for order in self.asks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Any) -> EngineSnapshot:
        if not isinstance(data, dict):
            raise TypeError("snapshot data must be a dict")
        version = data.get("version", 1)
        if version != 1:
            raise ValueError(f"unsupported snapshot version: {version!r}")
        if "last_sequence" not in data or "next_trade_id" not in data:
            raise ValueError("snapshot data missing required fields")
        if "bids" not in data or "asks" not in data:
            raise ValueError("snapshot data missing bids or asks")
        if not isinstance(data["bids"], (list, tuple)) or not isinstance(
            data["asks"], (list, tuple)
        ):
            raise TypeError("bids and asks must be lists or tuples")

        bids = tuple(OrderSnapshot.from_dict(item) for item in data["bids"])
        asks = tuple(OrderSnapshot.from_dict(item) for item in data["asks"])
        return cls(
            bids=bids,
            asks=asks,
            next_trade_id=data["next_trade_id"],
            last_sequence=data["last_sequence"],
        )

    @classmethod
    def from_json(cls, text: str) -> EngineSnapshot:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in snapshot: {exc}") from exc
        return cls.from_dict(data)


Snapshot = EngineSnapshot


def create_snapshot(
    engine: MatchingEngine | Any,
    last_sequence: int | None = None,
) -> EngineSnapshot:
    """Create an EngineSnapshot from a MatchingEngine or RecordingMatchingEngine."""
    return EngineSnapshot.from_engine(engine, last_sequence=last_sequence)


def restore_engine_from_snapshot(snapshot: EngineSnapshot) -> MatchingEngine:
    """Restore a MatchingEngine from an EngineSnapshot."""
    if not isinstance(snapshot, EngineSnapshot):
        raise TypeError("snapshot must be an EngineSnapshot instance")
    return snapshot.restore_engine()


def restore_book_from_snapshot(snapshot: EngineSnapshot) -> OrderBook:
    """Restore an OrderBook from an EngineSnapshot."""
    if not isinstance(snapshot, EngineSnapshot):
        raise TypeError("snapshot must be an EngineSnapshot instance")
    return snapshot.restore_book()
