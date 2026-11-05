"""In-memory order book with heap-based best-price discovery."""

from heapq import heappop, heappush

from engine.order import Order
from engine.price_level import PriceLevel
from engine.types import OrderType, Side


class OrderBook:
    """Organize bid/ask price levels and FIFO queues.

    Bid prices are negated in the heap to put the highest bid first.
    Ask prices are stored normally to put the lowest ask first.
    Empty price levels are removed from the maps; stale heap entries are
    discarded lazily when the relevant side is queried.
    """

    def __init__(self) -> None:
        self._bids: dict[int, PriceLevel] = {}
        self._asks: dict[int, PriceLevel] = {}
        self._bid_heap: list[int] = []
        self._ask_heap: list[int] = []

    def __len__(self) -> int:
        return sum(map(len, self._bids.values())) + sum(map(len, self._asks.values()))

    @property
    def bid_levels(self) -> dict[int, PriceLevel]:
        """Current bid levels, keyed by price."""
        return self._bids

    @property
    def ask_levels(self) -> dict[int, PriceLevel]:
        """Current ask levels, keyed by price."""
        return self._asks

    def add_order(self, order: Order) -> None:
        """Add a limit order to its side and price level."""
        if not isinstance(order, Order):
            raise TypeError("order must be an Order instance")
        if order.order_type is not OrderType.LIMIT:
            raise ValueError("only LIMIT orders can be added to the book")
        if order.is_cancelled or order.is_filled:
            raise ValueError("cancelled or filled orders cannot be added")

        if order.side is Side.BUY:
            levels, heap, heap_price = self._bids, self._bid_heap, -order.price
        else:
            levels, heap, heap_price = self._asks, self._ask_heap, order.price

        level = levels.get(order.price)
        if level is None:
            level = PriceLevel(price=order.price, side=order.side)
            levels[order.price] = level
            heappush(heap, heap_price)
        level.add_order(order)

    def best_bid_price(self) -> int | None:
        """Return the highest bid, or None if no bids exist."""
        return self._best_price(self._bid_heap, self._bids, reverse=True)

    def best_ask_price(self) -> int | None:
        """Return the lowest ask, or None if no asks exist."""
        return self._best_price(self._ask_heap, self._asks, reverse=False)

    def best_bid_level(self) -> PriceLevel | None:
        price = self.best_bid_price()
        return self._bids.get(price) if price is not None else None

    def best_ask_level(self) -> PriceLevel | None:
        price = self.best_ask_price()
        return self._asks.get(price) if price is not None else None

    def peek_best_order(self, side: Side) -> Order | None:
        """Peek at the oldest order at the best price on a side."""
        if side is Side.BUY:
            level = self.best_bid_level()
        elif side is Side.SELL:
            level = self.best_ask_level()
        else:
            raise TypeError("side must be a Side enum value")
        return level.peek_front() if level is not None else None

    def pop_best_order(self, side: Side) -> Order:
        """Remove the oldest order at the best price on a side."""
        if side is Side.BUY:
            levels, level = self._bids, self.best_bid_level()
        elif side is Side.SELL:
            levels, level = self._asks, self.best_ask_level()
        else:
            raise TypeError("side must be a Side enum value")

        if level is None:
            raise IndexError(f"no {side.value.lower()} orders in the book")

        order = level.pop_front()
        if level.is_empty:
            del levels[level.price]
            # The corresponding heap entry is cleaned up lazily.
        return order

    @staticmethod
    def _best_price(
        heap: list[int],
        levels: dict[int, PriceLevel],
        *,
        reverse: bool,
    ) -> int | None:
        while heap:
            heap_price = heap[0]
            price = -heap_price if reverse else heap_price
            if price in levels:
                return price
            heappop(heap)
        return None
