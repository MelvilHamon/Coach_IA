"""
tests/conftest.py — Fixtures partagées pour la suite v1.

On utilise la DB SQLite dev (data/coachagent.db) avec des user_id uniques
par test pour ne pas polluer entre tests, plutôt qu'une DB temp : ça permet
de tester aussi les CREATE TABLE IF NOT EXISTS sur DB existante.
"""

import os
import shutil
import sys
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

# Évite l'auto-sync au startup pendant les tests.
os.environ.setdefault("APP_ENV", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from api.main import app  # noqa: E402
from api.database import get_db, init_tables  # noqa: E402
from api import api_keys  # noqa: E402
from api.user_data import UserPaths  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """Garantit le schéma à jour (le lifespan n'est pas déclenché par TestClient
    sans context manager). Idempotent : CREATE TABLE IF NOT EXISTS."""
    init_tables()


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


def _create_user(user_id: str, email: str):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute(text("""
            INSERT INTO users (id, email, display_name, created_at)
            VALUES (:id, :email, :name, :now)
        """), {"id": user_id, "email": email, "name": "test", "now": now})


def _cleanup_user(user_id: str):
    with get_db() as db:
        for table in ("session_feedback", "session_labels", "wellness_daily", "api_keys",
                      "sessions", "credentials", "user_profiles", "users"):
            try:
                db.execute(text(f"DELETE FROM {table} WHERE user_id = :uid OR id = :uid"),
                           {"uid": user_id})
            except Exception:
                pass
    paths = UserPaths(user_id)
    if os.path.isdir(paths.base):
        shutil.rmtree(paths.base, ignore_errors=True)


@pytest.fixture
def user():
    uid = f"test_{uuid.uuid4().hex[:10]}"
    _create_user(uid, f"{uid}@test.local")
    paths = UserPaths(uid)
    paths.ensure_dirs()
    yield {"id": uid, "paths": paths}
    _cleanup_user(uid)


@pytest.fixture
def api_key(user):
    minted = api_keys.mint(user["id"], label="test")
    return minted["key"]


@pytest.fixture
def auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture
def enriched_csv(user):
    """Écrit un CSV enrichi minimal pour le user de test."""
    import pandas as pd

    base = pd.Timestamp("2026-05-01", tz="UTC")
    rows = []
    # 35 jours avec une activité chaque jour, TRIMP ~ 50.
    for i in range(35):
        d = base + pd.Timedelta(days=i)
        rows.append({
            "ID": 1000 + i,
            "Date": d.isoformat(),
            "Nom": f"Run {i}",
            "Type": "Run",
            "sport": "run",
            "Distance (km)": 10.0,
            "Temps (min)": 50.0,
            "Dénivelé (m)": 50.0,
            "Allure (min/km)": 5.0,
            "Fréquence cardiaque (bpm)": 150,
            "session_type": "endurance fondamentale",
            "trimp": 50.0,
            "hrtss": 55.0,
            "acwr_km": 1.0,
            "ctl": 40.0 + i * 0.3,
            "atl": 38.0 + i * 0.2,
            "tsb": 2.0,
        })
    df = pd.DataFrame(rows)
    df.to_csv(user["paths"].enriched_csv, index=False)
    # Invalide le cache mtime.
    from api.deps import invalidate_cache
    invalidate_cache(["activities"], user_id=user["id"])
    return df
