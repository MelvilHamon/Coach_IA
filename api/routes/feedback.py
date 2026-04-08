"""
api/routes/feedback.py — Ressentis / feedback subjectif sur une activité.

Stockage : data/users/{user_id}/feedback/{activity_id}.json
"""

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from api.dependencies import get_current_user
from api.user_data import get_user_paths

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackPayload(BaseModel):
    sensations: Optional[str] = None
    difficulty: int = Field(..., ge=1, le=10)


def _feedback_dir(user_id: str) -> str:
    paths = get_user_paths(user_id)
    d = os.path.join(paths.base, "feedback")
    os.makedirs(d, exist_ok=True)
    return d


def _feedback_path(user_id: str, activity_id: int) -> str:
    return os.path.join(_feedback_dir(user_id), f"{activity_id}.json")


@router.get("/{activity_id}")
def get_feedback(activity_id: int, user: dict = Depends(get_current_user)):
    path = _feedback_path(user["id"], activity_id)
    if not os.path.exists(path):
        return {"activity_id": activity_id, "feedback": None}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {"activity_id": activity_id, "feedback": data}


@router.put("/{activity_id}")
def save_feedback(activity_id: int, payload: FeedbackPayload, user: dict = Depends(get_current_user)):
    path = _feedback_path(user["id"], activity_id)
    now = datetime.now(timezone.utc).isoformat()

    # Preserve created_at if updating
    existing = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)

    data = {
        "activity_id": activity_id,
        "sensations": payload.sensations,
        "difficulty": payload.difficulty,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"activity_id": activity_id, "feedback": data}
