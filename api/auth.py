"""
api/auth.py — User management, sessions, and credential storage.

Uses SQLAlchemy via api/database.py (supports SQLite and PostgreSQL).
Authentication via OTP (magic code) — no passwords stored.
Garmin/Strava credentials encrypted with Fernet.
"""

import logging
import os
import random
import secrets
import smtplib
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from sqlalchemy import text

from api.database import get_db, init_tables

load_dotenv()

logger = logging.getLogger("coachagent.auth")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEY_PATH = os.path.join(_ROOT, "data", ".fernet_key")

SESSION_DURATION_DAYS = 30
OTP_EXPIRY_MINUTES = 10
OTP_LENGTH = 6


# ── Encryption key ────────────────────────────────────────────────────────────

def _get_fernet() -> Fernet:
    """Load or create the Fernet key for credential encryption."""
    if os.path.exists(_KEY_PATH):
        with open(_KEY_PATH, "rb") as f:
            key = f.read()
    else:
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(_KEY_PATH), exist_ok=True)
        with open(_KEY_PATH, "wb") as f:
            f.write(key)
    return Fernet(key)


_fernet = None

def _encrypt(value: str) -> str:
    global _fernet
    if _fernet is None:
        _fernet = _get_fernet()
    return _fernet.encrypt(value.encode()).decode()

def _decrypt(token: str) -> str:
    global _fernet
    if _fernet is None:
        _fernet = _get_fernet()
    return _fernet.decrypt(token.encode()).decode()


# ── Database init ────────────────────────────────────────────────────────────

def init_db():
    """Create tables if they don't exist."""
    init_tables()
    logger.info("Database tables initialized")


# ── Rate limiting (in-memory) ────────────────────────────────────────────────

_rate_lock = threading.Lock()
_rate_buckets: dict[str, list[datetime]] = defaultdict(list)


def _rate_check(key: str, max_attempts: int, window_minutes: int) -> bool:
    """
    Return True if the action is allowed, False if rate-limited.
    Tracks timestamps per key and prunes expired entries.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)
    with _rate_lock:
        bucket = _rate_buckets[key]
        _rate_buckets[key] = [t for t in bucket if t > cutoff]
        if len(_rate_buckets[key]) >= max_attempts:
            return False
        _rate_buckets[key].append(now)
        return True


def _rate_count(key: str, window_minutes: int) -> int:
    """Return number of attempts in the current window."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    with _rate_lock:
        bucket = _rate_buckets.get(key, [])
        return sum(1 for t in bucket if t > cutoff)


# ── OTP generation & email ───────────────────────────────────────────────────

def _generate_otp() -> str:
    """Generate a random 6-digit OTP code."""
    return "".join(str(random.randint(0, 9)) for _ in range(OTP_LENGTH))


def _send_otp_email(email: str, code: str) -> bool:
    """
    Send OTP via Gmail (SMTP_SSL on port 465) using GMAIL_* env vars.
    Fallback: print to console if not configured.
    Returns True if email was sent, False if printed to console.
    """
    gmail_user = os.environ.get("GMAIL_EXPEDITEUR")
    gmail_pass = os.environ.get("GMAIL_MOT_DE_PASSE")

    if not gmail_user or not gmail_pass:
        logger.info("No Gmail configured — printing OTP to console")
        print(f"\n{'='*50}")
        print(f"  CODE DE CONNEXION pour {email}")
        print(f"  → {code}")
        print(f"  (expire dans {OTP_EXPIRY_MINUTES} minutes)")
        print(f"{'='*50}\n")
        return False

    msg = MIMEText(
        f"Ton code de connexion CoachAgent :\n\n"
        f"    {code}\n\n"
        f"Ce code expire dans {OTP_EXPIRY_MINUTES} minutes.\n"
        f"Si tu n'as pas demandé ce code, ignore cet email.",
        "plain", "utf-8",
    )
    msg["Subject"] = f"CoachAgent — Code de connexion : {code}"
    msg["From"] = gmail_user
    msg["To"] = email

    # Try port 587 (STARTTLS) first — works on cloud providers that block port 465
    # Fallback to port 465 (SMTP_SSL) if 587 fails
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, email, msg.as_string())
        logger.info("OTP envoyé par email à %s (port 587)", email)
        return True
    except Exception as e587:
        logger.warning("SMTP port 587 failed: %s — trying 465", e587)
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(gmail_user, email, msg.as_string())
            logger.info("OTP envoyé par email à %s (port 465)", email)
            return True
        except Exception as e465:
            logger.error("Erreur envoi email à %s: 587=%s, 465=%s", email, e587, e465)
            print(f"\n  CODE DE CONNEXION pour {email}: {code}\n")
            return False


