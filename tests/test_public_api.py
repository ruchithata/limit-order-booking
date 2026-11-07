"""Tests for the engine public API surface."""

import engine
from engine import (
    LevelSnapshot,
    MatchingEngine,
    Order,
    OrderBook,
    OrderBookSnapshot,
    OrderType,
    PriceLevelSnapshot,
    Side,
    Trade,
    __version__,
)
from engine.matching_engine import MatchingEngine as InternalMatchingEngine
from engine.order import Order as InternalOrder
from engine.order import Trade as InternalTrade
from engine.order_book import LevelSnapshot as InternalLevelSnapshot
from engine.order_book import OrderBook as InternalOrderBook
from engine.order_book import OrderBookSnapshot as InternalOrderBookSnapshot
from engine.types import OrderType as InternalOrderType
from engine.types import Side as InternalSide


def test_package_version_exported() -> None:
    assert __version__ == "0.1.0"
    assert engine.__version__ == "0.1.0"


def test_main_classes_are_exported() -> None:
    expected_exports = {
        "Order",
        "Trade",
        "OrderBook",
        "MatchingEngine",
        "Side",
        "OrderType",
        "OrderBookSnapshot",
        "LevelSnapshot",
        "PriceLevelSnapshot",
        "OrderId",
        "__version__",
    }
    assert expected_exports.issubset(set(engine.__all__))
    for name in expected_exports:
        assert hasattr(engine, name), f"Missing public export: {name}"


def test_exported_classes_identity() -> None:
    assert Order is InternalOrder
    assert Trade is InternalTrade
    assert OrderBook is InternalOrderBook
    assert MatchingEngine is InternalMatchingEngine
    assert Side is InternalSide
    assert OrderType is InternalOrderType
    assert OrderBookSnapshot is InternalOrderBookSnapshot
    assert LevelSnapshot is InternalLevelSnapshot
    assert PriceLevelSnapshot is InternalLevelSnapshot


def test_no_private_or_internal_leaks_in_dunder_all() -> None:
    internal_names = {
        "heappop",
        "heappush",
        "deque",
        "PriceLevel",
        "OrderIndex",
        "_bids",
        "_asks",
    }
    for name in internal_names:
        assert name not in engine.__all__


def test_full_workflow_via_public_api() -> None:
    # Set up matching engine entirely via top-level imports
    matching_engine = MatchingEngine()
    assert len(matching_engine) == 0

    # Submit resting limit orders
    buy_order = Order("B1", Side.BUY, OrderType.LIMIT, 10, 100)
    sell_order = Order("S1", Side.SELL, OrderType.LIMIT, 5, 105)
    assert matching_engine.submit_order(buy_order) == []
    assert matching_engine.submit_order(sell_order) == []
    assert len(matching_engine) == 2

    # Inspect order-book snapshot
    snapshot = matching_engine.get_snapshot()
    assert isinstance(snapshot, OrderBookSnapshot)
    assert snapshot.bids == ((100, 10),)
    assert snapshot.asks == ((105, 5),)

    # Submit matching taker order
    market_buy = Order("M1", Side.BUY, OrderType.MARKET, 3)
    trades = matching_engine.submit_order(market_buy)
    assert len(trades) == 1
    trade = trades[0]
    assert isinstance(trade, Trade)
    assert trade.price == 105
    assert trade.quantity == 3
    assert trade.maker_order_id == "S1"
    assert trade.taker_order_id == "M1"

    # Updated snapshot
    updated = matching_engine.get_snapshot()
    assert updated.asks == ((105, 2),)

    # Cancellation
    assert matching_engine.cancel_order("B1")
    assert matching_engine.get_snapshot().bids == ()
