from __future__ import annotations

import ast
import logging
import operator as op
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_BINOPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.Gt: op.gt,
    ast.GtE: op.ge,
    ast.Lt: op.lt,
    ast.LtE: op.le,
    ast.Eq: op.eq,
    ast.NotEq: op.ne,
    ast.And: lambda a, b: bool(a) and bool(b),
    ast.Or: lambda a, b: bool(a) or bool(b),
}

_ALLOWED_UNARY = {ast.UAdd: op.pos, ast.USub: op.neg, ast.Not: op.not_}


def _safe_eval(node: ast.AST, ctx: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, ctx)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)) or node.value is None:
            return node.value
        raise ValueError("disallowed constant")
    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        raise ValueError(f"unknown name {node.id}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BINOPS:
            raise ValueError("disallowed binop")
        return _ALLOWED_BINOPS[op_type](_safe_eval(node.left, ctx), _safe_eval(node.right, ctx))
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_UNARY:
            raise ValueError("disallowed unaryop")
        return _ALLOWED_UNARY[op_type](_safe_eval(node.operand, ctx))
    if isinstance(node, ast.Compare):
        cur = _safe_eval(node.left, ctx)
        for i, op_el in enumerate(node.ops):
            right = _safe_eval(node.comparators[i], ctx)
            op_type = type(op_el)
            if op_type not in _ALLOWED_BINOPS:
                raise ValueError("disallowed compare op")
            if not _ALLOWED_BINOPS[op_type](cur, right):
                return False
            cur = right
        return True
    if isinstance(node, ast.BoolOp):
        vals = [_safe_eval(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        if isinstance(node.op, ast.Or):
            return any(vals)
        raise ValueError("unsupported bool op")
    raise ValueError("unsupported expression")


def eval_condition(expr: str, values: dict[str, Any]) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    try:
        tree = ast.parse(expr, mode="eval")
        return bool(_safe_eval(tree, values))
    except Exception as e:
        logger.debug("rule eval failed: %s (%s)", expr, e)
        return False


class SignalDetector:
    def __init__(self, strategy: dict[str, Any]) -> None:
        self.strategy = strategy

    def evaluate(self, indicator_values: dict[str, Any]) -> str | None:
        rules = self.strategy.get("rules") or {}
        buy_expr = rules.get("buy_when", "")
        sell_expr = rules.get("sell_when", "")
        ctx = {k: v for k, v in indicator_values.items() if v is not None}
        if not ctx:
            return None
        buy = eval_condition(buy_expr, ctx) if buy_expr else False
        sell = eval_condition(sell_expr, ctx) if sell_expr else False
        if buy and not sell:
            return "buy"
        if sell and not buy:
            return "sell"
        return None


def _truthy(x: Any) -> bool:
    if x is True:
        return True
    if x in (1, 1.0):
        return True
    if isinstance(x, str) and x.strip().lower() in ("1", "true", "yes"):
        return True
    return False


def signal_from_indicator_output(
    *,
    indicator: str,
    values: dict[str, Any],
    strategy: dict[str, Any],
) -> str | None:
    """
    Pine-first: translated ``active.py`` should return a dict that includes either
    ``signal`` (\"buy\" / \"sell\") or boolean ``buy`` / ``sell`` for the *last* bar.

    JSON ``rules`` in strategy config apply only to ``builtin_rsi`` (legacy).
    """
    if not values:
        return None
    raw = values.get("signal")
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("buy", "sell"):
            return s
    b = _truthy(values.get("buy"))
    s = _truthy(values.get("sell"))
    if b and not s:
        return "buy"
    if s and not b:
        return "sell"
    if indicator == "builtin_rsi":
        return SignalDetector(strategy).evaluate(values)
    return None