def send_otp(email: str) -> dict:
    """
    Generate an OTP for the given email and send it.
    Returns {"ok": True, "method": "email"|"console"}.
    Raises ValueError if rate-limited.
    """
    from api.config import OTP_SEND_MAX_PER_HOUR

    email = email.strip().lower()
    if not email:
        raise ValueError("Email requis.")

    if not _rate_check(f"otp_send:{email}", OTP_SEND_MAX_PER_HOUR, 60):
        logger.warning("OTP send rate-limited for %s", email)
        raise ValueError("Trop de demandes. Réessaie dans quelques minutes.")

    code = _generate_otp()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

    with get_db() as db:
        db.execute(
            text("UPDATE otp_codes SET used = 1 WHERE email = :email AND used = 0"),
            {"email": email},
        )
        db.execute(
            text("INSERT INTO otp_codes (email, code, created_at, expires_at) VALUES (:email, :code, :created_at, :expires_at)"),
            {"email": email, "code": code, "created_at": now.isoformat(), "expires_at": expires.isoformat()},
        )

    sent = _send_otp_email(email, code)
    return {"ok": True, "method": "email" if sent else "console"}


def verify_otp(email: str, code: str) -> dict | None:
    """
    Verify an OTP code. If valid, auto-creates user if new.
    Returns user dict or None if invalid/expired.
    """
    from api.config import OTP_VERIFY_MAX_ATTEMPTS, OTP_LOCKOUT_MINUTES

    email = email.strip().lower()
    code = code.strip()

    if not _rate_check(f"otp_verify:{email}", OTP_VERIFY_MAX_ATTEMPTS, OTP_LOCKOUT_MINUTES):
        logger.warning("OTP verify rate-limited for %s", email)
        return None

    with get_db() as db:
        row = db.execute(
            text("SELECT id, code, expires_at FROM otp_codes WHERE email = :email AND used = 0 ORDER BY id DESC LIMIT 1"),
            {"email": email},
        ).mappings().fetchone()

        if not row:
            return None

        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            db.execute(text("UPDATE otp_codes SET used = 1 WHERE id = :id"), {"id": row["id"]})
            return None

        if row["code"] != code:
            return None

        db.execute(text("UPDATE otp_codes SET used = 1 WHERE id = :id"), {"id": row["id"]})

        user_row = db.execute(
            text("SELECT id, email, display_name FROM users WHERE email = :email"),
            {"email": email},
        ).mappings().fetchone()

        if user_row:
            return {"id": user_row["id"], "email": user_row["email"], "display_name": user_row["display_name"]}

        user_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        display_name = email.split("@")[0]
        db.execute(
            text("INSERT INTO users (id, email, display_name, created_at) VALUES (:id, :email, :display_name, :created_at)"),
            {"id": user_id, "email": email, "display_name": display_name, "created_at": now},
        )
        return {"id": user_id, "email": email, "display_name": display_name}


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(user_id: str) -> str:
    """Create a session token for user_id. Returns the token."""
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_DURATION_DAYS)
    with get_db() as db:
        db.execute(
            text("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (:token, :user_id, :created_at, :expires_at)"),
            {"token": token, "user_id": user_id, "created_at": now.isoformat(), "expires_at": expires.isoformat()},
        )
    return token


