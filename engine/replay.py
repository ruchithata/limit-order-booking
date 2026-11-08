"""Reconstruct a matching engine by replaying its accepted commands."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from engine.event_log import EngineEvent, EventLog, read_events
from engine.matching_engine import MatchingEngine
from engine.order import Order, Trade


class ReplayError(RuntimeError):
    """Raised when a recorded event cannot be applied to a fresh engine."""


@dataclass(frozen=True, slots=True)
class ReplayResult:
    matching_engine: MatchingEngine
    trades: tuple[Trade, ...]
    events_replayed: int


def replay_events(events: Iterable[EngineEvent]) -> ReplayResult:
    engine = MatchingEngine()
    trades: list[Trade] = []
    expected = 1
    for event in events:
        if not isinstance(event, EngineEvent):
            raise TypeError("events must contain EngineEvent instances")
        if event.sequence != expected:
            raise ReplayError(
                f"expected event sequence {expected}, got {event.sequence}"
            )
        try:
            if event.kind == "ORDER_SUBMITTED":
                order = Order(
                    event.order_id,
                    event.side,
                    event.order_type,
                    event.quantity,
                    event.price,
                )
                trades.extend(engine.submit_order(order))
            elif event.kind == "ORDER_CANCELLED":
                if not engine.cancel_order(event.order_id):
                    raise ReplayError(
                        f"cancellation references inactive order {event.order_id!r}"
                    )
            else:
                raise ReplayError(f"unsupported event kind: {event.kind!r}")
        except ReplayError:
            raise
        except (TypeError, ValueError, RuntimeError) as exc:
            raise ReplayError(
                f"failed to replay event {event.sequence}: {exc}"
            ) from exc
        expected += 1
    return ReplayResult(engine, tuple(trades), expected - 1)


def replay_event_log(source: EventLog | str | Path) -> ReplayResult:
    events = source.events if isinstance(source, EventLog) else read_events(source)
    return replay_events(events)
