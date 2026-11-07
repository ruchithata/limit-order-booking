"""Tests for order-book snapshots, ordering, immutability, and safety."""

import pytest
from engine import (
    LevelSnapshot,
    MatchingEngine,
    Order,
    OrderBook,
    OrderBookSnapshot,
    OrderType,
    Side,
)


def make_order(order_id: str, side: Side, price: int, quantity: int) -> Order:
    return Order(order_id, side, OrderType.LIMIT, quantity, price)


def test_empty_book_snapshot() -> None:
    book = OrderBook()
    snapshot = book.get_snapshot()

    assert snapshot.bids == ()
    assert snapshot.asks == ()
    assert len(snapshot.bids) == 0
    assert len(snapshot.asks) == 0
    assert len(snapshot) == 2
    assert snapshot == OrderBookSnapshot(bids=(), asks=())
    assert snapshot == ((), ())

    # Aliases and helper accessors
    assert book.snapshot() == snapshot
    assert book.bids() == ()
    assert book.asks() == ()
    assert book.get_bids() == ()
    assert book.get_asks() == ()

    # Unpacking and indexing
    bids, asks = snapshot
    assert bids == () and asks == ()
    assert snapshot[0] == ()
    assert snapshot[1] == ()
    assert snapshot["bids"] == ()
    assert snapshot["asks"] == ()


def test_empty_matching_engine_snapshot() -> None:
    engine = MatchingEngine()
    snapshot = engine.get_snapshot()

    assert snapshot.bids == ()
    assert snapshot.asks == ()
    assert engine.snapshot() == snapshot
    assert engine.bids() == ()
    assert engine.asks() == ()
    assert engine.best_bid_price() is None
    assert engine.best_ask_price() is None


def test_snapshot_ordering_bids_descending_and_asks_ascending() -> None:
    book = OrderBook()

    # Add bids out of order
    for price in (100, 105, 102, 110, 95):
        book.add_order(make_order(f"B-{price}", Side.BUY, price, 10))

    # Add asks out of order
    for price in (115, 111, 120, 113, 118):
        book.add_order(make_order(f"S-{price}", Side.SELL, price, 5))

    snapshot = book.get_snapshot()

    # Bids must be strictly descending (highest price first)
    bid_prices = [level.price for level in snapshot.bids]
    assert bid_prices == [110, 105, 102, 100, 95]
    assert snapshot.bids[0].price == book.best_bid_price()

    # Asks must be strictly ascending (lowest price first)
    ask_prices = [level.price for level in snapshot.asks]
    assert ask_prices == [111, 113, 115, 118, 120]
    assert snapshot.asks[0].price == book.best_ask_price()


def test_snapshot_aggregates_multiple_orders_at_same_price() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", Side.BUY, 100, 10))
    book.add_order(make_order("B2", Side.BUY, 100, 25))
    book.add_order(make_order("B3", Side.BUY, 100, 15))

    book.add_order(make_order("S1", Side.SELL, 105, 7))
    book.add_order(make_order("S2", Side.SELL, 105, 13))

    snapshot = book.get_snapshot()

    assert len(snapshot.bids) == 1
    assert snapshot.bids[0].price == 100
    assert snapshot.bids[0].quantity == 50

    assert len(snapshot.asks) == 1
    assert snapshot.asks[0].price == 105
    assert snapshot.asks[0].quantity == 20


def test_snapshot_single_side_populated() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", Side.BUY, 100, 10))

    snap = book.get_snapshot()
    assert snap.bids == ((100, 10),)
    assert snap.asks == ()

    book2 = OrderBook()
    book2.add_order(make_order("S1", Side.SELL, 105, 10))

    snap2 = book2.get_snapshot()
    assert snap2.bids == ()
    assert snap2.asks == ((105, 10),)


def test_snapshot_depth_limiting() -> None:
    book = OrderBook()
    for price in (100, 105, 102, 110, 95):
        book.add_order(make_order(f"B-{price}", Side.BUY, price, 10))
    for price in (115, 111, 120, 113, 118):
        book.add_order(make_order(f"S-{price}", Side.SELL, price, 5))

    # depth = 2
    snap2 = book.get_snapshot(depth=2)
    assert [lvl.price for lvl in snap2.bids] == [110, 105]
    assert [lvl.price for lvl in snap2.asks] == [111, 113]

    # depth = 0
    snap0 = book.get_snapshot(depth=0)
    assert snap0.bids == ()
    assert snap0.asks == ()

    # depth larger than active levels
    snap_large = book.get_snapshot(depth=50)
    assert len(snap_large.bids) == 5
    assert len(snap_large.asks) == 5

    # depth via helper methods
    assert book.bids(depth=1) == ((110, 10),)
    assert book.asks(depth=1) == ((111, 5),)