def get_user_by_session(token: str) -> dict | None:
    """Validate a session token. Returns user dict or None if expired/invalid."""
    if not token:
        return None
    with get_db() as db:
        row = db.execute(text("""
            SELECT u.id, u.email, u.display_name, s.expires_at
            FROM sessions s JOIN users u ON s.user_id = u.id
            WHERE s.token = :token
        """), {"token": token}).mappings().fetchone()

    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        delete_session(token)
        return None
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}


def delete_session(token: str):
    with get_db() as db:
        db.execute(text("DELETE FROM sessions WHERE token = :token"), {"token": token})


def delete_user_sessions(user_id: str):
    with get_db() as db:
        db.execute(text("DELETE FROM sessions WHERE user_id = :user_id"), {"user_id": user_id})


# ── User profile update ─────────────────────────────────────────────────────

def update_display_name(user_id: str, display_name: str):
    """Update user display name."""
    with get_db() as db:
        db.execute(
            text("UPDATE users SET display_name = :name WHERE id = :id"),
            {"name": display_name.strip(), "id": user_id},
        )


# ── User profile (physio) ───────────────────────────────────────────────────

def save_user_profile(user_id: str, profile: dict):
    """Save or update user physiological profile (gender, HR zones)."""
    params = {
        "user_id": user_id,
        "gender": profile.get("gender", "male"),
        "hr_max": profile.get("hr_max"),
        "hr_rest": profile.get("hr_rest"),
        "hr_threshold": profile.get("hr_threshold"),
        "hr_z1_max": profile.get("hr_z1_max"),
        "hr_z2_max": profile.get("hr_z2_max"),
        "hr_z3_max": profile.get("hr_z3_max"),
        "hr_z4_max": profile.get("hr_z4_max"),
        "hr_z5_max": profile.get("hr_z5_max"),
        "weight_kg": profile.get("weight_kg"),
    }
    with get_db() as db:
        # Use INSERT ... ON CONFLICT for upsert (works on both SQLite and PostgreSQL)
        db.execute(text("""
            INSERT INTO user_profiles (user_id, gender, hr_max, hr_rest, hr_threshold,
                                       hr_z1_max, hr_z2_max, hr_z3_max, hr_z4_max, hr_z5_max,
                                       weight_kg)
            VALUES (:user_id, :gender, :hr_max, :hr_rest, :hr_threshold,
                    :hr_z1_max, :hr_z2_max, :hr_z3_max, :hr_z4_max, :hr_z5_max,
                    :weight_kg)
            ON CONFLICT(user_id) DO UPDATE SET
                gender = :gender, hr_max = :hr_max, hr_rest = :hr_rest, hr_threshold = :hr_threshold,
                hr_z1_max = :hr_z1_max, hr_z2_max = :hr_z2_max,
                hr_z3_max = :hr_z3_max, hr_z4_max = :hr_z4_max, hr_z5_max = :hr_z5_max,
                weight_kg = :weight_kg
        """), params)


