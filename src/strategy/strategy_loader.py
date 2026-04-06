from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_strategy(path: Path) -> dict[str, Any]:
    if not path.is_file():
        logger.warning("strategy file missing: %s", path)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error("bad strategy json: %s", e)
        return {}
