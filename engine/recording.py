"""Recording facade around the existing matching engine."""

from engine.event_log import EventLog
from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderId, Trade
from engine.order_book import OrderBookSnapshot


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

    def __len__(self) -> int:
        return len(self.matching_engine)
