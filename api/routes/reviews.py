"""
api/routes/reviews.py — Endpoints reviews LLM (par activite + bilan hebdo).
"""

import logging

from fastapi import APIRouter, Depends, Query

from api.deps import get_review, nan_safe
from api.dependencies import get_current_user
from api.user_data import UserPaths

router = APIRouter(prefix="/api/reviews", tags=["reviews"])
logger = logging.getLogger("coachagent")


@router.get("/{activity_id}")
def read_review(activity_id: int, user: dict = Depends(get_current_user)):
    """Retourne la review cached ou null."""
    review = get_review(activity_id, user["id"])
    if not review:
        return {"activity_id": activity_id, "review": None}
    return {"activity_id": activity_id, "review": nan_safe(review)}


@router.post("/{activity_id}")
def generate_review_endpoint(activity_id: int, user: dict = Depends(get_current_user)):
    """Genere ou regenere la review LLM structuree."""
    try:
        from analyse.llm_review import generate_review
        paths = UserPaths(user["id"])
        result = generate_review(
            activity_id,
            force=True,
            data_dir=paths.base,
            config_path=paths.config_json,
        )
        return {"activity_id": activity_id, "review": nan_safe(result)}
    except Exception as e:
        logger.error("Review generation failed for %s: %s", activity_id, e)
        return {"activity_id": activity_id, "error": "Erreur lors de la generation de la review."}


@router.get("/weekly/current")
def read_weekly_review(
    offset: int = Query(0, ge=0, le=12, description="0=semaine en cours, 1=precedente, etc."),
    user: dict = Depends(get_current_user),
):
    """Retourne le bilan hebdomadaire cached ou null."""
    import os, json
    paths = UserPaths(user["id"])
    import pandas as pd
    from datetime import timezone
    now = pd.Timestamp.now(tz=timezone.utc)
    week_start = (now - pd.Timedelta(days=now.weekday()) - pd.Timedelta(weeks=offset)).normalize()
    cache_key = week_start.strftime("%Y-W%W")
    cache_path = os.path.join(paths.reviews_dir, f"weekly_{cache_key}.json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        data["cached"] = True
        return {"week": cache_key, "review": nan_safe(data)}
    return {"week": cache_key, "review": None}


@router.post("/weekly/generate")
def generate_weekly_review_endpoint(
    offset: int = Query(0, ge=0, le=12),
    user: dict = Depends(get_current_user),
):
    """Genere le bilan hebdomadaire LLM."""
    try:
        from analyse.llm_review import generate_weekly_review
        paths = UserPaths(user["id"])
        result = generate_weekly_review(
            user_data_dir=paths.base,
            config_path=paths.config_json,
            force=True,
            week_offset=offset,
        )
        return {"week": result.get("week"), "review": nan_safe(result)}
    except Exception as e:
        logger.error("Weekly review generation failed: %s", e)
        return {"error": "Erreur lors de la generation du bilan hebdomadaire."}
