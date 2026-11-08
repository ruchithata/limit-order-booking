"""Tests for engine state snapshotting, serialization, and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine import (
    EngineSnapshot,
    MatchingEngine,
    Order,
    OrderSnapshot,
    OrderType,
    RecordingMatchingEngine,
    Side,
    Snapshot,
    SnapshotManager,
    create_snapshot,
    load_snapshot,
    restore_book_from_snapshot,
    restore_engine_from_snapshot,
    save_snapshot,
)


def test_order_snapshot_construction_and_validation() -> None:
    snap = OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 100, 10)
    assert snap.order_id == "B1"
    assert snap.side is Side.BUY
    assert snap.order_type is OrderType.LIMIT
    assert snap.quantity == 10
    assert snap.price == 100
    assert snap.remaining_quantity == 10

    # Default remaining_quantity equals quantity
    snap_default = OrderSnapshot("B2", Side.BUY, OrderType.LIMIT, 15, 100)
    assert snap_default.remaining_quantity == 15

    # Immutability
    with pytest.raises((AttributeError, TypeError)):
        snap.price = 105  # type: ignore[misc]

    # Validation
    with pytest.raises(
        ValueError, match="remaining_quantity cannot exceed initial quantity"
    ):
        OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 100, 15)

    with pytest.raises(ValueError, match="only LIMIT orders"):
        OrderSnapshot("M1", Side.BUY, OrderType.MARKET, 10, 100)

    with pytest.raises(ValueError, match="price must be positive"):
        OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 0)

    with pytest.raises(ValueError, match="quantity must be positive"):
        OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 0, 100)

    with pytest.raises(TypeError, match="side must be a Side"):
        OrderSnapshot("B1", "BUY", OrderType.LIMIT, 10, 100)  # type: ignore[arg-type]


def test_order_snapshot_from_and_to_order() -> None:
    order = Order("B1", Side.BUY, OrderType.LIMIT, 20, 100)
    order.apply_fill(5)
    assert order.remaining_quantity == 15

    snap = OrderSnapshot.from_order(order)
    assert snap.quantity == 20
    assert snap.remaining_quantity == 15

    restored = snap.to_order()
    assert restored.order_id == "B1"
    assert restored.side is Side.BUY
    assert restored.order_type is OrderType.LIMIT
    assert restored.quantity == 20
    assert restored.price == 100
    assert restored.remaining_quantity == 15
    assert not restored.is_filled
    assert not restored.is_cancelled

    # Reject filled or cancelled orders
    order.cancel()
    with pytest.raises(ValueError, match="cancelled"):
        OrderSnapshot.from_order(order)

    filled = Order("B2", Side.BUY, OrderType.LIMIT, 5, 100)
    filled.apply_fill(5)
    with pytest.raises(ValueError, match="filled"):
        OrderSnapshot.from_order(filled)


def test_order_snapshot_dict_round_trip() -> None:
    snap = OrderSnapshot("S1", Side.SELL, OrderType.LIMIT, 50, 200, 35)
    d = snap.to_dict()
    assert d == {
        "order_id": "S1",
        "side": "SELL",
        "order_type": "LIMIT",
        "quantity": 50,
        "price": 200,
        "remaining_quantity": 35,
    }

    roundtripped = OrderSnapshot.from_dict(d)
    assert roundtripped == snap

    with pytest.raises(TypeError, match="must be a dict"):
        OrderSnapshot.from_dict("not-a-dict")

    with pytest.raises(ValueError, match="missing or unknown fields"):
        OrderSnapshot.from_dict({"order_id": "S1"})


def test_engine_snapshot_empty() -> None:
    engine = MatchingEngine()
    snap = EngineSnapshot.from_engine(engine)
    assert snap.bids == ()
    assert snap.asks == ()
    assert snap.next_trade_id == 1
    assert snap.last_sequence == 0

    restored = snap.restore_engine()
    assert len(restored) == 0
    assert restored.best_bid_price() is None
    assert restored.best_ask_price() is None
    assert restored.order_book.validate_invariants()


def test_engine_snapshot_preserves_orders_and_fifo_levels() -> None:
    engine = MatchingEngine()
    # Add bids across multiple price levels, multiple orders per level
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    engine.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 5, 100))
    engine.submit_order(Order("B3", Side.BUY, OrderType.LIMIT, 20, 99))
    engine.submit_order(Order("B4", Side.BUY, OrderType.LIMIT, 8, 98))

    # Add asks across multiple price levels, multiple orders per level
    engine.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 12, 105))
    engine.submit_order(Order("S2", Side.SELL, OrderType.LIMIT, 7, 105))
    engine.submit_order(Order("S3", Side.SELL, OrderType.LIMIT, 15, 106))

    snap = create_snapshot(engine, last_sequence=7)
    assert snap.last_sequence == 7
    assert snap.next_trade_id == 1

    # Bids descending by price, FIFO within level
    bid_ids = [o.order_id for o in snap.bids]
    assert bid_ids == ["B1", "B2", "B3", "B4"]
    bid_prices = [o.price for o in snap.bids]
    assert bid_prices == [100, 100, 99, 98]

    # Asks ascending by price, FIFO within level
    ask_ids = [o.order_id for o in snap.asks]
    assert ask_ids == ["S1", "S2", "S3"]
    ask_prices = [o.price for o in snap.asks]
    assert ask_prices == [105, 105, 106]

    # Restore into fresh engine
    restored = restore_engine_from_snapshot(snap)
    assert len(restored) == 7
    assert restored.best_bid_price() == 100
    assert restored.best_ask_price() == 105
    assert restored.order_book.validate_invariants()

    # Verify FIFO priority is preserved during execution on restored engine
    trades = restored.submit_order(Order("M_SELL", Side.SELL, OrderType.LIMIT, 12, 100))
    assert len(trades) == 2
    assert trades[0].maker_order_id == "B1"
    assert trades[0].quantity == 10
    assert trades[1].maker_order_id == "B2"
    assert trades[1].quantity == 2

    # B2 now has 3 remaining
    b2 = restored.get_order("B2")
    assert b2 is not None
    assert b2.remaining_quantity == 3
    assert restored.get_order("B1") is None
    assert restored.order_book.validate_invariants()


def test_engine_snapshot_excludes_cancelled_and_filled_orders() -> None:
    engine = MatchingEngine()
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    engine.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 5, 100))
    engine.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 8, 105))
    engine.submit_order(Order("S2", Side.SELL, OrderType.LIMIT, 10, 110))

    # Cancel B1
    assert engine.cancel_order("B1")
    # Fully match S1
    trades = engine.submit_order(Order("B3", Side.BUY, OrderType.LIMIT, 8, 105))
    assert len(trades) == 1
    assert trades[0].maker_order_id == "S1"

    snap = EngineSnapshot.from_engine(engine)
    assert [o.order_id for o in snap.bids] == ["B2"]
    assert [o.order_id for o in snap.asks] == ["S2"]
    assert snap.next_trade_id == 2

    restored = snap.restore_engine()
    assert len(restored) == 2
    assert restored.get_order("B1") is None
    assert restored.get_order("S1") is None
    assert restored.get_order("B2") is not None
    assert restored.get_order("S2") is not None
    assert restored.order_book.validate_invariants()


def test_engine_snapshot_preserves_partially_filled_order() -> None:
    engine = MatchingEngine()
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    # Partially fill B1
    trades = engine.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 4, 100))
    assert len(trades) == 1

    b1 = engine.get_order("B1")
    assert b1 is not None
    assert b1.quantity == 10
    assert b1.remaining_quantity == 6

    snap = EngineSnapshot.from_engine(engine)
    assert len(snap.bids) == 1
    assert snap.bids[0].quantity == 10
    assert snap.bids[0].remaining_quantity == 6

    restored = snap.restore_engine()
    restored_b1 = restored.get_order("B1")
    assert restored_b1 is not None
    assert restored_b1.quantity == 10
    assert restored_b1.remaining_quantity == 6
    assert restored.get_snapshot().bids == ((100, 6),)
    assert restored.order_book.validate_invariants()


def test_engine_snapshot_preserves_trade_ids() -> None:
    engine = MatchingEngine()
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    engine.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 2, 100))
    engine.submit_order(Order("S2", Side.SELL, OrderType.LIMIT, 3, 100))
    assert engine.next_trade_id == 3

    snap = EngineSnapshot.from_engine(engine)
    assert snap.next_trade_id == 3

    restored = snap.restore_engine()
    assert restored.next_trade_id == 3

    # Subsequent matching on restored engine produces trade_id=3
    trades = restored.submit_order(Order("S3", Side.SELL, OrderType.LIMIT, 1, 100))
    assert len(trades) == 1
    assert trades[0].trade_id == 3
    assert restored.next_trade_id == 4


def test_engine_snapshot_validation() -> None:
    # Crossed book
    with pytest.raises(ValueError, match="crossed order book"):
        EngineSnapshot(
            bids=(OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 105),),
            asks=(OrderSnapshot("S1", Side.SELL, OrderType.LIMIT, 10, 100),),
        )

    # Equal best bid and ask (crossed)
    with pytest.raises(ValueError, match="crossed order book"):
        EngineSnapshot(
            bids=(OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 100),),
            asks=(OrderSnapshot("S1", Side.SELL, OrderType.LIMIT, 10, 100),),
        )

    # Unordered bids
    with pytest.raises(ValueError, match="non-ascending"):
        EngineSnapshot(
            bids=(
                OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 99),
                OrderSnapshot("B2", Side.BUY, OrderType.LIMIT, 10, 100),
            ),
            asks=(),
        )

    # Unordered asks
    with pytest.raises(ValueError, match="non-descending"):
        EngineSnapshot(
            bids=(),
            asks=(
                OrderSnapshot("S1", Side.SELL, OrderType.LIMIT, 10, 105),
                OrderSnapshot("S2", Side.SELL, OrderType.LIMIT, 10, 101),
            ),
        )

    # Duplicate order ID across sides
    with pytest.raises(ValueError, match="duplicate order_id"):
        EngineSnapshot(
            bids=(OrderSnapshot("ID1", Side.BUY, OrderType.LIMIT, 10, 90),),
            asks=(OrderSnapshot("ID1", Side.SELL, OrderType.LIMIT, 10, 110),),
        )

    # Wrong side in bids
    with pytest.raises(ValueError, match="non-BUY"):
        EngineSnapshot(
            bids=(OrderSnapshot("S1", Side.SELL, OrderType.LIMIT, 10, 90),),
            asks=(),
        )

    # Wrong side in asks
    with pytest.raises(ValueError, match="non-SELL"):
        EngineSnapshot(
            bids=(),
            asks=(OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 110),),
        )


def test_engine_snapshot_json_round_trip() -> None:
    snap = EngineSnapshot(
        bids=(
            OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 100),
            OrderSnapshot("B2", Side.BUY, OrderType.LIMIT, 5, 99, 3),
        ),
        asks=(OrderSnapshot("S1", Side.SELL, OrderType.LIMIT, 8, 105),),
        next_trade_id=4,
        last_sequence=12,
    )
    raw_json = snap.to_json()
    parsed = json.loads(raw_json)
    assert parsed["version"] == 1
    assert parsed["next_trade_id"] == 4
    assert parsed["last_sequence"] == 12
    assert len(parsed["bids"]) == 2
    assert len(parsed["asks"]) == 1

    restored_snap = EngineSnapshot.from_json(raw_json)
    assert restored_snap == snap
    assert restored_snap.bids == snap.bids
    assert restored_snap.asks == snap.asks
    assert restored_snap.next_trade_id == snap.next_trade_id
    assert restored_snap.last_sequence == snap.last_sequence

    # Rejection of invalid JSON
    with pytest.raises(ValueError, match="invalid JSON"):
        EngineSnapshot.from_json("{corrupted json")

    # Rejection of unsupported version
    with pytest.raises(ValueError, match="unsupported snapshot version"):
        EngineSnapshot.from_dict(
            {
                "version": 99,
                "last_sequence": 0,
                "next_trade_id": 1,
                "bids": [],
                "asks": [],
            }
        )


def test_snapshot_persistence_save_and_load(tmp_path: Path) -> None:
    snap_file = tmp_path / "snapshots" / "market.json"
    engine = MatchingEngine()
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    engine.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 5, 105))

    snap = EngineSnapshot.from_engine(engine, last_sequence=2)
    saved_path = save_snapshot(snap, snap_file)
    assert saved_path == snap_file
    assert snap_file.is_file()

    loaded = load_snapshot(snap_file)
    assert loaded == snap

    # Load non-existent file
    with pytest.raises(FileNotFoundError):
        load_snapshot(tmp_path / "does_not_exist.json")

    # Type validation
    with pytest.raises(TypeError, match="must be an EngineSnapshot"):
        save_snapshot("not-a-snapshot", snap_file)  # type: ignore[arg-type]


def test_snapshot_manager(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path / "snaps")
    assert manager.latest() is None
    assert manager.list_snapshots() == []

    snap1 = EngineSnapshot(last_sequence=1)
    snap2 = EngineSnapshot(last_sequence=2)

    manager.save(snap1)
    manager.save(snap2)

    snapshots = manager.list_snapshots()
    assert len(snapshots) == 2
    assert snapshots[0].name == "snapshot_00000001.json"
    assert snapshots[1].name == "snapshot_00000002.json"

    latest = manager.latest()
    assert latest is not None
    assert latest.last_sequence == 2

    loaded1 = manager.load("snapshot_00000001.json")
    assert loaded1.last_sequence == 1


def test_engine_convenience_methods(tmp_path: Path) -> None:
    engine = MatchingEngine()
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    snap = engine.create_snapshot(last_sequence=1)
    assert snap.last_sequence == 1
    assert len(snap.bids) == 1

    path = tmp_path / "engine_snap.json"
    engine.save_snapshot(path, last_sequence=1)
    assert path.is_file()
    assert load_snapshot(path).last_sequence == 1

    # RecordingMatchingEngine
    recorder = RecordingMatchingEngine()
    recorder.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 5, 100))
    assert recorder.next_trade_id == 1
    assert len(recorder.order_book) == 1
    rec_snap = recorder.create_snapshot()
    assert rec_snap.last_sequence == 1

    rec_path = tmp_path / "recorder_snap.json"
    recorder.save_snapshot(rec_path)
    assert load_snapshot(rec_path).last_sequence == 1


def test_restore_book_from_snapshot() -> None:
    snap = EngineSnapshot(
        bids=(OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 100),),
        asks=(OrderSnapshot("S1", Side.SELL, OrderType.LIMIT, 5, 105),),
    )
    book = restore_book_from_snapshot(snap)
    assert len(book) == 2
    assert book.best_bid_price() == 100
    assert book.best_ask_price() == 105
    assert book.validate_invariants()

    with pytest.raises(TypeError):
        restore_book_from_snapshot("invalid")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        restore_engine_from_snapshot("invalid")  # type: ignore[arg-type]


def test_snapshot_alias() -> None:
    assert Snapshot is EngineSnapshot
