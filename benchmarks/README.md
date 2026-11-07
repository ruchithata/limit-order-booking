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
- **Throughput**: Mean operations processed per second ($\text{ops}/\text{sec}$).
- **Mean Latency**: Average duration per operation ($\mu\text{s}/\text{op}$).

---

## 5. Architectural Discussion & Systems Trade-Offs

- **Cancellation**: Soft tombstone cancellation through `OrderIndex` operates in $O(1)$ amortized time by marking `is_cancelled = True` in place, avoiding expensive $O(N)$ deque traversals.
- **Insertion**: Python `heapq` and dictionary hash lookups provide predictable $O(\log P)$ insertion overhead where $P$ represents active price levels rather than order count $N$.
- **Snapshot Overhead ($O(P \log P)$)**: Slicing snapshots by `depth` limits sorting to the top $N$ price tiers rather than the full active book.
