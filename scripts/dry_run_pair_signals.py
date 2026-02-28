#!/usr/bin/env python3
"""
Dry-run: fetch candles for a pair, run all 3 strategies, log results.
Run twice with a short delay to see if candle data and confidence change.
Usage: from project root:  python scripts/dry_run_pair_signals.py [PAIR]
Default PAIR: B-OP_USDT
"""
import os
import sys
import time

# Run from project root; bot must be on path for coindcx and strategy_manager
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bot_path = os.path.join(project_root, "bot")
if bot_path not in sys.path:
    sys.path.insert(0, bot_path)
os.chdir(bot_path)

from coindcx import CoinDCXREST

# Strategy keys (must match server)
STRATEGY_ORDER = ["double_ema_pullback"]


def get_strategy_instance(key):
    try:
        import strategy_manager
        strategies = getattr(strategy_manager.strategy_manager, "strategies", {})
        # Keys in strategy_manager are get_name().lower().replace(' ', '_')
        strategy_class = strategies.get(key)
        if strategy_class:
            return strategy_class()
    except Exception as e:
        print(f"  [WARN] Could not get strategy {key}: {e}")
    return None


def normalize_candles(candles):
    return [
        {
            "open": c.get("open"),
            "high": c.get("high"),
            "low": c.get("low"),
            "close": c.get("close"),
            "volume": c.get("volume", 0),
            "time": c.get("time"),
        }
        for c in candles
    ]


def run_one(pair, run_label):
    client = CoinDCXREST("", "")
    candles = client.get_candles(pair, "5m", limit=200)

    print(f"\n--- {run_label} ---")
    print(f"  pair: {pair}")
    print(f"  candles type: {type(candles).__name__}, len: {len(candles) if candles else 0}")

    if not candles or len(candles) < 50:
        print(f"  -> SKIP (not enough candles; would use enabled_at_confidence in API)")
        return None

    last = candles[-1]
    last_close = last.get("close") or last.get("c")
    last_time = last.get("time") or last.get("t")
    print(f"  last candle: close={last_close}, time={last_time}")

    candles_norm = normalize_candles(candles)
    best_conf = 0.0
    best_key = None
    per_strategy = []

    for key in STRATEGY_ORDER:
        strat = get_strategy_instance(key)
        if not strat:
            per_strategy.append((key, None))
            continue
        try:
            ev = strat.evaluate(candles_norm, return_confidence=True)
            if ev and isinstance(ev, dict):
                c = float(ev.get("confidence", 0))
                sig = ev.get("signal")
                per_strategy.append((key, c))
                if c > best_conf:
                    best_conf = c
                    best_key = key
            else:
                per_strategy.append((key, 0.0))
        except Exception as e:
            per_strategy.append((key, f"err: {e}"))

    print(f"  per-strategy confidence: {per_strategy}")
    print(f"  best: {best_conf}% from {best_key}")
    return {"last_close": last_close, "last_time": last_time, "best_confidence": best_conf, "best_strategy": best_key}


def main():
    pair = (sys.argv[1] if len(sys.argv) > 1 else "B-OP_USDT").strip()
    print(f"Dry-run pair_signals logic for {pair} (two runs, 15s apart)")

    r1 = run_one(pair, "Run 1")
    if r1 is None:
        return
    time.sleep(15)
    r2 = run_one(pair, "Run 2")

    if r2 is None:
        return
    print("\n--- Comparison ---")
    print(f"  last_close same: {r1.get('last_close') == r2.get('last_close')}")
    print(f"  last_time same:  {r1.get('last_time') == r2.get('last_time')}")
    print(f"  best_confidence same: {r1.get('best_confidence') == r2.get('best_confidence')}")
    if r1.get("best_confidence") != r2.get("best_confidence"):
        print(f"  -> Confidence CHANGED (expected if candles updated)")
    else:
        print(f"  -> Confidence UNCHANGED (expected if still same 5m window or API returned same data)")


if __name__ == "__main__":
    main()
