"""Execution runner and reporter for matching engine performance benchmarks."""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path when script is executed directly
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engine import MatchingEngine  # noqa: E402

from benchmarks.regression import (  # noqa: E402
    compare_benchmarks,
    load_baseline,
    print_regression_report,
    save_baseline,
)
from benchmarks.workloads import (  # noqa: E402
    MixedWorkload,
    generate_cancellation_workload,
    generate_crossing_limit_workload,
    generate_market_order_matching_workload,
    generate_mixed_workload,
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
    peak_memory_bytes: int = 0
    net_memory_bytes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def peak_memory_mb(self) -> float:
        return self.peak_memory_bytes / (1024 * 1024)

    @property
    def net_memory_mb(self) -> float:
        return self.net_memory_bytes / (1024 * 1024)


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
    measure_memory: bool = True,
) -> BenchmarkResult:
    """Execute warmup, timed repetitions, and memory profiling of a benchmark.

    setup_fn() is called before each run to initialize fresh data and engine state.
    Timed runs use time.perf_counter() with zero instrumentation overhead.
    Memory profiling uses standard library tracemalloc in a dedicated pass.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if warmup < 0:
        raise ValueError("warmup cannot be negative")
    if workload_size < 0:
        raise ValueError("workload_size cannot be negative")

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

    throughput = workload_size / mean_s if mean_s > 0 and workload_size > 0 else 0.0
    latency_us = (mean_s / workload_size) * 1_000_000 if workload_size > 0 else 0.0

    peak_bytes = 0
    net_bytes = 0
    if measure_memory:
        try:
            mem_ctx = setup_fn()
            gc.collect()
            tracemalloc.start()
            tracemalloc.reset_peak()
            start_mem = tracemalloc.get_traced_memory()[0]
            run_fn(mem_ctx)
            end_mem, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_bytes = peak
            net_bytes = max(0, end_mem - start_mem)
        except Exception:
            if tracemalloc.is_tracing():
                tracemalloc.stop()

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
        peak_memory_bytes=peak_bytes,
        net_memory_bytes=net_bytes,
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


def benchmark_mixed_workload(
    sizes: list[int], *, repetitions: int = 3
) -> list[BenchmarkResult]:
    """Benchmark realistic interleaved stream of limit, market, and cancel actions."""
    results: list[BenchmarkResult] = []

    for size in sizes:

        def setup(n: int = size) -> tuple[MatchingEngine, MixedWorkload]:
            book_size = min(5000, max(200, n // 2))
            workload = generate_mixed_workload(
                n, initial_book_size=book_size, seed=700 + n
            )
            engine = MatchingEngine()
            for order in workload.initial_resting_orders:
                engine.submit_order(order)
            return engine, workload

        def run(ctx: tuple[MatchingEngine, MixedWorkload]) -> dict[str, int]:
            engine, workload = ctx
            actions_executed = 0
            for action in workload.actions:
                action.execute(engine)
                actions_executed += 1
            return {
                "actions_executed": actions_executed,
                "final_book_size": len(engine),
            }

        res = measure_benchmark(
            name="Mixed Order Flow",
            suite="mixed",
            workload_description=f"{size:,} mixed limit/market/cancel flow",
            workload_size=size,
            setup_fn=setup,
            run_fn=run,
            repetitions=repetitions,
        )
        results.append(res)

    return results


def benchmark_stress(
    sizes: list[int] | None = None, *, repetitions: int = 1
) -> list[BenchmarkResult]:
    """Stress testing suite under high-volume operations and deep order books."""
    results: list[BenchmarkResult] = []
    stress_sizes = sizes if sizes is not None else [25_000, 50_000]

    for size in stress_sizes:
        # 1. High-volume order book insertion
        def setup_insert(n: int = size) -> tuple[MatchingEngine, list[Any]]:
            orders = generate_resting_orders(n, seed=800 + n, tick_range=2000)
            engine = MatchingEngine()
            return engine, orders

        def run_insert(ctx: tuple[MatchingEngine, list[Any]]) -> dict[str, int]:
            engine, orders = ctx
            for o in orders:
                engine.submit_order(o)
            return {"final_size": len(engine)}

        res_ins = measure_benchmark(
            name="Stress Book Insertion",
            suite="stress",
            workload_description=f"Insert {size:,} orders into deep book",
            workload_size=size,
            setup_fn=setup_insert,
            run_fn=run_insert,
            repetitions=repetitions,
        )
        results.append(res_ins)

        # 2. High-churn cancellation (cancel 80% of book)
        cancel_cnt = int(size * 0.8)

        def setup_cancel(
            n: int = size, c: int = cancel_cnt
        ) -> tuple[MatchingEngine, list[Any]]:
            workload = generate_cancellation_workload(n, cancel_count=c, seed=850 + n)
            engine = MatchingEngine()
            for o in workload.resting_orders:
                engine.submit_order(o)
            return engine, workload.cancel_order_ids

        def run_cancel(ctx: tuple[MatchingEngine, list[Any]]) -> dict[str, int]:
            engine, cancel_ids = ctx
            for cid in cancel_ids:
                engine.cancel_order(cid)
            return {"cancelled": len(cancel_ids), "remaining": len(engine)}

        res_canc = measure_benchmark(
            name="Stress High-Churn Cancellation",
            suite="stress",
            workload_description=(
                f"Cancel {cancel_cnt:,} orders in {size:,} book (80% churn)"
            ),
            workload_size=cancel_cnt,
            setup_fn=setup_cancel,
            run_fn=run_cancel,
            repetitions=repetitions,
        )
        results.append(res_canc)

        # 3. High-volume mixed flow
        def setup_mixed(n: int = size) -> tuple[MatchingEngine, MixedWorkload]:
            workload = generate_mixed_workload(
                n, initial_book_size=n // 4, seed=900 + n
            )
            engine = MatchingEngine()
            for o in workload.initial_resting_orders:
                engine.submit_order(o)
            return engine, workload

        def run_mixed(ctx: tuple[MatchingEngine, MixedWorkload]) -> dict[str, int]:
            engine, workload = ctx
            for act in workload.actions:
                act.execute(engine)
            return {"actions": len(workload.actions)}

        res_mix = measure_benchmark(
            name="Stress Mixed Flow",
            suite="stress",
            workload_description=f"Execute {size:,} high-volume mixed actions",
            workload_size=size,
            setup_fn=setup_mixed,
            run_fn=run_mixed,
            repetitions=repetitions,
        )
        results.append(res_mix)

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
    title = "LIMIT ORDER BOOK PERFORMANCE & MEMORY BENCHMARK REPORT"
    line = "=" * 122
    subline = "-" * 122

    print(f"\n{line}")
    print(f"{title:^122}")
    print(line)
    header = (
        f"{'Benchmark':<24} | {'Workload Details':<32} | "
        f"{'Size':>8} | {'Min (s)':>8} | {'Mean (s)':>8} | "
        f"{'Peak Mem':>9} | {'Throughput':>13} | {'Latency':>9}"
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
        if r.peak_memory_mb >= 0.1:
            mem_str = f"{r.peak_memory_mb:.2f} MB"
        elif r.peak_memory_bytes > 0:
            mem_str = f"{r.peak_memory_bytes / 1024:.0f} KB"
        else:
            mem_str = "0 B"

        print(
            f"  {r.name:<22} | {r.workload_description[:32]:<32} | "
            f"{r.workload_size:>8,} | {r.min_time_s:>8.4f} | {r.mean_time_s:>8.4f} | "
            f"{mem_str:>9} | {tp_str:>13} | {lat_str:>9}"
        )
    print(f"{line}\n")


def run_all_benchmarks(
    *,
    quick: bool = False,
    large: bool = False,
    suite: str = "all",
    repetitions: int = 3,
) -> list[BenchmarkResult]:
    """Execute selected benchmark suites and return results."""
    all_results: list[BenchmarkResult] = []

    if quick:
        insertion_sizes = [1_000, 5_000]
        cancellation_sizes = [1_000, 5_000]
        matching_sizes = [1_000, 5_000]
        mixed_sizes = [1_000, 5_000]
        stress_sizes = [5_000]
        snapshot_levels = [20, 50]
        snapshot_depths: list[int | None] = [5, None]
        snapshot_iterations = 200
    elif large:
        insertion_sizes = [10_000, 50_000, 100_000]
        cancellation_sizes = [10_000, 50_000, 100_000]
        matching_sizes = [10_000, 25_000, 50_000]
        mixed_sizes = [10_000, 50_000, 100_000]
        stress_sizes = [50_000, 100_000]
        snapshot_levels = [50, 200, 500]
        snapshot_depths = [10, 50, None]
        snapshot_iterations = 2_000
    else:
        insertion_sizes = [1_000, 10_000, 50_000]
        cancellation_sizes = [1_000, 10_000, 50_000]
        matching_sizes = [1_000, 10_000, 25_000]
        mixed_sizes = [1_000, 10_000, 25_000]
        stress_sizes = [25_000]
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

    if suite in ("all", "mixed"):
        all_results.extend(
            benchmark_mixed_workload(mixed_sizes, repetitions=repetitions)
        )

    if suite in ("all", "snapshot"):
        all_results.extend(
            benchmark_snapshots(
                snapshot_levels,
                snapshot_depths,
                iterations=snapshot_iterations,
                repetitions=repetitions,
            )
        )

    if suite in ("all", "stress"):
        all_results.extend(
            benchmark_stress(stress_sizes, repetitions=max(1, repetitions // 2))
        )

    return all_results


def main() -> int:
    """CLI entry point for running benchmarks and regression comparisons."""
    parser = argparse.ArgumentParser(
        description="Limit Order Book Performance Benchmarks & Stress Testing"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run quick benchmarks with reduced sizes for rapid feedback.",
    )
    parser.add_argument(
        "--large",
        action="store_true",
        help="Run large-scale workloads with up to 100,000+ orders.",
    )
    parser.add_argument(
        "--suite",
        choices=[
            "all",
            "insertion",
            "cancellation",
            "matching",
            "snapshot",
            "mixed",
            "stress",
        ],
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
    parser.add_argument(
        "--save-baseline",
        type=str,
        default=None,
        help="Save benchmark results to JSON file as a performance baseline.",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="Compare current benchmark results against a saved baseline JSON file.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=20.0,
        help="Throughput regression tolerance percentage (default: 20.0%%).",
    )

    args = parser.parse_args()

    results = run_all_benchmarks(
        quick=args.quick,
        large=args.large,
        suite=args.suite,
        repetitions=args.repetitions,
    )

    if args.save_baseline:
        saved_path = save_baseline(results, args.save_baseline)
        print(f"Saved benchmark baseline to {saved_path}")

    if args.baseline:
        base_records = load_baseline(args.baseline)
        report = compare_benchmarks(
            results, base_records, throughput_tolerance_pct=args.threshold
        )
        print_regression_report(report)
    elif args.json:
        data = [asdict(r) for r in results]
        print(json.dumps(data, indent=2))
    else:
        print_results_table(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
