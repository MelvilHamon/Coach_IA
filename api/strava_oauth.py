"""
api/strava_oauth.py — Service OAuth Strava (centralisé).

UNE seule app Strava (CLIENT_ID / CLIENT_SECRET dans .env).
PLUSIEURS utilisateurs, chacun avec ses propres tokens.

Flow OAuth :
  1. /api/auth/strava/login  → redirect vers Strava
  2. Strava redirige vers /api/auth/strava/callback?code=XXX
  3. On échange le code → access_token, refresh_token, expires_at, athlete_id
  4. On stocke tout en DB par user_id

Refresh automatique :
  get_valid_access_token(user_id) vérifie l'expiration et refresh si nécessaire.
"""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config app Strava (unique, depuis .env) ──────────────────────────────────

STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID") or os.environ.get("CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET") or os.environ.get("CLIENT_SECRET")

if not STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET:
    print("[strava_oauth] WARNING: STRAVA_CLIENT_ID ou STRAVA_CLIENT_SECRET manquant dans .env")
    print("[strava_oauth]   Variables cherchées: STRAVA_CLIENT_ID / CLIENT_ID et STRAVA_CLIENT_SECRET / CLIENT_SECRET")
else:
    print(f"[strava_oauth] Config OK: client_id={STRAVA_CLIENT_ID}")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_SCOPES = "activity:read_all"


def get_authorize_url(redirect_uri: str, state: str = "") -> str:
    """Génère l'URL d'autorisation Strava pour rediriger l'utilisateur."""
    if not STRAVA_CLIENT_ID:
        raise ValueError("STRAVA_CLIENT_ID non configuré dans .env")
    params = {
        "client_id": STRAVA_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": STRAVA_SCOPES,
        "approval_prompt": "auto",
    }
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{STRAVA_AUTH_URL}?{qs}"


def exchange_code(code: str) -> dict:
    """
    Échange un authorization code contre des tokens.

    Returns dict avec : access_token, refresh_token, expires_at, athlete_id, athlete_name.
    Raises ValueError si l'échange échoue.
    """
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }, timeout=15)

    if resp.status_code != 200:
        raise ValueError(f"Strava token exchange failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    athlete = data.get("athlete", {})

    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": data["expires_at"],  # epoch timestamp
        "athlete_id": athlete.get("id"),
        "athlete_name": f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip(),
    }


def refresh_access_token(refresh_token: str) -> dict:
    """
    Refresh un access_token expiré.

    Returns dict avec : access_token, refresh_token, expires_at.
    Raises ValueError si le refresh échoue.
    """
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)

    if resp.status_code != 200:
        raise ValueError(f"Strava token refresh failed ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],  # Strava peut renvoyer un nouveau refresh_token
        "expires_at": data["expires_at"],
    }


def get_valid_access_token(user_id: str) -> str | None:
    """
    Retourne un access_token valide pour l'utilisateur.
    Refresh automatiquement si expiré. Retourne None si pas de tokens.
    """
    from api.auth import get_strava_tokens, save_strava_tokens

    tokens = get_strava_tokens(user_id)
    if not tokens:
        return None

    # Marge de 5 minutes avant expiration
    if tokens["expires_at"] and tokens["expires_at"] > int(time.time()) + 300:
        return tokens["access_token"]

    # Token expiré → refresh
    try:
        new_tokens = refresh_access_token(tokens["refresh_token"])
        save_strava_tokens(
            user_id=user_id,
            athlete_id=tokens["athlete_id"],
            access_token=new_tokens["access_token"],
            refresh_token=new_tokens["refresh_token"],
            expires_at=new_tokens["expires_at"],
        )
        print(f"[strava] Token refreshed for user {user_id}")
        return new_tokens["access_token"]
    except Exception as e:
        print(f"[strava] Token refresh failed for user {user_id}: {e}")
        return None
