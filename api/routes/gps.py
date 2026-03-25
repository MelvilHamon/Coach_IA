"""
api/routes/gps.py — Endpoints GPS et métriques GPS à la volée.
"""

from fastapi import APIRouter

import json
import os

from api.deps import get_gps_points, nan_safe, GARMIN_STREAMS

router = APIRouter(prefix="/api/gps", tags=["gps"])


@router.get("/{activity_id}")
def get_gps(activity_id: int):
    """
    Points GPS + métriques calculées à la volée via gps_metrics.summarize_gps().
    Retourne les points (lat, lon, time_s, altitude_m) et les métriques scalaires.
    """
    gps_data = get_gps_points(activity_id)
    if not gps_data:
        return {"error": "no_gps", "points": [], "metrics": None}

    points = gps_data.get("points", [])
    if not points:
        return {"error": "empty_points", "points": [], "metrics": None}

    # Métriques GPS à la volée
    try:
        from gps_metrics import summarize_gps
        summary = summarize_gps(points)

        # Séparer scalaires et arrays
        _ARRAY_KEYS = {"speed_array", "pace_array", "distance_array", "altitude_array"}
        metrics = nan_safe({k: v for k, v in summary.items() if k not in _ARRAY_KEYS})
    except Exception:
        metrics = None

    # Points compacts pour la carte (on garde lat, lon, time_s, altitude_m)
    compact_points = []
    for p in points:
        cp = {"lat": p.get("lat"), "lon": p.get("lon")}
        if "time_s" in p:
            cp["time_s"] = p["time_s"]
        if "altitude_m" in p:
            cp["altitude_m"] = p["altitude_m"]
        compact_points.append(cp)

    return {
        "activity_id": activity_id,
        "source":      gps_data.get("source"),
        "garmin_id":   gps_data.get("garmin_id"),
        "strava_id":   gps_data.get("strava_id"),
        "n_points":    len(compact_points),
        "points":      compact_points,
        "metrics":     metrics,
    }


@router.get("/{activity_id}/speed")
def get_gps_speed(activity_id: int):
    """Array de vitesse lissée (Savitzky-Golay) depuis les points GPS."""
    gps_data = get_gps_points(activity_id)
    if not gps_data or not gps_data.get("points"):
        return {"error": "no_gps", "speed": [], "distance": []}

    try:
        import numpy as np
        from gps_metrics import compute_speed, compute_distances
        points = gps_data["points"]
        speed = compute_speed(points, smooth=True)
        distances = np.cumsum(compute_distances(points))
        return nan_safe({
            "speed_kmh":   speed.tolist(),
            "distance_m":  distances.tolist(),
        })
    except Exception as e:
        return {"error": str(e), "speed": [], "distance": []}


@router.get("/{activity_id}/altitude")
def get_gps_altitude(activity_id: int):
    """Array d'altitude depuis les points GPS ou le stream Garmin."""
    gps_data = get_gps_points(activity_id)
    if not gps_data or not gps_data.get("points"):
        return {"error": "no_gps", "altitude": [], "distance": []}

    points = gps_data["points"]

    # Si les points n'ont pas d'altitude, chercher dans le stream Garmin
    if all(p.get("altitude_m") is None for p in points):
        garmin_id = gps_data.get("garmin_id")
        if garmin_id:
            garmin_path = os.path.join(GARMIN_STREAMS, f"{garmin_id}.json")
            if os.path.exists(garmin_path):
                try:
                    with open(garmin_path, encoding="utf-8") as f:
                        garmin_data = json.load(f)
                    garmin_pts = garmin_data.get("points", [])
                    if garmin_pts and any(p.get("altitude_m") is not None for p in garmin_pts):
                        points = garmin_pts
                except (json.JSONDecodeError, OSError):
                    pass

    try:
        import numpy as np
        from gps_metrics import compute_distances
        distances = np.cumsum(compute_distances(points))
        altitudes = [p.get("altitude_m") for p in points]

        # Si aucun point n'a d'altitude
        if all(a is None for a in altitudes):
            return {"error": "no_altitude", "altitude": [], "distance": []}

        return nan_safe({
            "altitude_m":  altitudes,
            "distance_m":  distances.tolist(),
        })
    except Exception as e:
        return {"error": str(e), "altitude": [], "distance": []}


@router.get("/{activity_id}/gap")
def get_gps_gap(activity_id: int):
    """Gradient Adjusted Pace depuis les points GPS + altitude."""
    gps_data = get_gps_points(activity_id)
    if not gps_data or not gps_data.get("points"):
        return {"error": "no_gps"}

    points = gps_data["points"]

    # Si pas d'altitude dans les points, tenter le stream Garmin
    if all(p.get("altitude_m") is None for p in points):
        garmin_id = gps_data.get("garmin_id")
        if garmin_id:
            garmin_path = os.path.join(GARMIN_STREAMS, f"{garmin_id}.json")
            if os.path.exists(garmin_path):
                try:
                    with open(garmin_path, encoding="utf-8") as f:
                        garmin_data = json.load(f)
                    garmin_pts = garmin_data.get("points", [])
                    if garmin_pts and any(p.get("altitude_m") is not None for p in garmin_pts):
                        points = garmin_pts
                except (json.JSONDecodeError, OSError):
                    pass

    try:
        from metrics import compute_gap
        result = compute_gap(points)
        return nan_safe(result)
    except Exception as e:
        return {"error": str(e)}
