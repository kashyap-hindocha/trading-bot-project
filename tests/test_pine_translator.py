import tempfile
from pathlib import Path

from src.indicators import pine_translator


def test_ensure_compute_entrypoint_idempotent():
    src = "def compute(closes, **params):\n    return {}\n"
    assert pine_translator.ensure_compute_entrypoint(src) == src


def test_ensure_compute_entrypoint_appends():
    src = "x = 1\n"
    out = pine_translator.ensure_compute_entrypoint(src)
    assert "def compute(" in out
    assert "x = 1" in out


def test_validate_translated_python_has_compute():
    tmp = Path(tempfile.mkdtemp())
    src = """
def compute(closes, **params):
    return {"signal": "buy"} if closes else {}
"""
    ok, err = pine_translator.validate_translated_python_has_compute(src, tmp)
    assert ok is True
    assert err is None
