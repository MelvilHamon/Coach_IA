"""
api/database.py — Database engine and session management.

Uses SQLAlchemy for connection pooling and PostgreSQL/SQLite compatibility.
- Production: set DATABASE_URL=postgresql://user:pass@host/db
- Development: defaults to SQLite at data/coachagent.db
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

from api.config import DATABASE_URL

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SQLITE_PATH = os.path.join(_ROOT, "data", "coachagent.db")


def _build_url() -> str:
    if DATABASE_URL:
        return DATABASE_URL
    os.makedirs(os.path.dirname(_SQLITE_PATH), exist_ok=True)
    return f"sqlite:///{_SQLITE_PATH}"


_url = _build_url()
IS_SQLITE = _url.startswith("sqlite")

_engine_kwargs = {}
if IS_SQLITE:
    # SQLite needs check_same_thread=False for multi-threaded FastAPI
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["pool_pre_ping"] = True
else:
    # PostgreSQL connection pooling
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 300

engine = create_engine(_url, **_engine_kwargs)

# Enable WAL mode for SQLite (better concurrent reads)
if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_db():
    """Context manager that yields a SQLAlchemy session and auto-commits/rollbacks."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_tables():
    """Create all tables if they don't exist. Compatible with SQLite and PostgreSQL."""
    auto_increment = "AUTOINCREMENT" if IS_SQLITE else ""
    serial_type = "INTEGER" if IS_SQLITE else "SERIAL"
    bool_type = "INTEGER" if IS_SQLITE else "BOOLEAN"

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS users (
                id           TEXT PRIMARY KEY,
                email        TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL
            )
        """))

        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """))

        # otp_codes: use SERIAL for PostgreSQL, AUTOINCREMENT for SQLite
        if IS_SQLITE:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS otp_codes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    email      TEXT NOT NULL,
                    code       TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used       INTEGER NOT NULL DEFAULT 0
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS otp_codes (
                    id         SERIAL PRIMARY KEY,
                    email      TEXT NOT NULL,
                    code       TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used       INTEGER NOT NULL DEFAULT 0
                )
            """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id      TEXT PRIMARY KEY REFERENCES users(id),
                gender       TEXT NOT NULL DEFAULT 'male',
                hr_max       INTEGER,
                hr_rest      INTEGER,
                hr_threshold INTEGER,
                hr_z1_max    INTEGER,
                hr_z2_max    INTEGER,
                hr_z3_max    INTEGER,
                hr_z4_max    INTEGER,
                hr_z5_max    INTEGER,
                weight_kg    REAL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS credentials (
                user_id                TEXT PRIMARY KEY REFERENCES users(id),
                garmin_email           TEXT,
                garmin_password_enc    TEXT,
                strava_athlete_id      INTEGER,
                strava_access_token    TEXT,
                strava_refresh_token   TEXT,
                strava_token_expires_at INTEGER
            )
        """))

    # Migrations: add columns that may not exist in older databases
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE user_profiles ADD COLUMN weight_kg REAL"))
        except Exception:
            pass  # Column already exists

    # Create indexes for performance
    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_codes(email, used)"))
        except Exception:
            pass  # Index already exists
