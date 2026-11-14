# Deterministic In-Memory Limit Order Book & Matching Core

A deterministic, zero-dependency electronic order matching engine written in Python 3.10+. This project models a continuous double-auction exchange core executing incoming flow under strict **Price-Time Priority ($FIFO$)**, fixed-point decimal arithmetic, and amortized $O(1)$ order cancellations.

---

## 1. Architectural Overview & Time Complexities

The engine isolates the matching core entirely in RAM—avoiding disk I/O, database bottlenecks, and floating-point errors to simulate low-latency exchange execution dynamics.

```text
                  MATCHING CORE TOPOLOGY

     [ BIDS: Inverted Min-Heap ]                 [ ASKS: Min-Heap ]
        (Highest Price on top)                 (Lowest Price on top)
                 │                                       │
                 ▼                                       ▼
       Price Tier: $100.50                     Price Tier: $100.60
   deque([Order A] -> [Order B])           deque([Order C] -> [Order D])
           (FIFO Queue)                            (FIFO Queue)
                 ▲                                       ▲
                 └───────────────────┬───────────────────┘
                                     │
                    [ Inverted Order Index: Dict ]
                        order_id ──> Order Ref
                         (O(1) Soft Cancellation)
```

### Algorithmic Complexity Guarantees

| Operation | Implementation Structure | Time Complexity | Engineering Rationale |
| :--- | :--- | :--- | :--- |
| **Top-of-Book Peek** | Binary Heap (`heapq`) | $O(1)$ | Best bid and ask prices are accessible immediately at the root index without scanning. |
| **New Limit Resting** | Binary Heap + Hash Map | $O(\log P)$ | $P$ represents active price tiers (hundreds), distinct from total orders $N$ (millions). |
| **Trade Execution** | Doubly-ended Queue (`collections.deque`) | $O(1)$ per fill | Time priority ($FIFO$) appends to tail and consumes/pops directly from head. |
| **Order Cancellation** | Inverted Hash Index + Tombstone | $O(1)$ amortized | Avoids $O(N)$ linear scans through queues by flagging cancellations in place. |
| **Book Snapshot** | Sorted Price Tiers + Tuple | $O(P \log P)$ | Generates immutable view of active bids/asks without mutating or exposing internal heaps or deques. |

---

## 2. Core Engineering Principles

### Fixed-Point Integer Pricing (Zero IEEE-754 Precision Drift)
Currency prices and quantities are strictly modeled as 64-bit unsigned integers representing fixed ticks (e.g., cents). Binary floating-point representation (`float`) introduces precision rounding bugs (e.g., `0.1 + 0.2 != 0.3`). Fixed-point representation guarantees zero accounting discrepancy across millions of state transitions.

### Lazy Tombstone Deletion
Deleting an order from the middle of a continuous queue requires an $O(N)$ traversal. To maintain low latency, `cancel_order()` marks the target order's internal flag (`is_cancelled = True`) in $O(1)$ time via an auxiliary lookup table. The engine lazily evicts dead orders only when they bubble up to the top of the queue or book during active matching.

### Decoupled Pure State Machine
The core engine contains no networking, external storage, or framework dependencies. Inputs and outputs are strictly deterministic domain events (`Order` in, list of `Trade` records out), allowing the matching logic to be directly ported to systems languages like C++ or OCaml.

---

## 3. Directory Layout

