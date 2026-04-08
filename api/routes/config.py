"""
api/routes/config.py — Endpoints configuration et état.
"""

from fastapi import APIRouter, Depends

from api.deps import load_config, load_sync_state, load_activities, nan_safe
from api.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def read_config(user: dict = Depends(get_current_user)):
    """Configuration athlète et seuils."""
    cfg = load_config(user["id"])
    return nan_safe({
        "athlete":    cfg.get("athlete", {}),
        "acwr":       cfg.get("acwr", {}),
        "injury_risk": cfg.get("injury_risk", {}),
    })


@router.get("/status")
def read_status(user: dict = Depends(get_current_user)):
    """État global : nombre d'activités, dernier sync, etc."""
    df = load_activities(user["id"])
    state = load_sync_state(user["id"])

    last_date = None
    if not df.empty:
        last_date = df.iloc[0]["Date"].isoformat()

    return nan_safe({
        "n_activities":     len(df),
        "last_activity":    last_date,
        "sync_state":       state,
    })
