import json

import pytest
from engine import OrderType, Side
from engine.event_log import EngineEvent, EventLog, read_events


def test_jsonl_round_trip_and_sequence(tmp_path):
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append_submission(
        order_id="B1", side=Side.BUY, order_type=OrderType.LIMIT, quantity=8, price=100
    )
    log.append_cancellation("B1")
    assert read_events(path) == log.events
    assert [event.sequence for event in log.events] == [1, 2]


def test_reopening_log_continues_sequence(tmp_path):
    path = tmp_path / "events.jsonl"
    EventLog(path).append_cancellation("A")
    EventLog(path).append_cancellation("B")
    assert [event.sequence for event in read_events(path)] == [1, 2]


def test_invalid_sequence_is_rejected(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps({"sequence": 2, "kind": "ORDER_CANCELLED", "order_id": "B1"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expected 1, got 2"):
        read_events(path)


def test_invalid_record_is_rejected(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"kind":"UNKNOWN"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid event at line 1"):
        read_events(path)


def test_market_event_requires_no_price():
    event = EngineEvent(1, "ORDER_SUBMITTED", "M1", Side.BUY, OrderType.MARKET, 3, None)
    assert event.to_dict()["price"] is None
