"""
api/routes/config.py — Endpoints configuration et état.
"""

from fastapi import APIRouter

from api.deps import load_config, load_sync_state, load_activities, nan_safe

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def read_config():
    """Configuration athlète et seuils."""
    cfg = load_config()
    return nan_safe({
        "athlete":    cfg.get("athlete", {}),
        "acwr":       cfg.get("acwr", {}),
        "injury_risk": cfg.get("injury_risk", {}),
    })


@router.get("/status")
def read_status():
    """État global : nombre d'activités, dernier sync, etc."""
    df = load_activities()
    state = load_sync_state()

    last_date = None
    if not df.empty:
        last_date = df.iloc[0]["Date"].isoformat()

    return nan_safe({
        "n_activities":     len(df),
        "last_activity":    last_date,
        "sync_state":       state,
    })
