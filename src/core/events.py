from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class NewCandleEvent:
    symbol: str
    interval: str
    candle: dict[str, Any]
    closed: bool
