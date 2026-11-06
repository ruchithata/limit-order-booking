"""In-memory order book with heap-based best-price discovery."""

from heapq import heappop, heappush

from engine.order import Order, OrderId
from engine.order_index import OrderIndex
from engine.price_level import PriceLevel
from engine.types import OrderType, Side


class OrderBook:
    """Organize bid/ask levels, FIFO queues, and active order IDs."""

    def __init__(self) -> None:
        self._bids: dict[int, PriceLevel] = {}
        self._asks: dict[int, PriceLevel] = {}
        self._bid_heap: list[int] = []
        self._ask_heap: list[int] = []
        self._order_index = OrderIndex()

    def __len__(self) -> int:
        return len(self._order_index)

    @property
    def bid_levels(self) -> dict[int, PriceLevel]:
        return self._bids

    @property
    def ask_levels(self) -> dict[int, PriceLevel]:
        return self._asks

    def add_order(self, order: Order) -> None:
        if not isinstance(order, Order):
            raise TypeError("order must be an Order instance")
        if order.order_type is not OrderType.LIMIT:
            raise ValueError("only LIMIT orders can be added to the book")
        if order.is_cancelled or order.is_filled:
            raise ValueError("cancelled or filled orders cannot be added")
        if order.order_id in self._order_index:
            raise ValueError(f"duplicate active order ID: {order.order_id!r}")

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
        self._order_index.add(order, level)

    def get_order(self, order_id: OrderId) -> Order | None:
        entry = self._order_index.get(order_id)
        return entry[0] if entry is not None else None

    def cancel_order(self, order_id: OrderId) -> bool:
        """Cancel an active resting order; return False for unknown IDs."""
        entry = self._order_index.get(order_id)
        if entry is None:
            return False
        order, level = entry
        level.cancel_order(order)
        self._order_index.remove(order_id)
        return True

    def best_bid_price(self) -> int | None:
        level = self.best_bid_level()
        return level.price if level is not None else None

    def best_ask_price(self) -> int | None:
        level = self.best_ask_level()
        return level.price if level is not None else None

    def best_bid_level(self) -> PriceLevel | None:
        return self._best_level(Side.BUY)

    def best_ask_level(self) -> PriceLevel | None:
        return self._best_level(Side.SELL)

    def peek_best_order(self, side: Side) -> Order | None:
        level = self._best_level(side)
        return level.peek_front() if level is not None else None

    def pop_best_order(self, side: Side) -> Order:
        level = self._best_level(side)
        if level is None:
            raise IndexError(f"no {side.value.lower()} orders in the book")
        order = level.pop_front()
        self._order_index.remove(order.order_id)
        if level.is_empty:
            levels = self._bids if side is Side.BUY else self._asks
            del levels[level.price]
        return order

    def _best_level(self, side: Side) -> PriceLevel | None:
        if side is Side.BUY:
            heap, levels, reverse = self._bid_heap, self._bids, True
        elif side is Side.SELL:
            heap, levels, reverse = self._ask_heap, self._asks, False
        else:
            raise TypeError("side must be a Side enum value")
        while True:
            price = self._best_price(heap, levels, reverse=reverse)
            if price is None:
                return None
            level = levels[price]
            if level.peek_front() is not None:
                return level
            del levels[price]

    @staticmethod
    def _best_price(
        heap: list[int], levels: dict[int, PriceLevel], *, reverse: bool
    ) -> int | None:
        while heap:
            heap_price = heap[0]
            price = -heap_price if reverse else heap_price
            if price in levels:
                return price
            heappop(heap)
        return None
