"""Tests for order-book price priority and FIFO behavior."""

import pytest
from engine.order import Order
from engine.order_book import OrderBook
from engine.types import OrderType, Side


def make_order(order_id: str, side: Side, price: int, quantity: int = 5) -> Order:
    return Order(order_id, side, OrderType.LIMIT, quantity, price)


def test_empty_book_has_no_best_prices() -> None:
    book = OrderBook()
    assert len(book) == 0
    assert book.best_bid_price() is None
    assert book.best_ask_price() is None
    assert book.peek_best_order(Side.BUY) is None
    assert book.peek_best_order(Side.SELL) is None


def test_best_bid_is_highest_price() -> None:
    book = OrderBook()
    for price in (100, 105, 102):
        book.add_order(make_order(str(price), Side.BUY, price))
    assert book.best_bid_price() == 105


def test_best_ask_is_lowest_price() -> None:
    book = OrderBook()
    for price in (110, 103, 107):
        book.add_order(make_order(str(price), Side.SELL, price))
    assert book.best_ask_price() == 103


def test_fifo_is_preserved_at_same_price() -> None:
    book = OrderBook()
    first, second = (
        make_order("first", Side.BUY, 100),
        make_order("second", Side.BUY, 100),
    )
    book.add_order(first)
    book.add_order(second)
    assert book.peek_best_order(Side.BUY) is first
    assert book.pop_best_order(Side.BUY) is first
    assert book.pop_best_order(Side.BUY) is second
    assert book.best_bid_price() is None


def test_price_priority_precedes_fifo_across_levels() -> None:
    book = OrderBook()
    lower = make_order("lower", Side.BUY, 99)
    higher = make_order("higher", Side.BUY, 105)
    book.add_order(lower)
    book.add_order(higher)
    assert book.pop_best_order(Side.BUY) is higher
    assert book.best_bid_price() == 99


def test_bid_and_ask_sides_are_independent() -> None:
    book = OrderBook()
    book.add_order(make_order("bid", Side.BUY, 100))
    book.add_order(make_order("ask", Side.SELL, 101))
    assert book.best_bid_price() == 100
    assert book.best_ask_price() == 101
    assert len(book) == 2


def test_empty_price_level_is_cleaned_from_heap_lazily() -> None:
    book = OrderBook()
    book.add_order(make_order("top", Side.BUY, 105))
    book.add_order(make_order("next", Side.BUY, 100))
    book.pop_best_order(Side.BUY)
    assert 105 not in book.bid_levels
    assert book.best_bid_price() == 100


def test_market_orders_cannot_be_added_to_book() -> None:
    book = OrderBook()
    market = Order("market", Side.BUY, OrderType.MARKET, 2)
    with pytest.raises(ValueError):
        book.add_order(market)


def test_pop_from_empty_side_raises() -> None:
    with pytest.raises(IndexError):
        OrderBook().pop_best_order(Side.SELL)


def test_book_rejects_non_order_argument() -> None:
    with pytest.raises(TypeError):
        OrderBook().add_order("not-an-order")  # type: ignore[arg-type]
