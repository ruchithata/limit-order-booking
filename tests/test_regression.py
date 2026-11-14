"""Tests for benchmark comparison and regression detection."""

from __future__ import annotations

from pathlib import Path

import pytest
from benchmarks.regression import (
    BenchmarkComparison,
    ComparisonMetric,
    RegressionReport,
    compare_benchmarks,
    format_regression_table,
    load_baseline,
    save_baseline,
)
from benchmarks.run_benchmarks import BenchmarkResult


def _create_mock_result(
    suite: str,
    name: str,
    size: int,
    tput: float,
    lat: float,
    mem: int = 1_000_000,
) -> BenchmarkResult:
    return BenchmarkResult(
        suite=suite,
        name=name,
        workload_description="mock",
        workload_size=size,
        repetitions=3,
        min_time_s=size / tput,
        mean_time_s=size / tput,
        max_time_s=size / tput,
        stdev_time_s=0.0,
        throughput_ops_per_s=tput,
        mean_latency_us=lat,
        peak_memory_bytes=mem,
    )


def test_compare_benchmarks_detects_regressions_and_improvements() -> None:
    baseline = [
        _create_mock_result("insertion", "Limit Order Insertion", 5000, 100_000, 10.0),
        _create_mock_result("cancellation", "Order Cancellation", 5000, 100_000, 10.0),
        _create_mock_result("matching", "Market Order Execution", 5000, 100_000, 10.0),
    ]

    current = [
        # 50% throughput drop (regression)
        _create_mock_result("insertion", "Limit Order Insertion", 5000, 50_000, 20.0),
        # 40% throughput increase (improvement)
        _create_mock_result("cancellation", "Order Cancellation", 5000, 140_000, 7.14),
        # 5% change (similar)
        _create_mock_result("matching", "Market Order Execution", 5000, 105_000, 9.52),
    ]

    report = compare_benchmarks(
        current, baseline, throughput_tolerance_pct=20.0, memory_tolerance_pct=25.0
    )

    assert isinstance(report, RegressionReport)
    assert report.has_regressions is True
    assert report.regressions_count == 1
    assert report.improvements_count == 1
    assert report.similar_count == 1

    cmp_map = {c.suite: c for c in report.comparisons}
    assert cmp_map["insertion"].status == "REGRESSION"
    assert cmp_map["cancellation"].status == "IMPROVED"
    assert cmp_map["matching"].status == "SIMILAR"


def test_compare_benchmarks_memory_regression() -> None:
    baseline = [
        _create_mock_result(
            "stress", "Stress Flow", 10_000, 100_000, 10.0, mem=2_000_000
        ),
    ]

    # Memory increases by 60% (from 2MB to 3.2MB) with 25% tolerance
    current_regressed = [
        _create_mock_result(
            "stress", "Stress Flow", 10_000, 100_000, 10.0, mem=3_200_000
        ),
    ]

    report_reg = compare_benchmarks(
        current_regressed, baseline, memory_tolerance_pct=25.0
    )
    assert report_reg.regressions_count == 1
    assert report_reg.comparisons[0].peak_memory.status == "REGRESSION"

    # Memory decreases by 40% (improvement)
    current_improved = [
        _create_mock_result(
            "stress", "Stress Flow", 10_000, 100_000, 10.0, mem=1_200_000
        ),
    ]

    report_imp = compare_benchmarks(
        current_improved, baseline, memory_tolerance_pct=25.0
    )
    assert report_imp.improvements_count == 1
    assert report_imp.comparisons[0].peak_memory.status == "IMPROVED"


def test_compare_benchmarks_handles_unmatched_records() -> None:
    baseline = [
        _create_mock_result("insertion", "Old Benchmark", 1000, 50_000, 20.0),
    ]
    current = [
        _create_mock_result("matching", "New Benchmark", 2000, 80_000, 12.5),
    ]

    report = compare_benchmarks(current, baseline)
    assert len(report.comparisons) == 0
    assert len(report.unmatched_current) == 1
    assert len(report.unmatched_baseline) == 1


def test_save_and_load_baseline(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    results = [
        _create_mock_result("insertion", "Insert", 1000, 50_000, 20.0),
        _create_mock_result("matching", "Match", 1000, 30_000, 33.3),
    ]

    saved = save_baseline(results, path)
    assert saved == path
    assert path.is_file()

    loaded = load_baseline(path)
    assert len(loaded) == 2
    assert loaded[0]["name"] == "Insert"
    assert loaded[1]["name"] == "Match"

    # Compare directly with loaded dicts
    report = compare_benchmarks(results, loaded)
    assert report.regressions_count == 0
    assert report.similar_count == 2


def test_regression_input_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="throughput_tolerance_pct cannot be negative"):
        compare_benchmarks([], [], throughput_tolerance_pct=-5.0)

    with pytest.raises(ValueError, match="memory_tolerance_pct cannot be negative"):
        compare_benchmarks([], [], memory_tolerance_pct=-5.0)

    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path / "missing.json")


def test_format_regression_table() -> None:
    metric = ComparisonMetric("throughput", 100_000, 80_000, 20_000, 25.0, "IMPROVED")
    lat_metric = ComparisonMetric("latency", 10.0, 12.5, -2.5, -20.0, "IMPROVED")
    mem_metric = ComparisonMetric(
        "peak_memory", 1_000_000, 1_000_000, 0, 0.0, "SIMILAR"
    )

    cmp = BenchmarkComparison(
        name="Test Benchmark",
        suite="test",
        workload_size=5000,
        throughput=metric,
        latency=lat_metric,
        peak_memory=mem_metric,
        status="IMPROVED",
    )

    report = RegressionReport(
        comparisons=(cmp,),
        regressions_count=0,
        improvements_count=1,
        similar_count=0,
        unmatched_current=(),
        unmatched_baseline=(),
    )

    table = format_regression_table(report)
    assert "BENCHMARK PERFORMANCE & MEMORY REGRESSION REPORT" in table
    assert "Test Benchmark" in table
    assert "IMPROVED" in table
    assert "Summary:" in table
