"""Invariant and matching edge-case tests for the order book."""

import pytest
from engine.matching_engine import MatchingEngine
from engine.order import Order
from engine.order_book import OrderBook
from engine.types import OrderType, Side


def limit_order(order_id: str, side: Side, quantity: int, price: int) -> Order:
    return Order(order_id, side, OrderType.LIMIT, quantity, price)


def test_empty_book_satisfies_invariants() -> None:
    assert OrderBook().validate_invariants()


def test_invariants_hold_after_add_cancel_partial_fill_and_full_fill() -> None:
    engine = MatchingEngine()
    first = limit_order("S1", Side.SELL, 8, 100)
    second = limit_order("S2", Side.SELL, 5, 101)
    engine.order_book.add_order(first)
    engine.order_book.add_order(second)
    assert engine.order_book.validate_invariants()

    assert engine.order_book.cancel_order("S2")
    assert engine.order_book.validate_invariants()

    trades = engine.submit_order(limit_order("B1", Side.BUY, 3, 100))
    assert sum(trade.quantity for trade in trades) == 3
    assert first.remaining_quantity == 5
    assert engine.order_book.validate_invariants()

    trades = engine.submit_order(limit_order("B2", Side.BUY, 5, 100))
    assert sum(trade.quantity for trade in trades) == 5
    assert engine.order_book.get_order("S1") is None
    assert engine.order_book.validate_invariants()


def test_market_order_with_no_liquidity_is_cancelled_without_book_changes() -> None:
    engine = MatchingEngine()
    market = Order("M1", Side.BUY, OrderType.MARKET, 7)
    assert engine.submit_order(market) == []
    assert market.is_cancelled
    assert engine.order_book.validate_invariants()


def test_market_order_partial_fill_cancels_only_unfilled_remainder() -> None:
    engine = MatchingEngine()
    resting = limit_order("S1", Side.SELL, 4, 100)
    engine.order_book.add_order(resting)
    market = Order("M1", Side.BUY, OrderType.MARKET, 9)

    trades = engine.submit_order(market)

    assert [(trade.price, trade.quantity) for trade in trades] == [(100, 4)]
    assert market.remaining_quantity == 5
    assert market.is_cancelled
    assert engine.order_book.get_order("S1") is None
    assert engine.order_book.validate_invariants()


def test_market_order_sweeps_multiple_levels_and_leaves_no_residual() -> None:
    engine = MatchingEngine()
    engine.order_book.add_order(limit_order("S1", Side.SELL, 2, 100))
    engine.order_book.add_order(limit_order("S2", Side.SELL, 3, 101))
    market = Order("M1", Side.BUY, OrderType.MARKET, 5)

    trades = engine.submit_order(market)

    assert [(trade.price, trade.quantity) for trade in trades] == [
        (100, 2),
        (101, 3),
    ]
    assert market.is_filled
    assert not market.is_cancelled
    assert engine.order_book.validate_invariants()


def test_partial_fill_updates_index_and_level_quantity() -> None:
    engine = MatchingEngine()
    resting = limit_order("S1", Side.SELL, 10, 100)
    engine.order_book.add_order(resting)

    engine.submit_order(limit_order("B1", Side.BUY, 4, 100))

    level = engine.order_book.best_ask_level()
    assert level is not None
    assert level.total_quantity == 6
    assert engine.order_book.get_order("S1") is resting
    assert engine.order_book.validate_invariants()


def test_cancelled_middle_order_does_not_break_remaining_fifo() -> None:
    book = OrderBook()
    orders = [
        limit_order("B1", Side.BUY, 2, 100),
        limit_order("B2", Side.BUY, 3, 100),
        limit_order("B3", Side.BUY, 4, 100),
    ]
    for order in orders:
        book.add_order(order)
    assert book.cancel_order("B2")
    assert book.validate_invariants()
    assert book.pop_best_order(Side.BUY) is orders[0]
    assert book.pop_best_order(Side.BUY) is orders[2]
    assert book.validate_invariants()


def test_invariant_checker_detects_quantity_corruption() -> None:
    book = OrderBook()
    book.add_order(limit_order("B1", Side.BUY, 5, 100))
    book.best_bid_level().total_quantity = 99

    with pytest.raises(AssertionError, match="quantity mismatch"):
        book.validate_invariants()


def test_invariant_checker_detects_missing_index_entry() -> None:
    book = OrderBook()
    book.add_order(limit_order("B1", Side.BUY, 5, 100))
    book._order_index.remove("B1")

    with pytest.raises(AssertionError, match="order index IDs"):
        book.validate_invariants()
