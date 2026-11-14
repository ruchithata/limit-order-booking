# Matching Engine Benchmarks & Profiling

A reproducible, zero-dependency performance benchmarking suite for the deterministic limit order book matching engine.

---

## 1. Quickstart

Run all benchmark suites directly from the repository root:

```bash
# Full benchmark suite (default 3 repetitions across small, medium, and large workloads)
python -m benchmarks.run_benchmarks

# Quick mode for rapid local smoke testing (~1-2 seconds)
python -m benchmarks.run_benchmarks --quick

# Large-scale workloads (up to 100,000+ orders)
python -m benchmarks.run_benchmarks --large

# Filter by a specific benchmark suite
python -m benchmarks.run_benchmarks --suite insertion
python -m benchmarks.run_benchmarks --suite cancellation
python -m benchmarks.run_benchmarks --suite matching
python -m benchmarks.run_benchmarks --suite mixed
python -m benchmarks.run_benchmarks --suite snapshot
python -m benchmarks.run_benchmarks --suite stress

# Save a performance and memory baseline
python -m benchmarks.run_benchmarks --save-baseline baseline.json

# Compare current execution against a saved baseline (detect regressions without brittle CI thresholds)
python -m benchmarks.run_benchmarks --baseline baseline.json

# Output JSON for automated reporting / visualization
python -m benchmarks.run_benchmarks --quick --json
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

### 5. Mixed Order Flow (`mixed`)
- **Workload**: Realistic continuous stream interleaving resting limit orders (makers), crossing limit orders (aggressive takers), market orders, and cancellations of previously resting orders.
- **Operations Measured**: End-to-end execution of live multi-action order streams reflecting authentic double-auction exchange dynamics.
- **Complexity**: Blended $O(1)$ amortized across FIFO queue fills, soft cancellations, and $O(\log P)$ heap insertions.

### 6. Stress Testing & Large-Scale Workloads (`stress`)
- **Workload**: High-volume operations under deep order books (up to 100,000 orders), extreme price spreads, high cancellation churn (80%+ tombstones), and deep multi-level sweeps.
- **Operations Measured**: Memory consumption, queue integrity, and throughput stability under prolonged pressure and high queue density.

---

## 3. Methodology & Design

1. **Zero Runtime Dependencies**: Timing uses standard Python `time.perf_counter()` with sub-microsecond resolution.
2. **Warmup & Multi-Repetition Timing**: Each workload runs an unmeasured warmup pass to warm instruction caches and allocator pools, followed by $R$ measured repetitions (default: 3).
3. **Isolated Setup per Repetition**: Every repetition operates on freshly initialized orders and engine state, ensuring that order state mutations (such as fill deductions and cancellation flags) never leak between runs.
4. **Memory Profiling (`tracemalloc`)**: Measures peak and net memory consumption per workload using Python's standard `tracemalloc` in a dedicated pass, avoiding instrumentation overhead during timed latency/throughput runs.
5. **Statistical Rigor**: Reports minimum elapsed time (best-case to filter OS preemption noise), arithmetic mean, standard deviation, operations per second (throughput based on mean duration), and mean latency per operation ($\mu\text{s}/\text{op}$).
6. **Regression Analysis Without Fragile CI Gates**: Side-by-side comparison against baseline JSON runs identifies performance drops or memory growth with configurable tolerances, avoiding flaky wall-clock threshold failures in virtualized CI environments.
7. **Decoupled from Unit Tests**: Fast unit tests validate workload generation and comparator mechanics, while heavy stress suites remain decoupled or run on demand.

---

## 4. Benchmark Execution & Reporting

Run the benchmark suite to generate baseline metrics on your environment:

```bash
python -m benchmarks.run_benchmarks
```

The runner formats results in an ASCII table or JSON export (`--json`) reporting:
- **Workload Size**: Number of operations executed in the timed block.
- **Min & Mean Elapsed Time**: Best and average durations across repetitions.
- **Peak Memory**: Maximum memory tracked by `tracemalloc` during execution.
- **Throughput**: Mean operations processed per second ($\text{ops}/\text{sec}$, calculated consistently from mean duration).
- **Mean Latency**: Average duration per operation ($\mu\text{s}/\text{op}$, calculated consistently from mean duration).

### Machine-Specific Sample Baseline

> [!NOTE]
> The figures below represent machine-specific benchmark measurements captured in a local development environment (Python 3.13.1 on x86-64 Windows, 13th Gen Intel Core i7). They are provided solely for illustrative reference and should not be interpreted as guaranteed or uniform performance across all hardware, operating systems, or Python runtimes. Run `python -m benchmarks.run_benchmarks` to establish a baseline for your specific environment.

```text
==========================================================================================================================
                                  LIMIT ORDER BOOK PERFORMANCE & MEMORY BENCHMARK REPORT                                  
==========================================================================================================================
Benchmark                | Workload Details                 |     Size |  Min (s) | Mean (s) |  Peak Mem |    Throughput |   Latency
--------------------------------------------------------------------------------------------------------------------------
[INSERTION]
  Limit Order Insertion  | Insert 1,000 non-crossing limit  |    1,000 |   0.0081 |   0.0091 |   0.62 MB |  109,942 op/s |   9.10 us
  Limit Order Insertion  | Insert 5,000 non-crossing limit  |    5,000 |   0.0180 |   0.0258 |   1.24 MB |  193,774 op/s |   5.16 us
