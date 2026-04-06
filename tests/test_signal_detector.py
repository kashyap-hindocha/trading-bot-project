from src.strategy.signal_detector import (
    SignalDetector,
    eval_condition,
    signal_from_indicator_output,
)


def test_eval_simple_condition():
    assert eval_condition("rsi < 30", {"rsi": 25.0}) is True
    assert eval_condition("rsi < 30", {"rsi": 40.0}) is False


def test_detector_buy_signal():
    strat = {
        "rules": {
            "buy_when": "rsi < 30",
            "sell_when": "rsi > 70",
        }
    }
    d = SignalDetector(strat)
    assert d.evaluate({"rsi": 28.0}) == "buy"
    assert d.evaluate({"rsi": 75.0}) == "sell"


def test_detector_chained_compare():
    strat = {
        "rules": {
            "buy_when": "rsi_prev >= 30 and rsi < 30",
            "sell_when": "rsi > 80",
        }
    }
    d = SignalDetector(strat)
    assert d.evaluate({"rsi": 29.0, "rsi_prev": 31.0}) == "buy"


def test_signal_from_pine_signal_key():
    strat = {"rules": {}}
    assert (
        signal_from_indicator_output(
            indicator="user:active", values={"signal": "buy"}, strategy=strat
        )
        == "buy"
    )
    assert (
        signal_from_indicator_output(
            indicator="user:active", values={"signal": "SELL"}, strategy=strat
        )
        == "sell"
    )


def test_signal_from_pine_buy_sell_flags():
    strat = {"rules": {}}
    assert (
        signal_from_indicator_output(
            indicator="user:active", values={"buy": True, "sell": False}, strategy=strat
        )
        == "buy"
    )
    assert (
        signal_from_indicator_output(
            indicator="user:active", values={"buy": 0, "sell": 1}, strategy=strat
        )
        == "sell"
    )


def test_user_indicator_ignores_json_rules():
    strat = {
        "rules": {
            "buy_when": "rsi < 30",
            "sell_when": "rsi > 70",
        }
    }
    assert (
        signal_from_indicator_output(
            indicator="user:active",
            values={"rsi": 50.0, "buy": True},
            strategy=strat,
        )
        == "buy"
    )


def test_builtin_rsi_still_uses_json_rules():
    strat = {
        "rules": {
            "buy_when": "rsi < 30",
            "sell_when": "rsi > 70",
        }
    }
    assert (
        signal_from_indicator_output(
            indicator="builtin_rsi", values={"rsi": 25.0}, strategy=strat
        )
        == "buy"
    )
