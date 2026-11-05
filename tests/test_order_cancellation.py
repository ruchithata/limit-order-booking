"""Tests for order-ID indexing and resting-order cancellation."""

import pytest
from engine.order import Order
from engine.order_book import OrderBook
from engine.types import OrderType, Side


def make_order(
    order_id: str,
    side: Side = Side.BUY,
    price: int = 100,
    quantity: int = 5,
) -> Order:
    return Order(order_id, side, OrderType.LIMIT, quantity, price)


def test_order_can_be_retrieved_by_id() -> None:
    book = OrderBook()
    order = make_order("B1")
    book.add_order(order)
    assert book.get_order("B1") is order


def test_unknown_order_id_returns_none() -> None:
    assert OrderBook().get_order("missing") is None


def test_duplicate_active_order_id_is_rejected() -> None:
    book = OrderBook()
    book.add_order(make_order("B1"))
    with pytest.raises(ValueError, match="duplicate"):
        book.add_order(make_order("B1", Side.SELL, 101))


def test_cancel_marks_order_and_removes_it_from_index() -> None:
    book = OrderBook()
    order = make_order("B1")
    book.add_order(order)
    assert book.cancel_order("B1") is True
    assert order.is_cancelled
    assert book.get_order("B1") is None
    assert len(book) == 0


def test_unknown_or_previously_cancelled_id_returns_false() -> None:
    book = OrderBook()
    assert book.cancel_order("missing") is False
    book.add_order(make_order("B1"))
    assert book.cancel_order("B1") is True
    assert book.cancel_order("B1") is False


def test_cancelled_front_order_is_skipped_and_quantity_updated() -> None:
    book = OrderBook()
    first = make_order("B1", quantity=4)
    second = make_order("B2", quantity=6)
    book.add_order(first)
    book.add_order(second)
    assert book.cancel_order("B1")
    assert book.peek_best_order(Side.BUY) is second
    assert book.best_bid_level().total_quantity == 6


def test_cancelled_middle_order_preserves_fifo() -> None:
    book = OrderBook()
    first = make_order("B1", quantity=2)
    middle = make_order("B2", quantity=3)
    last = make_order("B3", quantity=4)
    for order in (first, middle, last):
        book.add_order(order)
    assert book.cancel_order("B2")
    assert book.pop_best_order(Side.BUY) is first
    assert book.pop_best_order(Side.BUY) is last


def test_cancelling_all_orders_removes_price_level_lazily() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", price=105))
    book.add_order(make_order("B2", price=105))
    assert book.cancel_order("B1")
    assert book.cancel_order("B2")
    assert book.best_bid_price() is None
    assert 105 not in book.bid_levels


def test_cancelled_quantity_is_removed_from_level_total() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", quantity=7))
    book.add_order(make_order("B2", quantity=5))
    book.cancel_order("B1")
    assert book.best_bid_level().total_quantity == 5


def test_filled_order_is_removed_from_index_by_matching_engine() -> None:
    from engine.matching_engine import MatchingEngine

    engine = MatchingEngine()
    resting = make_order("S1", Side.SELL, 100, 2)
    engine.order_book.add_order(resting)
    incoming = Order("B1", Side.BUY, OrderType.LIMIT, 2, 100)
    engine.submit_order(incoming)
    assert engine.order_book.get_order("S1") is None
    assert len(engine.order_book) == 0


def test_cancelled_order_id_can_be_reused() -> None:
    book = OrderBook()
    book.add_order(make_order("B1"))
    book.cancel_order("B1")
    replacement = make_order("B1", price=101)
    book.add_order(replacement)
    assert book.get_order("B1") is replacement
    assert book.peek_best_order(Side.BUY) is replacement


def test_matching_engine_rejects_duplicate_active_order_id() -> None:
    from engine.matching_engine import MatchingEngine

    engine = MatchingEngine()
    engine.order_book.add_order(make_order("S1", Side.SELL, 100))
    duplicate = make_order("S1", Side.BUY, 100)
    with pytest.raises(ValueError, match="duplicate"):
        engine.submit_order(duplicate)
