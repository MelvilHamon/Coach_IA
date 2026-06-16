"""
api/api_keys.py — Mint / lookup / revoke pour les API keys Bearer de /api/v1.

Choix de design (cf. plan v1) :
- Minting via endpoint cookie-protected (POST /api/auth/api-keys) plutôt que
  CLI : l'utilisateur est déjà loggué dans le dashboard pour configurer son
  app mobile, un bouton "Générer une clé" est moins friction qu'une commande
  shell à distribuer.
- La clé claire (`ca_v1_...`) n'est retournée qu'une fois ; seul son hash
  SHA-256 est stocké. Le `prefix` (12 premiers chars) est gardé en clair pour
  permettre à l'UI de lister les clés sans dévoiler le secret.
- Pas de pepper : si l'attaquant a la DB il a déjà accès aux tokens Strava
  chiffrés Fernet, le pepper n'ajouterait rien au modèle de menace local.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from api.database import get_db

KEY_PREFIX = "ca_v1_"
PREFIX_STORED_LEN = 12  # = len("ca_v1_") + 6 random chars


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def mint(user_id: str, label: str = "") -> dict:
    """Génère une nouvelle clé. La valeur claire n'est retournée qu'ici."""
    secret = secrets.token_urlsafe(36)  # ~48 chars
    key = f"{KEY_PREFIX}{secret}"
    key_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute(text("""
            INSERT INTO api_keys (id, user_id, label, key_hash, prefix, created_at)
            VALUES (:id, :user_id, :label, :key_hash, :prefix, :created_at)
        """), {
            "id": key_id,
            "user_id": user_id,
            "label": label.strip(),
            "key_hash": _hash(key),
            "prefix": key[:PREFIX_STORED_LEN],
            "created_at": now,
        })
    return {
        "id": key_id,
        "key": key,
        "prefix": key[:PREFIX_STORED_LEN],
        "label": label.strip(),
        "created_at": now,
    }


def lookup(key: str) -> dict | None:
    """Cherche une clé non-révoquée. Bump last_used_at si trouvée."""
    if not key or not key.startswith(KEY_PREFIX):
        return None
    h = _hash(key)
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        row = db.execute(text("""
            SELECT id, user_id, label, prefix, created_at, revoked_at
            FROM api_keys WHERE key_hash = :h
        """), {"h": h}).mappings().fetchone()
        if not row or row["revoked_at"]:
            return None
        db.execute(text("UPDATE api_keys SET last_used_at = :now WHERE id = :id"),
                   {"now": now, "id": row["id"]})
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "label": row["label"],
        "prefix": row["prefix"],
        "created_at": row["created_at"],
    }


def list_for_user(user_id: str) -> list[dict]:
    with get_db() as db:
        rows = db.execute(text("""
            SELECT id, label, prefix, created_at, last_used_at, revoked_at
            FROM api_keys WHERE user_id = :uid ORDER BY created_at DESC
        """), {"uid": user_id}).mappings().all()
    return [dict(r) for r in rows]


def revoke(user_id: str, key_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        result = db.execute(text("""
            UPDATE api_keys SET revoked_at = :now
            WHERE id = :id AND user_id = :uid AND revoked_at IS NULL
        """), {"now": now, "id": key_id, "uid": user_id})
    return result.rowcount > 0
