"""Public API for the limit order book engine."""

from engine.event_log import EngineEvent, EventLog, read_events
from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderId, Trade
from engine.order_book import (
    LevelSnapshot,
    OrderBook,
    OrderBookSnapshot,
    PriceLevelSnapshot,
)
from engine.persistence import SnapshotManager, load_snapshot, save_snapshot
from engine.recording import RecordingMatchingEngine
from engine.recovery import (
    RecoveryError,
    RecoveryResult,
    recover_engine,
    recover_recording_engine,
    recover_state,
)
from engine.replay import ReplayError, ReplayResult, replay_event_log, replay_events
from engine.snapshot import (
    EngineSnapshot,
    OrderSnapshot,
    Snapshot,
    create_snapshot,
    restore_book_from_snapshot,
    restore_engine_from_snapshot,
)
from engine.types import OrderType, Side

__version__ = "0.1.0"

__all__ = [
    "EngineEvent",
    "EngineSnapshot",
    "EventLog",
    "LevelSnapshot",
    "MatchingEngine",
    "Order",
    "OrderBook",
    "OrderBookSnapshot",
    "OrderId",
    "OrderSnapshot",
    "OrderType",
    "PriceLevelSnapshot",
    "RecordingMatchingEngine",
    "RecoveryError",
    "RecoveryResult",
    "ReplayError",
    "ReplayResult",
    "Side",
    "Snapshot",
    "SnapshotManager",
    "Trade",
    "__version__",
    "create_snapshot",
    "load_snapshot",
    "read_events",
    "recover_engine",
    "recover_recording_engine",
    "recover_state",
    "replay_event_log",
    "replay_events",
    "restore_book_from_snapshot",
    "restore_engine_from_snapshot",
    "save_snapshot",
]
