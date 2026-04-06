from __future__ import annotations

from typing import Any

import pandas as pd


def compute_rsi_series(closes: list[float], length: int = 14) -> list[float | None]:
    if len(closes) < length + 1:
        return [None] * len(closes)
    s = pd.Series(closes, dtype=float)
    try:
        import pandas_ta as ta

        r = ta.rsi(s, length=length)
    except Exception:
        delta = s.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        r = 100 - (100 / (1 + rs))
    out: list[float | None] = []
    for v in r.tolist():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out.append(None)
        else:
            out.append(float(v))
    return out


def last_values(closes: list[float], length: int = 14) -> dict[str, Any]:
    rsi = compute_rsi_series(closes, length=length)
    last = rsi[-1] if rsi else None
    prev = rsi[-2] if len(rsi) > 1 else None
    return {"rsi": last, "rsi_prev": prev}
