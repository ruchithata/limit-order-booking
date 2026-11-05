"""FIFO queue for orders sharing one side and price."""

from collections import deque
from dataclasses import dataclass, field

from engine.order import Order
from engine.types import OrderType, Side


@dataclass
class PriceLevel:
    """Store orders at one price while preserving time priority."""

    price: int
    side: Side
    orders: deque[Order] = field(default_factory=deque)
    total_quantity: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.price, bool) or not isinstance(self.price, int):
            raise TypeError("price must be an integer")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if not isinstance(self.side, Side):
            raise TypeError("side must be a Side")

    def _discard_cancelled_front(self) -> None:
        while self.orders and self.orders[0].is_cancelled:
            self.orders.popleft()

    @property
    def is_empty(self) -> bool:
        self._discard_cancelled_front()
        return not self.orders

    def __len__(self) -> int:
        return sum(not order.is_cancelled for order in self.orders)

    def add_order(self, order: Order) -> None:
        if not isinstance(order, Order):
            raise TypeError("order must be an Order")
        if order.order_type is not OrderType.LIMIT:
            raise ValueError("only limit orders can be added to a price level")
        if order.side is not self.side or order.price != self.price:
            raise ValueError("order side and price must match the price level")
        if order.is_cancelled or order.is_filled:
            raise ValueError("cancelled or filled orders cannot be added")
        self.orders.append(order)
        self.total_quantity += order.remaining_quantity

    def peek_front(self) -> Order | None:
        self._discard_cancelled_front()
        return self.orders[0] if self.orders else None

    def pop_front(self) -> Order:
        self._discard_cancelled_front()
        if not self.orders:
            raise IndexError("cannot pop from an empty price level")
        order = self.orders.popleft()
        self.total_quantity -= order.remaining_quantity
        return order

    def cancel_order(self, order: Order) -> None:
        """Cancel an order resolved through OrderBook's active index."""
        if order.is_cancelled or order.is_filled:
            raise ValueError("order is already inactive")
        order.cancel()
        self.total_quantity -= order.remaining_quantity

    def apply_fill_to_front(self, quantity: int) -> Order:
        order = self.peek_front()
        if order is None:
            raise IndexError("cannot fill an empty price level")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("fill quantity must be an integer")
        if quantity <= 0 or quantity > order.remaining_quantity:
            raise ValueError(
                "fill quantity must be positive and within remaining quantity"
            )
        order.apply_fill(quantity)
        self.total_quantity -= quantity
        return order
