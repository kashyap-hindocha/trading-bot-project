from __future__ import annotations

from pathlib import Path
from typing import Any

from src.indicators import pine_translator
from src.indicators.builtins.rsi import last_values


class IndicatorEngine:
    """User Pine (``user_indicators/active.py``) must expose ``compute(closes, **params) -> dict`` with either:

    - ``signal``: ``\"buy\"`` or ``\"sell\"`` for the last bar, or
    - ``buy`` / ``sell``: booleans (or 1/0) for the last bar.
    """

    def __init__(self, user_indicators_dir: Path) -> None:
        self.user_indicators_dir = user_indicators_dir

    def compute(
        self,
        *,
        indicator: str,
        params: dict[str, Any],
        closes: list[float],
    ) -> dict[str, Any]:
        if indicator == "builtin_rsi":
            return last_values(closes, length=int(params.get("length", 14)))
        if indicator.startswith("user:"):
            name = indicator.split(":", 1)[1]
            p = self.user_indicators_dir / f"{name}.pine"
            fn = pine_translator.load_optional_user_module(p)
            if fn:
                return fn(closes=closes, **params)
        return {}
