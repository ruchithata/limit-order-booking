"""Execution runner and reporter for matching engine performance benchmarks."""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path when script is executed directly
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engine import MatchingEngine  # noqa: E402

from benchmarks.workloads import (  # noqa: E402
    generate_cancellation_workload,
    generate_crossing_limit_workload,
    generate_market_order_matching_workload,
    generate_multi_level_sweep_workload,
    generate_resting_orders,
    generate_snapshot_workload,
)


@dataclass
class BenchmarkResult:
    """Benchmark outcome for a specific workload."""

    suite: str
    name: str
    workload_description: str
    workload_size: int
    repetitions: int
    min_time_s: float
    mean_time_s: float
    max_time_s: float
    stdev_time_s: float
    throughput_ops_per_s: float
    mean_latency_us: float
    extra: dict[str, Any] = field(default_factory=dict)


def measure_benchmark(
    name: str,
    suite: str,
    workload_description: str,
    workload_size: int,
    setup_fn: Callable[[], Any],
    run_fn: Callable[[Any], Any],
    *,
    repetitions: int = 3,
    warmup: int = 1,
) -> BenchmarkResult:
    """Execute warmup and timed repetitions of a benchmark with clean setups.

    setup_fn() is called before each run to initialize fresh data and engine state.
    Only the execution of run_fn(context) is timed with time.perf_counter().
    """
    for _ in range(warmup):
        ctx = setup_fn()
        run_fn(ctx)

    durations: list[float] = []
    last_extra: dict[str, Any] = {}

    for _ in range(repetitions):
        ctx = setup_fn()
        start = time.perf_counter()
        result = run_fn(ctx)
        elapsed = time.perf_counter() - start
        durations.append(elapsed)
        if isinstance(result, dict):
            last_extra = result

    min_s = min(durations)
    mean_s = statistics.mean(durations)
    max_s = max(durations)
    stdev_s = statistics.stdev(durations) if len(durations) > 1 else 0.0

    throughput = (workload_size / min_s) if min_s > 0 else 0.0
    latency_us = (mean_s / workload_size) * 1_000_000 if workload_size > 0 else 0.0

    return BenchmarkResult(
        suite=suite,
        name=name,
        workload_description=workload_description,
        workload_size=workload_size,
        repetitions=repetitions,
        min_time_s=min_s,
        mean_time_s=mean_s,
        max_time_s=max_s,
        stdev_time_s=stdev_s,
        throughput_ops_per_s=throughput,
        mean_latency_us=latency_us,
        extra=last_extra,
    )


# ---------------------------------------------------------------------------
# Benchmark Suites
# ---------------------------------------------------------------------------


def benchmark_order_insertion(
    sizes: list[int], *, repetitions: int = 3
) -> list[BenchmarkResult]:
    """Benchmark submitting non-crossing limit orders to the engine."""
    results: list[BenchmarkResult] = []

    for size in sizes:

        def setup(n: int = size) -> tuple[MatchingEngine, list[Any]]:
            orders = generate_resting_orders(n, seed=100 + n)
            engine = MatchingEngine()
            return engine, orders

        def run(ctx: tuple[MatchingEngine, list[Any]]) -> None:
            engine, orders = ctx
            for order in orders:
                engine.submit_order(order)

        res = measure_benchmark(
            name="Limit Order Insertion",
            suite="insertion",
            workload_description=f"Insert {size:,} non-crossing limit orders",
            workload_size=size,
            setup_fn=setup,
            run_fn=run,
            repetitions=repetitions,
        )
        results.append(res)

    return results


def benchmark_cancellation(
    sizes: list[int], *, repetitions: int = 3
) -> list[BenchmarkResult]:
    """Benchmark cancelling orders across various resting book sizes."""
    results: list[BenchmarkResult] = []

    for size in sizes:
        cancel_count = size // 2

        def setup(
            n: int = size, c: int = cancel_count
        ) -> tuple[MatchingEngine, list[Any]]:
            workload = generate_cancellation_workload(n, cancel_count=c, seed=200 + n)
            engine = MatchingEngine()
            for order in workload.resting_orders:
                engine.submit_order(order)
            return engine, workload.cancel_order_ids

        def run(ctx: tuple[MatchingEngine, list[Any]]) -> None:
            engine, cancel_ids = ctx
            for order_id in cancel_ids:
                engine.cancel_order(order_id)

        res = measure_benchmark(
            name="Order Cancellation",
            suite="cancellation",
            workload_description=(
                f"Cancel {cancel_count:,} orders in book of size {size:,}"
            ),
            workload_size=cancel_count,
            setup_fn=setup,
            run_fn=run,
            repetitions=repetitions,
        )
        res.extra["initial_book_size"] = size
        results.append(res)

    return results


