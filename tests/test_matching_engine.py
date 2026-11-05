"""Tests for matching, execution prices, and price-time priority."""

import pytest
from engine.matching_engine import MatchingEngine
from engine.order import Order
from engine.types import OrderType, Side


def make_order(
    order_id: str,
    side: Side,
    quantity: int,
    price: int | None = 100,
    order_type: OrderType = OrderType.LIMIT,
) -> Order:
    return Order(order_id, side, order_type, quantity, price)


def test_buy_order_matches_best_ask_first_at_maker_price() -> None:
    engine = MatchingEngine()
    engine.order_book.add_order(make_order("S1", Side.SELL, 5, 101))
    engine.order_book.add_order(make_order("S2", Side.SELL, 5, 100))

    trades = engine.submit_order(make_order("B1", Side.BUY, 5, 105))

    assert len(trades) == 1
    assert trades[0].sell_order_id == "S2"
    assert trades[0].buy_order_id == "B1"
    assert trades[0].price == 100
    assert trades[0].quantity == 5
    assert trades[0].maker_order_id == "S2"
    assert trades[0].taker_order_id == "B1"
    assert engine.order_book.best_ask_price() == 101


def test_sell_order_matches_best_bid_first_at_maker_price() -> None:
    engine = MatchingEngine()
    engine.order_book.add_order(make_order("B1", Side.BUY, 4, 105))
    engine.order_book.add_order(make_order("B2", Side.BUY, 4, 110))

    trades = engine.submit_order(make_order("S1", Side.SELL, 4, 100))

    assert len(trades) == 1
    assert trades[0].buy_order_id == "B2"
    assert trades[0].sell_order_id == "S1"
    assert trades[0].price == 110


def test_partial_fill_leaves_resting_order_and_updates_level_quantity() -> None:
    engine = MatchingEngine()
    resting = make_order("S1", Side.SELL, 10, 100)
    engine.order_book.add_order(resting)

    trades = engine.submit_order(make_order("B1", Side.BUY, 4, 105))

    assert len(trades) == 1
    assert trades[0].quantity == 4
    assert resting.remaining_quantity == 6
    assert engine.order_book.best_ask_level().total_quantity == 6
    assert engine.order_book.peek_best_order(Side.SELL) is resting


def test_incoming_order_sweeps_multiple_price_levels() -> None:
    engine = MatchingEngine()
    engine.order_book.add_order(make_order("S1", Side.SELL, 3, 100))
    engine.order_book.add_order(make_order("S2", Side.SELL, 4, 102))
    engine.order_book.add_order(make_order("S3", Side.SELL, 5, 104))

    trades = engine.submit_order(make_order("B1", Side.BUY, 8, 103))

    assert [trade.price for trade in trades] == [100, 102]
    assert [trade.quantity for trade in trades] == [3, 4]
    assert [trade.trade_id for trade in trades] == [1, 2]
    assert engine.order_book.best_ask_price() == 104


def test_unfilled_limit_order_rests_in_book() -> None:
    engine = MatchingEngine()

    order = make_order("B1", Side.BUY, 7, 99)
    trades = engine.submit_order(order)

    assert trades == []
    assert engine.order_book.peek_best_order(Side.BUY) is order
    assert order.remaining_quantity == 7


def test_non_crossing_limit_order_does_not_trade() -> None:
    engine = MatchingEngine()
    engine.order_book.add_order(make_order("S1", Side.SELL, 5, 110))

    trades = engine.submit_order(make_order("B1", Side.BUY, 5, 105))

    assert trades == []
    assert engine.order_book.best_ask_price() == 110
    assert engine.order_book.best_bid_price() == 105


def test_market_order_executes_available_liquidity_and_cancels_remainder() -> None:
    engine = MatchingEngine()
    engine.order_book.add_order(make_order("S1", Side.SELL, 3, 100))
    market_buy = make_order("B1", Side.BUY, 8, None, OrderType.MARKET)

    trades = engine.submit_order(market_buy)

    assert len(trades) == 1
    assert trades[0].quantity == 3
    assert market_buy.remaining_quantity == 5
    assert market_buy.is_cancelled
    assert engine.order_book.peek_best_order(Side.BUY) is None


def test_market_order_with_no_liquidity_is_cancelled() -> None:
    engine = MatchingEngine()
    market_buy = make_order("B1", Side.BUY, 8, None, OrderType.MARKET)

    assert engine.submit_order(market_buy) == []
    assert market_buy.is_cancelled
    assert len(engine.order_book) == 0


def test_fully_filled_resting_order_is_removed_from_book() -> None:
    engine = MatchingEngine()
    resting = make_order("S1", Side.SELL, 5, 100)
    engine.order_book.add_order(resting)

    trades = engine.submit_order(make_order("B1", Side.BUY, 5, 100))

    assert len(trades) == 1
    assert resting.is_filled
    assert engine.order_book.best_ask_price() is None


def test_fifo_is_used_when_resting_orders_have_same_price() -> None:
    engine = MatchingEngine()
    first = make_order("S1", Side.SELL, 3, 100)
    second = make_order("S2", Side.SELL, 3, 100)
    engine.order_book.add_order(first)
    engine.order_book.add_order(second)

    trades = engine.submit_order(make_order("B1", Side.BUY, 4, 100))

    assert [trade.sell_order_id for trade in trades] == ["S1", "S2"]
    assert [trade.quantity for trade in trades] == [3, 1]
    assert second.remaining_quantity == 2


def test_trade_ids_increase_across_submissions() -> None:
    engine = MatchingEngine()
    engine.order_book.add_order(make_order("S1", Side.SELL, 2, 100))
    engine.order_book.add_order(make_order("S2", Side.SELL, 2, 101))

    first = engine.submit_order(make_order("B1", Side.BUY, 1, 100))
    second = engine.submit_order(make_order("B2", Side.BUY, 1, 101))

    assert first[0].trade_id == 1
    assert second[0].trade_id == 2


def test_invalid_order_argument_is_rejected() -> None:
    engine = MatchingEngine()
    with pytest.raises(TypeError):
        engine.submit_order("not-an-order")  # type: ignore[arg-type]


def test_filled_order_cannot_be_submitted_again() -> None:
    engine = MatchingEngine()
    order = make_order("B1", Side.BUY, 1, 100)
    order.apply_fill(1)

    with pytest.raises(ValueError, match="filled"):
        engine.submit_order(order)
