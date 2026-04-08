"""
api/routes/planning.py — CRUD séances planifiées.

Stocke les séances planifiées par utilisateur dans un fichier JSON.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.user_data import get_user_paths

router = APIRouter(prefix="/api/planning", tags=["planning"])


# ── Models ────────────────────────────────────────────────────────────────────

class Exercise(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[str] = None           # "12" or "30s" (isometric)
    weight: Optional[str] = None         # "20kg", "poids du corps"
    rest: Optional[str] = None           # "1min", "30s"


class PlannedWorkout(BaseModel):
    date: str                            # YYYY-MM-DD
    type: str                            # "Endurance fondamentale", "Fractionné", "Renforcement musculaire", etc.
    target: str = "distance"             # "distance" | "duration"
    distance_km: Optional[float] = None
    duration_min: Optional[float] = None
    allure: Optional[str] = None         # "5:30" format
    reps: Optional[str] = None           # "8x400m"
    allure_effort: Optional[str] = None
    recovery: Optional[str] = None
    exercises: Optional[List[Exercise]] = None  # For strength workouts
    notes: Optional[str] = None


class PlannedWorkoutUpdate(PlannedWorkout):
    pass


# ── Storage helpers ───────────────────────────────────────────────────────────

def _planning_path(user_id: str) -> str:
    paths = get_user_paths(user_id)
    return os.path.join(paths.base, "planned_workouts.json")


def _load_workouts(user_id: str) -> list[dict]:
    path = _planning_path(user_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_workouts(user_id: str, workouts: list[dict]):
    path = _planning_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workouts, f, indent=2, ensure_ascii=False)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_workouts(user: dict = Depends(get_current_user)):
    """Liste toutes les séances planifiées."""
    return {"workouts": _load_workouts(user["id"])}


@router.post("", status_code=201)
def create_workout(body: PlannedWorkout, user: dict = Depends(get_current_user)):
    """Crée une séance planifiée."""
    workouts = _load_workouts(user["id"])
    workout = {
        "id": uuid.uuid4().hex[:12],
        **body.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    workouts.append(workout)
    _save_workouts(user["id"], workouts)
    return {"ok": True, "workout": workout}


@router.put("/{workout_id}")
def update_workout(workout_id: str, body: PlannedWorkoutUpdate, user: dict = Depends(get_current_user)):
    """Modifie une séance planifiée."""
    workouts = _load_workouts(user["id"])
    for i, w in enumerate(workouts):
        if w["id"] == workout_id:
            workouts[i] = {
                **w,
                **body.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_workouts(user["id"], workouts)
            return {"ok": True, "workout": workouts[i]}
    return {"ok": False, "error": "not_found"}


@router.delete("/{workout_id}")
def delete_workout(workout_id: str, user: dict = Depends(get_current_user)):
    """Supprime une séance planifiée."""
    workouts = _load_workouts(user["id"])
    before = len(workouts)
    workouts = [w for w in workouts if w["id"] != workout_id]
    if len(workouts) == before:
        return {"ok": False, "error": "not_found"}
    _save_workouts(user["id"], workouts)
    return {"ok": True}
