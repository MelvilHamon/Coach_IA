"""
gps_metrics.py — Extraction de métriques depuis les traces GPS Garmin.

Calcule depuis les coordonnées brutes {lat, lon, time_s, altitude_m} :
- Vitesse instantanée lissée (m/s et km/h)
- Distance cumulée (méthode haversine)
- Dénivelé positif/négatif (avec seuil de bruit)
- Allure instantanée (min/km)
- Métriques résumées : distance totale, D+, D-, vitesse moy/max, allure moy

Références :
- Haversine : Sinnott RW (1984). Virtues of the Haversine. Sky and Telescope.
- Lissage vitesse : Savitzky-Golay filter (scipy.signal.savgol_filter)
  fenêtre 11s, ordre 3 — bon compromis entre latence et suppression du bruit GPS.
"""

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter


# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points GPS."""
    R = 6_371_000  # rayon Terre en mètres
    φ1, φ2 = np.radians(lat1), np.radians(lat2)
    Δφ = np.radians(lat2 - lat1)
    Δλ = np.radians(lon2 - lon1)
    a = np.sin(Δφ / 2) ** 2 + np.cos(φ1) * np.cos(φ2) * np.sin(Δλ / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


# ── Distance cumulée ──────────────────────────────────────────────────────────

def compute_distances(points: list[dict]) -> np.ndarray:
    """
    Distance haversine entre chaque point consécutif, en mètres.

    Retourne un array de longueur len(points) (premier élément = 0).
    """
    n = len(points)
    if n == 0:
        return np.array([])

    dists = np.zeros(n)
    for i in range(1, n):
        p0, p1 = points[i - 1], points[i]
        try:
            dists[i] = _haversine(
                float(p0["lat"]), float(p0["lon"]),
                float(p1["lat"]), float(p1["lon"]),
            )
        except (KeyError, TypeError, ValueError):
            dists[i] = 0.0

    return dists


# ── Vitesse ───────────────────────────────────────────────────────────────────

def compute_speed(points: list[dict], smooth: bool = True) -> np.ndarray:
    """
    Vitesse instantanée en km/h.

    Calcul brut : distance haversine / Δtime_s entre points consécutifs.
    Les time_s=None sont interpolés linéairement depuis les voisins valides.
    Les spikes > 50 km/h (bruit GPS) sont clippés.
    Si smooth=True : Savitzky-Golay (window=11, polyorder=3) appliqué après.
    """
    n = len(points)
    if n < 2:
        return np.zeros(n)

    # Récupération et interpolation des time_s
    time_raw = [p.get("time_s") for p in points]
    times = pd.array(time_raw, dtype="Float64")
    times_series = pd.Series(times, dtype=float)
    times_interp = times_series.interpolate(method="linear", limit_direction="both").values

    dists = compute_distances(points)

    speeds_ms = np.zeros(n)
    for i in range(1, n):
        dt = times_interp[i] - times_interp[i - 1]
        if dt > 0:
            speeds_ms[i] = dists[i] / dt
        else:
            speeds_ms[i] = 0.0

    speeds_kmh = speeds_ms * 3.6

    # Clip des valeurs aberrantes
    speeds_kmh = np.clip(speeds_kmh, 0.0, 50.0)

    if smooth and n >= 11:
        # Longueur de fenêtre doit être impaire et ≤ n
        wl = min(11, n if n % 2 == 1 else n - 1)
        if wl >= 5:
            speeds_kmh = savgol_filter(speeds_kmh, window_length=wl, polyorder=3)
            speeds_kmh = np.clip(speeds_kmh, 0.0, 50.0)

    return speeds_kmh


# ── Dénivelé ─────────────────────────────────────────────────────────────────

def compute_elevation_metrics(
    points: list[dict],
    noise_threshold_m: float = 2.0,
) -> dict:
    """
    D+ et D- en mètres.

    Ne compte un gain/perte que si la variation dépasse noise_threshold_m
    (filtre le bruit altimétrique GPS qui génère du D+ fantôme).

    Retourne {"elevation_gain_m": float, "elevation_loss_m": float}.
    """
    alts = [p.get("altitude_m") for p in points]
    alts_valid = [a for a in alts if a is not None]
    if len(alts_valid) < 2:
        return {"elevation_gain_m": 0.0, "elevation_loss_m": 0.0}

    # Interpolation des None
    alt_series = pd.Series(
        [float(a) if a is not None else float("nan") for a in alts]
    )
    alt_interp = alt_series.interpolate(method="linear", limit_direction="both").values

    gain = 0.0
    loss = 0.0
    for i in range(1, len(alt_interp)):
        diff = alt_interp[i] - alt_interp[i - 1]
        if diff > noise_threshold_m:
            gain += diff
        elif diff < -noise_threshold_m:
            loss += abs(diff)

    return {
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
    }


# ── Allure ────────────────────────────────────────────────────────────────────

def compute_pace(speed_kmh: np.ndarray) -> np.ndarray:
    """
    Allure en secondes/km depuis la vitesse en km/h.

    Vitesse = 0 → NaN (évite les infinis).
    Clippé à 20 min/km max (1200 s/km).
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        pace = np.where(speed_kmh > 0, 3600.0 / speed_kmh, np.nan)

    pace = np.where(pace > 1200.0, np.nan, pace)
    return pace


# ── Résumé complet ────────────────────────────────────────────────────────────

def summarize_gps(points: list[dict]) -> dict:
    """
    Calcule toutes les métriques GPS depuis une liste de points bruts.

    Paramètres
    ----------
    points : liste de dicts {lat, lon, time_s, altitude_m}

    Retourne
    --------
    dict avec :
      distance_m, elevation_gain_m, elevation_loss_m, duration_s,
      avg_speed_kmh, max_speed_kmh, avg_pace_sec_km,
      speed_array, pace_array, distance_array, altitude_array
    """
    if not points:
        return {
            "distance_m": 0.0, "elevation_gain_m": 0.0, "elevation_loss_m": 0.0,
            "duration_s": 0.0, "avg_speed_kmh": 0.0, "max_speed_kmh": 0.0,
            "avg_pace_sec_km": float("nan"),
            "speed_array": [], "pace_array": [], "distance_array": [],
            "altitude_array": [],
        }

    dists   = compute_distances(points)
    speeds  = compute_speed(points, smooth=True)
    elev    = compute_elevation_metrics(points)
    pace    = compute_pace(speeds)

    dist_cumul = np.cumsum(dists)
    total_dist = float(dist_cumul[-1])

    # Durée
    times_valid = [p["time_s"] for p in points if p.get("time_s") is not None]
    if len(times_valid) >= 2:
        duration_s = float(times_valid[-1] - times_valid[0])
    else:
        duration_s = 0.0

    # Vitesse moy (points où vitesse > 0, pour ne pas biaiser avec les arrêts)
    moving = speeds[speeds > 0]
    avg_speed = float(moving.mean()) if len(moving) > 0 else 0.0
    max_speed = float(speeds.max())

    # Allure moy (valeurs finies uniquement)
    pace_finite = pace[np.isfinite(pace)]
    avg_pace = float(pace_finite.mean()) if len(pace_finite) > 0 else float("nan")

    # Altitude brute par point
    altitude_array = [p.get("altitude_m") for p in points]

    return {
        "distance_m":       round(total_dist, 1),
        "elevation_gain_m": elev["elevation_gain_m"],
        "elevation_loss_m": elev["elevation_loss_m"],
        "duration_s":       round(duration_s, 1),
        "avg_speed_kmh":    round(avg_speed, 2),
        "max_speed_kmh":    round(max_speed, 2),
        "avg_pace_sec_km":  round(avg_pace, 1) if not np.isnan(avg_pace) else float("nan"),
        "speed_array":      speeds.tolist(),
        "pace_array":       [float(v) if np.isfinite(v) else None for v in pace],
        "distance_array":   dist_cumul.tolist(),
        "altitude_array":   altitude_array,
    }


# ── Comparaison GPS ↔ Strava ──────────────────────────────────────────────────

def compare_with_strava(gps_summary: dict, strava_row: "pd.Series") -> dict:
    """
    Compare les métriques GPS calculées avec celles de Strava.

    Permet de valider la qualité du matching et détecter les écarts.

    match_quality :
      "excellent"   : distance diff < 2 %, durée diff < 30 s
      "bon"         : distance diff < 5 %, durée diff < 60 s
      "approximatif": distance diff < 10 %
      "suspect"     : au-delà

    Retourne
    --------
    dict {distance_diff_pct, duration_diff_s, elevation_diff_m, match_quality}
    """
    try:
        strava_dist_m = float(strava_row.get("Distance (km)", 0) or 0) * 1000.0
        strava_dur_s  = float(strava_row.get("Temps (min)", 0) or 0) * 60.0
        strava_elev_m = float(strava_row.get("Dénivelé (m)", 0) or 0)
    except (TypeError, ValueError):
        return {
            "distance_diff_pct": float("nan"),
            "duration_diff_s":   float("nan"),
            "elevation_diff_m":  float("nan"),
            "match_quality":     "inconnu",
        }

    gps_dist = gps_summary.get("distance_m", 0.0) or 0.0
    gps_dur  = gps_summary.get("duration_s", 0.0) or 0.0
    gps_elev = gps_summary.get("elevation_gain_m", 0.0) or 0.0

    dist_diff_pct = (
        (gps_dist - strava_dist_m) / strava_dist_m * 100
        if strava_dist_m > 0 else float("nan")
    )
    dur_diff_s   = gps_dur - strava_dur_s
    elev_diff_m  = gps_elev - strava_elev_m

    abs_dist = abs(dist_diff_pct) if not np.isnan(dist_diff_pct) else 999
    abs_dur  = abs(dur_diff_s)

    if abs_dist < 2 and abs_dur < 30:
        quality = "excellent"
    elif abs_dist < 5 and abs_dur < 60:
        quality = "bon"
    elif abs_dist < 10:
        quality = "approximatif"
    else:
        quality = "suspect"

    return {
        "distance_diff_pct": round(dist_diff_pct, 2) if not np.isnan(dist_diff_pct) else float("nan"),
        "duration_diff_s":   round(dur_diff_s, 1),
        "elevation_diff_m":  round(elev_diff_m, 1),
        "match_quality":     quality,
    }
