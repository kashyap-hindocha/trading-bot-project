import os
import tempfile

import pytest

fd, DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ.setdefault("COINDCX_API_KEY", "")
os.environ.setdefault("COINDCX_API_SECRET", "")

from config.settings import get_settings

get_settings.cache_clear()

import src.persistence.database as db_mod

db_mod._engine = None
db_mod._SessionLocal = None

from src.persistence.database import init_db
from src.persistence.repository import Repository
from src.trading.paper_executor import PaperExecutor


@pytest.fixture
def repo():
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._SessionLocal = None
    init_db()
    r = Repository()
    yield r
    r.close()


def test_paper_open_and_tp(repo):
    s = get_settings()
    pe = PaperExecutor(s, repo)
    out = pe.place_market(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        ltp=100_000.0,
        leverage=5,
        tp_price=110_000.0,
        sl_price=90_000.0,
    )
    assert out["ok"] is True
    closed = pe.on_price("BTCUSDT", 110_000.0)
    assert len(closed) == 1
