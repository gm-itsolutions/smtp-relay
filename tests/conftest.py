"""Test setup: a fresh, fully migrated SQLite DB per test.

Run from the repo root:  python -m pytest -q
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ENCRYPTION_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
os.environ.setdefault("SECRET_KEY", "t" * 64)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import common.db as db

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'relay.db'}")
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path / "archive"))
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "ui/alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    db._engine = None
    db._sessionmaker = None

    from common.models import Settings

    async def _seed():
        async with db.session_scope() as s:
            s.add(Settings(id=1))

    run(_seed())
    yield
    if db._engine is not None:
        run(db.dispose_engine())
    db._engine = None
    db._sessionmaker = None


def run(coro):
    return asyncio.run(coro)
