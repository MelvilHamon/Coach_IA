"""
session_classifier.py — Détection automatique du type de séance.

Hiérarchie de classification :
  1. Sport non-running (Soccer, Hike, Workout…) → type brut Strava
  2. Trail : sport_type == 'TrailRun' OU D+/km > seuil config
  3. Fractionné : stream disponible + detect_fract_v2 détecte des patterns
  4. Récupération active : durée courte + FC basse
  5. Sortie longue : distance > seuil
  6. Tempo/seuil : FC moyenne > 80 % FC_max
  7. Endurance fondamentale : défaut pour les runs

Types de fractionné possibles (retournés par detect_fract_v2) :
  - 'fractionné court'               : blocs < 500 m, 3+ répétitions identiques
  - 'fractionné moyen'               : blocs 500–1200 m, 3+ répétitions identiques
  - 'fractionné long'                : blocs 1200–2500 m, 3+ répétitions identiques
  - 'mixte'                          : plusieurs séries de distances très différentes
  - 'tempo / allure'                 : bloc(s) > 2500 m
  - 'fractionné pyramide symétrique' : durées croissantes puis décroissantes (ou inversement)
  - 'fractionné pyramide ascendante' : durées strictement croissantes
  - 'fractionné pyramide descendante': durées strictement décroissantes
"""

import os
import sys

import warnings

import numpy as np
import pandas as pd

# Ajout du répertoire analyse/ au path pour l'import relatif
_ANALYSE_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANALYSE_DIR not in sys.path:
    sys.path.insert(0, _ANALYSE_DIR)

from detect_fract_v2 import analyze_fractionne
from sport_mapping import get_sport


# Types d'activité Strava qui ne sont pas de la course à pied ni du vélo
_NON_SPORT_TYPES = {"Soccer", "Workout", "WeightTraining", "Yoga", "Crossfit",
                    "RockClimbing", "Swim", "Walk"}


