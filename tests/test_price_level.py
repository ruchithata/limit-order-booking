"""Tests for FIFO price levels."""

import pytest
from engine.order import Order
from engine.price_level import PriceLevel
from engine.types import OrderType, Side


def make_order(
    order_id: str, side: Side = Side.BUY, price: int = 100, quantity: int = 5
) -> Order:
    return Order(order_id, side, OrderType.LIMIT, quantity, price)


def test_price_level_preserves_fifo_order() -> None:
    level = PriceLevel(100, Side.BUY)
    first, second = make_order("first"), make_order("second")
    level.add_order(first)
    level.add_order(second)
    assert len(level) == 2
    assert level.peek_front() is first
    assert level.pop_front() is first
    assert level.pop_front() is second
    assert level.is_empty
    assert level.total_quantity == 0


def test_price_level_tracks_total_quantity() -> None:
    level = PriceLevel(100, Side.BUY)
    level.add_order(make_order("one", quantity=4))
    level.add_order(make_order("two", quantity=7))
    assert level.total_quantity == 11
    level.pop_front()
    assert level.total_quantity == 7


@pytest.mark.parametrize(
    ("order", "price", "side"),
    [
        (make_order("wrong-price", price=101), 100, Side.BUY),
        (make_order("wrong-side", side=Side.SELL), 100, Side.BUY),
        (Order("market", Side.BUY, OrderType.MARKET, 1), 100, Side.BUY),
    ],
)
def test_price_level_rejects_incompatible_orders(
    order: Order, price: int, side: Side
) -> None:
    with pytest.raises(ValueError):
        PriceLevel(price, side).add_order(order)


def test_price_level_rejects_non_positive_price() -> None:
    with pytest.raises(ValueError):
        PriceLevel(0, Side.BUY)


def test_pop_empty_level_raises() -> None:
    with pytest.raises(IndexError):
        PriceLevel(100, Side.BUY).pop_front()
