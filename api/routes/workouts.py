"""
api/routes/workouts.py — Génération de fichiers .FIT et descriptions de séances.

Endpoints :
  POST /api/workouts/generate-fit/{workout_id}  → génère un .fit depuis une séance planifiée
  POST /api/workouts/text-to-fit                → texte libre → .fit via LLM
  POST /api/workouts/describe                   → description détaillée d'une séance
  GET  /api/workouts/download/{filename}        → télécharge un .fit généré
"""

import json
import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.user_data import get_user_paths

router = APIRouter(prefix="/api/workouts", tags=["workouts"])
logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONFIG = os.path.join(_ROOT, "config.json")


def _fit_output_dir(user_id: str) -> str:
    paths = get_user_paths(user_id)
    d = os.path.join(paths.base, "fit_workouts")
    os.makedirs(d, exist_ok=True)
    return d


def _load_config() -> dict:
    if os.path.exists(_CONFIG):
        with open(_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_planned_workouts(user_id: str) -> list[dict]:
    paths = get_user_paths(user_id)
    path = os.path.join(paths.base, "planned_workouts.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_hr_zones(user_id: str) -> dict | None:
    """Charge les zones FC depuis le profil utilisateur ou la config."""
    try:
        from api.auth import get_user_profile
        profile = get_user_profile(user_id)
        if profile and profile.get("hr_max"):
            return profile
    except Exception:
        pass

    cfg = _load_config()
    athlete = cfg.get("athlete", {})
    if athlete.get("hr_max"):
        return athlete
    return None


# ── Models ──────────────────────────────────────────────────────────────────


class TextToFitRequest(BaseModel):
    text: str
    workout_name: Optional[str] = None


class DescribeRequest(BaseModel):
    text: Optional[str] = None
    workout_id: Optional[str] = None


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("/generate-fit/{workout_id}")
def generate_fit_from_planned(workout_id: str, user: dict = Depends(get_current_user)):
    """Génère un fichier .FIT à partir d'une séance planifiée existante."""
    from fit_builder.workout_builder import generate_fit_file

    workouts = _load_planned_workouts(user["id"])
    workout = next((w for w in workouts if w.get("id") == workout_id), None)
    if not workout:
        raise HTTPException(404, "Séance planifiée non trouvée")

    output_dir = _fit_output_dir(user["id"])
    hr_zones = _get_hr_zones(user["id"])

    try:
        filepath = generate_fit_file(workout, output_dir, hr_zones=hr_zones)
        filename = os.path.basename(filepath)
        return {
            "ok": True,
            "filename": filename,
            "download_url": f"/api/workouts/download/{filename}",
        }
    except Exception as e:
        logger.error(f"Erreur génération FIT: {e}", exc_info=True)
        raise HTTPException(500, f"Erreur génération FIT: {str(e)}")


@router.post("/text-to-fit")
def text_to_fit(body: TextToFitRequest, user: dict = Depends(get_current_user)):
    """Convertit un texte libre en fichier .FIT via LLM."""
    from fit_builder.llm_converter import text_to_structured
    from fit_builder.workout_builder import generate_fit_file

    cfg = _load_config()
    llm_cfg = cfg.get("llm", {})

    try:
        structured = text_to_structured(body.text, temperature=0.4, llm_cfg=llm_cfg)
    except Exception as e:
        logger.error(f"Erreur LLM text-to-fit: {e}", exc_info=True)
        raise HTTPException(500, f"Erreur conversion LLM: {str(e)}")

    output_dir = _fit_output_dir(user["id"])
    hr_zones = _get_hr_zones(user["id"])

    # Créer un pseudo workout pour generate_fit_file
    pseudo_workout = {
        "id": "txt_" + str(hash(body.text))[-8:],
        "type": structured.get("name", body.workout_name or "Workout"),
    }

    try:
        filepath = generate_fit_file(pseudo_workout, output_dir,
                                      structured=structured, hr_zones=hr_zones)
        filename = os.path.basename(filepath)
        return {
            "ok": True,
            "filename": filename,
            "download_url": f"/api/workouts/download/{filename}",
            "structured": structured,
        }
    except Exception as e:
        logger.error(f"Erreur génération FIT depuis texte: {e}", exc_info=True)
        raise HTTPException(500, f"Erreur génération FIT: {str(e)}")


@router.post("/describe")
def describe_workout(body: DescribeRequest, user: dict = Depends(get_current_user)):
    """Génère une description détaillée de séance."""
    from fit_builder.llm_converter import (
        generate_description_from_text,
        planned_to_description,
    )

    cfg = _load_config()
    llm_cfg = cfg.get("llm", {})

    # Si workout_id fourni, charger la séance et la décrire
    if body.workout_id:
        workouts = _load_planned_workouts(user["id"])
        workout = next((w for w in workouts if w.get("id") == body.workout_id), None)
        if not workout:
            raise HTTPException(404, "Séance non trouvée")

        # Description basique depuis les champs
        basic_desc = planned_to_description(workout)

        # Enrichir via LLM
        try:
            detailed = generate_description_from_text(basic_desc, llm_cfg=llm_cfg)
            return {"ok": True, "description": detailed, "basic": basic_desc}
        except Exception as e:
            # Fallback : description basique
            return {"ok": True, "description": basic_desc, "basic": basic_desc}

    # Texte libre
    if body.text:
        try:
            detailed = generate_description_from_text(body.text, llm_cfg=llm_cfg)
            return {"ok": True, "description": detailed}
        except Exception as e:
            raise HTTPException(500, f"Erreur description: {str(e)}")

    raise HTTPException(400, "Fournir text ou workout_id")


@router.get("/download/{filename}")
def download_fit(filename: str, user: dict = Depends(get_current_user)):
    """Télécharge un fichier .FIT généré."""
    if not filename.endswith(".fit"):
        raise HTTPException(400, "Fichier invalide")

    # Sécurité : empêcher la traversée de répertoire
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Nom de fichier invalide")

    output_dir = _fit_output_dir(user["id"])
    filepath = os.path.join(output_dir, filename)

    if not os.path.exists(filepath):
        raise HTTPException(404, "Fichier non trouvé")

    return FileResponse(
        filepath,
        media_type="application/octet-stream",
        filename=filename,
    )
