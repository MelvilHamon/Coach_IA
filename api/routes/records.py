"""
api/routes/records.py — Endpoint Personal Records.
"""

import json
import os

from fastapi import APIRouter, Depends

from api.dependencies import get_current_user
from api.user_data import UserPaths

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("")
def get_records(user: dict = Depends(get_current_user)):
    """Records personnels (sliding window GPS)."""
    paths = UserPaths(user["id"])
    pr_path = paths.personal_records_json

    # Fallback to legacy path if user-scoped doesn't exist
    if not os.path.exists(pr_path):
        pr_path = os.path.join(_ROOT, "data", "personal_records.json")

    if not os.path.exists(pr_path):
        return {"distances": {}}

    try:
        with open(pr_path, encoding="utf-8") as f:
            data = json.load(f)
        return {"distances": data}
    except (json.JSONDecodeError, OSError):
        return {"distances": {}}