def benchmark_matching(
    sizes: list[int], *, repetitions: int = 3
) -> list[BenchmarkResult]:
    """Benchmark matching: market orders, crossing limits, and multi-level sweeps."""
    results: list[BenchmarkResult] = []

    for size in sizes:
        # 1. Market order matching against resting depth
        resting_count = size * 2
        market_count = size

        def setup_market(
            r_cnt: int = resting_count, m_cnt: int = market_count
        ) -> tuple[MatchingEngine, list[Any]]:
            workload = generate_market_order_matching_workload(
                resting_count=r_cnt,
                market_order_count=m_cnt,
                seed=300 + m_cnt,
            )
            engine = MatchingEngine()
            for order in workload.resting_orders:
                engine.submit_order(order)
            return engine, workload.incoming_orders

        def run_market(ctx: tuple[MatchingEngine, list[Any]]) -> dict[str, int]:
            engine, incoming = ctx
            total_trades = 0
            for order in incoming:
                trades = engine.submit_order(order)
                total_trades += len(trades)
            return {"trades": total_trades}

        res_mkt = measure_benchmark(
            name="Market Order Execution",
            suite="matching",
            workload_description=(
                f"{market_count:,} market orders against {resting_count:,} resting"
            ),
            workload_size=market_count,
            setup_fn=setup_market,
            run_fn=run_market,
            repetitions=repetitions,
        )
        results.append(res_mkt)

        # 2. Crossing limit order flow
        def setup_crossing(n: int = size) -> tuple[MatchingEngine, list[Any]]:
            orders = generate_crossing_limit_workload(n, seed=400 + n)
            engine = MatchingEngine()
            return engine, orders

        def run_crossing(ctx: tuple[MatchingEngine, list[Any]]) -> dict[str, int]:
            engine, orders = ctx
            total_trades = 0
            for order in orders:
                trades = engine.submit_order(order)
                total_trades += len(trades)
            return {"trades": total_trades}

        res_crossing = measure_benchmark(
            name="Crossing Limit Orders",
            suite="matching",
            workload_description=f"{size:,} continuous crossing limit orders",
            workload_size=size,
            setup_fn=setup_crossing,
            run_fn=run_crossing,
            repetitions=repetitions,
        )
        results.append(res_crossing)

    # 3. Multi-level sweep benchmark
    def setup_sweep() -> tuple[MatchingEngine, list[Any]]:
        workload = generate_multi_level_sweep_workload(
            levels_per_side=50, orders_per_level=10, qty_per_order=20, seed=500
        )
        engine = MatchingEngine()
        for order in workload.resting_orders:
            engine.submit_order(order)
        return engine, workload.incoming_orders

    def run_sweep(ctx: tuple[MatchingEngine, list[Any]]) -> dict[str, int]:
        engine, incoming = ctx
        trades_count = 0
        for sweeper in incoming:
            trades = engine.submit_order(sweeper)
            trades_count += len(trades)
        return {"trades": trades_count}

    res_sweep = measure_benchmark(
        name="Multi-Level Sweep",
        suite="matching",
        workload_description="Sweeping 25 price levels in resting book",
        workload_size=2,
        setup_fn=setup_sweep,
        run_fn=run_sweep,
        repetitions=repetitions,
    )
    results.append(res_sweep)

    return results


def benchmark_snapshots(
    level_counts: list[int],
    depths: list[int | None],
    *,
    iterations: int = 1000,
    repetitions: int = 3,
) -> list[BenchmarkResult]:
    """Benchmark generating order-book snapshots across book sizes and depths."""
    results: list[BenchmarkResult] = []

    for num_levels in level_counts:
        # Pre-populate engine once for this level count
        orders = generate_snapshot_workload(
            levels_per_side=num_levels, orders_per_level=5, seed=600 + num_levels
        )
        engine = MatchingEngine()
        for order in orders:
            engine.submit_order(order)

        for depth in depths:
            depth_desc = f"depth={depth}" if depth is not None else "full depth"

            def setup(eng: MatchingEngine = engine) -> MatchingEngine:
                return eng

            def run(
                eng: MatchingEngine, d: int | None = depth, iters: int = iterations
            ) -> None:
                for _ in range(iters):
                    eng.get_snapshot(depth=d)

            res = measure_benchmark(
                name="OrderBook Snapshot",
                suite="snapshot",
                workload_description=(
                    f"{num_levels} levels/side ({depth_desc}, {iterations:,} calls)"
                ),
                workload_size=iterations,
                setup_fn=setup,
                run_fn=run,
                repetitions=repetitions,
            )
            results.append(res)

    return results


