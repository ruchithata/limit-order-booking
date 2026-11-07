"""Example script demonstrating the public API and safe order-book snapshots."""

from engine import MatchingEngine, Order, OrderType, Side


def main() -> None:
    print("=== Limit Order Book Public API & Snapshot Demo ===\n")

    # 1. Initialize matching engine
    engine = MatchingEngine()

    # 2. Place resting liquidity (limit orders)
    print("Submitting resting limit orders...")
    bids_to_add = [
        Order(
            order_id="B1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100,
        ),
        Order(
            order_id="B2",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=25,
            price=100,
        ),
        Order(
            order_id="B3",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=15,
            price=99,
        ),
        Order(
            order_id="B4",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=30,
            price=98,
        ),
    ]
    asks_to_add = [
        Order(
            order_id="S1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=12,
            price=105,
        ),
        Order(
            order_id="S2",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=18,
            price=106,
        ),
        Order(
            order_id="S3",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=50,
            price=108,
        ),
    ]

    for order in bids_to_add + asks_to_add:
        engine.submit_order(order)

    # 3. Inspect order-book snapshot
    print("\n--- Current Order Book Snapshot ---")
    snapshot = engine.get_snapshot()

    print("Bids (Price-descending):")
    for level in snapshot.bids:
        print(f"  Price: {level.price:>4} | Volume: {level.quantity:>3}")

    print("Asks (Price-ascending):")
    for level in snapshot.asks:
        print(f"  Price: {level.price:>4} | Volume: {level.quantity:>3}")

    print(
        f"\nBest Bid: {engine.best_bid_price()} | Best Ask: {engine.best_ask_price()}"
    )

    # 4. Limited depth snapshot (Top-2 levels)
    top2 = engine.get_snapshot(depth=2)
    print(f"\nTop-2 Bids: {top2.bids}")
    print(f"Top-2 Asks: {top2.asks}")

    # 5. Execute an incoming market buy order
    print("\nExecuting incoming market BUY order for 15 units...")
    market_buy = Order(
        order_id="M1", side=Side.BUY, order_type=OrderType.MARKET, quantity=15
    )
    trades = engine.submit_order(market_buy)

    print(f"Executed {len(trades)} trade(s):")
    for trade in trades:
        print(
            f"  Trade #{trade.trade_id}: {trade.quantity} units @ ${trade.price} "
            f"(Maker: {trade.maker_order_id}, Taker: {trade.taker_order_id})"
        )

    # 6. Inspect updated snapshot after execution
    updated_snap = engine.get_snapshot()
    print("\nAsks after execution:")
    for level in updated_snap.asks:
        print(f"  Price: {level.price:>4} | Volume: {level.quantity:>3}")

    # 7. Order cancellation
    print("\nCancelling order B1...")
    cancelled = engine.cancel_order("B1")
    print(f"Order B1 cancelled: {cancelled}")

    after_cancel = engine.get_snapshot()
    print("Bids after B1 cancellation:")
    for level in after_cancel.bids:
        print(f"  Price: {level.price:>4} | Volume: {level.quantity:>3}")


if __name__ == "__main__":
    main()