[CANCELLATION]
  Order Cancellation     | Cancel 500 orders in book of siz |      500 |   0.0002 |   0.0004 |      0 KB | 1,192,464 op/s |   0.84 us
  Order Cancellation     | Cancel 2,500 orders in book of s |    2,500 |   0.0013 |   0.0021 |      0 KB | 1,178,208 op/s |   0.85 us
[MATCHING]
  Market Order Execution | 1,000 market orders against 2,00 |    1,000 |   0.0188 |   0.0322 |      6 KB |   31,089 op/s |  32.17 us
  Crossing Limit Orders  | 1,000 continuous crossing limit  |    1,000 |   0.0158 |   0.0167 |     80 KB |   59,881 op/s |  16.70 us
  Market Order Execution | 5,000 market orders against 10,0 |    5,000 |   0.1744 |   0.3094 |      7 KB |   16,160 op/s |  61.88 us
  Crossing Limit Orders  | 5,000 continuous crossing limit  |    5,000 |   0.1841 |   0.1905 |   0.17 MB |   26,243 op/s |  38.11 us
  Multi-Level Sweep      | Sweeping 25 price levels in rest |        2 |   0.0156 |   0.0183 |     56 KB |      109 op/s |   9.15 ms
[MIXED]
  Mixed Order Flow       | 1,000 mixed limit/market/cancel  |    1,000 |   0.0317 |   0.0340 |     68 KB |   29,403 op/s |  34.01 us
  Mixed Order Flow       | 5,000 mixed limit/market/cancel  |    5,000 |   0.1666 |   0.2079 |   0.19 MB |   24,055 op/s |  41.57 us
[SNAPSHOT]
  OrderBook Snapshot     | 20 levels/side (depth=5, 200 cal |      200 |   0.0152 |   0.0158 |     34 KB |   12,646 op/s |  79.07 us
  OrderBook Snapshot     | 20 levels/side (full depth, 200  |      200 |   0.0406 |   0.0455 |     83 KB |    4,391 op/s | 227.74 us
  OrderBook Snapshot     | 50 levels/side (depth=5, 200 cal |      200 |   0.0212 |   0.0227 |     34 KB |    8,819 op/s | 113.39 us
  OrderBook Snapshot     | 50 levels/side (full depth, 200  |      200 |   0.1040 |   0.1052 |     10 KB |    1,901 op/s | 526.13 us
[STRESS]
  Stress Book Insertion  | Insert 5,000 orders into deep bo |    5,000 |   0.1202 |   0.1202 |   2.93 MB |   41,586 op/s |  24.05 us
  Stress High-Churn Cancellation | Cancel 4,000 orders in 5,000 boo |    4,000 |   0.0086 |   0.0086 |      1 KB |  465,891 op/s |   2.15 us
  Stress Mixed Flow      | Execute 5,000 high-volume mixed  |    5,000 |   0.2178 |   0.2178 |   0.18 MB |   22,957 op/s |  43.56 us
==========================================================================================================================
```

### Baseline Regression Comparison

Save a baseline from one version and compare future runs against it:

```bash
# Save baseline from main or pre-PR branch
python -m benchmarks.run_benchmarks --save-baseline baseline.json

# Compare feature branch against baseline
python -m benchmarks.run_benchmarks --baseline baseline.json
```

Sample comparison report:

```text
===================================================================================================================
                                 BENCHMARK PERFORMANCE & MEMORY REGRESSION REPORT                                  
===================================================================================================================
Benchmark                |     Size | Current Tput |    Base Tput |  Tput Chg |  Peak Mem |     Status
-------------------------------------------------------------------------------------------------------------------
Limit Order Insertion    |    1,000 |      115,200 |      109,942 |     +4.8% |    0.62MB |    SIMILAR
Order Cancellation       |      500 |    1,250,000 |    1,192,464 |     +4.8% |       0KB |    SIMILAR
Market Order Execution   |    1,000 |       32,500 |       31,089 |     +4.5% |       6KB |    SIMILAR
Mixed Order Flow         |    1,000 |       31,200 |       29,403 |     +6.1% |      68KB |    SIMILAR
===================================================================================================================
Summary: Compared 4 benchmarks: 0 regressions, 0 improvements, 4 similar.
```

---

## 5. Architectural Discussion & Systems Trade-Offs

- **Cancellation**: Soft tombstone cancellation through `OrderIndex` operates in $O(1)$ amortized time by marking `is_cancelled = True` in place, avoiding expensive $O(N)$ deque traversals.
- **Insertion**: Python `heapq` and dictionary hash lookups provide predictable $O(\log P)$ insertion overhead where $P$ represents active price levels rather than order count $N$.
- **Snapshot Overhead ($O(P \log P)$)**: Slicing snapshots by `depth` limits sorting to the top $N$ price tiers rather than the full active book.
