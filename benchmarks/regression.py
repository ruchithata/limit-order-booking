"""Regression detection and benchmark comparison utilities."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ComparisonMetric:
    """Comparison of a single metric between current and baseline runs."""

    name: str
    current: float
    baseline: float
    diff: float
    pct_change: float
    status: str  # "IMPROVED", "SIMILAR", "REGRESSION"


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    """Side-by-side comparison of a single benchmark workload."""

    name: str
    suite: str
    workload_size: int
    throughput: ComparisonMetric
    latency: ComparisonMetric
    peak_memory: ComparisonMetric
    status: str  # "IMPROVED", "SIMILAR", "REGRESSION"

    @property
    def has_regression(self) -> bool:
        return self.status == "REGRESSION"


@dataclass(frozen=True, slots=True)
class RegressionReport:
    """Comprehensive comparison report across all benchmark workloads."""

    comparisons: tuple[BenchmarkComparison, ...]
    regressions_count: int
    improvements_count: int
    similar_count: int
    unmatched_current: tuple[str, ...]
    unmatched_baseline: tuple[str, ...]

    @property
    def has_regressions(self) -> bool:
        return self.regressions_count > 0

    @property
    def summary(self) -> str:
        total = len(self.comparisons)
        return (
            f"Compared {total} benchmarks: "
            f"{self.regressions_count} regressions, "
            f"{self.improvements_count} improvements, "
            f"{self.similar_count} similar."
        )


def _to_dict_record(item: Any) -> dict[str, Any]:
    if hasattr(item, "__dataclass_fields__"):
        return asdict(item)
    if isinstance(item, dict):
        return item
    raise TypeError(f"expected BenchmarkResult or dict, got {type(item).__name__}")


def compare_benchmarks(
    current: list[Any],
    baseline: list[Any],
    *,
    throughput_tolerance_pct: float = 20.0,
    memory_tolerance_pct: float = 25.0,
) -> RegressionReport:
    """Compare current benchmark results against baseline measurements.

    Identifies regressions and improvements in throughput, latency, and memory
    allocation without imposing hard machine-specific timing assertions in CI.
    """
    if throughput_tolerance_pct < 0:
        raise ValueError("throughput_tolerance_pct cannot be negative")
    if memory_tolerance_pct < 0:
        raise ValueError("memory_tolerance_pct cannot be negative")

    current_dicts = [_to_dict_record(r) for r in current]
    baseline_dicts = [_to_dict_record(r) for r in baseline]

    # Index baseline by (suite, name, workload_size)
    base_map: dict[tuple[str, str, int], dict[str, Any]] = {}
    for b in baseline_dicts:
        key = (
            str(b.get("suite", "")),
            str(b.get("name", "")),
            int(b.get("workload_size", 0)),
        )
        base_map[key] = b

    curr_keys: set[tuple[str, str, int]] = set()
    comparisons: list[BenchmarkComparison] = []
    regressions = 0
    improvements = 0
    similar = 0

    for c in current_dicts:
        key = (
            str(c.get("suite", "")),
            str(c.get("name", "")),
            int(c.get("workload_size", 0)),
        )
        curr_keys.add(key)
        if key not in base_map:
            continue

        b = base_map[key]

        # 1. Throughput (higher is better)
        c_tput = float(c.get("throughput_ops_per_s", 0.0))
        b_tput = float(b.get("throughput_ops_per_s", 0.0))
        diff_tput = c_tput - b_tput
        pct_tput = (diff_tput / b_tput * 100.0) if b_tput > 0 else 0.0

        if pct_tput < -throughput_tolerance_pct:
            status_tput = "REGRESSION"
        elif pct_tput > throughput_tolerance_pct:
            status_tput = "IMPROVED"
        else:
            status_tput = "SIMILAR"

        tput_metric = ComparisonMetric(
            name="throughput",
            current=c_tput,
            baseline=b_tput,
            diff=diff_tput,
            pct_change=pct_tput,
            status=status_tput,
        )

        # 2. Latency (lower is better)
        c_lat = float(c.get("mean_latency_us", 0.0))
        b_lat = float(b.get("mean_latency_us", 0.0))
        diff_lat = c_lat - b_lat
        pct_lat = (diff_lat / b_lat * 100.0) if b_lat > 0 else 0.0

        if pct_lat > throughput_tolerance_pct:
            status_lat = "REGRESSION"
        elif pct_lat < -throughput_tolerance_pct:
            status_lat = "IMPROVED"
        else:
            status_lat = "SIMILAR"

        lat_metric = ComparisonMetric(
            name="latency",
            current=c_lat,
            baseline=b_lat,
            diff=diff_lat,
            pct_change=pct_lat,
            status=status_lat,
        )

        # 3. Peak Memory (lower is better)
        c_mem = float(c.get("peak_memory_bytes", 0))
        b_mem = float(b.get("peak_memory_bytes", 0))
        diff_mem = c_mem - b_mem
        pct_mem = (diff_mem / b_mem * 100.0) if b_mem > 0 else 0.0

        if b_mem > 0:
            if pct_mem > memory_tolerance_pct:
                status_mem = "REGRESSION"
            elif pct_mem < -memory_tolerance_pct:
                status_mem = "IMPROVED"
            else:
                status_mem = "SIMILAR"
        else:
            status_mem = "SIMILAR"

        mem_metric = ComparisonMetric(
            name="peak_memory",
            current=c_mem,
            baseline=b_mem,
            diff=diff_mem,
            pct_change=pct_mem,
            status=status_mem,
        )

        # Overall status for this benchmark
        if status_tput == "REGRESSION" or status_mem == "REGRESSION":
            overall_status = "REGRESSION"
            regressions += 1
        elif status_tput == "IMPROVED" or status_mem == "IMPROVED":
            overall_status = "IMPROVED"
            improvements += 1
        else:
            overall_status = "SIMILAR"
            similar += 1

        comparisons.append(
            BenchmarkComparison(
                name=key[1],
                suite=key[0],
                workload_size=key[2],
                throughput=tput_metric,
                latency=lat_metric,
                peak_memory=mem_metric,
                status=overall_status,
            )
        )

    unmatched_curr = tuple(
        f"{c.get('suite')}/{c.get('name')} ({c.get('workload_size', 0):,})"
        for c in current_dicts
        if (
            str(c.get("suite", "")),
            str(c.get("name", "")),
            int(c.get("workload_size", 0)),
        )
        not in base_map
    )
    unmatched_base = tuple(
        f"{k[0]}/{k[1]} ({k[2]:,})" for k in base_map if k not in curr_keys
    )

    return RegressionReport(
        comparisons=tuple(comparisons),
        regressions_count=regressions,
        improvements_count=improvements,
        similar_count=similar,
        unmatched_current=unmatched_curr,
        unmatched_baseline=unmatched_base,
    )


def format_regression_table(report: RegressionReport) -> str:
    """Format benchmark comparison results as an aligned ASCII table."""
    title = "BENCHMARK PERFORMANCE & MEMORY REGRESSION REPORT"
    line = "=" * 115
    subline = "-" * 115

    lines = [f"\n{line}", f"{title:^115}", line]
    header = (
        f"{'Benchmark':<24} | {'Size':>8} | "
        f"{'Current Tput':>12} | {'Base Tput':>12} | {'Tput Chg':>9} | "
        f"{'Peak Mem':>9} | {'Status':>10}"
    )
    lines.append(header)
    lines.append(subline)

    for c in report.comparisons:
        c_tput_str = f"{c.throughput.current:,.0f}"
        b_tput_str = f"{c.throughput.baseline:,.0f}"
        tput_chg = f"{c.throughput.pct_change:+.1f}%"
        mem_mb = c.peak_memory.current / (1024 * 1024)
        mem_str = (
            f"{mem_mb:.2f}MB"
            if mem_mb >= 0.1
            else f"{c.peak_memory.current / 1024:.0f}KB"
        )

        lines.append(
            f"{c.name[:24]:<24} | {c.workload_size:>8,} | "
            f"{c_tput_str:>12} | {b_tput_str:>12} | {tput_chg:>9} | "
            f"{mem_str:>9} | {c.status:>10}"
        )

    lines.append(line)
    lines.append(f"Summary: {report.summary}")
    if report.unmatched_current:
        lines.append(f"New benchmarks in current run: {len(report.unmatched_current)}")
    if report.unmatched_baseline:
        lines.append(
            f"Missing benchmarks from baseline: {len(report.unmatched_baseline)}"
        )
    lines.append("")
    return "\n".join(lines)


def print_regression_report(report: RegressionReport) -> None:
    """Print the formatted regression report to stdout."""
    print(format_regression_table(report))


def save_baseline(results: list[Any], path: str | Path) -> Path:
    """Save benchmark results to disk as a JSON baseline file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = [_to_dict_record(r) for r in results]
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


def load_baseline(path: str | Path) -> list[dict[str, Any]]:
    """Load benchmark baseline results from a JSON file."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"baseline file not found: {target}")
    content = target.read_text(encoding="utf-8")
    data = json.loads(content)
    if not isinstance(data, list):
        raise ValueError("baseline JSON must contain a list of benchmark records")
    return data
