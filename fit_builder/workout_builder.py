"""
fit_builder/workout_builder.py — Convertit une séance planifiée en fichier .FIT.

Pipeline : PlannedWorkout (JSON) → steps FIT → fichier .fit
"""

from __future__ import annotations

import logging
import os
import time
import re
from pathlib import Path

from fit_tool.profile.profile_type import Sport

from .workout_utils import (
    ACT, WU, CD, REC,
    resolve_intensity,
    dist_pace, dist_open, dist_hr,
    time_pace, time_step, time_hr,
    open_step, repeat_step,
    save_workout,
)

logger = logging.getLogger(__name__)


def _parse_reps(reps_str: str) -> tuple[int, float, str]:
    """Parse '8x400m' ou '6x1000m' → (count, distance_km, unit).
    Gère aussi '8x1min', '6x30s', '4x3min'.
    """
    if not reps_str:
        raise ValueError("Champ reps vide")

    m = re.match(r"(\d+)\s*[xX×]\s*(\d+)\s*(m|km|min|s)\b", reps_str.strip())
    if not m:
        raise ValueError(f"Format reps invalide: '{reps_str}', attendu NxDISTunité (ex: 8x400m)")

    count = int(m.group(1))
    value = float(m.group(2))
    unit = m.group(3)

    return count, value, unit


def _parse_recovery(recovery_str: str | None) -> int:
    """Parse '1min', '90s', '2min', '3min' → secondes."""
    if not recovery_str:
        return 60

    r = recovery_str.strip().lower()
    m = re.match(r"(\d+)\s*(min|s|sec)", r)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        return val * 60 if unit == "min" else val

    # Fallback : essayer un nombre seul (secondes)
    try:
        return int(r)
    except ValueError:
        return 60


def _pace_with_margin(pace_str: str, margin_sec: int = 15) -> tuple[str, str]:
    """Crée un range (fast, slow) autour d'une allure avec une marge.
    '5:00' avec margin=15 → ('4:45', '5:15')
    """
    if not pace_str or ":" not in pace_str:
        return ("5:00", "6:00")

    parts = pace_str.split(":")
    mm, ss = int(parts[0]), int(parts[1])
    total = mm * 60 + ss

    fast_total = max(60, total - margin_sec)
    slow_total = total + margin_sec

    fast = f"{fast_total // 60}:{fast_total % 60:02d}"
    slow = f"{slow_total // 60}:{slow_total % 60:02d}"
    return fast, slow


