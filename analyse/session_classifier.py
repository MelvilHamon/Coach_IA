"""
session_classifier.py — Détection automatique du type de séance.

Hiérarchie de classification :
  1. Sport non-running (Soccer, Hike, Workout…) → type brut Strava
  2. Trail : sport_type == 'TrailRun' OU D+/km > seuil config
  3. Fractionné : stream disponible + detect_fract_v2 détecte des patterns
  4. Tempo/seuil (allure) : vitesse moyenne ≥ p80 athlète ET durée ≥ 15 min
  5. Récupération active : durée courte + FC basse
  6. Sortie longue : distance > seuil
  7. Tempo/seuil (FC) : FC moyenne > 80 % FC_max
  8. Endurance fondamentale : défaut pour les runs

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

from detect_fract_v2 import analyze_fractionne, _read_stream_csv, detect_sprints
from detect_fract_velo import analyze_fractionne_velo
from sport_mapping import get_sport


def _compute_active_avgs(
    stream_path: str,
    walk_threshold_kmh: float = 6.0,
) -> tuple[float, float | None, float] | None:
    """
    Recalcule allure moyenne et FC moyenne en excluant les samples de marche/arrêt
    (speed < walk_threshold_kmh). Sert à corriger les classifications biaisées
    par des pauses marche au milieu d'une séance.

    Retourne (avg_spd_active_kmh, avg_hr_active_or_None, active_ratio) ou None
    si stream illisible. active_ratio = part du temps total au-dessus du seuil.
    """
    try:
        df = _read_stream_csv(stream_path)
        if "speed_kmh" not in df.columns or len(df) < 30:
            return None
        spd = df["speed_kmh"].ffill().values
        mask = spd >= walk_threshold_kmh
        active_ratio = float(mask.mean()) if len(mask) else 0.0
        if not mask.any():
            return (0.0, None, 0.0)
        avg_spd_active = float(spd[mask].mean())
        avg_hr_active: float | None = None
        if "bpm" in df.columns:
            bpm = df["bpm"].ffill().values
            valid = mask & np.isfinite(bpm) & (bpm > 0)
            if valid.any():
                avg_hr_active = float(bpm[valid].mean())
        return (avg_spd_active, avg_hr_active, active_ratio)
    except Exception:
        return None

# storage : abstraction R2/local. Les streams vivent dans R2 en prod, sur le
# filesystem local en dev. os.path.exists ne sait pas voir R2, d'où l'usage
# de storage.exists pour les checks de présence de stream.
try:
    from api import storage as _storage
except Exception:
    _storage = None


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
            stream_path=stream_path,
        )

    # ── 3. Outlier : "Run" Strava à allure de marche (< 4 km/h ~ > 15 min/km)
    # Probable marche, randonnée mal taggée, ou pause technique. On les classe
    # en "autre" pour les sortir des agrégats running (profil vitesse,
    # progression, ACWR running). L'activité reste visible dans l'historique.
    if distance_km > 0 and duration_min > 0:
        avg_spd_kmh = (distance_km / duration_min) * 60.0
        if avg_spd_kmh < 4.0:
            return "autre"

    # ── 4. Trail (running uniquement) ────────────────────────────────────────
    if sport_type == "TrailRun":
        return "trail"
    if distance_km > 0:
        elev_per_km = elevation_m / distance_km
        if elev_per_km >= trail_elev_km:
            return "trail"

    # ── 4. Fractionné (détection via stream) ─────────────────────────────────
    athlete_mean_spd = float(speed_profile.get("mean_kmh", 0.0))
    # Pour les profils lents (< ~10.5 km/h), la distribution de vitesses est
    # resserrée : le p75 est très proche de la moyenne, ce qui rend le critère
    # de vitesse absolue trop strict. On utilise alors p70 comme plancher.
    if athlete_mean_spd > 0 and athlete_mean_spd < 10.5:
        min_effort_spd = float(speed_profile.get("p70_kmh", 0.0))
    else:
        min_effort_spd = float(speed_profile.get("p75_kmh", 0.0))

    # Résoudre max_block_cv depuis la config utilisateur (pas la config racine)
    if sport_type == "TrailRun":
        _max_blk_cv = det_cfg.get("max_block_cv_trail", None)
    else:
        _max_blk_cv = det_cfg.get("max_block_cv_run", None)
    _max_recup_cv = det_cfg.get("max_recup_cv", None)

    if stream_path and (_storage.exists(stream_path) if _storage else os.path.exists(stream_path)):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                result = analyze_fractionne(
                    stream_path, verbose=False,
                    sport_type=sport_type,
                    min_effort_speed_kmh=min_effort_spd,
                    athlete_mean_speed_kmh=athlete_mean_spd,
                    hr_max=float(hr_max),
                    athlete_speed_profile=speed_profile,
                    max_block_cv=_max_blk_cv,
                    max_recup_cv=_max_recup_cv,
                )
            if result.get("is_fractionne"):
                return result.get("session_type", "fractionné")
        except Exception:
            pass  # en cas d'erreur de parsing, on continue avec les règles suivantes

        # Fallback sprint : pics courts (2-30s) très violents que le pipeline
        # fractionné rate à cause de min_effort_s=15s et du lissage sigma=3.
        # Pas appliqué au trail (faux positifs sur descentes).
        if sport_type != "TrailRun":
            try:
                sprint_res = detect_sprints(stream_path)
                if sprint_res.get("is_sprint"):
                    return sprint_res.get("session_type", "fractionné sprint")
            except Exception:
                pass

    # Allure et FC "actives" : moyennes calculées sur le temps en mouvement
    # (speed >= 6 km/h), pour corriger les séances diluées par de la marche
    # ou des arrêts (FC et allure moyennes brutes sous-estiment alors l'effort).
    # Garde-fou : ne s'applique que si >= 60% du temps est actif.
    avg_spd_active = None
    avg_hr_active = None
    active_ratio = 1.0
    if stream_path and (_storage.exists(stream_path) if _storage else os.path.exists(stream_path)):
        active = _compute_active_avgs(stream_path)
        if active is not None and active[2] >= 0.60:
            avg_spd_active = active[0]
            avg_hr_active = active[1]
            active_ratio = active[2]

    # ── 5. Tempo/seuil basé sur l'allure (avant récup pour éviter les
    #      faux positifs récup à FC basse chez les profils à hr_max élevé ou
    #      mal calibré). Rattrape les cas où la FC moyenne ne franchit pas
    #      80% hr_max parce que le profil FC est imprécis ou que l'athlète
    #      ne pousse pas en FC alors que l'allure est clairement tempo.
    p80_kmh = float(speed_profile.get("p80_kmh", 0.0))
    if p80_kmh > 0 and distance_km >= 5 and duration_min >= 15:
        avg_spd_kmh = (distance_km / duration_min) * 60.0
        if avg_spd_kmh >= p80_kmh:
            return "tempo / seuil"
        if avg_spd_active is not None:
            # Tolérance de 2% uniquement si >5% du temps a été en marche/arrêt :
            # signal qu'il y a un vrai biais à corriger. Sinon p80 strict.
            tol = 0.98 if active_ratio < 0.95 else 1.0
            if avg_spd_active >= p80_kmh * tol:
                return "tempo / seuil"

    # ── 6. Récupération active ────────────────────────────────────────────────
    if hr_mean and duration_min > 0:
        if duration_min < recov_max_dur and hr_mean < hr_max * recov_max_hrp:
            return "récupération active"
    elif duration_min > 0 and duration_min < recov_max_dur and distance_km < 6:
        # Pas de FC mais courte sortie légère
        return "récupération active"

    # ── 6bis. Tempo/seuil par FC active : on teste AVANT sortie longue
    #         car une FC moyenne tirée vers le bas par des phases de marche
    #         doit pouvoir basculer en tempo. La FC active est un signal fort.
    if avg_hr_active is not None and avg_hr_active / hr_max >= 0.80:
        return "tempo / seuil"

    # ── 7. Sortie longue ──────────────────────────────────────────────────────
    if distance_km >= long_run_km:
        return "sortie longue"

    # ── 8. Tempo / seuil (basé sur FC moyenne) ───────────────────────────────
    if hr_mean:
        hr_pct = hr_mean / hr_max
        if hr_pct >= 0.80:
            return "tempo / seuil"

    # ── 9. Endurance fondamentale (défaut pour tout run) ──────────────────────
    return "endurance fondamentale"


def _classify_velo(
    distance_km: float,
    duration_min: float,
    elevation_m: float,
    hr_mean: float | None,
    hr_max: int,
    config: dict,
    stream_path: str | None = None,
) -> str:
    """
    Classification des séances vélo.

    Hiérarchie :
      1. Intervalles vélo : detect_fract_velo (mode power si capteur, sinon
         fallback vitesse + FC, tolérant aux faux positifs)
      2. Récupération vélo : durée courte + FC basse
      3. Sortie longue vélo : distance ≥ seuil (défaut 60 km)
      4. Tempo vélo : FC ≥ 80% FC_max
      5. Endurance vélo : défaut
    """
    velo_cfg = config.get("velo_classifier", {})
    long_ride_km = velo_cfg.get("long_ride_threshold_km", 60.0)
    recov_max_dur = velo_cfg.get("recovery_max_duration_min", 45)
    recov_max_hrp = velo_cfg.get("recovery_max_hr_pct", 0.65)

    # Intervalles vélo (détection via stream)
    if stream_path and (_storage.exists(stream_path) if _storage else os.path.exists(stream_path)):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                result = analyze_fractionne_velo(
                    stream_path,
                    verbose=False,
                    config=config.get("detection_fractionne_velo", {}),
                )
            if result.get("is_fractionne"):
                return "intervalles vélo"
        except Exception:
            pass  # parsing/sklearn error → on continue avec les règles suivantes

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
