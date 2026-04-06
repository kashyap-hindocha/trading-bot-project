from __future__ import annotations

import json
import uuid
from typing import Any


def new_trade_id() -> str:
    return str(uuid.uuid4())


def json_dumps_compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)
