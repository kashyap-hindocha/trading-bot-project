"""ASGI app for this project.

Use either:
  - `python start.py`
  - `uvicorn src.web.asgi:app --host 0.0.0.0 --port 8000`

`src.web.app` only defines `create_app(engine)` — there is no `app` object there, so
`uvicorn src.web.app:app` will not work and routes like POST /api/order/close will 404.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from config.settings import get_settings
from src.core.engine import build_engine
from src.core.scheduler import start_scheduler
from src.utils.logger import setup_logging
from src.web.app import create_app

_settings = get_settings()
setup_logging(_settings.log_level, ROOT / "logs")
_engine = build_engine()
_engine.start()
start_scheduler(_engine)
app = create_app(_engine)
