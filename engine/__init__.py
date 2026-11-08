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
from engine.recording import RecordingMatchingEngine
from engine.replay import ReplayError, ReplayResult, replay_event_log, replay_events
from engine.types import OrderType, Side

__version__ = "0.1.0"

__all__ = [
    "EngineEvent",
    "EventLog",
    "LevelSnapshot",
    "MatchingEngine",
    "Order",
    "OrderBook",
    "OrderBookSnapshot",
    "OrderId",
    "OrderType",
    "PriceLevelSnapshot",
    "RecordingMatchingEngine",
    "ReplayError",
    "ReplayResult",
    "Side",
    "Trade",
    "__version__",
    "read_events",
    "replay_event_log",
    "replay_events",
]
