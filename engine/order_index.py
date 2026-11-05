"""Active order-ID index for the in-memory order book."""

from engine.order import Order, OrderId
from engine.price_level import PriceLevel


class OrderIndex:
    """Map active order IDs to their order and owning price level."""

    def __init__(self) -> None:
        self._entries: dict[OrderId, tuple[Order, PriceLevel]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, order_id: OrderId) -> bool:
        return order_id in self._entries

    def add(self, order: Order, level: PriceLevel) -> None:
        if order.order_id in self._entries:
            raise ValueError(f"duplicate active order ID: {order.order_id!r}")
        self._entries[order.order_id] = (order, level)

    def get(self, order_id: OrderId) -> tuple[Order, PriceLevel] | None:
        return self._entries.get(order_id)

    def remove(self, order_id: OrderId) -> tuple[Order, PriceLevel] | None:
        return self._entries.pop(order_id, None)