def get_user_profile(user_id: str) -> dict | None:
    """Return user physiological profile or None."""
    with get_db() as db:
        row = db.execute(
            text("SELECT * FROM user_profiles WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).mappings().fetchone()
    if not row:
        return None
    return {
        "gender": row["gender"],
        "hr_max": row["hr_max"],
        "hr_rest": row["hr_rest"],
        "hr_threshold": row["hr_threshold"],
        "hr_z1_max": row["hr_z1_max"],
        "hr_z2_max": row["hr_z2_max"],
        "hr_z3_max": row["hr_z3_max"],
        "hr_z4_max": row["hr_z4_max"],
        "hr_z5_max": row["hr_z5_max"],
        "weight_kg": row["weight_kg"],
    }


# ── Credentials ───────────────────────────────────────────────────────────────

def save_garmin_credentials(user_id: str, garmin_email: str, garmin_password: str):
    """Store Garmin credentials (password encrypted at rest)."""
    enc_pw = _encrypt(garmin_password)
    with get_db() as db:
        db.execute(text("""
            INSERT INTO credentials (user_id, garmin_email, garmin_password_enc)
            VALUES (:user_id, :email, :enc_pw)
            ON CONFLICT(user_id) DO UPDATE SET garmin_email = :email, garmin_password_enc = :enc_pw
        """), {"user_id": user_id, "email": garmin_email, "enc_pw": enc_pw})


def get_garmin_credentials(user_id: str) -> dict | None:
    """Return decrypted Garmin credentials or None."""
    with get_db() as db:
        row = db.execute(
            text("SELECT garmin_email, garmin_password_enc FROM credentials WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).mappings().fetchone()
    if not row or not row["garmin_email"]:
        return None
    return {
        "email": row["garmin_email"],
        "password": _decrypt(row["garmin_password_enc"]),
    }


def save_strava_tokens(user_id: str, athlete_id: int, access_token: str,
                       refresh_token: str, expires_at: int):
    """Store Strava OAuth tokens after authorization or refresh."""
    with get_db() as db:
        db.execute(text("""
            INSERT INTO credentials (user_id, strava_athlete_id, strava_access_token,
                                     strava_refresh_token, strava_token_expires_at)
            VALUES (:user_id, :athlete_id, :access_token, :refresh_token, :expires_at)
            ON CONFLICT(user_id) DO UPDATE SET
                strava_athlete_id = :athlete_id, strava_access_token = :access_token,
                strava_refresh_token = :refresh_token, strava_token_expires_at = :expires_at
        """), {"user_id": user_id, "athlete_id": athlete_id, "access_token": access_token,
               "refresh_token": refresh_token, "expires_at": expires_at})


def get_strava_tokens(user_id: str) -> dict | None:
    """Return Strava tokens for a user, or None if not connected."""
    with get_db() as db:
        row = db.execute(
            text("""SELECT strava_athlete_id, strava_access_token, strava_refresh_token,
                          strava_token_expires_at
                   FROM credentials WHERE user_id = :user_id"""),
            {"user_id": user_id},
        ).mappings().fetchone()
    if not row or not row["strava_athlete_id"]:
        return None
    return {
        "athlete_id": row["strava_athlete_id"],
        "access_token": row["strava_access_token"],
        "refresh_token": row["strava_refresh_token"],
        "expires_at": row["strava_token_expires_at"],
    }


def disconnect_strava(user_id: str):
    """Remove Strava tokens for a user."""
    with get_db() as db:
        db.execute(text("""
            UPDATE credentials SET
                strava_athlete_id = NULL, strava_access_token = NULL,
                strava_refresh_token = NULL, strava_token_expires_at = NULL
            WHERE user_id = :user_id
        """), {"user_id": user_id})


def has_garmin_credentials(user_id: str) -> bool:
    with get_db() as db:
        row = db.execute(
            text("SELECT garmin_email FROM credentials WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).mappings().fetchone()
    return bool(row and row["garmin_email"])


def has_strava_connected(user_id: str) -> bool:
    """Check if user has a connected Strava account."""
    with get_db() as db:
        row = db.execute(
            text("SELECT strava_athlete_id FROM credentials WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).mappings().fetchone()
    return bool(row and row["strava_athlete_id"])


# ── OAuth state (CSRF protection) ───────────────────────────────────────────

_oauth_states: dict[str, tuple[str, datetime]] = {}  # state -> (user_id, expiry)
_oauth_lock = threading.Lock()


def create_oauth_state(user_id: str) -> str:
    """Generate a random state token for OAuth CSRF protection."""
    state = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    with _oauth_lock:
        now = datetime.now(timezone.utc)
        expired = [k for k, (_, exp) in _oauth_states.items() if exp < now]
        for k in expired:
            del _oauth_states[k]
        _oauth_states[state] = (user_id, expiry)
    return state


def verify_oauth_state(state: str) -> str | None:
    """
    Verify and consume an OAuth state token.
    Returns user_id if valid, None otherwise.
    """
    if not state:
        return None
    with _oauth_lock:
        entry = _oauth_states.pop(state, None)
    if not entry:
        return None
    user_id, expiry = entry
    if expiry < datetime.now(timezone.utc):
        return None
    return user_id
