"""
api/routes/reviews.py — Endpoints reviews LLM.
"""

from fastapi import APIRouter, Depends

from api.deps import get_review, nan_safe
from api.dependencies import get_current_user
from api.user_data import UserPaths

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/{activity_id}")
def read_review(activity_id: int, user: dict = Depends(get_current_user)):
    """Retourne la review cached ou null."""
    review = get_review(activity_id, user["id"])
    if not review:
        return {"activity_id": activity_id, "review": None}
    return {"activity_id": activity_id, "review": nan_safe(review)}


@router.post("/{activity_id}")
def generate_review_endpoint(activity_id: int, user: dict = Depends(get_current_user)):
    """Génère ou régénère la review LLM."""
    try:
        from llm_review import generate_review
        paths = UserPaths(user["id"])
        result = generate_review(
            activity_id,
            force=True,
            data_dir=paths.base,
            config_path=paths.config_json,
        )
        return {"activity_id": activity_id, "review": nan_safe(result)}
    except Exception as e:
        import logging
        logging.getLogger("coachagent").error("Review generation failed for %s: %s", activity_id, e)
        return {"activity_id": activity_id, "error": "Erreur lors de la génération de la review."}