```plaintext
limit_order_book/
├── benchmarks/
│   ├── __init__.py        # Benchmark package initialization
│   ├── workloads.py       # Deterministic synthetic order workload generators
│   ├── regression.py      # Benchmark regression comparator and baseline management
│   ├── run_benchmarks.py  # Benchmark harness, memory profiler, and reporting tool
│   └── README.md          # Benchmark methodology, suites, and profiling notes
├── engine/
│   ├── __init__.py        # Public module exports
│   ├── event_log.py       # Append-only deterministic command journal
│   ├── matching_engine.py # Continuous double-auction matching engine
│   ├── order.py           # Order and Trade dataclass models
│   ├── order_book.py      # OrderBook and LevelSnapshot/OrderBookSnapshot models
│   ├── order_index.py     # O(1) active order index
│   ├── persistence.py     # Atomic snapshot disk persistence and manager
│   ├── price_level.py     # FIFO queue for price tiers
│   ├── recording.py       # RecordingMatchingEngine facade
│   ├── recovery.py        # Snapshot loading, replay gap check, and engine recovery
│   ├── replay.py          # Deterministic engine replay
│   ├── snapshot.py        # OrderSnapshot and EngineSnapshot serialization
│   └── types.py           # Domain enums (Side, OrderType)
├── examples/
│   └── basic_usage.py     # Runnable public API demonstration
├── tests/
│   ├── test_benchmark_workloads.py
│   ├── test_event_log.py
│   ├── test_invariants.py
│   ├── test_matching_engine.py
│   ├── test_order.py
│   ├── test_order_book.py
│   ├── test_order_cancellation.py
│   ├── test_price_level.py
│   ├── test_public_api.py
│   ├── test_recovery.py
│   ├── test_regression.py
│   ├── test_replay.py
│   ├── test_smoke.py
│   ├── test_snapshot.py
│   ├── test_snapshots.py
│   └── test_stress.py
├── pyproject.toml         # Packaging & test configuration
├── .gitignore
└── README.md
```

---

## 4. Public API & Usage

All core interfaces can be imported directly from the `engine` package:

```python
from engine import MatchingEngine, Order, OrderType, Side

# 1. Initialize the matching engine
engine = MatchingEngine()

# 2. Submit resting limit orders
engine.submit_order(
    Order(
        order_id="B1", side=Side.BUY, order_type=OrderType.LIMIT, quantity=10, price=100
    )
)
engine.submit_order(
    Order(
        order_id="S1", side=Side.SELL, order_type=OrderType.LIMIT, quantity=5, price=105
    )
)

# 3. Take an immutable order-book snapshot (safe from internal mutations)
snapshot = engine.get_snapshot()

# Inspect bids (descending by price) and asks (ascending by price)
print("Bids:", [(lvl.price, lvl.quantity) for lvl in snapshot.bids])  # [(100, 10)]
print("Asks:", [(lvl.price, lvl.quantity) for lvl in snapshot.asks])  # [(105, 5)]

# Limit snapshot depth to top N levels
top1 = engine.get_snapshot(depth=1)

# 4. Submit a matching order (generates Trade records)
trades = engine.submit_order(
    Order(order_id="M1", side=Side.BUY, order_type=OrderType.MARKET, quantity=3)
)
for trade in trades:
    print(f"Trade #{trade.trade_id}: {trade.quantity} @ {trade.price}")

# 5. Cancel a resting order in O(1) time
engine.cancel_order("B1")
```

---

## 5. State Persistence, Event Logging & Fast Recovery

Replaying an entire event journal from inception becomes computationally prohibitive when an exchange core processes millions of orders. To achieve fast, crash-resilient recovery:

1. **State Snapshotting (`EngineSnapshot`)**: Periodically captures active resting orders (preserving exact price-time FIFO ordering), next trade ID, and the last processed sequence number.
2. **Atomic Persistence (`save_snapshot`, `SnapshotManager`)**: Writes snapshots via temp files with atomic rename to guarantee files on disk are never corrupted by process interruptions.
3. **Deterministic Recovery (`recover_state`, `recover_recording_engine`)**: Restores engine state directly from the latest snapshot and replays only newer subsequent events, validating sequence continuity and order book invariants.

```text
                  RECOVERY WORKFLOW TOPOLOGY

     [ Event Journal: events.jsonl ]
      (Events 1 .. 1,000,000)
              │
              ├─── Events 1..500,000 (Already incorporated)
              │
     [ Snapshot: snapshot.json ] ───> Restore Engine State directly (O(Active Orders))
      (Taken at sequence 500,000)
              │
              └─── Events 500,001..1,000,000 ───> Replay ONLY newer delta
                                                         │
                                                         ▼
                                              [ Fully Restored Engine ]
```

### Persistence and Recovery Example

