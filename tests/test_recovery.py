"""Tests for order book recovery and consistency."""

from __future__ import annotations

from pathlib import Path

import pytest
from engine import (
    EngineEvent,
    EngineSnapshot,
    EventLog,
    MatchingEngine,
    Order,
    OrderSnapshot,
    OrderType,
    RecordingMatchingEngine,
    RecoveryError,
    Side,
    recover_engine,
    recover_recording_engine,
    recover_state,
    save_snapshot,
)


def test_recovery_from_snapshot_and_events() -> None:
    recorder = RecordingMatchingEngine()

    # 1. Submit resting limit orders
    recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    recorder.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 5, 100))
    recorder.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 8, 105))
    recorder.submit_order(Order("S2", Side.SELL, OrderType.LIMIT, 12, 110))

    # 2. Market order execution (event 5)
    t1 = recorder.submit_order(Order("M1", Side.BUY, OrderType.MARKET, 4))
    assert len(t1) == 1
    assert t1[0].maker_order_id == "S1"
    assert t1[0].quantity == 4

    # 3. Snapshot state at event 5
    snap = recorder.create_snapshot()
    assert snap.last_sequence == 5
    assert snap.next_trade_id == 2
    assert [o.order_id for o in snap.bids] == ["B1", "B2"]
    assert [o.order_id for o in snap.asks] == ["S1", "S2"]
    assert snap.asks[0].remaining_quantity == 4  # S1 partially filled

    # 4. Continue operations on original engine
    recorder.submit_order(Order("B3", Side.BUY, OrderType.LIMIT, 15, 99))  # event 6
    assert recorder.cancel_order("B1")  # event 7
    # Crossing sell sweeps B2 (5 @ 100) and leaves 3 resting at 100 (event 8)
    t2 = recorder.submit_order(Order("S3", Side.SELL, OrderType.LIMIT, 8, 100))
    assert len(t2) == 1
    assert t2[0].maker_order_id == "B2"
    assert t2[0].quantity == 5
    assert recorder.cancel_order("S2")  # event 9

    assert len(recorder.event_log.events) == 9

    # 5. Recover a fresh engine from snapshot (seq 5) + replay newer events (6..9)
    result = recover_state(snapshot=snap, events=recorder.event_log)

    assert result.events_replayed == 4
    assert result.last_sequence == 9
    assert len(result.trades) == 1
    assert result.trades[0] == t2[0]

    recovered = result.matching_engine
    # Compare state between original and recovered engine
    assert recovered.get_snapshot() == recorder.get_snapshot()
    assert recovered.best_bid_price() == recorder.best_bid_price()
    assert recovered.best_ask_price() == recorder.best_ask_price()
    assert recovered.next_trade_id == recorder.next_trade_id
    assert len(recovered) == len(recorder)
    assert recovered.order_book.validate_invariants()


def test_recovery_subsequent_matching_matches_original() -> None:
    recorder = RecordingMatchingEngine()
    recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    recorder.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 10, 105))
    snap = recorder.create_snapshot()

    recorder.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 8, 99))
    recorder.submit_order(Order("S2", Side.SELL, OrderType.LIMIT, 5, 106))

    result = recover_state(snapshot=snap, events=recorder.event_log)
    recovered = result.matching_engine

    # Submit an identical matching taker order to both engines
    incoming1 = Order("TAKER", Side.BUY, OrderType.LIMIT, 12, 106)
    incoming2 = Order("TAKER", Side.BUY, OrderType.LIMIT, 12, 106)

    trades_original = recorder.matching_engine.submit_order(incoming1)
    trades_recovered = recovered.submit_order(incoming2)

    assert trades_original == trades_recovered
    assert recorder.get_snapshot() == recovered.get_snapshot()
    assert recorder.next_trade_id == recovered.next_trade_id
    assert recovered.order_book.validate_invariants()


def test_recovery_snapshot_only_no_events() -> None:
    engine = MatchingEngine()
    engine.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    snap = EngineSnapshot.from_engine(engine, last_sequence=4)

    result = recover_state(snapshot=snap, events=None)
    assert result.events_replayed == 0
    assert result.last_sequence == 4
    assert result.trades == ()
    assert len(result.matching_engine) == 1
    assert result.matching_engine.get_snapshot().bids == ((100, 10),)


