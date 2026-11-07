"""Tests for synthetic benchmark workloads and benchmark execution runners."""

import pytest
from benchmarks.run_benchmarks import (
    BenchmarkResult,
    measure_benchmark,
    run_all_benchmarks,
)
from benchmarks.workloads import (
    CancellationWorkload,
    MatchingWorkload,
    generate_cancellation_workload,
    generate_crossing_limit_workload,
    generate_market_order_matching_workload,
    generate_multi_level_sweep_workload,
    generate_resting_orders,
    generate_snapshot_workload,
)
from engine import MatchingEngine, OrderType


def test_generate_resting_orders_is_reproducible_and_non_crossing() -> None:
    orders_1 = generate_resting_orders(100, seed=42)
    orders_2 = generate_resting_orders(100, seed=42)
    orders_diff = generate_resting_orders(100, seed=99)

    assert len(orders_1) == 100
    assert [(o.order_id, o.price, o.quantity, o.side) for o in orders_1] == [
        (o.order_id, o.price, o.quantity, o.side) for o in orders_2
    ]
    assert [(o.price, o.quantity) for o in orders_1] != [
        (o.price, o.quantity) for o in orders_diff
    ]

    # Verify no orders cross when submitted
    engine = MatchingEngine()
    trades = []
    for order in orders_1:
        trades.extend(engine.submit_order(order))

    assert len(trades) == 0
    assert len(engine) == 100
    assert engine.best_bid_price() is not None
    assert engine.best_ask_price() is not None
    assert engine.best_bid_price() < engine.best_ask_price()


def test_generate_cancellation_workload_validation_and_execution() -> None:
    with pytest.raises(ValueError, match="cancel_count cannot exceed book_size"):
        generate_cancellation_workload(10, cancel_count=20)

    workload = generate_cancellation_workload(50, cancel_count=20, seed=123)
    assert isinstance(workload, CancellationWorkload)
    assert len(workload.resting_orders) == 50
    assert len(workload.cancel_order_ids) == 20

    # Ensure all cancel IDs belong to the resting orders
    resting_id_set = {o.order_id for o in workload.resting_orders}
    for cid in workload.cancel_order_ids:
        assert cid in resting_id_set

    # Verify cancellation executes successfully
    engine = MatchingEngine()
    for order in workload.resting_orders:
        engine.submit_order(order)
    assert len(engine) == 50

    for cid in workload.cancel_order_ids:
        assert engine.cancel_order(cid) is True

    assert len(engine) == 30


def test_generate_market_order_matching_workload() -> None:
    workload = generate_market_order_matching_workload(
        resting_count=40, market_order_count=10, seed=77
    )
    assert isinstance(workload, MatchingWorkload)
    assert len(workload.resting_orders) == 40
    assert len(workload.incoming_orders) == 10

    for mkt in workload.incoming_orders:
        assert mkt.order_type is OrderType.MARKET
        assert mkt.price is None

    engine = MatchingEngine()
    for o in workload.resting_orders:
        engine.submit_order(o)

    trades = []
    for mkt in workload.incoming_orders:
        trades.extend(engine.submit_order(mkt))

    assert len(trades) > 0


def test_generate_crossing_limit_workload() -> None:
    orders = generate_crossing_limit_workload(60, seed=88, mid_price=10000)
    assert len(orders) == 60

    engine = MatchingEngine()
    total_trades = 0
    for o in orders:
        trades = engine.submit_order(o)
        total_trades += len(trades)

    assert total_trades > 0


def test_generate_multi_level_sweep_workload() -> None:
    workload = generate_multi_level_sweep_workload(
        levels_per_side=10, orders_per_level=3, qty_per_order=10, seed=11
    )
    assert len(workload.resting_orders) == 60  # 10 * 3 * 2 sides
    assert len(workload.incoming_orders) == 2  # Sweeper BUY and Sweeper SELL

    engine = MatchingEngine()
    for o in workload.resting_orders:
        engine.submit_order(o)

    # Buy sweeper sweeps ask levels
    trades_buy = engine.submit_order(workload.incoming_orders[0])
    # Should sweep multiple price levels
    traded_prices = {t.price for t in trades_buy}
    assert len(traded_prices) > 1

    # Sell sweeper sweeps bid levels
    trades_sell = engine.submit_order(workload.incoming_orders[1])
    traded_bid_prices = {t.price for t in trades_sell}
    assert len(traded_bid_prices) > 1


def test_generate_snapshot_workload() -> None:
    orders = generate_snapshot_workload(levels_per_side=15, orders_per_level=4, seed=55)
    assert len(orders) == 120  # 15 * 4 * 2 sides

    engine = MatchingEngine()
    for o in orders:
        engine.submit_order(o)

    snap = engine.get_snapshot()
    assert len(snap.bids) == 15
    assert len(snap.asks) == 15

    top5 = engine.get_snapshot(depth=5)
    assert len(top5.bids) == 5
    assert len(top5.asks) == 5


def test_measure_benchmark_returns_valid_metrics() -> None:
    call_count = 0

    def setup() -> int:
        nonlocal call_count
        call_count += 1
        return call_count

    def run(val: int) -> dict[str, int]:
        return {"val": val}

    res = measure_benchmark(
        name="Test Benchmark",
        suite="test",
        workload_description="Test metric validity",
        workload_size=100,
        setup_fn=setup,
        run_fn=run,
        repetitions=3,
        warmup=1,
    )

    assert isinstance(res, BenchmarkResult)
    assert res.name == "Test Benchmark"
    assert res.suite == "test"
    assert res.workload_size == 100
    assert res.repetitions == 3
    assert res.min_time_s >= 0.0
    assert res.mean_time_s >= 0.0
    assert res.throughput_ops_per_s > 0.0
    assert res.mean_latency_us >= 0.0
    assert call_count == 4  # 1 warmup + 3 repetitions


def test_run_all_benchmarks_quick_smoke() -> None:
    results = run_all_benchmarks(quick=True, repetitions=1)
    suites = {r.suite for r in results}
    assert {"insertion", "cancellation", "matching", "snapshot"}.issubset(suites)
    assert len(results) > 0
    for r in results:
        assert r.throughput_ops_per_s > 0
        assert r.mean_time_s > 0
