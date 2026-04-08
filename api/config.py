"""
api/config.py — Server configuration from environment variables.

All settings are centralized here. Defaults are safe for development.
In production, set APP_ENV=production and configure the required variables.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ── Environment ──────────────────────────────────────────────────────────────

APP_ENV = os.environ.get("APP_ENV", "development")  # "development" or "production"
IS_PROD = APP_ENV == "production"

# ── Server ───────────────────────────────────────────────────────────────────

# Allowed origins for CORS (comma-separated in env)
# In production: "https://yourdomain.com"
# In development: "http://localhost:8000" (or "*" for convenience)
_origins_env = os.environ.get("ALLOWED_ORIGINS", "")
if _origins_env:
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
elif IS_PROD:
    ALLOWED_ORIGINS = []  # Must be configured in production
else:
    ALLOWED_ORIGINS = ["*"]

# ── Cookies ──────────────────────────────────────────────────────────────────

COOKIE_SECURE = IS_PROD  # True in production (HTTPS only)
COOKIE_SAMESITE = "lax"
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", None)  # e.g. ".yourdomain.com"
SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", "30"))

# ── Rate limiting ────────────────────────────────────────────────────────────

OTP_SEND_MAX_PER_HOUR = int(os.environ.get("OTP_SEND_MAX_PER_HOUR", "5"))
OTP_VERIFY_MAX_ATTEMPTS = int(os.environ.get("OTP_VERIFY_MAX_ATTEMPTS", "5"))
OTP_LOCKOUT_MINUTES = int(os.environ.get("OTP_LOCKOUT_MINUTES", "15"))

# ── Database ─────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")  # PostgreSQL in prod, empty = SQLite

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO" if IS_PROD else "DEBUG")
