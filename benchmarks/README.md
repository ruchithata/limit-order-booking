# Matching Engine Benchmarks & Profiling

A reproducible, zero-dependency performance benchmarking suite for the deterministic limit order book matching engine.

---

## 1. Quickstart

Run all benchmark suites directly from the repository root:

```bash
# Full benchmark suite (default 3 repetitions across small, medium, and large workloads)
python -m benchmarks.run_benchmarks

# Quick mode for rapid local smoke testing (~1-2 seconds)
python benchmarks/run_benchmarks.py --quick

# Filter by a specific benchmark suite
python benchmarks/run_benchmarks.py --suite insertion
python benchmarks/run_benchmarks.py --suite cancellation
python benchmarks/run_benchmarks.py --suite matching
python benchmarks/run_benchmarks.py --suite snapshot

# Output JSON for automated reporting / visualization
python benchmarks/run_benchmarks.py --quick --json
```

---

## 2. Benchmark Suites & Workloads

All synthetic workloads are generated deterministically using standard pseudorandom seeds (`random.Random(seed)`), guaranteeing identical, reproducible input streams across runs.

### 1. Order Insertion (`insertion`)
- **Workload**: Streams of non-crossing BUY and SELL limit orders.
- **Operations Measured**: Ingesting orders into the active order book, pushing new price tiers into binary heaps (`heapq`), and appending to price-level FIFO queues (`collections.deque`).
- **Complexity**: $O(\log P)$ for new price tiers; $O(1)$ for existing price tiers.

### 2. Order Cancellation (`cancellation`)
- **Workload**: Books pre-populated with $1,000$ to $50,000$ resting orders; random samples (50% of the book) are targeted for cancellation.
- **Operations Measured**: Look up in `OrderIndex` hash map, tombstone flagging (`is_cancelled = True`), and aggregate quantity deduction.
- **Complexity**: $O(1)$ amortized soft cancellation (avoiding $O(N)$ linear scans through FIFO queues).

### 3. Order Matching (`matching`)
- **Workload**:
  - **Market Orders**: Ingestion of incoming market orders executing against deep resting liquidity on both bid and ask sides.
  - **Crossing Limit Orders**: Interleaved limit orders crossing the spread, exercising continuous matches, partial fills, and residual limit resting.
  - **Multi-Level Sweeps**: Aggressive market orders large enough to completely exhaust multiple price tiers (25+ levels), measuring heap popping and level cleanups.
- **Complexity**: $O(1)$ per fill queue operation; $O(\log P)$ for price level transitions.

### 4. Order-Book Snapshots (`snapshot`)
- **Workload**: Order books populated across 50 to 200 active price levels.
- **Operations Measured**: Generating immutable [`OrderBookSnapshot`](../engine/order_book.py) instances across full book depth and truncated slices (`depth=10`, `depth=50`).
- **Complexity**: $O(P \log P)$ where $P$ is active price levels.

---

## 3. Methodology & Design

1. **Zero Runtime Dependencies**: Timing uses standard Python `time.perf_counter()` with sub-microsecond resolution.
2. **Warmup & Multi-Repetition Timing**: Each workload runs an unmeasured warmup pass to warm instruction caches and allocator pools, followed by $R$ measured repetitions (default: 3).
3. **Isolated Setup per Repetition**: Every repetition operates on freshly initialized orders and engine state, ensuring that order state mutations (such as fill deductions and cancellation flags) never leak between runs.
4. **Statistical Rigor**: Reports minimum elapsed time (best-case to filter OS preemption noise), arithmetic mean, standard deviation, operations per second (throughput based on mean duration), and mean latency per operation ($\mu\text{s}/\text{op}$).
5. **Decoupled from CI / Unit Tests**: The test suite in `tests/test_benchmark_workloads.py` only validates workload generation correctness and runner metrics on miniature datasets, keeping `pytest` sub-second and immune to environment jitter.

---

## 4. Benchmark Execution & Reporting

Run the benchmark suite to generate baseline metrics on your environment:

