"""
api/dependencies.py — FastAPI dependencies for user context.
"""

from fastapi import Request, HTTPException

from api.auth import get_user_by_session
from api import api_keys

SESSION_COOKIE = "ca_session"


def get_current_user(request: Request) -> dict:
    """FastAPI dependency: extract user from session cookie. Raises 401 if invalid."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expirée")
    return user


def require_api_key(request: Request) -> dict:
    """
    FastAPI dependency pour /api/v1/* : lit `Authorization: Bearer <api_key>`
    et retourne le dict utilisateur. Lève 401 avec un detail structuré que
    l'exception handler global convertit en {"error": ..., "message": ...}.
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={
            "error": "unauthorized",
            "message": "Header Authorization: Bearer <api_key> requis.",
        })
    key = auth.split(" ", 1)[1].strip()
    info = api_keys.lookup(key)
    if not info:
        raise HTTPException(status_code=401, detail={
            "error": "invalid_api_key",
            "message": "Clé API inconnue ou révoquée.",
        })
    return {"id": info["user_id"], "api_key_id": info["id"]}
