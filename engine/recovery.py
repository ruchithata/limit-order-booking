"""Restore engine state from snapshots and replay subsequent events."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from engine.event_log import EngineEvent, EventLog, read_events
from engine.matching_engine import MatchingEngine
from engine.order import Order, Trade
from engine.persistence import load_snapshot
from engine.recording import RecordingMatchingEngine
from engine.replay import ReplayError
from engine.snapshot import EngineSnapshot


class RecoveryError(ReplayError):
    """Raised when engine state recovery fails."""


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Result of state restoration and subsequent event replay."""

    matching_engine: MatchingEngine
    snapshot: EngineSnapshot | None
    trades: tuple[Trade, ...]
    events_replayed: int
    last_sequence: int


def recover_state(
    snapshot: EngineSnapshot | str | Path | None = None,
    events: Iterable[EngineEvent] | EventLog | str | Path | None = None,
) -> RecoveryResult:
    """Restore engine state from a snapshot and replay newer events.

    Events with sequence <= snapshot.last_sequence are skipped because their
    effects are already included in the snapshot. Events after the snapshot
    are replayed sequentially.
    """
    snap: EngineSnapshot | None = None
    if snapshot is not None:
        if isinstance(snapshot, (str, Path)):
            snap = load_snapshot(snapshot)
        elif isinstance(snapshot, EngineSnapshot):
            snap = snapshot
        else:
            raise TypeError("snapshot must be an EngineSnapshot, str, Path, or None")
        engine = snap.restore_engine()
        last_seq = snap.last_sequence
    else:
        engine = MatchingEngine()
        last_seq = 0

    event_list: list[EngineEvent] = []
    if events is not None:
        if isinstance(events, (str, Path)):
            event_list = list(read_events(events))
        elif isinstance(events, EventLog):
            event_list = list(events.events)
        elif isinstance(events, Iterable):
            event_list = list(events)
        else:
            raise TypeError(
                "events must be an Iterable[EngineEvent], EventLog, path, or None"
            )

    trades: list[Trade] = []
    replayed_count = 0
    expected_seq = last_seq + 1

    for event in event_list:
        if not isinstance(event, EngineEvent):
            raise TypeError(
                f"expected EngineEvent instance, got {type(event).__name__}"
            )

        if event.sequence <= last_seq:
            continue

        if event.sequence != expected_seq:
            raise RecoveryError(
                f"sequence gap during recovery: expected sequence {expected_seq}, "
                f"got {event.sequence}"
            )

        try:
            if event.kind == "ORDER_SUBMITTED":
                order = Order(
                    order_id=event.order_id,
                    side=event.side,  # type: ignore[arg-type]
                    order_type=event.order_type,  # type: ignore[arg-type]
                    quantity=event.quantity,  # type: ignore[arg-type]
                    price=event.price,
                )
                trades.extend(engine.submit_order(order))
            elif event.kind == "ORDER_CANCELLED":
                if not engine.cancel_order(event.order_id):
                    raise RecoveryError(
                        f"cancellation references inactive order {event.order_id!r}"
                    )
            else:
                raise RecoveryError(f"unsupported event kind: {event.kind!r}")
        except RecoveryError:
            raise
        except Exception as exc:
            raise RecoveryError(
                f"failed to replay event {event.sequence}: {exc}"
            ) from exc

        expected_seq += 1
        replayed_count += 1

    engine.order_book.validate_invariants()
    final_sequence = expected_seq - 1

    return RecoveryResult(
        matching_engine=engine,
        snapshot=snap,
        trades=tuple(trades),
        events_replayed=replayed_count,
        last_sequence=final_sequence,
    )


def recover_engine(
    snapshot: EngineSnapshot | str | Path | None = None,
    events: Iterable[EngineEvent] | EventLog | str | Path | None = None,
) -> MatchingEngine:
    """Recover and return a reconstructed MatchingEngine."""
    return recover_state(snapshot=snapshot, events=events).matching_engine


def recover_recording_engine(
    snapshot: EngineSnapshot | str | Path | None = None,
    event_log: EventLog | str | Path | None = None,
) -> RecordingMatchingEngine:
    """Recover an engine and wrap it in a RecordingMatchingEngine.

    Subsequent commands continue appending to the given or newly created event log.
    """
    result = recover_state(snapshot=snapshot, events=event_log)
    if isinstance(event_log, EventLog):
        log = event_log
    elif isinstance(event_log, (str, Path)):
        log = EventLog(event_log)
    else:
        log = EventLog()
    return RecordingMatchingEngine(
        matching_engine=result.matching_engine,
        event_log=log,
    )
