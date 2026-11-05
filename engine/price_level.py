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

    @property
    def is_empty(self) -> bool:
        """Return whether this price level contains no orders."""
        return not self.orders

    def __len__(self) -> int:
        """Return the number of orders stored at this price."""
        return len(self.orders)

    def add_order(self, order: Order) -> None:
        """Append a compatible live limit order to this price level."""
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
        """Return the oldest order without removing it."""
        return self.orders[0] if self.orders else None

    def pop_front(self) -> Order:
        """Remove and return the oldest order."""
        if not self.orders:
            raise IndexError("cannot pop from an empty price level")
        order = self.orders.popleft()
        self.total_quantity -= order.remaining_quantity
        return order

    def apply_fill_to_front(self, quantity: int) -> Order:
        """Apply a fill to the oldest order and update aggregate quantity.

        A fully filled order remains at the front until the owning OrderBook
        removes it with ``pop_best_order``. This lets the book perform its
        normal empty-level and heap cleanup.
        """
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
