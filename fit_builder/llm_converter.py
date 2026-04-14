"""
fit_builder/llm_converter.py — Convertit un texte libre en structure de séance via LLM.

Pipeline : texte utilisateur → LLM (OpenAI) → JSON structuré → steps FIT
"""

from __future__ import annotations

import json
import logging
import os
import re

from dotenv import load_dotenv

from analyse.llm_client import get_llm_client

load_dotenv()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Tu es un assistant spécialisé dans la création de séances d'entraînement structurées pour montres Garmin.

L'utilisateur te donne une description textuelle d'une séance d'entraînement (course à pied principalement).
Tu dois convertir cette description en une structure JSON stricte qui sera utilisée pour générer un fichier .FIT.

## Format de sortie

Retourne UNIQUEMENT un objet JSON valide (pas de markdown, pas de commentaires) avec cette structure :

{
  "name": "Nom court de la séance (max 20 chars pour l'affichage montre)",
  "description": "Description détaillée de la séance pour le coureur",
  "steps": [
    {
      "type": "<type_step>",
      "intensity": "<warmup|active|recovery|cooldown>",
      // + champs spécifiques au type
    }
  ]
}

## Types de steps disponibles

1. **dist_pace** — Distance avec cible d'allure
   {"type": "dist_pace", "km": 2.0, "pace_fast": "5:00", "pace_slow": "5:30", "intensity": "warmup"}

2. **dist_open** — Distance sans cible
   {"type": "dist_open", "km": 1.0, "intensity": "cooldown"}

3. **dist_hr** — Distance avec cible FC
   {"type": "dist_hr", "km": 5.0, "hr_low": 140, "hr_high": 155, "intensity": "active"}

4. **time_pace** — Temps avec cible d'allure
   {"type": "time_pace", "seconds": 600, "pace_fast": "4:30", "pace_slow": "4:50", "intensity": "active"}

5. **time_step** — Temps sans cible (récupération, échauffement libre)
   {"type": "time_step", "seconds": 120, "intensity": "recovery"}

6. **time_hr** — Temps avec cible FC
   {"type": "time_hr", "seconds": 1200, "hr_low": 150, "hr_high": 165, "intensity": "active"}

7. **open_step** — Step libre (bouton lap pour avancer)
   {"type": "open_step", "intensity": "active"}

8. **repeat** — Répétition d'un bloc
   {"type": "repeat", "back_to_offset": 1, "count": 6}
   → back_to_offset = index (0-based) du premier step du bloc à répéter

## Règles

- Les allures sont au format "MM:SS" (minutes:secondes par km), avec MM >= 1
- pace_fast < pace_slow (fast = plus rapide = allure plus basse en min/km)
- hr_low < hr_high
- Pour les intervalles : échauffement 2km + bloc effort/récup + repeat + retour calme 1km
- Intensités valides : warmup, active, recovery, cooldown
- Utilise des allures réalistes pour un coureur amateur-intermédiaire sauf indication contraire
- Le champ "description" doit être une explication claire de la séance en français

## Exemples

Texte : "10x400m en 1:30 avec 1min de récup"
→ échauffement 2km + 400m à ~3:45/km + 60s récup + repeat x10 + 1km retour calme

Texte : "Sortie longue 20km à 5:30/km"
→ 2km échauffement à 5:45-6:00 + 18km à 5:15-5:45

Texte : "45min en endurance fondamentale"
→ 10min échauffement + 35min à 5:30-6:00

Texte : "Seuil 3x2km à 4:30 récup 2min"
→ 2km échauffement + 2km à 4:20-4:40 + 2min récup + repeat x3 + 1km retour calme
"""


def text_to_structured(text: str, model: str | None = None,
                       temperature: float = 0.4,
                       llm_cfg: dict | None = None) -> dict:
    """Convertit un texte libre en structure de séance via LLM.

    Args:
        text: description textuelle de la séance
        model: override du modèle (ignoré si llm_cfg fourni)
        temperature: température du LLM
        llm_cfg: section "llm" du config.json (provider, model, etc.)

    Returns:
        dict avec name, description, steps
    """
    cfg = llm_cfg or {}
    if model and not llm_cfg:
        cfg["model"] = model
    client, resolved_model = get_llm_client(cfg)

    response = client.chat.completions.create(
        model=resolved_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content.strip()

    # Nettoyage : supprimer les blocs markdown si présents
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    result = json.loads(content)

    # Validation basique
    if "steps" not in result or not isinstance(result["steps"], list):
        raise ValueError("Le LLM n'a pas retourné de steps valides")

    if len(result["steps"]) == 0:
        raise ValueError("Le LLM a retourné une liste de steps vide")

    # Validation de chaque step
    for i, step in enumerate(result["steps"]):
        if "type" not in step:
            raise ValueError(f"Step {i} sans type")

    logger.info(f"LLM a généré {len(result['steps'])} steps pour: {text[:50]}...")
    return result


def planned_to_description(workout: dict) -> str:
    """Génère une description textuelle lisible d'une séance planifiée.

    Args:
        workout: dict de la séance planifiée

    Returns:
        Description en français
    """
    wtype = workout.get("type", "Séance")
    parts = [f"**{wtype}**"]

    if workout.get("distance_km"):
        parts.append(f"Distance : {workout['distance_km']} km")
    if workout.get("duration_min"):
        parts.append(f"Durée : {workout['duration_min']} min")
    if workout.get("allure"):
        parts.append(f"Allure cible : {workout['allure']}/km")

    if workout.get("reps"):
        parts.append(f"Intervalles : {workout['reps']}")
        if workout.get("allure_effort"):
            parts.append(f"Allure effort : {workout['allure_effort']}/km")
        if workout.get("recovery"):
            parts.append(f"Récupération : {workout['recovery']}")

    if workout.get("notes"):
        parts.append(f"Notes : {workout['notes']}")

    return "\n".join(parts)


def generate_description_from_text(text: str, model: str | None = None,
                                    temperature: float = 0.5,
                                    llm_cfg: dict | None = None) -> str:
    """Génère une description détaillée de séance à partir d'un texte court.

    Args:
        text: texte court décrivant la séance
        model: override du modèle (ignoré si llm_cfg fourni)
        temperature: température
        llm_cfg: section "llm" du config.json

    Returns:
        Description détaillée en français
    """
    cfg = llm_cfg or {}
    if model and not llm_cfg:
        cfg["model"] = model
    client, resolved_model = get_llm_client(cfg)

    response = client.chat.completions.create(
        model=resolved_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": (
                "Tu es un coach de course à pied. "
                "L'utilisateur te donne une description courte de séance. "
                "Génère une description détaillée et claire de la séance en français, "
                "avec les consignes d'allure, les objectifs, et les conseils pratiques. "
                "Sois concis mais précis. Pas de markdown, juste du texte brut."
            )},
            {"role": "user", "content": text},
        ],
    )

    return response.choices[0].message.content.strip()
