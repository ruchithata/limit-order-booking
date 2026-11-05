"""FIFO queue for orders at one price."""

from collections import deque
from dataclasses import dataclass, field

from engine.order import Order
from engine.types import OrderType, Side


@dataclass(slots=True)
class PriceLevel:
    """Orders at a single price, stored in arrival order."""

    price: int
    side: Side
    orders: deque[Order] = field(default_factory=deque, init=False)
    total_quantity: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if isinstance(self.price, bool) or not isinstance(self.price, int):
            raise TypeError("price must be an integer")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if not isinstance(self.side, Side):
            raise TypeError("side must be a Side enum value")

    def __len__(self) -> int:
        return len(self.orders)

    @property
    def is_empty(self) -> bool:
        return not self.orders

    def add_order(self, order: Order) -> None:
        """Append a valid limit order to the FIFO queue."""
        if not isinstance(order, Order):
            raise TypeError("order must be an Order instance")
        if order.order_type is not OrderType.LIMIT:
            raise ValueError("only LIMIT orders can rest in a price level")
        if order.side is not self.side:
            raise ValueError("order side does not match price level side")
        if order.price != self.price:
            raise ValueError("order price does not match price level price")
        if order.is_cancelled or order.is_filled:
            raise ValueError("cancelled or filled orders cannot be added")

        self.orders.append(order)
        self.total_quantity += order.remaining_quantity

    def peek_front(self) -> Order | None:
        """Return the oldest order without removing it."""
        return self.orders[0] if self.orders else None

    def pop_front(self) -> Order:
        """Remove and return the oldest order."""
        if not self.orders:
            raise IndexError("cannot pop from an empty price level")
        order = self.orders.popleft()
        self.total_quantity -= order.remaining_quantity
        return order
