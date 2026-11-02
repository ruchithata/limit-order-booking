"""Validated order and trade domain models."""

from dataclasses import dataclass, field
from typing import TypeAlias

from engine.types import OrderType, Side

OrderId: TypeAlias = int | str
U64_MAX = (1 << 64) - 1


def _validate_order_id(order_id: OrderId) -> None:
    """Validate a string or unsigned 64-bit integer order ID."""
    if isinstance(order_id, bool) or not isinstance(order_id, (int, str)):
        raise TypeError("order_id must be an int or str")
    if isinstance(order_id, int) and not 0 <= order_id <= U64_MAX:
        raise ValueError("integer order_id must be between 0 and 2**64 - 1")
    if isinstance(order_id, str) and not order_id.strip():
        raise ValueError("string order_id must not be empty or whitespace")


def _validate_u64(value: int, field_name: str, *, allow_zero: bool = False) -> None:
    """Validate an integer in the unsigned 64-bit range."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    minimum = 0 if allow_zero else 1
    if not minimum <= value <= U64_MAX:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field_name} must be {qualifier} and at most 2**64 - 1")


@dataclass(slots=True)
class Order:
    """An order submitted to the book.

    Prices are integer ticks (for example, cents), never floating-point values.
    LIMIT orders require a positive price. MARKET orders must use ``price=None``.
    ``quantity`` is the original size; ``remaining_quantity`` is reduced as
    executions occur.
    """

    order_id: OrderId
    side: Side
    order_type: OrderType
    quantity: int
    price: int | None = None
    remaining_quantity: int = field(init=False)
    is_cancelled: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validate_order_id(self.order_id)
        if not isinstance(self.side, Side):
            raise TypeError("side must be a Side enum value")
        if not isinstance(self.order_type, OrderType):
            raise TypeError("order_type must be an OrderType enum value")
        _validate_u64(self.quantity, "quantity")

        if self.order_type is OrderType.LIMIT:
            if self.price is None:
                raise ValueError("LIMIT orders require a price")
            _validate_u64(self.price, "price")
        elif self.price is not None:
            raise ValueError("MARKET orders must have price=None")

        self.remaining_quantity = self.quantity

    @property
    def is_filled(self) -> bool:
        """Return whether the order has no quantity left to execute."""
        return self.remaining_quantity == 0

    def apply_fill(self, quantity: int) -> None:
        """Reduce remaining quantity after an execution."""
        _validate_u64(quantity, "fill quantity")
        if quantity > self.remaining_quantity:
            raise ValueError("fill quantity cannot exceed remaining quantity")
        self.remaining_quantity -= quantity

    def cancel(self) -> None:
        """Mark the order as cancelled.

        Order-book/index integration and cancellation policy are implemented later.
        """
        self.is_cancelled = True


@dataclass(frozen=True, slots=True)
class Trade:
    """An execution between one buy order and one sell order."""

    trade_id: int
    buy_order_id: OrderId
    sell_order_id: OrderId
    price: int
    quantity: int
    maker_order_id: OrderId
    taker_order_id: OrderId

    def __post_init__(self) -> None:
        _validate_u64(self.trade_id, "trade_id")
        _validate_order_id(self.buy_order_id)
        _validate_order_id(self.sell_order_id)
        _validate_u64(self.price, "price")
        _validate_u64(self.quantity, "quantity")
        _validate_order_id(self.maker_order_id)
        _validate_order_id(self.taker_order_id)

        if self.buy_order_id == self.sell_order_id:
            raise ValueError("buy and sell order IDs must be different")
        participants = {self.buy_order_id, self.sell_order_id}
        if {self.maker_order_id, self.taker_order_id} != participants:
            raise ValueError("maker and taker IDs must match the trade's buy/sell IDs")