def test_snapshot_depth_zero_returns_empty_sides() -> None:
    engine = MatchingEngine()
    engine.submit_order(
        Order(
            order_id=1,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100,
        )
    )
    snapshot = engine.get_snapshot(depth=0)
    assert snapshot.bids == ()
    assert snapshot.asks == ()


def test_snapshot_negative_depth_raises_value_error() -> None:
    engine = MatchingEngine()
    with pytest.raises(ValueError):
        engine.get_snapshot(depth=-1)


@pytest.mark.parametrize("depth", [True, 1.5, "2"])
def test_snapshot_rejects_invalid_depth_types(depth: object) -> None:
    engine = MatchingEngine()
    with pytest.raises(TypeError):
        engine.get_snapshot(depth=depth)  # type: ignore[arg-type]


def test_snapshot_is_unchanged_after_new_order() -> None:
    engine = MatchingEngine()
    engine.submit_order(
        Order(
            order_id=1,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100,
        )
    )
    old_snapshot = engine.get_snapshot()
    engine.submit_order(
        Order(
            order_id=2,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=5,
            price=99,
        )
    )
    new_snapshot = engine.get_snapshot()
    assert old_snapshot.bids == ((100, 10),)
    assert new_snapshot.bids == ((100, 10), (99, 5))


def test_snapshot_updates_after_order_cancellation() -> None:
    engine = MatchingEngine()
    engine.submit_order(
        Order(
            order_id=1,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100,
        )
    )
    engine.cancel_order(1)
    snapshot = engine.get_snapshot()
    assert snapshot.bids == ()


def test_snapshot_depth_validation() -> None:
    book = OrderBook()
    with pytest.raises(ValueError, match="depth must be non-negative"):
        book.get_snapshot(depth=-1)

    with pytest.raises(TypeError, match="depth must be an integer or None"):
        book.get_snapshot(depth="2")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="depth must be an integer or None"):
        book.get_snapshot(depth=True)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="depth must be an integer or None"):
        book.get_snapshot(depth=1.5)  # type: ignore[arg-type]


def test_snapshot_immutability() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", Side.BUY, 100, 10))
    book.add_order(make_order("S1", Side.SELL, 105, 5))
    snapshot = book.get_snapshot()

    # Cannot mutate snapshot attributes
    with pytest.raises(AttributeError):
        snapshot.bids = ()  # type: ignore[misc]

    with pytest.raises(AttributeError):
        snapshot.asks = ()  # type: ignore[misc]

    with pytest.raises(AttributeError):
        snapshot.new_field = "test"  # type: ignore[attr-defined]

    with pytest.raises(AttributeError):
        del snapshot.bids  # type: ignore[misc]

    # Cannot mutate bids/asks collections
    with pytest.raises(TypeError):
        snapshot.bids[0] = LevelSnapshot(99, 10)  # type: ignore[index]

    with pytest.raises(AttributeError):
        snapshot.bids.append(LevelSnapshot(99, 10))  # type: ignore[attr-defined]

    # Cannot mutate LevelSnapshot attributes or items
    level = snapshot.bids[0]
    with pytest.raises(AttributeError):
        level.price = 99  # type: ignore[misc]

    with pytest.raises(AttributeError):
        level.quantity = 99  # type: ignore[misc]

    with pytest.raises(TypeError):
        level[0] = 99  # type: ignore[index]

    with pytest.raises(AttributeError):
        level.extra = 1  # type: ignore[attr-defined]


def test_modifying_book_does_not_mutate_existing_snapshots() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", Side.BUY, 100, 10))
    snap1 = book.get_snapshot()

    assert snap1.bids == ((100, 10),)

    # Add more orders to book
    book.add_order(make_order("B2", Side.BUY, 100, 5))
    book.add_order(make_order("B3", Side.BUY, 102, 8))
    book.add_order(make_order("S1", Side.SELL, 105, 20))

    snap2 = book.get_snapshot()

    # snap1 MUST remain completely unchanged
    assert snap1.bids == ((100, 10),)
    assert snap1.asks == ()

    # snap2 has the updated state
    assert snap2.bids == ((102, 8), (100, 15))
    assert snap2.asks == ((105, 20),)


