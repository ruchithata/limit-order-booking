"""Reproducible synthetic trading workload generators for benchmarks."""

from random import Random
from typing import NamedTuple

from engine import Order, OrderId, OrderType, Side


class CancellationWorkload(NamedTuple):
    """Workload containing resting orders to populate the book and IDs to cancel."""

    resting_orders: list[Order]
    cancel_order_ids: list[OrderId]


class MatchingWorkload(NamedTuple):
    """Workload containing initial resting orders and incoming orders to match."""

    resting_orders: list[Order]
    incoming_orders: list[Order]


def generate_resting_orders(
    count: int,
    *,
    seed: int = 42,
    mid_price: int = 10000,
    spread: int = 20,
    tick_range: int = 500,
    min_qty: int = 1,
    max_qty: int = 50,
) -> list[Order]:
    """Generate reproducible non-crossing limit orders for order book insertion.

    Bids are placed strictly below (mid_price - spread // 2).
    Asks are placed strictly above (mid_price + spread // 2).
    No executions will occur when submitted sequentially.
    """
    if count < 0:
        raise ValueError("count cannot be negative")
    if min_qty <= 0:
        raise ValueError("min_qty must be positive")
    if max_qty < min_qty:
        raise ValueError("max_qty must be greater than or equal to min_qty")
    if mid_price <= 0:
        raise ValueError("mid_price must be positive")
    if spread < 0:
        raise ValueError("spread cannot be negative")
    if tick_range <= 0:
        raise ValueError("tick_range must be positive")

    rng = Random(seed)
    orders: list[Order] = []
    max_bid = mid_price - (spread // 2)
    min_ask = mid_price + (spread // 2)
    min_bid = max(1, max_bid - tick_range)
    max_ask = min_ask + tick_range

    for i in range(count):
        side = Side.BUY if (i % 2 == 0) else Side.SELL
        if side is Side.BUY:
            price = rng.randint(min_bid, max_bid)
        else:
            price = rng.randint(min_ask, max_ask)
        quantity = rng.randint(min_qty, max_qty)
        order_id = f"R-{i + 1}"
        orders.append(
            Order(
                order_id=order_id,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=price,
            )
        )
    return orders


def generate_cancellation_workload(
    book_size: int,
    cancel_count: int | None = None,
    *,
    seed: int = 42,
    mid_price: int = 10000,
    spread: int = 20,
) -> CancellationWorkload:
    """Generate resting orders to populate the book and a subset of IDs to cancel."""
    if book_size < 0:
        raise ValueError("book_size cannot be negative")
    if cancel_count is None:
        cancel_count = book_size // 2
    if cancel_count < 0:
        raise ValueError("cancel_count cannot be negative")
    if cancel_count > book_size:
        raise ValueError("cancel_count cannot exceed book_size")

    resting_orders = generate_resting_orders(
        book_size, seed=seed, mid_price=mid_price, spread=spread
    )
    rng = Random(seed + 1)
    all_ids = [order.order_id for order in resting_orders]
    cancel_ids = rng.sample(all_ids, cancel_count)

    return CancellationWorkload(
        resting_orders=resting_orders,
        cancel_order_ids=cancel_ids,
    )


def generate_market_order_matching_workload(
    resting_count: int,
    market_order_count: int,
    *,
    seed: int = 42,
    mid_price: int = 10000,
    spread: int = 20,
    avg_resting_qty: int = 10,
) -> MatchingWorkload:
    """Generate resting limit orders and incoming market orders that cross them."""
    if resting_count < 0:
        raise ValueError("resting_count cannot be negative")
    if market_order_count < 0:
        raise ValueError("market_order_count cannot be negative")
    if avg_resting_qty <= 0:
        raise ValueError("avg_resting_qty must be positive")

    min_resting_qty = max(1, avg_resting_qty // 2)
    max_resting_qty = max(min_resting_qty, avg_resting_qty * 2)

    resting = generate_resting_orders(
        resting_count,
        seed=seed,
        mid_price=mid_price,
        spread=spread,
        min_qty=min_resting_qty,
        max_qty=max_resting_qty,
    )
    rng = Random(seed + 2)
    incoming: list[Order] = []

    max_mkt_qty = max(1, avg_resting_qty * 3)
    for i in range(market_order_count):
        side = Side.BUY if rng.random() < 0.5 else Side.SELL
        quantity = rng.randint(1, max_mkt_qty)
        incoming.append(
            Order(
                order_id=f"MKT-{i + 1}",
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
            )
        )

    return MatchingWorkload(resting_orders=resting, incoming_orders=incoming)


def generate_crossing_limit_workload(
    count: int,
    *,
    seed: int = 42,
    mid_price: int = 10000,
    volatility: int = 40,
    min_qty: int = 1,
    max_qty: int = 20,
) -> list[Order]:
    """Generate interleaved limit orders that frequently cross and trade."""
    if count < 0:
        raise ValueError("count cannot be negative")
    if min_qty <= 0:
        raise ValueError("min_qty must be positive")
    if max_qty < min_qty:
        raise ValueError("max_qty must be greater than or equal to min_qty")
    if mid_price <= 0:
        raise ValueError("mid_price must be positive")
    if volatility < 0:
        raise ValueError("volatility cannot be negative")

    rng = Random(seed)
    orders: list[Order] = []

    for i in range(count):
        side = Side.BUY if rng.random() < 0.5 else Side.SELL
        offset = rng.randint(-volatility, volatility)
        price = max(1, mid_price + offset)
        quantity = rng.randint(min_qty, max_qty)
        orders.append(
            Order(
                order_id=f"LIM-{i + 1}",
                side=side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=price,
            )
        )
    return orders


def generate_multi_level_sweep_workload(
    levels_per_side: int = 20,
    orders_per_level: int = 5,
    qty_per_order: int = 10,
    *,
    seed: int = 42,
    mid_price: int = 10000,
    tick_spacing: int = 5,
) -> MatchingWorkload:
    """Generate orders across multiple price tiers and large orders that sweep them."""
    if levels_per_side <= 0:
        raise ValueError("levels_per_side must be positive")
    if orders_per_level <= 0:
        raise ValueError("orders_per_level must be positive")
    if qty_per_order <= 0:
        raise ValueError("qty_per_order must be positive")
    if mid_price <= 0:
        raise ValueError("mid_price must be positive")
    if tick_spacing <= 0:
        raise ValueError("tick_spacing must be positive")

    resting: list[Order] = []
    order_num = 1

    # Populate buy side (bids below mid)
    for level_idx in range(1, levels_per_side + 1):
        price = mid_price - (level_idx * tick_spacing)
        for _ in range(orders_per_level):
            resting.append(
                Order(
                    order_id=f"SWP-B-{order_num}",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=qty_per_order,
                    price=price,
                )
            )
            order_num += 1

    # Populate sell side (asks above mid)
    for level_idx in range(1, levels_per_side + 1):
        price = mid_price + (level_idx * tick_spacing)
        for _ in range(orders_per_level):
            resting.append(
                Order(
                    order_id=f"SWP-S-{order_num}",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=qty_per_order,
                    price=price,
                )
            )
            order_num += 1

    # Create sweeping orders: large market buy sweeps multiple ask levels;
    # large market sell sweeps multiple bid levels.
    sweep_qty = (levels_per_side // 2) * orders_per_level * qty_per_order
    sweepers = [
        Order(
            order_id="SWEEPER-BUY",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=sweep_qty,
        ),
        Order(
            order_id="SWEEPER-SELL",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=sweep_qty,
        ),
    ]

    return MatchingWorkload(resting_orders=resting, incoming_orders=sweepers)


def generate_snapshot_workload(
    levels_per_side: int = 100,
    orders_per_level: int = 10,
    *,
    seed: int = 42,
    mid_price: int = 10000,
    min_qty: int = 5,
    max_qty: int = 50,
) -> list[Order]:
    """Generate orders to populate an order book with many distinct price levels."""
    if levels_per_side <= 0:
        raise ValueError("levels_per_side must be positive")
    if orders_per_level <= 0:
        raise ValueError("orders_per_level must be positive")
    if min_qty <= 0:
        raise ValueError("min_qty must be positive")
    if max_qty < min_qty:
        raise ValueError("max_qty must be greater than or equal to min_qty")
    if mid_price <= 0:
        raise ValueError("mid_price must be positive")

    rng = Random(seed)
    orders: list[Order] = []
    order_num = 1

    for level in range(1, levels_per_side + 1):
        bid_price = max(1, mid_price - level)
        ask_price = mid_price + level
        for _ in range(orders_per_level):
            orders.append(
                Order(
                    order_id=f"SNAP-B-{order_num}",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=rng.randint(min_qty, max_qty),
                    price=bid_price,
                )
            )
            orders.append(
                Order(
                    order_id=f"SNAP-S-{order_num}",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=rng.randint(min_qty, max_qty),
                    price=ask_price,
                )
            )
            order_num += 1

    return orders
