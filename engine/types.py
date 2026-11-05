"""Core domain enums for the matching engine."""

from enum import Enum


class Side(str, Enum):
    """The direction of an order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Supported order instructions."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"
