"""Tests for order and trade domain models."""

import pytest
from engine.order import U64_MAX, Order, Trade
from engine.types import OrderType, Side


def test_limit_order_initializes_remaining_quantity() -> None:
    order = Order(
        order_id="buy-1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=10_250,
        quantity=7,
    )
    assert order.remaining_quantity == 7
    assert not order.is_filled
    assert not order.is_cancelled


def test_market_order_has_no_price() -> None:
    order = Order(
        order_id=2,
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=3,
    )
    assert order.price is None
    assert order.remaining_quantity == 3


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (
            {
                "order_id": "x",
                "side": Side.BUY,
                "order_type": OrderType.LIMIT,
                "quantity": 1,
            },
            ValueError,
        ),
        (
            {
                "order_id": "x",
                "side": Side.BUY,
                "order_type": OrderType.LIMIT,
                "price": 0,
                "quantity": 1,
            },
            ValueError,
        ),
        (
            {
                "order_id": "x",
                "side": Side.BUY,
                "order_type": OrderType.MARKET,
                "price": 10,
                "quantity": 1,
            },
            ValueError,
        ),
        (
            {
                "order_id": "x",
                "side": Side.BUY,
                "order_type": OrderType.LIMIT,
                "price": 10,
                "quantity": 0,
            },
            ValueError,
        ),
        (
            {
                "order_id": "x",
                "side": "BUY",
                "order_type": OrderType.LIMIT,
                "price": 10,
                "quantity": 1,
            },
            TypeError,
        ),
        (
            {
                "order_id": "x",
                "side": Side.BUY,
                "order_type": OrderType.LIMIT,
                "price": 1.5,
                "quantity": 1,
            },
            TypeError,
        ),
        (
            {
                "order_id": "x",
                "side": Side.BUY,
                "order_type": OrderType.LIMIT,
                "price": 10,
                "quantity": True,
            },
            TypeError,
        ),
        (
            {
                "order_id": " ",
                "side": Side.BUY,
                "order_type": OrderType.LIMIT,
                "price": 10,
                "quantity": 1,
            },
            ValueError,
        ),
        (
            {
                "order_id": True,
                "side": Side.BUY,
                "order_type": OrderType.LIMIT,
                "price": 10,
                "quantity": 1,
            },
            TypeError,
        ),
    ],
)
def test_invalid_orders_are_rejected(
    kwargs: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        Order(**kwargs)  # type: ignore[arg-type]


def test_order_rejects_values_above_unsigned_64_bit_range() -> None:
    with pytest.raises(ValueError):
        Order(
            order_id="too-large",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=U64_MAX + 1,
            quantity=1,
        )


def test_apply_fill_updates_remaining_quantity() -> None:
    order = Order(
        order_id=1,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=100,
        quantity=5,
    )
    order.apply_fill(2)
    assert order.remaining_quantity == 3
    order.apply_fill(3)
    assert order.remaining_quantity == 0
    assert order.is_filled


@pytest.mark.parametrize("fill_quantity", [0, -1, 6, True, 1.5])
def test_apply_fill_rejects_invalid_quantity(fill_quantity: int) -> None:
    order = Order(
        order_id=1,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=100,
        quantity=5,
    )
    with pytest.raises((TypeError, ValueError)):
        order.apply_fill(fill_quantity)


def test_trade_is_immutable_and_validates_participants() -> None:
    trade = Trade(
        trade_id=1,
        buy_order_id="buy-1",
        sell_order_id="sell-1",
        price=105,
        quantity=2,
        maker_order_id="sell-1",
        taker_order_id="buy-1",
    )
    assert trade.quantity == 2
    with pytest.raises((AttributeError, TypeError)):
        trade.quantity = 3  # type: ignore[misc]


def test_trade_rejects_inconsistent_maker_taker_ids() -> None:
    with pytest.raises(ValueError):
        Trade(
            trade_id=1,
            buy_order_id="buy-1",
            sell_order_id="sell-1",
            price=105,
            quantity=2,
            maker_order_id="other",
            taker_order_id="buy-1",
        )
