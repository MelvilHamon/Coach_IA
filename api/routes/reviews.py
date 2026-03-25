"""
api/routes/reviews.py — Endpoints reviews LLM.
"""

from fastapi import APIRouter

from api.deps import get_review, nan_safe

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/{activity_id}")
def read_review(activity_id: int):
    """Retourne la review cached ou null."""
    review = get_review(activity_id)
    if not review:
        return {"activity_id": activity_id, "review": None}
    return {"activity_id": activity_id, "review": nan_safe(review)}


@router.post("/{activity_id}")
def generate_review_endpoint(activity_id: int):
    """Génère ou régénère la review LLM."""
    try:
        from llm_review import generate_review
        result = generate_review(activity_id, force=True)
        return {"activity_id": activity_id, "review": nan_safe(result)}
    except Exception as e:
        return {"activity_id": activity_id, "error": str(e)}