def test_recovery_events_only_no_snapshot() -> None:
    log = EventLog()
    log.append_submission(
        order_id="B1", side=Side.BUY, order_type=OrderType.LIMIT, quantity=10, price=100
    )
    log.append_submission(
        order_id="S1", side=Side.SELL, order_type=OrderType.LIMIT, quantity=5, price=100
    )

    result = recover_state(snapshot=None, events=log)
    assert result.events_replayed == 2
    assert result.last_sequence == 2
    assert len(result.trades) == 1
    assert result.trades[0].quantity == 5
    assert result.matching_engine.get_snapshot().bids == ((100, 5),)


def test_recovery_from_file_paths(tmp_path: Path) -> None:
    snap_path = tmp_path / "snapshot.json"
    log_path = tmp_path / "events.jsonl"

    recorder = RecordingMatchingEngine(event_log=EventLog(log_path))
    recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    recorder.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 10, 105))
    save_snapshot(recorder.create_snapshot(), snap_path)

    recorder.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 6, 99))
    recorder.cancel_order("B1")

    # Recover using file paths as strings or Path objects
    result = recover_state(snapshot=snap_path, events=log_path)
    assert result.events_replayed == 2
    assert result.last_sequence == 4
    assert result.matching_engine.get_snapshot().bids == ((99, 6),)
    assert result.matching_engine.get_snapshot().asks == ((105, 10),)


def test_recovery_detects_sequence_gap() -> None:
    snap = EngineSnapshot(last_sequence=5)
    # Events start at 7 instead of expected 6
    gapped_events = [
        EngineEvent(7, "ORDER_SUBMITTED", "B1", Side.BUY, OrderType.LIMIT, 10, 100)
    ]
    with pytest.raises(
        RecoveryError,
        match="sequence gap during recovery: expected sequence 6, got 7",
    ):
        recover_state(snapshot=snap, events=gapped_events)


def test_recovery_handles_invalid_cancellation() -> None:
    snap = EngineSnapshot(last_sequence=1)
    # Event 2 cancels order that was never in snapshot or added
    events = [EngineEvent(2, "ORDER_CANCELLED", "MISSING")]
    with pytest.raises(RecoveryError, match="cancellation references inactive order"):
        recover_state(snapshot=snap, events=events)


def test_recover_recording_engine_continues_logging(tmp_path: Path) -> None:
    snap_path = tmp_path / "snap.json"
    log_path = tmp_path / "events.jsonl"

    recorder = RecordingMatchingEngine(event_log=EventLog(log_path))
    recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    recorder.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 5, 105))
    recorder.save_snapshot(snap_path)

    recorder.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 8, 98))

    # Recover recording engine from snapshot + log
    recovered_recorder = recover_recording_engine(
        snapshot=snap_path, event_log=log_path
    )
    assert len(recovered_recorder) == 3

    # Subsequent order continues appending with next sequence (seq 4)
    recovered_recorder.submit_order(Order("B3", Side.BUY, OrderType.LIMIT, 2, 97))
    assert len(recovered_recorder.event_log.events) == 4
    assert recovered_recorder.event_log.events[-1].sequence == 4
    assert recovered_recorder.event_log.events[-1].order_id == "B3"


def test_recover_engine_convenience_function() -> None:
    snap = EngineSnapshot(
        bids=(OrderSnapshot("B1", Side.BUY, OrderType.LIMIT, 10, 100),),
        asks=(),
        last_sequence=1,
    )
    engine = recover_engine(snapshot=snap)
    assert isinstance(engine, MatchingEngine)
    assert engine.best_bid_price() == 100
    assert engine.order_book.validate_invariants()


def test_recovery_type_validation() -> None:
    with pytest.raises(TypeError, match="snapshot must be"):
        recover_state(snapshot=123)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="events must be"):
        recover_state(snapshot=None, events=123)  # type: ignore[arg-type]

    snap = EngineSnapshot()
    with pytest.raises(TypeError, match="expected EngineEvent"):
        recover_state(snapshot=snap, events=["not-an-event"])  # type: ignore[list-item]
