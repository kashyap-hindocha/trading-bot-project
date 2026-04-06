from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Re-export ASGI app so `uvicorn start:app` matches `uvicorn src.web.asgi:app`.
from src.web.asgi import app


def main() -> None:
    import uvicorn

    from config.settings import get_settings

    uvicorn.run(app, host="0.0.0.0", port=get_settings().web_port)


if __name__ == "__main__":
    main()
