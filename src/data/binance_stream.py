from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import websocket

logger = logging.getLogger(__name__)


class BinanceKlineStream:
    """Binance spot kline WebSocket (plain WS, not Socket.IO)."""

    def __init__(
        self,
        symbol: str,
        interval: str,
        on_kline: Callable[[dict], None],
    ) -> None:
        sym = symbol.lower().replace("/", "")
        self._url = f"wss://stream.binance.com:9443/ws/{sym}@kline_{interval}"
        self.on_kline = on_kline
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _on_message(self, _ws: websocket.WebSocketApp, message: str) -> None:
        try:
            d = json.loads(message)
            k = d.get("k")
            if isinstance(k, dict):
                self.on_kline(k)
        except Exception as e:
            logger.debug("binance kline parse: %s", e)

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    self._url,
                    on_message=self._on_message,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                logger.warning("Binance WS error: %s", e)
            if self._stop.is_set():
                break
            time.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="binance-kline", daemon=True)
        self._thread.start()
        logger.info("Binance kline stream started %s", self._url)

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
