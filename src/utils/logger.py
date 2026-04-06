from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level: str = "INFO", log_dir: str | Path | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s UTC %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt.converter = time.gmtime

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.handlers.clear()
    root.addHandler(sh)

    if log_dir:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            path / "bot.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
