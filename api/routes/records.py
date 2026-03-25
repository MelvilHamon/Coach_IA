"""
api/routes/records.py — Endpoint Personal Records.
"""

import json
import os

from fastapi import APIRouter

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PR_PATH = os.path.join(_ROOT, "data", "personal_records.json")

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("")
def get_records():
    """Records personnels (sliding window GPS)."""
    if not os.path.exists(_PR_PATH):
        return {"distances": {}}

    try:
        with open(_PR_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {"distances": data}
    except (json.JSONDecodeError, OSError):
        return {"distances": {}}
