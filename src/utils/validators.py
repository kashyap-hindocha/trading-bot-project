from __future__ import annotations


def clamp_leverage(x: int, cap: int = 20) -> int:
    return max(1, min(int(x), cap))