# ---------------------------------------------------------------------------
# Formatting and Reporting
# ---------------------------------------------------------------------------


def print_results_table(results: list[BenchmarkResult]) -> None:
    """Print benchmark results in an aligned ASCII table."""
    title = "LIMIT ORDER BOOK PERFORMANCE BENCHMARK REPORT"
    line = "=" * 110
    subline = "-" * 110

    print(f"\n{line}")
    print(f"{title:^110}")
    print(line)
    header = (
        f"{'Benchmark':<24} | {'Workload Details':<34} | "
        f"{'Size':>8} | {'Min (s)':>8} | {'Mean (s)':>8} | "
        f"{'Throughput':>13} | {'Latency':>9}"
    )
    print(header)
    print(subline)

    current_suite = ""
    for r in results:
        if r.suite != current_suite:
            current_suite = r.suite
            print(f"[{current_suite.upper()}]")

        tp_str = f"{r.throughput_ops_per_s:,.0f} op/s"
        lat_str = (
            f"{r.mean_latency_us:.2f} us"
            if r.mean_latency_us < 1000
            else f"{r.mean_latency_us / 1000:.2f} ms"
        )
        print(
            f"  {r.name:<22} | {r.workload_description[:34]:<34} | "
            f"{r.workload_size:>8,} | {r.min_time_s:>8.4f} | {r.mean_time_s:>8.4f} | "
            f"{tp_str:>13} | {lat_str:>9}"
        )
    print(f"{line}\n")


def run_all_benchmarks(
    *,
    quick: bool = False,
    suite: str = "all",
    repetitions: int = 3,
) -> list[BenchmarkResult]:
    """Execute selected benchmark suites and return results."""
    all_results: list[BenchmarkResult] = []

    if quick:
        insertion_sizes = [1_000, 5_000]
        cancellation_sizes = [1_000, 5_000]
        matching_sizes = [1_000, 5_000]
        snapshot_levels = [20, 50]
        snapshot_depths: list[int | None] = [5, None]
        snapshot_iterations = 200
    else:
        insertion_sizes = [1_000, 10_000, 50_000]
        cancellation_sizes = [1_000, 10_000, 50_000]
        matching_sizes = [1_000, 10_000, 25_000]
        snapshot_levels = [50, 200]
        snapshot_depths = [10, 50, None]
        snapshot_iterations = 1_000

    if suite in ("all", "insertion"):
        all_results.extend(
            benchmark_order_insertion(insertion_sizes, repetitions=repetitions)
        )

    if suite in ("all", "cancellation"):
        all_results.extend(
            benchmark_cancellation(cancellation_sizes, repetitions=repetitions)
        )

    if suite in ("all", "matching"):
        all_results.extend(benchmark_matching(matching_sizes, repetitions=repetitions))

    if suite in ("all", "snapshot"):
        all_results.extend(
            benchmark_snapshots(
                snapshot_levels,
                snapshot_depths,
                iterations=snapshot_iterations,
                repetitions=repetitions,
            )
        )

    return all_results


def main() -> int:
    """CLI entry point for running benchmarks."""
    parser = argparse.ArgumentParser(
        description="Limit Order Book Performance Benchmarks & Profiling"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run quick benchmarks with reduced sizes for rapid feedback.",
    )
    parser.add_argument(
        "--suite",
        choices=["all", "insertion", "cancellation", "matching", "snapshot"],
        default="all",
        help="Specific benchmark suite to run (default: all).",
    )
    parser.add_argument(
        "--repetitions",
        "-r",
        type=int,
        default=3,
        help="Number of repetitions per benchmark (default: 3).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output benchmark results as JSON instead of an ASCII table.",
    )

    args = parser.parse_args()

    results = run_all_benchmarks(
        quick=args.quick,
        suite=args.suite,
        repetitions=args.repetitions,
    )

    if args.json:
        data = [asdict(r) for r in results]
        print(json.dumps(data, indent=2))
    else:
        print_results_table(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