def detect_session_type(
    activity_row: pd.Series,
    stream_path: str | None = None,
    config: dict | None = None,
) -> str:
    """
    Classifie automatiquement le type de séance.

    Paramètres
    ----------
    activity_row : ligne du CSV des activités (avec colonnes standard)
    stream_path  : chemin vers le CSV du stream (optionnel)
    config       : dict chargé depuis config.json (optionnel, utilise les défauts si absent)

    Retourne
    --------
    str parmi :
        'fractionné court', 'fractionné moyen', 'fractionné long',
        'tempo / allure', 'endurance fondamentale', 'sortie longue',
        'trail', 'récupération active', 'randonnée', 'autre'
    """
    cfg = config or {}
    athlete_cfg  = cfg.get("athlete", {})
    sess_cfg     = cfg.get("session_classifier", {})
    speed_profile = cfg.get("athlete_speed_profile", {})
    det_cfg      = cfg.get("detection_fractionne", {})

    hr_max         = athlete_cfg.get("hr_max", 195)
    long_run_km    = athlete_cfg.get("long_run_threshold_km", 15.0)
    trail_elev_km  = athlete_cfg.get("trail_elevation_per_km", 30.0)
    recov_max_dur  = sess_cfg.get("recovery_max_duration_min", 35)
    recov_max_hrp  = sess_cfg.get("recovery_max_hr_pct", 0.68)
    tempo_z34_pct  = sess_cfg.get("tempo_z34_min_pct", 0.40)

    sport_type   = str(activity_row.get("Type", "Run"))
    sport        = get_sport(sport_type)
    distance_km  = float(activity_row.get("Distance (km)", 0) or 0)
    duration_min = float(activity_row.get("Temps (min)", 0) or 0)
    elevation_m  = float(activity_row.get("Dénivelé (m)", 0) or 0)
    hr_mean_raw  = activity_row.get("Fréquence cardiaque (bpm)")
    hr_mean      = float(hr_mean_raw) if hr_mean_raw and not (isinstance(hr_mean_raw, float) and np.isnan(hr_mean_raw)) else None

    # ── 1. Activités non-sport (ni run, ni vélo) ─────────────────────────────
    if sport_type == "Hike":
        return "randonnée"
    if sport_type in _NON_SPORT_TYPES:
        return "autre"

    # ── 2. Classification VÉLO ───────────────────────────────────────────────
    if sport == "velo":
        return _classify_velo(
            distance_km=distance_km,
            duration_min=duration_min,
            elevation_m=elevation_m,
            hr_mean=hr_mean,
            hr_max=hr_max,
            config=cfg,
        )

    # ── 3. Trail (running uniquement) ────────────────────────────────────────
    if sport_type == "TrailRun":
        return "trail"
    if distance_km > 0:
        elev_per_km = elevation_m / distance_km
        if elev_per_km >= trail_elev_km:
            return "trail"

    # ── 4. Fractionné (détection via stream) ─────────────────────────────────
    min_effort_spd = float(speed_profile.get("p75_kmh", 0.0))
    athlete_mean_spd = float(speed_profile.get("mean_kmh", 0.0))

    # Résoudre max_block_cv depuis la config utilisateur (pas la config racine)
    if sport_type == "TrailRun":
        _max_blk_cv = det_cfg.get("max_block_cv_trail", None)
    else:
        _max_blk_cv = det_cfg.get("max_block_cv_run", None)
    _max_recup_cv = det_cfg.get("max_recup_cv", None)

    if stream_path and os.path.exists(stream_path):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                result = analyze_fractionne(
                    stream_path, verbose=False,
                    sport_type=sport_type,
                    min_effort_speed_kmh=min_effort_spd,
                    athlete_mean_speed_kmh=athlete_mean_spd,
                    max_block_cv=_max_blk_cv,
                    max_recup_cv=_max_recup_cv,
                )
            if result.get("is_fractionne"):
                return result.get("session_type", "fractionné")
        except Exception:
            pass  # en cas d'erreur de parsing, on continue avec les règles suivantes

    # ── 5. Récupération active ────────────────────────────────────────────────
    if hr_mean and duration_min > 0:
        if duration_min < recov_max_dur and hr_mean < hr_max * recov_max_hrp:
            return "récupération active"
    elif duration_min > 0 and duration_min < recov_max_dur and distance_km < 6:
        # Pas de FC mais courte sortie légère
        return "récupération active"

    # ── 6. Sortie longue ──────────────────────────────────────────────────────
    if distance_km >= long_run_km:
        return "sortie longue"

    # ── 7. Tempo / seuil (basé sur FC moyenne) ───────────────────────────────
    if hr_mean:
        hr_pct = hr_mean / hr_max
        if hr_pct >= 0.80:
            return "tempo / seuil"

    # ── 8. Endurance fondamentale (défaut pour tout run) ──────────────────────
    return "endurance fondamentale"


def _classify_velo(
    distance_km: float,
    duration_min: float,
    elevation_m: float,
    hr_mean: float | None,
    hr_max: int,
    config: dict,
) -> str:
    """
    Classification des séances vélo.

    Hiérarchie :
      1. Récupération vélo : durée courte + FC basse
      2. Sortie longue vélo : distance ≥ seuil (défaut 60 km)
      3. Tempo vélo : FC ≥ 80% FC_max
      4. Endurance vélo : défaut
    """
    velo_cfg = config.get("velo_classifier", {})
    long_ride_km = velo_cfg.get("long_ride_threshold_km", 60.0)
    recov_max_dur = velo_cfg.get("recovery_max_duration_min", 45)
    recov_max_hrp = velo_cfg.get("recovery_max_hr_pct", 0.65)

    # Récupération vélo
    if hr_mean and duration_min > 0:
        if duration_min < recov_max_dur and hr_mean < hr_max * recov_max_hrp:
            return "récupération vélo"
    elif duration_min > 0 and duration_min < recov_max_dur and distance_km < 15:
        return "récupération vélo"

    # Sortie longue vélo
    if distance_km >= long_ride_km:
        return "sortie longue vélo"

    # Tempo vélo (FC élevée)
    if hr_mean:
        hr_pct = hr_mean / hr_max
        if hr_pct >= 0.80:
            return "tempo vélo"

    # Endurance vélo (défaut)
    return "endurance vélo"
