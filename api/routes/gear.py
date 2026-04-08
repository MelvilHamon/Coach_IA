"""
api/routes/gear.py — CRUD matériel (chaussures, montres).

Stocke le matériel par utilisateur dans un fichier JSON.
Calcule les km cumulés à partir des activités enrichies.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.deps import load_activities, nan_safe
from api.user_data import get_user_paths

router = APIRouter(prefix="/api/gear", tags=["gear"])


# ── Models ────────────────────────────────────────────────────────────────────

class GearCreate(BaseModel):
    name: str
    type: str                          # "shoes" | "watch"
    brand: Optional[str] = None
    acquired_date: Optional[str] = None  # YYYY-MM-DD
    retired: bool = False


class GearUpdate(GearCreate):
    pass


class GearAssign(BaseModel):
    gear_id: Optional[str] = None      # null to unassign


# ── Storage helpers ───────────────────────────────────────────────────────────

def _gear_path(user_id: str) -> str:
    paths = get_user_paths(user_id)
    return os.path.join(paths.base, "gear.json")


def _assignments_path(user_id: str) -> str:
    paths = get_user_paths(user_id)
    return os.path.join(paths.base, "gear_assignments.json")


def _load_gear(user_id: str) -> list[dict]:
    path = _gear_path(user_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_gear(user_id: str, items: list[dict]):
    path = _gear_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def _load_assignments(user_id: str) -> dict:
    """Returns {activity_id: {shoes: gear_id, watch: gear_id}}."""
    path = _assignments_path(user_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_assignments(user_id: str, data: dict):
    path = _assignments_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Km computation ────────────────────────────────────────────────────────────

def _compute_gear_km(user_id: str, gear_items: list[dict]) -> dict:
    """Returns {gear_id: total_km}.

    For shoes: if there is exactly one non-retired shoe, all activities
    since its acquired_date count automatically (no manual assignment needed).
    """
    assignments = _load_assignments(user_id)
    df = load_activities(user_id)

    km_by_gear = {g["id"]: 0.0 for g in gear_items}

    if df.empty:
        return km_by_gear

    # Detect sole active shoe for auto-attribution
    active_shoes = [g for g in gear_items if g["type"] == "shoes" and not g.get("retired")]
    sole_shoe = active_shoes[0] if len(active_shoes) == 1 else None

    # Build set of activity IDs explicitly assigned to each gear
    assigned_acts = {}  # {gear_id: set(act_id)}
    for act_id_str, mapping in assignments.items():
        try:
            act_id = int(act_id_str)
        except (ValueError, TypeError):
            continue
        row = df[df["ID"] == act_id]
        if row.empty:
            continue
        dist = row.iloc[0].get("Distance (km)")
        if pd.isna(dist) or dist is None:
            continue
        for gear_id in mapping.values():
            if gear_id in km_by_gear:
                km_by_gear[gear_id] += float(dist)
                assigned_acts.setdefault(gear_id, set()).add(act_id)

    # Auto-attribute unassigned activities to sole shoe since acquired_date
    if sole_shoe:
        shoe_id = sole_shoe["id"]
        already = assigned_acts.get(shoe_id, set())
        cutoff = None
        if sole_shoe.get("acquired_date"):
            try:
                cutoff = pd.Timestamp(sole_shoe["acquired_date"], tz="UTC")
            except Exception:
                cutoff = None

        for _, row in df.iterrows():
            act_id = int(row["ID"])
            if act_id in already:
                continue
            # Skip if this activity has a different shoe assigned
            act_assign = assignments.get(str(act_id), {})
            if "shoes" in act_assign and act_assign["shoes"] != shoe_id:
                continue
            dist = row.get("Distance (km)")
            if pd.isna(dist) or dist is None:
                continue
            if cutoff is not None and row.get("Date") is not None:
                act_date = pd.Timestamp(row["Date"])
                if act_date.tzinfo is None:
                    act_date = act_date.tz_localize("UTC")
                if act_date < cutoff:
                    continue
            km_by_gear[shoe_id] += float(dist)

    return km_by_gear


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_gear(user: dict = Depends(get_current_user)):
    """Liste tout le matériel avec km cumulés."""
    items = _load_gear(user["id"])
    km_map = _compute_gear_km(user["id"], items)
    for item in items:
        item["total_km"] = round(km_map.get(item["id"], 0), 1)
    return {"gear": items}


@router.post("", status_code=201)
def create_gear(body: GearCreate, user: dict = Depends(get_current_user)):
    """Crée un équipement."""
    items = _load_gear(user["id"])
    item = {
        "id": uuid.uuid4().hex[:12],
        **body.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items.append(item)
    _save_gear(user["id"], items)
    return {"ok": True, "item": item}


@router.put("/{gear_id}")
def update_gear(gear_id: str, body: GearUpdate, user: dict = Depends(get_current_user)):
    """Modifie un équipement."""
    items = _load_gear(user["id"])
    for i, g in enumerate(items):
        if g["id"] == gear_id:
            items[i] = {**g, **body.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat()}
            _save_gear(user["id"], items)
            return {"ok": True, "item": items[i]}
    return {"ok": False, "error": "not_found"}


@router.delete("/{gear_id}")
def delete_gear(gear_id: str, user: dict = Depends(get_current_user)):
    """Supprime un équipement et ses associations."""
    items = _load_gear(user["id"])
    before = len(items)
    items = [g for g in items if g["id"] != gear_id]
    if len(items) == before:
        return {"ok": False, "error": "not_found"}
    _save_gear(user["id"], items)

    # Clean up assignments
    assignments = _load_assignments(user["id"])
    changed = False
    for act_id, mapping in list(assignments.items()):
        for slot, gid in list(mapping.items()):
            if gid == gear_id:
                del mapping[slot]
                changed = True
        if not mapping:
            del assignments[act_id]
            changed = True
    if changed:
        _save_assignments(user["id"], assignments)

    return {"ok": True}


@router.get("/assignments")
def list_assignments(user: dict = Depends(get_current_user)):
    """Retourne toutes les associations activité → matériel."""
    return {"assignments": _load_assignments(user["id"])}


@router.put("/assign/{activity_id}/{slot}")
def assign_gear(activity_id: str, slot: str, body: GearAssign, user: dict = Depends(get_current_user)):
    """Associe ou dissocie un matériel à une activité.

    slot: "shoes" ou "watch"
    """
    if slot not in ("shoes", "watch"):
        return {"ok": False, "error": "slot must be 'shoes' or 'watch'"}

    assignments = _load_assignments(user["id"])

    if body.gear_id:
        if activity_id not in assignments:
            assignments[activity_id] = {}
        assignments[activity_id][slot] = body.gear_id
    else:
        if activity_id in assignments and slot in assignments[activity_id]:
            del assignments[activity_id][slot]
            if not assignments[activity_id]:
                del assignments[activity_id]

    _save_assignments(user["id"], assignments)
    return {"ok": True}
