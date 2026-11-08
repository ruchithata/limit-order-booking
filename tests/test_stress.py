"""High-volume stress tests and invariant verification under heavy load."""

from __future__ import annotations

import gc
import tracemalloc

from benchmarks.workloads import (
    generate_cancellation_workload,
    generate_mixed_workload,
    generate_multi_level_sweep_workload,
    generate_resting_orders,
)
from engine import (
    EngineSnapshot,
    MatchingEngine,
    Order,
    OrderType,
    RecordingMatchingEngine,
    Side,
    recover_state,
)


def test_stress_large_book_insertion_and_invariants() -> None:
    orders = generate_resting_orders(
        10_000, seed=1234, mid_price=50000, spread=50, tick_range=1000
    )
    engine = MatchingEngine()
    for o in orders:
        engine.submit_order(o)

    assert len(engine) == 10_000
    assert engine.best_bid_price() is not None
    assert engine.best_ask_price() is not None
    assert engine.best_bid_price() < engine.best_ask_price()
    assert engine.order_book.validate_invariants()


def test_stress_heavy_cancellation_churn_and_matching() -> None:
    # 5,000 orders in book; cancel 4,000 (80% churn, creating thousands of tombstones)
    workload = generate_cancellation_workload(5000, cancel_count=4000, seed=2345)
    engine = MatchingEngine()
    for o in workload.resting_orders:
        engine.submit_order(o)

    for cid in workload.cancel_order_ids:
        assert engine.cancel_order(cid) is True

    assert len(engine) == 1000
    assert engine.order_book.validate_invariants()

    # Incoming market orders execute against remaining active orders,
    # navigating through dead tombstones without corruption
    best_bid = engine.best_bid_price()
    assert best_bid is not None

    mkt_sell = Order("SWP-MKT", Side.SELL, OrderType.MARKET, quantity=2000)
    trades = engine.submit_order(mkt_sell)
    assert len(trades) > 0

    for t in trades:
        # Maker orders must not have been cancelled
        assert t.maker_order_id not in workload.cancel_order_ids
        assert t.price > 0
        assert t.quantity > 0

    assert engine.order_book.validate_invariants()


def test_stress_deep_multi_level_sweep() -> None:
    # 50 price levels on each side with 10 orders per level (1,000 total orders)
    workload = generate_multi_level_sweep_workload(
        levels_per_side=50, orders_per_level=10, qty_per_order=20, seed=3456
    )
    engine = MatchingEngine()
    for o in workload.resting_orders:
        engine.submit_order(o)

    initial_best_ask = engine.best_ask_price()
    assert initial_best_ask is not None

    # Sweep 25 ask levels in a single aggressive taker order
    sweeper_buy = workload.incoming_orders[0]
    trades = engine.submit_order(sweeper_buy)

    traded_levels = {t.price for t in trades}
    assert len(traded_levels) == 25
    assert len(trades) == 250  # 25 levels * 10 orders

    # Trade IDs must be sequential
    for i in range(len(trades) - 1):
        assert trades[i + 1].trade_id == trades[i].trade_id + 1

    new_best_ask = engine.best_ask_price()
    assert new_best_ask is not None
    assert new_best_ask > initial_best_ask
    assert engine.order_book.validate_invariants()


def test_stress_mixed_workload_execution() -> None:
    # 5,000 interleaved operations with 1,000 initial resting orders
    workload = generate_mixed_workload(
        5000,
        initial_book_size=1000,
        limit_pct=0.60,
        market_pct=0.20,
        cancel_pct=0.20,
        seed=4567,
    )
    engine = MatchingEngine()
    for o in workload.initial_resting_orders:
        engine.submit_order(o)

    for action in workload.actions:
        action.execute(engine)

    assert len(engine) > 0
    assert engine.order_book.validate_invariants()


def test_stress_snapshot_and_recovery_heavy_flow() -> None:
    workload = generate_mixed_workload(
        3000,
        initial_book_size=500,
        limit_pct=0.60,
        market_pct=0.20,
        cancel_pct=0.20,
        seed=5678,
    )
    recorder = RecordingMatchingEngine()
    for o in workload.initial_resting_orders:
        recorder.submit_order(o)

    # Execute first 1,500 actions
    for action in workload.actions[:1500]:
        action.execute(recorder)

    # Checkpoint snapshot at sequence 2,000 (500 initial + 1500 actions)
    snap = recorder.create_snapshot()
    assert isinstance(snap, EngineSnapshot)

    # Continue executing remaining 1,500 actions
    for action in workload.actions[1500:]:
        action.execute(recorder)

    total_events = len(recorder.event_log.events)

    # Recover fresh engine from snapshot + replay newer events
    result = recover_state(snapshot=snap, events=recorder.event_log)
    assert result.last_sequence == total_events

    recovered = result.matching_engine
    assert recovered.get_snapshot() == recorder.get_snapshot()
    assert recovered.next_trade_id == recorder.next_trade_id
    assert len(recovered) == len(recorder)
    assert recovered.order_book.validate_invariants()


def test_stress_memory_cleanup_after_orders_cleared() -> None:
    engine = MatchingEngine()
    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()

    # Insert 5,000 orders
    orders = generate_resting_orders(5000, seed=6789)
    for o in orders:
        engine.submit_order(o)

    _, peak_populated = tracemalloc.get_traced_memory()
    assert peak_populated > 0

    # Cancel all orders
    for o in orders:
        engine.cancel_order(o.order_id)

    # Pop front / flush by executing empty search
    assert len(engine) == 0
    assert engine.best_bid_price() is None
    assert engine.best_ask_price() is None

    current_mem, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Retained memory after clearing all orders should be substantially lower than peak
    assert current_mem < peak_populated
    assert engine.order_book.validate_invariants()


def test_stress_extreme_price_tiers_and_queue_depth() -> None:
    engine = MatchingEngine()
    u64_max = (1 << 64) - 1

    # Price boundaries
    engine.submit_order(Order("MIN-BID", Side.BUY, OrderType.LIMIT, 10, 1))
    engine.submit_order(Order("MAX-ASK", Side.SELL, OrderType.LIMIT, 10, u64_max))
    assert engine.best_bid_price() == 1
    assert engine.best_ask_price() == u64_max

    # Queue 1,000 orders at the exact same price level (tick 500)
    for i in range(1000):
        engine.submit_order(Order(f"SAME-{i}", Side.BUY, OrderType.LIMIT, 5, 500))

    level = engine.order_book.best_bid_level()
    assert level is not None
    assert level.price == 500
    assert level.total_quantity == 5000
    assert len(level) == 1000

    # Cancel orders from the front, middle, and back of the queue
    assert engine.cancel_order("SAME-0")
    assert engine.cancel_order("SAME-500")
    assert engine.cancel_order("SAME-999")
    assert level.total_quantity == 4985
    assert len(level) == 997

    # Matching respects FIFO: front order is now SAME-1
    trades = engine.submit_order(Order("FILL-1", Side.SELL, OrderType.LIMIT, 5, 500))
    assert len(trades) == 1
    assert trades[0].maker_order_id == "SAME-1"
    assert engine.order_book.validate_invariants()
