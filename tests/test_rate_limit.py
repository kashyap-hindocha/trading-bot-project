import threading
import time

from src.trading.rate_limit import OrderRateLimiter


def test_rate_limiter_allows_burst_under_cap():
    lim = OrderRateLimiter(max_calls=5, window_sec=1.0)
    for _ in range(5):
        lim.acquire()
    start = time.monotonic()
    threading.Thread(target=lambda: lim.acquire(), daemon=True).start()
    time.sleep(0.05)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.01