```bash
python -m benchmarks.run_benchmarks
```

The runner formats results in an ASCII table or JSON export (`--json`) reporting:
- **Workload Size**: Number of operations executed in the timed block.
- **Min & Mean Elapsed Time**: Best and average durations across repetitions.
- **Throughput**: Mean operations processed per second ($\text{ops}/\text{sec}$, calculated consistently from mean duration).
- **Mean Latency**: Average duration per operation ($\mu\text{s}/\text{op}$, calculated consistently from mean duration).

### Machine-Specific Sample Baseline

> [!NOTE]
> The figures below represent machine-specific benchmark measurements captured in a local development environment (Python 3.13.1 on x86-64 Windows, 13th Gen Intel Core i7). They are provided solely for illustrative reference and should not be interpreted as guaranteed or uniform performance across all hardware, operating systems, or Python runtimes. Run `python -m benchmarks.run_benchmarks` to establish a baseline for your specific environment.

```text
==============================================================================================================
                                LIMIT ORDER BOOK PERFORMANCE BENCHMARK REPORT                                 
==============================================================================================================
Benchmark                | Workload Details                   |     Size |  Min (s) | Mean (s) |    Throughput |   Latency
--------------------------------------------------------------------------------------------------------------
[INSERTION]
  Limit Order Insertion  | Insert 1,000 non-crossing limit or |    1,000 |   0.0027 |   0.0032 |  311,805 op/s |   3.21 us
  Limit Order Insertion  | Insert 5,000 non-crossing limit or |    5,000 |   0.0120 |   0.0126 |  397,124 op/s |   2.52 us
[CANCELLATION]
  Order Cancellation     | Cancel 500 orders in book of size  |      500 |   0.0002 |   0.0002 | 2,515,934 op/s |   0.40 us
  Order Cancellation     | Cancel 2,500 orders in book of siz |    2,500 |   0.0009 |   0.0011 | 2,304,006 op/s |   0.43 us
[MATCHING]
  Market Order Execution | 1,000 market orders against 2,000  |    1,000 |   0.0129 |   0.0145 |   68,947 op/s |  14.50 us
  Crossing Limit Orders  | 1,000 continuous crossing limit or |    1,000 |   0.0060 |   0.0062 |  161,200 op/s |   6.20 us
  Market Order Execution | 5,000 market orders against 10,000 |    5,000 |   0.0872 |   0.0884 |   56,573 op/s |  17.68 us
  Crossing Limit Orders  | 5,000 continuous crossing limit or |    5,000 |   0.0375 |   0.0398 |  125,553 op/s |   7.96 us
  Multi-Level Sweep      | Sweeping 25 price levels in restin |        2 |   0.0028 |   0.0037 |      548 op/s |   1.83 ms
[SNAPSHOT]
  OrderBook Snapshot     | 20 levels/side (depth=5, 200 calls |      200 |   0.0032 |   0.0039 |   51,553 op/s |  19.40 us
  OrderBook Snapshot     | 20 levels/side (full depth, 200 ca |      200 |   0.0100 |   0.0127 |   15,798 op/s |  63.30 us
  OrderBook Snapshot     | 50 levels/side (depth=5, 200 calls |      200 |   0.0043 |   0.0060 |   33,592 op/s |  29.77 us
  OrderBook Snapshot     | 50 levels/side (full depth, 200 ca |      200 |   0.0263 |   0.0296 |    6,749 op/s | 148.18 us
==============================================================================================================
```

---

## 5. Architectural Discussion & Systems Trade-Offs

- **Cancellation**: Soft tombstone cancellation through `OrderIndex` operates in $O(1)$ amortized time by marking `is_cancelled = True` in place, avoiding expensive $O(N)$ deque traversals.
- **Insertion**: Python `heapq` and dictionary hash lookups provide predictable $O(\log P)$ insertion overhead where $P$ represents active price levels rather than order count $N$.
- **Snapshot Overhead ($O(P \log P)$)**: Slicing snapshots by `depth` limits sorting to the top $N$ price tiers rather than the full active book.