def test_taking_snapshot_does_not_mutate_book_or_invariants() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", Side.BUY, 100, 10))
    book.add_order(make_order("S1", Side.SELL, 105, 10))

    assert book.validate_invariants()
    snap = book.get_snapshot()
    assert book.validate_invariants()
    assert len(book) == 2
    assert book.best_bid_price() == 100
    assert book.best_ask_price() == 105

    # Repeated calls return equal snapshots
    assert book.get_snapshot() == snap
    assert book.validate_invariants()


def test_snapshot_reflects_cancellations_and_lazy_tombstones() -> None:
    book = OrderBook()
    book.add_order(make_order("B1", Side.BUY, 100, 10))
    book.add_order(make_order("B2", Side.BUY, 100, 15))
    book.add_order(make_order("B3", Side.BUY, 99, 8))

    # Partial cancellation at level 100
    assert book.cancel_order("B1")
    snap = book.get_snapshot()
    assert snap.bids == ((100, 15), (99, 8))

    # Cancel all orders at level 100
    assert book.cancel_order("B2")
    snap2 = book.get_snapshot()
    # Level 100 should not appear at all (quantity 0 excluded)
    assert snap2.bids == ((99, 8),)


def test_snapshot_reflects_matching_executions() -> None:
    engine = MatchingEngine()
    engine.submit_order(make_order("S1", Side.SELL, 105, 10))
    engine.submit_order(make_order("S2", Side.SELL, 106, 20))

    # Partial execution of best ask
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 4, 105))
    snap = engine.get_snapshot()
    assert snap.asks == ((105, 6), (106, 20))

    # Full execution of remainder of best ask
    engine.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 6, 105))
    snap2 = engine.get_snapshot()
    assert snap2.asks == ((106, 20),)


def test_level_snapshot_tuple_properties_and_validation() -> None:
    lvl = LevelSnapshot(100, 25)
    assert isinstance(lvl, tuple)
    assert lvl.price == 100
    assert lvl.quantity == 25
    assert lvl[0] == 100
    assert lvl[1] == 25
    assert lvl["price"] == 100
    assert lvl["quantity"] == 25
    assert len(lvl) == 2

    price, qty = lvl
    assert price == 100
    assert qty == 25

    assert lvl == (100, 25)
    assert lvl == LevelSnapshot(100, 25)
    assert repr(lvl) == "LevelSnapshot(price=100, quantity=25)"

    # Validation
    with pytest.raises(ValueError, match="price must be a positive integer"):
        LevelSnapshot(0, 10)

    with pytest.raises(ValueError, match="price must be a positive integer"):
        LevelSnapshot(-5, 10)

    with pytest.raises(ValueError, match="price must be a positive integer"):
        LevelSnapshot(True, 10)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="quantity must be a positive integer"):
        LevelSnapshot(100, 0)

    with pytest.raises(ValueError, match="quantity must be a positive integer"):
        LevelSnapshot(100, -1)

    with pytest.raises(ValueError, match="quantity must be a positive integer"):
        LevelSnapshot(100, False)  # type: ignore[arg-type]


def test_order_book_snapshot_constructor_and_repr() -> None:
    snapshot = OrderBookSnapshot(
        bids=[(100, 10), (99, 20)],
        asks=[(105, 5)],
    )
    assert snapshot.bids == ((100, 10), (99, 20))
    assert snapshot.asks == ((105, 5),)
    assert isinstance(snapshot.bids[0], LevelSnapshot)
    assert isinstance(snapshot.asks[0], LevelSnapshot)

    repr_str = repr(snapshot)
    assert "OrderBookSnapshot" in repr_str
    assert "100" in repr_str

    with pytest.raises(TypeError, match="invalid price level in snapshot"):
        OrderBookSnapshot(bids=["invalid"])  # type: ignore[list-item]

    with pytest.raises(KeyError):
        _ = snapshot["unknown"]


def test_order_book_snapshot_rejects_unordered_bids() -> None:
    with pytest.raises(
        ValueError, match="bid levels must be in descending price order"
    ):
        OrderBookSnapshot(bids=[(99, 10), (100, 20)])

    with pytest.raises(
        ValueError, match="bid levels must be in descending price order"
    ):
        OrderBookSnapshot(bids=[(100, 10), (100, 20)])


def test_order_book_snapshot_rejects_unordered_asks() -> None:
    with pytest.raises(ValueError, match="ask levels must be in ascending price order"):
        OrderBookSnapshot(asks=[(110, 5), (105, 10)])

    with pytest.raises(ValueError, match="ask levels must be in ascending price order"):
        OrderBookSnapshot(asks=[(105, 10), (105, 5)])
