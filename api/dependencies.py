"""
api/dependencies.py — FastAPI dependencies for user context.
"""

from fastapi import Request, HTTPException

from api.auth import get_user_by_session

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
