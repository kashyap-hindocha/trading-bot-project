from __future__ import annotations

import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


def try_translate_pine(pine_code: str) -> tuple[str | None, str | None]:
    """
    Pine → Python via pine2py (required dependency). Returns (python_source, error).
    """
    try:
        import pine2py  # type: ignore
    except ImportError:
        logger.warning("pine2py not installed")
        return (
            None,
            "pine2py is required: pip install -r requirements.txt (includes pine2py from git).",
        )

    try:
        if hasattr(pine2py, "translate"):
            out = pine2py.translate(pine_code)  # type: ignore
            return str(out), None
        if hasattr(pine2py, "compile"):
            out = pine2py.compile(pine_code)  # type: ignore
            return str(out), None
    except Exception as e:
        logger.exception("pine2py translate failed")
        return None, str(e)
    return None, "pine2py has no supported translate/compile API"


def ensure_compute_entrypoint(py: str) -> str:
    """
    pine2py often emits helpers without ``compute``. We append a standard bridge so
    the module loads; you should edit the body to mirror Pine on the **last** bar.
    """
    if re.search(r"^\s*def\s+compute\s*\(", py, re.MULTILINE):
        return py
    return (
        py.rstrip()
        + "\n\n"
        "# --- AlgoTrader: required entrypoint — connect your Pine logic to last-bar signal ---\n"
        "def compute(closes, **params):\n"
        "    if not closes:\n"
        "        return {}\n"
        "    # Return e.g. {\"signal\": \"buy\"} / {\"signal\": \"sell\"} or buy/sell booleans for the last bar.\n"
        "    return {}\n"
    )


def validate_translated_python_has_compute(source: str, scratch_dir: Path) -> tuple[bool, str | None]:
    """
    Ensure translated Python is runnable and defines ``compute(closes, **params) -> dict``.
    Uses a scratch file so normal imports in generated code work.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    path = scratch_dir / "_pine_compile_validate.py"
    path.write_text(source, encoding="utf-8")
    mod_name = "_pine_compile_validate"
    mod_obj: object | None = None
    try:
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return False, "could not load translated module"
        mod_obj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod_obj)
    except SyntaxError as e:
        return False, f"translated Python syntax error: {e}"
    except Exception as e:
        return False, f"translated Python failed to import/run: {e}"
    finally:
        if path.is_file():
            path.unlink(missing_ok=True)
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    fn = getattr(mod_obj, "compute", None)
    if callable(fn):
        return True, None
    return False, "Translated module must define compute(closes, **params) -> dict with signal/buy/sell for the last bar."


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:64]


def save_user_indicator(name: str, pine_code: str, user_dir: Path) -> Path:
    user_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(name)
    path = user_dir / f"{safe}.pine"
    path.write_text(pine_code, encoding="utf-8")
    return path


def save_python_source(name: str, source: str, user_dir: Path) -> Path:
    user_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(name)
    path = user_dir / f"{safe}.py"
    path.write_text(source, encoding="utf-8")
    return path


def load_optional_user_module(path: Path) -> Callable | None:
    """Load translated .py if present alongside .pine (manual workflow)."""
    py_path = path.with_suffix(".py")
    if not py_path.is_file():
        return None
    stem = py_path.stem
    if stem in sys.modules:
        del sys.modules[stem]

    spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "compute", None)
    if callable(fn):
        return fn
    return None