```python
from engine import (
    EventLog,
    Order,
    OrderType,
    RecordingMatchingEngine,
    Side,
    load_snapshot,
    recover_recording_engine,
    recover_state,
    save_snapshot,
)

# 1. Run engine with append-only event logging
log = EventLog("events.jsonl")
recorder = RecordingMatchingEngine(event_log=log)

recorder.submit_order(Order("B1", Side.BUY, OrderType.LIMIT, 10, 100))
recorder.submit_order(Order("S1", Side.SELL, OrderType.LIMIT, 5, 105))

# 2. Periodically persist state snapshot atomically
save_snapshot(recorder.create_snapshot(), "snapshot.json")

# 3. Continue processing further orders
recorder.submit_order(Order("B2", Side.BUY, OrderType.LIMIT, 8, 99))
recorder.cancel_order("B1")

# 4. Fast Recovery: load snapshot and replay only newer events (B2, cancel B1)
result = recover_state(snapshot="snapshot.json", events="events.jsonl")
recovered_engine = result.matching_engine

print(f"Replayed {result.events_replayed} newer events")
print("Bids:", [(lvl.price, lvl.quantity) for lvl in recovered_engine.bids()])

# 5. Seamlessly resume recording new orders with contiguous sequence numbering
active_recorder = recover_recording_engine(
    snapshot="snapshot.json", event_log="events.jsonl"
)
active_recorder.submit_order(Order("B3", Side.BUY, OrderType.LIMIT, 4, 98))
```

---

## 6. Quickstart & Verification

### Prerequisites
- Python 3.10 or higher
- `pytest` for automated test verification

### 1. Installation & Environment

```bash
# Clone the repository
git clone https://github.com/<your-username>/limit-order-book.git
cd limit-order-book

# (Optional) Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install test dependencies
pip install pytest
```

### 2. Run Test Suite

The test suite validates Price-Time ($FIFO$) ordering, partial fills, resting limit queues, crossed-spread sweeps, and $O(1)$ cancellations:

```bash
pytest -v
```

### 3. Run Usage Example

Demonstrates submitting limit orders, executing trades, and inspecting immutable snapshots:

```bash
python examples/basic_usage.py
```

### 4. Run Performance Benchmarks

Measures order insertion, cancellation, matching, sweeps, and snapshots across reproducible synthetic workloads:

```bash
# Run full benchmark suite
python -m benchmarks.run_benchmarks

# Or run quick benchmarks for rapid feedback
python -m benchmarks.run_benchmarks --quick
```

---

## 7. Performance Benchmarking, Memory Profiling & Stress Testing

The engine includes reproducible micro-benchmarks, large-scale workloads (100,000+ orders), mixed order flows, high-volume stress tests, memory tracking (`tracemalloc`), and automated regression checks:

```bash
# Run standard benchmark suite
python -m benchmarks.run_benchmarks

# Run quick benchmark smoke test
python -m benchmarks.run_benchmarks --quick

# Run large-scale workloads (up to 100,000+ orders)
python -m benchmarks.run_benchmarks --large

# Run dedicated high-volume stress testing suite
python -m benchmarks.run_benchmarks --suite stress

# Save and compare against baselines (regression checks without brittle CI thresholds)
python -m benchmarks.run_benchmarks --save-baseline baseline.json
python -m benchmarks.run_benchmarks --baseline baseline.json
```

Detailed methodology, workload specifications, memory profiling metrics, and regression detection are documented in [`benchmarks/README.md`](benchmarks/README.md).

---

## 8. Next Steps & Production Systems Scaling

- **Intrusive Pre-allocated Memory Pools**: Porting this architecture to C++20 or OCaml to replace Python dynamic heap allocations with fixed-size contiguous memory blocks.
- **Direct Tick Array Indexing**: Utilizing dense array indexing for price tiers within active bands, finding best bid/ask via bitboards (`__builtin_ctzll`) in single CPU cycles.
- **Deterministic Replay (WAL)**: Appending raw binary message streams to append-only memory-mapped ring buffers for disaster recovery and crash idempotency.
