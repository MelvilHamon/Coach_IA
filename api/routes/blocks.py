"""
api/routes/blocks.py — Blocs manuels effort/récup sur une activité.

Stockage : data/users/{user_id}/blocks/{activity_id}.json

Chaque bloc : { start_km, end_km, type: "effort"|"recovery" }
Le frontend dessine ces blocs sur le graphe d'allure et calcule
les métriques (allure moy, FC moy, distance, durée) côté client
à partir des arrays speed/bpm déjà chargés.
"""

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List, Optional

from api.dependencies import get_current_user
from api.user_data import get_user_paths

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


class Block(BaseModel):
    start_km: float = Field(..., ge=0)
    end_km: float = Field(..., gt=0)
    type: str = Field("effort", pattern="^(effort|recovery)$")


class BlocksPayload(BaseModel):
    blocks: List[Block]


def _blocks_dir(user_id: str) -> str:
    paths = get_user_paths(user_id)
    d = os.path.join(paths.base, "blocks")
    os.makedirs(d, exist_ok=True)
    return d


def _blocks_path(user_id: str, activity_id: int) -> str:
    return os.path.join(_blocks_dir(user_id), f"{activity_id}.json")


@router.get("/{activity_id}")
def get_blocks(activity_id: int, user: dict = Depends(get_current_user)):
    path = _blocks_path(user["id"], activity_id)
    if not os.path.exists(path):
        return {"activity_id": activity_id, "blocks": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {"activity_id": activity_id, "blocks": data.get("blocks", [])}


@router.put("/{activity_id}")
def save_blocks(activity_id: int, payload: BlocksPayload, user: dict = Depends(get_current_user)):
    path = _blocks_path(user["id"], activity_id)
    now = datetime.now(timezone.utc).isoformat()

    data = {
        "activity_id": activity_id,
        "blocks": [b.model_dump() for b in payload.blocks],
        "updated_at": now,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"activity_id": activity_id, "blocks": data["blocks"]}


@router.delete("/{activity_id}")
def delete_blocks(activity_id: int, user: dict = Depends(get_current_user)):
    path = _blocks_path(user["id"], activity_id)
    if os.path.exists(path):
        os.remove(path)
    return {"activity_id": activity_id, "blocks": []}
