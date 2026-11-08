"""Recording facade around the existing matching engine."""

from __future__ import annotations

from pathlib import Path

from engine.event_log import EventLog
from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderId, Trade
from engine.order_book import OrderBook, OrderBookSnapshot


class RecordingMatchingEngine:
    """Record successful order submissions and cancellations.

    Events are appended after engine operations succeed. The log and in-memory
    engine are not a transactional pair; see EventLog's durability notes.
    """

    def __init__(
        self,
        matching_engine: MatchingEngine | None = None,
        event_log: EventLog | None = None,
    ) -> None:
        self.matching_engine = (
            matching_engine if matching_engine is not None else MatchingEngine()
        )
        self.event_log = event_log or EventLog()

    def submit_order(self, order: Order) -> list[Trade]:
        trades = self.matching_engine.submit_order(order)
        self.event_log.append_submission(
            order_id=order.order_id,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            price=order.price,
        )
        return trades

    def cancel_order(self, order_id: OrderId) -> bool:
        cancelled = self.matching_engine.cancel_order(order_id)
        if cancelled:
            self.event_log.append_cancellation(order_id)
        return cancelled

    def get_snapshot(self, depth: int | None = None) -> OrderBookSnapshot:
        return self.matching_engine.get_snapshot(depth)

    def get_order(self, order_id: OrderId) -> Order | None:
        return self.matching_engine.get_order(order_id)

    def best_bid_price(self) -> int | None:
        return self.matching_engine.best_bid_price()

    def best_ask_price(self) -> int | None:
        return self.matching_engine.best_ask_price()

    @property
    def next_trade_id(self) -> int:
        return self.matching_engine.next_trade_id

    @property
    def order_book(self) -> OrderBook:
        return self.matching_engine.order_book

    def create_snapshot(self):
        from engine.snapshot import EngineSnapshot

        return EngineSnapshot.from_engine(self)

    def save_snapshot(self, path: str | Path) -> Path:
        from engine.persistence import save_snapshot

        return save_snapshot(self.create_snapshot(), path)

    def __len__(self) -> int:
        return len(self.matching_engine)
