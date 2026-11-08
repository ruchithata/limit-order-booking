import pytest
from engine import Order, OrderType, Side
from engine.event_log import EventLog
from engine.recording import RecordingMatchingEngine
from engine.replay import ReplayError, replay_event_log, replay_events


def test_replay_reconstructs_book_and_trade_history():
    recorder = RecordingMatchingEngine()
    recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
    recorder.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 8, 105))
    original_trades = recorder.submit_order(Order("M1", Side.BUY, OrderType.MARKET, 5))
    assert recorder.cancel_order("B1")

    replay = replay_event_log(recorder.event_log)
    assert replay.matching_engine.get_snapshot() == recorder.get_snapshot()
    assert replay.trades == tuple(original_trades)
    assert replay.trades[0].trade_id == 1
    assert replay.events_replayed == 4


def test_only_successful_commands_are_recorded():
    recorder = RecordingMatchingEngine()
    assert not recorder.cancel_order("missing")
    recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 2, 100))
    with pytest.raises(ValueError):
        recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 1, 99))
    assert len(recorder.event_log.events) == 1


def test_replay_from_file(tmp_path):
    path = tmp_path / "log" / "events.jsonl"
    recorder = RecordingMatchingEngine(event_log=EventLog(path))
    recorder.submit_order(Order("A1", Side.SELL, OrderType.LIMIT, 4, 110))
    result = replay_event_log(path)
    assert result.matching_engine.get_snapshot().asks == ((110, 4),)


def test_replay_rejects_cancellation_of_inactive_order():
    log = EventLog()
    log.append_cancellation("missing")
    with pytest.raises(ReplayError, match="inactive order"):
        replay_events(log.events)


def test_empty_replay():
    result = replay_events(())
    assert result.events_replayed == 0
    assert result.matching_engine.get_snapshot().bids == ()
