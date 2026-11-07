"""In-memory order book with heap-based best-price discovery."""

from collections.abc import Iterable, Iterator
from heapq import heappop, heappush
from typing import Any

from engine.order import Order, OrderId
from engine.order_index import OrderIndex
from engine.price_level import PriceLevel
from engine.types import OrderType, Side


class LevelSnapshot(tuple):
    """An immutable price level containing price and aggregate quantity."""

    __slots__ = ()

    def __new__(cls, price: int, quantity: int) -> "LevelSnapshot":
        if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
            raise ValueError("price must be a positive integer")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        return super().__new__(cls, (price, quantity))

    @property
    def price(self) -> int:
        """The price tick of this level."""
        return self[0]

    @property
    def quantity(self) -> int:
        """The aggregate available quantity across active orders at this price."""
        return self[1]

    def __getitem__(self, item: Any) -> Any:
        if item == "price":
            return self[0]
        if item == "quantity":
            return self[1]
        return super().__getitem__(item)

    def __repr__(self) -> str:
        return f"LevelSnapshot(price={self[0]}, quantity={self[1]})"


PriceLevelSnapshot = LevelSnapshot


class OrderBookSnapshot:
    """An immutable point-in-time snapshot of the order book's bids and asks.

    Bids are ordered descending by price (highest bid first).
    Asks are ordered ascending by price (lowest ask first).
    """

    __slots__ = ("_bids", "_asks")

    def __init__(
        self,
        bids: Iterable[Any] = (),
        asks: Iterable[Any] = (),
    ) -> None:
        def _to_levels(items: Iterable[Any]) -> tuple[LevelSnapshot, ...]:
            levels: list[LevelSnapshot] = []
            for item in items:
                if isinstance(item, LevelSnapshot):
                    levels.append(item)
                elif isinstance(item, (tuple, list)) and len(item) == 2:
                    levels.append(LevelSnapshot(item[0], item[1]))
                else:
                    raise TypeError(f"invalid price level in snapshot: {item!r}")
            return tuple(levels)

        object.__setattr__(self, "_bids", _to_levels(bids))
        object.__setattr__(self, "_asks", _to_levels(asks))

        if any(
            self._bids[i].price <= self._bids[i + 1].price
            for i in range(len(self._bids) - 1)
        ):
            raise ValueError("bid levels must be in descending price order")
        if any(
            self._asks[i].price >= self._asks[i + 1].price
            for i in range(len(self._asks) - 1)
        ):
            raise ValueError("ask levels must be in ascending price order")

    @property
    def bids(self) -> tuple[LevelSnapshot, ...]:
        """Active bid price levels in descending price order."""
        return self._bids

    @property
    def asks(self) -> tuple[LevelSnapshot, ...]:
        """Active ask price levels in ascending price order."""
        return self._asks

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"{self.__class__.__name__} is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{self.__class__.__name__} is immutable")

    def __iter__(self) -> Iterator[tuple[LevelSnapshot, ...]]:
        yield self._bids
        yield self._asks

    def __getitem__(self, item: Any) -> Any:
        if item == "bids" or item == 0:
            return self._bids
        if item == "asks" or item == 1:
            return self._asks
        raise KeyError(item) if isinstance(item, str) else IndexError(item)

    def __len__(self) -> int:
        return 2

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, OrderBookSnapshot):
            return self._bids == other._bids and self._asks == other._asks
        if isinstance(other, tuple) and len(other) == 2:
            return (self._bids, self._asks) == other
        return False

    def __hash__(self) -> int:
        return hash((self._bids, self._asks))

    def __repr__(self) -> str:
        return f"OrderBookSnapshot(bids={self._bids!r}, asks={self._asks!r})"


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

    def get_snapshot(self, depth: int | None = None) -> OrderBookSnapshot:
        """Return an immutable snapshot of the order book's bids and asks.

        Bids are ordered descending by price (highest price first).
        Asks are ordered ascending by price (lowest price first).
        Only price levels with active (unfilled, non-cancelled) quantity are included.
        """
        if depth is not None:
            if isinstance(depth, bool) or not isinstance(depth, int):
                raise TypeError("depth must be an integer or None")
            if depth < 0:
                raise ValueError("depth must be non-negative")

        bid_prices = sorted(
            (price for price, level in self._bids.items() if level.total_quantity > 0),
            reverse=True,
        )
        ask_prices = sorted(
            price for price, level in self._asks.items() if level.total_quantity > 0
        )

        if depth is not None:
            bid_prices = bid_prices[:depth]
            ask_prices = ask_prices[:depth]

        bids = tuple(
            LevelSnapshot(price, self._bids[price].total_quantity)
            for price in bid_prices
        )
        asks = tuple(
            LevelSnapshot(price, self._asks[price].total_quantity)
            for price in ask_prices
        )
        return OrderBookSnapshot(bids=bids, asks=asks)

    def snapshot(self, depth: int | None = None) -> OrderBookSnapshot:
        """Alias for get_snapshot."""
        return self.get_snapshot(depth=depth)

    def bids(self, depth: int | None = None) -> tuple[LevelSnapshot, ...]:
        """Return an immutable snapshot of active bid levels."""
        return self.get_snapshot(depth=depth).bids

    def asks(self, depth: int | None = None) -> tuple[LevelSnapshot, ...]:
        """Return an immutable snapshot of active ask levels."""
        return self.get_snapshot(depth=depth).asks

    get_bids = bids
    get_asks = asks

    def validate_invariants(self) -> bool:
        """Raise AssertionError if internal book structures disagree.

        This diagnostic is intended for tests and debugging, not the matching
        hot path. Stale heap entries are allowed because heap cleanup is lazy.
        """
        active_orders: dict[OrderId, tuple[Order, PriceLevel]] = {}
        bid_heap_prices = {-price for price in self._bid_heap}
        ask_heap_prices = set(self._ask_heap)

        for side, levels, heap_prices in (
            (Side.BUY, self._bids, bid_heap_prices),
            (Side.SELL, self._asks, ask_heap_prices),
        ):
            for price, level in levels.items():
                assert level.price == price, "price-level key does not match price"
                assert level.side is side, "price level is stored on the wrong side"
                assert price in heap_prices, "active price level is missing from heap"

                expected_quantity = 0
                for order in level.orders:
                    if order.is_cancelled:
                        continue
                    assert not order.is_filled, "filled order remains in a price level"
                    assert order.side is side, "order is stored on the wrong side"
                    assert order.price == price, "order is stored at the wrong price"
                    assert order.order_id not in active_orders, (
                        "duplicate active order ID"
                    )
                    expected_quantity += order.remaining_quantity
                    active_orders[order.order_id] = (order, level)

                assert level.total_quantity == expected_quantity, (
                    f"quantity mismatch at {side.value} price {price}: "
                    f"{level.total_quantity} != {expected_quantity}"
                )

        indexed = self._order_index._entries
        assert set(indexed) == set(active_orders), "order index IDs do not match book"
        for order_id, (order, level) in active_orders.items():
            indexed_order, indexed_level = indexed[order_id]
            assert indexed_order is order, "order index points to a different order"
            assert indexed_level is level, "order index points to a different level"
        assert len(self._order_index) == len(active_orders)
        return True

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