def build_steps_from_planned(workout: dict, hr_zones: dict | None = None) -> list:
    """Construit les steps FIT à partir d'une séance planifiée CoachAgent.

    Args:
        workout: dict avec les champs du PlannedWorkout
        hr_zones: dict optionnel avec hr_max, hr_rest, etc.

    Returns:
        list de WorkoutStepMessage
    """
    wtype = (workout.get("type") or "").lower()
    steps = []
    idx = 0

    # ── Endurance / Récupération / Sortie longue ────────────────────────────
    if any(k in wtype for k in ("endurance", "récupération", "recup", "sortie longue")):
        allure = workout.get("allure")
        distance = workout.get("distance_km")
        duration = workout.get("duration_min")

        if allure:
            pace_fast, pace_slow = _pace_with_margin(allure, 15)
        elif "récup" in wtype or "recup" in wtype:
            pace_fast, pace_slow = "5:45", "6:30"
        else:
            pace_fast, pace_slow = "5:15", "6:00"

        # Échauffement 10min
        steps.append(time_step(idx, 600, WU))
        idx += 1

        # Corps de séance
        if workout.get("target") == "duration" and duration:
            main_sec = int(duration * 60) - 600  # Moins l'échauffement
            if main_sec > 0:
                steps.append(time_pace(idx, main_sec, pace_fast, pace_slow, ACT))
                idx += 1
        elif distance:
            warmup_km = min(1.0, distance * 0.1)
            main_km = distance - warmup_km
            # Remplacer l'échauffement temps par distance
            steps.pop()
            idx -= 1
            steps.append(dist_pace(idx, warmup_km, pace_fast, "6:30", WU))
            idx += 1
            steps.append(dist_pace(idx, main_km, pace_fast, pace_slow, ACT))
            idx += 1
        else:
            # Pas de distance ni durée → step ouvert
            steps.append(open_step(idx, ACT))
            idx += 1

        return steps

    # ── Seuil / Tempo ───────────────────────────────────────────────────────
    if "seuil" in wtype or "tempo" in wtype:
        allure = workout.get("allure")
        distance = workout.get("distance_km")
        duration = workout.get("duration_min")

        if allure:
            pace_fast, pace_slow = _pace_with_margin(allure, 10)
        else:
            pace_fast, pace_slow = "4:40", "5:00"

        warmup_km = 2.0
        cooldown_km = 1.0

        # Échauffement
        steps.append(dist_pace(idx, warmup_km, "5:30", "6:00", WU))
        idx += 1

        # Corps seuil
        if workout.get("target") == "duration" and duration:
            main_sec = int(duration * 60) - 15 * 60  # Moins échauffement+retour
            if main_sec > 0:
                steps.append(time_pace(idx, main_sec, pace_fast, pace_slow, ACT))
                idx += 1
        elif distance:
            main_km = max(1.0, distance - warmup_km - cooldown_km)
            steps.append(dist_pace(idx, main_km, pace_fast, pace_slow, ACT))
            idx += 1
        else:
            steps.append(time_pace(idx, 1200, pace_fast, pace_slow, ACT))
            idx += 1

        # Retour au calme
        steps.append(dist_pace(idx, cooldown_km, "5:30", "6:30", CD))
        idx += 1

        return steps

    # ── Fractionné ──────────────────────────────────────────────────────────
    if "fractionné" in wtype or "interval" in wtype:
        reps_str = workout.get("reps")
        allure_effort = workout.get("allure_effort")
        recovery_str = workout.get("recovery")

        if not reps_str:
            # Pas de reps définis → séance ouverte
            steps.append(time_step(idx, 900, WU))
            idx += 1
            steps.append(open_step(idx, ACT))
            idx += 1
            steps.append(time_step(idx, 600, CD))
            idx += 1
            return steps

        count, value, unit = _parse_reps(reps_str)
        recovery_sec = _parse_recovery(recovery_str)

        if allure_effort:
            effort_fast, effort_slow = _pace_with_margin(allure_effort, 10)
        else:
            effort_fast, effort_slow = "3:45", "4:15"

        # Échauffement 2km
        steps.append(dist_pace(idx, 2.0, "5:30", "6:15", WU))
        idx += 1

        # Step effort
        effort_start_idx = idx
        if unit in ("m", "km"):
            km_val = value / 1000.0 if unit == "m" else value
            steps.append(dist_pace(idx, km_val, effort_fast, effort_slow, ACT))
            idx += 1
        else:  # min, s
            sec_val = int(value * 60) if unit == "min" else int(value)
            steps.append(time_pace(idx, sec_val, effort_fast, effort_slow, ACT))
            idx += 1

        # Récupération
        steps.append(time_step(idx, recovery_sec, REC))
        idx += 1

        # Repeat
        steps.append(repeat_step(idx, effort_start_idx, count))
        idx += 1

        # Retour au calme 1km
        steps.append(dist_pace(idx, 1.0, "5:30", "6:30", CD))
        idx += 1

        return steps

    # ── Trail ───────────────────────────────────────────────────────────────
    if "trail" in wtype:
        distance = workout.get("distance_km")
        duration = workout.get("duration_min")

        # Trail → cible FC plutôt qu'allure
        hr_low = 135
        hr_high = 160
        if hr_zones:
            hr_low = hr_zones.get("hr_rest", 45) + 90
            hr_high = int(hr_zones.get("hr_max", 195) * 0.85)

        steps.append(time_hr(idx, 600, hr_low - 10, hr_low + 10, WU))
        idx += 1

        if distance:
            steps.append(dist_hr(idx, distance - 1.0, hr_low, hr_high, ACT))
            idx += 1
        elif duration:
            steps.append(time_hr(idx, int(duration * 60) - 600, hr_low, hr_high, ACT))
            idx += 1
        else:
            steps.append(open_step(idx, ACT))
            idx += 1

        steps.append(time_step(idx, 300, CD))
        idx += 1
        return steps

    # ── Compétition ─────────────────────────────────────────────────────────
    if "compétition" in wtype or "competition" in wtype:
        allure = workout.get("allure")
        distance = workout.get("distance_km")

        if allure and distance:
            pace_fast, pace_slow = _pace_with_margin(allure, 5)
            steps.append(dist_pace(idx, distance, pace_fast, pace_slow, ACT))
            idx += 1
        elif distance:
            steps.append(dist_open(idx, distance, ACT))
            idx += 1
        else:
            steps.append(open_step(idx, ACT))
            idx += 1
        return steps

    # ── Fallback : séance générique ─────────────────────────────────────────
    distance = workout.get("distance_km")
    duration = workout.get("duration_min")
    allure = workout.get("allure")

    if allure:
        pace_fast, pace_slow = _pace_with_margin(allure, 15)
    else:
        pace_fast, pace_slow = "5:15", "6:00"

    if distance:
        steps.append(dist_pace(idx, distance, pace_fast, pace_slow, ACT))
        idx += 1
    elif duration:
        steps.append(time_pace(idx, int(duration * 60), pace_fast, pace_slow, ACT))
        idx += 1
    else:
        steps.append(open_step(idx, ACT))
        idx += 1

    return steps


