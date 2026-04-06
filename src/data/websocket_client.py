from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import socketio

from config.settings import Settings

logger = logging.getLogger(__name__)

# CoinDCX uses Socket.IO v2-style server at this endpoint (docs).
STREAM_URL = "https://stream.coindcx.com"


class CoinDCXStreamClient:
    def __init__(
        self,
        settings: Settings,
        channels: list[str],
        on_candlestick: Callable[[dict], None],
    ) -> None:
        self.settings = settings
        self.channels = channels
        self.on_candlestick = on_candlestick
        self._sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        @self._sio.event
        def connect() -> None:
            logger.info("stream connected, joining %s channels", len(self.channels))
            for ch in self.channels:
                self._sio.emit("join", {"channelName": ch})

        @self._sio.event
        def disconnect() -> None:
            logger.warning("stream disconnected")

        @self._sio.on("candlestick")
        def on_candle(data) -> None:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return
            if isinstance(data, dict):
                self.on_candlestick(data)

    def _connect_loop(self) -> None:
        attempt = 0
        max_retries = self.settings.ws_max_retries
        base = self.settings.ws_backoff_base_sec
        while not self._stop.is_set():
            try:
                self._sio.connect(
                    STREAM_URL,
                    transports=["websocket"],
                    wait_timeout=20,
                )
                attempt = 0
                self._sio.wait()
            except Exception as e:
                attempt += 1
                logger.warning("stream connection error (attempt %s): %s", attempt, e)
                if attempt > max_retries:
                    attempt = 0
                time.sleep(min(base * (2 ** min(attempt, 6)), 60))
            finally:
                try:
                    if self._sio.connected:
                        self._sio.disconnect()
                except Exception:
                    pass

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def run() -> None:
            self._connect_loop()

        self._thread = threading.Thread(target=run, name="coindcx-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._sio.connected:
                self._sio.disconnect()
        except Exception:
            pass
