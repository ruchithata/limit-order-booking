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
- **Operations Measured**: Generating immutable [`OrderBookSnapshot`](file:///R:/projects/orders/limit-order-booking/engine/order_book.py) instances across full book depth and truncated slices (`depth=10`, `depth=50`).
- **Complexity**: $O(P \log P)$ where $P$ is active price levels.

---

## 3. Methodology & Design

1. **Zero Runtime Dependencies**: Timing uses standard Python `time.perf_counter()` with sub-microsecond resolution.
2. **Warmup & Multi-Repetition Timing**: Each workload runs an unmeasured warmup pass to warm instruction caches and allocator pools, followed by $R$ measured repetitions (default: 3).
3. **Isolated Setup per Repetition**: Every repetition operates on freshly initialized orders and engine state, ensuring that order state mutations (such as fill deductions and cancellation flags) never leak between runs.
4. **Statistical Rigor**: Reports minimum elapsed time (best-case to filter OS preemption noise), arithmetic mean, standard deviation, operations per second (throughput), and mean latency per operation ($\mu\text{s}/\text{op}$).
5. **Decoupled from CI / Unit Tests**: The test suite in `tests/test_benchmark_workloads.py` only validates workload generation correctness and runner metrics on miniature datasets, keeping `pytest` sub-second and immune to environment jitter.

---

## 4. Baseline Results

Measured on Python 3.13 (x86-64, Windows):

```text
==============================================================================================================
                                LIMIT ORDER BOOK PERFORMANCE BENCHMARK REPORT                                 
==============================================================================================================
Benchmark                | Workload Details                   |     Size |  Min (s) | Mean (s) |    Throughput |   Latency
--------------------------------------------------------------------------------------------------------------
[INSERTION]
  Limit Order Insertion  | Insert 1,000 non-crossing limit or |    1,000 |   0.0024 |   0.0035 |  425,279 op/s |   3.46 us
  Limit Order Insertion  | Insert 5,000 non-crossing limit or |    5,000 |   0.0141 |   0.0149 |  354,648 op/s |   2.99 us
[CANCELLATION]
  Order Cancellation     | Cancel 500 orders in book of size  |      500 |   0.0002 |   0.0002 | 2,863,689 op/s |   0.39 us
  Order Cancellation     | Cancel 2,500 orders in book of siz |    2,500 |   0.0010 |   0.0015 | 2,523,214 op/s |   0.60 us
[MATCHING]
  Market Order Execution | 1,000 market orders against 2,000  |    1,000 |   0.0163 |   0.0174 |   61,518 op/s |  17.39 us
  Crossing Limit Orders  | 1,000 continuous crossing limit or |    1,000 |   0.0059 |   0.0067 |  170,198 op/s |   6.73 us
  Market Order Execution | 5,000 market orders against 10,000 |    5,000 |   0.0707 |   0.0730 |   70,692 op/s |  14.60 us
  Crossing Limit Orders  | 5,000 continuous crossing limit or |    5,000 |   0.0570 |   0.0580 |   87,761 op/s |  11.61 us
  Multi-Level Sweep      | Sweeping 25 price levels in restin |        2 |   0.0084 |   0.0089 |      238 op/s |   4.43 ms
[SNAPSHOT]
  OrderBook Snapshot     | 20 levels/side (depth=5, 200 calls |      200 |   0.0031 |   0.0050 |   65,100 op/s |  25.08 us
  OrderBook Snapshot     | 20 levels/side (full depth, 200 ca |      200 |   0.0105 |   0.0113 |   18,963 op/s |  56.61 us
  OrderBook Snapshot     | 50 levels/side (depth=5, 200 calls |      200 |   0.0041 |   0.0052 |   49,159 op/s |  25.93 us
  OrderBook Snapshot     | 50 levels/side (full depth, 200 ca |      200 |   0.0254 |   0.0266 |    7,866 op/s | 132.97 us
==============================================================================================================
```

---

## 5. Architectural Discussion & Systems Trade-Offs

- **Cancellation ($2.5\text{M}+ \text{ops/s}$)**: Soft tombstone cancellation through `OrderIndex` achieves sub-microsecond latency ($~0.4-0.6\mu\text{s}$) by marking `is_cancelled = True` without shifting deque elements.
- **Insertion ($350\text{k}-425\text{k} \text{ops/s}$)**: Python `heapq` and dictionary hash lookups provide predictable $O(\log P)$ insertion.
- **Snapshot Overhead ($O(P \log P)$)**: Slicing snapshots by `depth` significantly accelerates throughput ($65\text{k}$ snapshots/sec at `depth=5` vs $18\text{k}$ at full depth).