def build_steps_from_structured(structured: dict) -> list:
    """Construit les steps FIT à partir d'une sortie structurée du LLM.

    Le format attendu est:
    {
        "name": "...",
        "steps": [
            {"type": "dist_pace", "km": 2.0, "pace_fast": "5:00", "pace_slow": "5:30", "intensity": "warmup"},
            {"type": "time_hr", "seconds": 1200, "hr_low": 140, "hr_high": 155, "intensity": "active"},
            {"type": "repeat", "back_to_offset": 1, "count": 6},
            ...
        ]
    }
    """
    raw_steps = structured.get("steps", [])
    if not raw_steps:
        raise ValueError("Aucun step défini dans la structure")

    steps = []
    idx = 0
    yaml_to_fit = {}

    # Premier pass : mapper les index YAML → FIT
    fit_idx = 0
    for yaml_idx, s in enumerate(raw_steps):
        yaml_to_fit[yaml_idx] = fit_idx
        fit_idx += 1

    # Deuxième pass : construire les steps
    for yaml_idx, s in enumerate(raw_steps):
        stype = s.get("type", "open_step")
        intensity = resolve_intensity(s.get("intensity"))

        if stype == "dist_pace":
            steps.append(dist_pace(idx, s["km"], s["pace_fast"], s["pace_slow"], intensity))
        elif stype == "dist_open":
            steps.append(dist_open(idx, s["km"], intensity))
        elif stype == "dist_hr":
            steps.append(dist_hr(idx, s["km"], s["hr_low"], s["hr_high"], intensity))
        elif stype == "time_pace":
            steps.append(time_pace(idx, s["seconds"], s["pace_fast"], s["pace_slow"], intensity))
        elif stype == "time_step":
            steps.append(time_step(idx, s["seconds"], intensity))
        elif stype == "time_hr":
            steps.append(time_hr(idx, s["seconds"], s["hr_low"], s["hr_high"], intensity))
        elif stype == "open_step":
            steps.append(open_step(idx, intensity))
        elif stype == "repeat":
            back_to = yaml_to_fit.get(s["back_to_offset"], s["back_to_offset"])
            steps.append(repeat_step(idx, back_to, s["count"]))
        else:
            raise ValueError(f"Type de step inconnu: {stype}")

        idx += 1

    return steps


def generate_fit_file(workout: dict, output_dir: str,
                      structured: dict | None = None,
                      hr_zones: dict | None = None) -> str:
    """Génère un fichier .FIT à partir d'une séance planifiée.

    Args:
        workout: dict de la séance planifiée (PlannedWorkout)
        output_dir: répertoire de sortie
        structured: si fourni, utilise la structure LLM au lieu de la planification
        hr_zones: zones FC optionnelles

    Returns:
        Chemin du fichier .fit généré
    """
    os.makedirs(output_dir, exist_ok=True)

    if structured and structured.get("steps"):
        steps = build_steps_from_structured(structured)
        name = structured.get("name") or workout.get("type", "Workout")
    else:
        steps = build_steps_from_planned(workout, hr_zones)
        name = workout.get("type", "Workout")

    # Nom de fichier sûr
    safe_name = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")[:40]
    workout_id = workout.get("id", "")[:8]
    filename = f"{safe_name}_{workout_id}.fit"
    filepath = os.path.join(output_dir, filename)

    # Sport
    wtype = (workout.get("type") or "").lower()
    sport = Sport.RUNNING
    if "vélo" in wtype or "cycli" in wtype:
        sport = Sport.CYCLING

    serial = int(time.time()) % 900000000 + 100000000
    save_workout(filepath, name, steps, sport=sport, serial_number=serial)

    logger.info(f"Fichier FIT généré : {filepath} ({len(steps)} steps)")
    return filepath
