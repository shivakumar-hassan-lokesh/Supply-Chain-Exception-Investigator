import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scagent.config import Config  # noqa: E402
from scagent.db import connect, init_db  # noqa: E402

TODAY = date(2026, 3, 16)


@pytest.fixture()
def db_path(tmp_path):
    """A fresh copy of the fictional database for each test."""
    return init_db(tmp_path / "test.db")


@pytest.fixture()
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture()
def cfg(db_path, tmp_path):
    return Config(provider="test", model="test-double", db_path=db_path,
                  investigation_date=TODAY, max_tool_calls=8, max_model_turns=12,
                  trace_dir=tmp_path / "traces")
