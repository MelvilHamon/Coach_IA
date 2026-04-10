"""
api/routes/gps.py — Endpoints GPS et métriques GPS à la volée.
"""

from fastapi import APIRouter, Depends

import json
import os

from api.deps import get_gps_points, get_stream, nan_safe, GARMIN_STREAMS
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/gps", tags=["gps"])


@router.get("/{activity_id}")
def get_gps(activity_id: int, user: dict = Depends(get_current_user)):
    """
    Points GPS + métriques calculées à la volée via gps_metrics.summarize_gps().
    Retourne les points (lat, lon, time_s, altitude_m) et les métriques scalaires.
    """
    gps_data = get_gps_points(activity_id, user["id"])
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
def get_gps_speed(activity_id: int, user: dict = Depends(get_current_user)):
    """Array de vitesse lissée (Savitzky-Golay) depuis les points GPS, fallback stream."""
    gps_data = get_gps_points(activity_id, user["id"])
    if gps_data and gps_data.get("points"):
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
        except Exception:
            pass

    # Fallback: use Strava stream if available
    stream_df = get_stream(activity_id, user["id"])
    if stream_df is not None and "speed_kmh" in stream_df.columns:
        import numpy as np
        df = stream_df.dropna(subset=["speed_kmh"]).copy()
        if not df.empty:
            time_s = df["time_s"].values
            speed_kmh = df["speed_kmh"].values
            speed_ms = np.nan_to_num(speed_kmh, nan=0.0) / 3.6
            dt = np.diff(time_s, prepend=time_s[0])
            dt[0] = 0
            dist_m = np.cumsum(speed_ms * dt)
            return nan_safe({
                "speed_kmh":   speed_kmh.tolist(),
                "distance_m":  dist_m.tolist(),
            })

    return {"error": "no_gps", "speed_kmh": [], "distance_m": []}


@router.get("/{activity_id}/altitude")
def get_gps_altitude(activity_id: int, user: dict = Depends(get_current_user)):
    """Array d'altitude depuis les points GPS, stream Garmin, ou stream Strava."""
    gps_data = get_gps_points(activity_id, user["id"])
    if gps_data and gps_data.get("points"):
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

            if not all(a is None for a in altitudes):
                return nan_safe({
                    "altitude_m":  altitudes,
                    "distance_m":  distances.tolist(),
                })
        except Exception:
            pass

    # Fallback: use Strava stream if available
    stream_df = get_stream(activity_id, user["id"])
    if stream_df is not None and "altitude_m" in stream_df.columns:
        import numpy as np
        df = stream_df.dropna(subset=["altitude_m"]).copy()
        if not df.empty:
            time_s = df["time_s"].values
            speed_kmh = df["speed_kmh"].values if "speed_kmh" in df.columns else None
            if speed_kmh is not None:
                speed_ms = np.nan_to_num(speed_kmh, nan=0.0) / 3.6
                dt = np.diff(time_s, prepend=time_s[0])
                dt[0] = 0
                dist_m = np.cumsum(speed_ms * dt)
            else:
                dist_m = np.linspace(0, 1000, len(df))
            return nan_safe({
                "altitude_m":  df["altitude_m"].tolist(),
                "distance_m":  dist_m.tolist(),
            })

    return {"error": "no_altitude", "altitude_m": [], "distance_m": []}


@router.get("/{activity_id}/gap")
def get_gps_gap(activity_id: int, user: dict = Depends(get_current_user)):
    """Gradient Adjusted Pace depuis les points GPS + altitude."""
    gps_data = get_gps_points(activity_id, user["id"])
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
        import logging
        logging.getLogger("coachagent").error("GAP computation failed: %s", e)
        return {"error": "Erreur lors du calcul GAP."}


@router.get("/{activity_id}/splits")
def get_gps_splits(activity_id: int, user: dict = Depends(get_current_user)):
    """Allure (min/km) par kilomètre entier depuis les points GPS ou stream."""
    import numpy as np

    cum_dist = None
    speed = None

    # Try GPS points first
    gps_data = get_gps_points(activity_id, user["id"])
    if gps_data and gps_data.get("points"):
        try:
            from gps_metrics import compute_distances, compute_speed
            points = gps_data["points"]
            cum_dist = np.cumsum(compute_distances(points))
            speed = compute_speed(points, smooth=True)
        except Exception:
            pass

    # Fallback: use Strava stream
    if cum_dist is None or speed is None:
        stream_df = get_stream(activity_id, user["id"])
        if stream_df is not None and "speed_kmh" in stream_df.columns:
            df = stream_df.dropna(subset=["speed_kmh"]).copy()
            if not df.empty:
                time_s = df["time_s"].values
                speed_kmh = df["speed_kmh"].values
                speed_ms = np.nan_to_num(speed_kmh, nan=0.0) / 3.6
                dt = np.diff(time_s, prepend=time_s[0])
                dt[0] = 0
                cum_dist = np.cumsum(speed_ms * dt)
                speed = speed_kmh

    if cum_dist is None or speed is None or len(cum_dist) == 0:
        return {"error": "no_data", "splits": []}

    try:
        total_km = int(cum_dist[-1] / 1000)
        if total_km < 1:
            return {"error": "too_short", "splits": []}

        splits = []
        for km in range(1, total_km + 1):
            lo = (km - 1) * 1000
            hi = km * 1000
            mask = (cum_dist >= lo) & (cum_dist < hi)
            seg_speed = speed[mask]
            seg_speed = seg_speed[seg_speed > 0.5]
            if len(seg_speed) == 0:
                continue
            avg_speed_kmh = float(np.mean(seg_speed))
            pace_s = 3600.0 / avg_speed_kmh
            pace_min = int(pace_s // 60)
            pace_sec = int(pace_s % 60)
            splits.append({
                "km": km,
                "pace_s_per_km": round(pace_s, 1),
                "pace_display": f"{pace_min}:{pace_sec:02d}",
                "avg_speed_kmh": round(avg_speed_kmh, 2),
            })

        return nan_safe({"splits": splits, "total_km": total_km})
    except Exception as e:
        import logging
        logging.getLogger("coachagent").error("Splits computation failed: %s", e)
        return {"error": "Erreur lors du calcul des splits.", "splits": []}


@router.get("/{activity_id}/session-analysis")
def get_session_analysis(activity_id: int, user: dict = Depends(get_current_user)):
    """Analyse détaillée de la séance (fractionné, tempo/seuil) via detect_fract_v2."""
    stream_df = get_stream(activity_id, user["id"])
    if stream_df is None:
        return {"error": "no_stream", "patterns": [], "session_type": None}

    # Write stream to a temp file for analyze_fractionne (expects a path)
    import tempfile
    import json as _json
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    try:
        stream_df.to_csv(tmp.name, index=False)
        tmp.close()

        from detect_fract_v2 import analyze_fractionne
        result = analyze_fractionne(tmp.name, verbose=False)

        patterns = result.get("patterns", [])
        session_type = result.get("session_type")
        is_frac = result.get("is_fractionne", False)

        return nan_safe({
            "activity_id": activity_id,
            "is_fractionne": is_frac,
            "session_type": session_type,
            "patterns": patterns,
            "cv_speed": result.get("cv_speed"),
            "ef_ratio": result.get("ef_ratio"),
        })
    except Exception as e:
        import logging
        logging.getLogger("coachagent").error("Session analysis failed: %s", e)
        return {"error": str(e), "patterns": [], "session_type": None}
    finally:
        os.unlink(tmp.name)


@router.get("/{activity_id}/bpm")
def get_gps_bpm(activity_id: int, user: dict = Depends(get_current_user)):
    """BPM aligné sur la distance (km) depuis le stream Strava."""
    stream_df = get_stream(activity_id, user["id"])
    if stream_df is None or "bpm" not in stream_df.columns:
        return {"error": "no_bpm", "bpm": [], "distance_m": []}

    import numpy as np

    df = stream_df.dropna(subset=["bpm"]).copy()
    if df.empty:
        return {"error": "no_bpm", "bpm": [], "distance_m": []}

    time_s = df["time_s"].values
    speed_kmh = df["speed_kmh"].values if "speed_kmh" in df.columns else None

    if speed_kmh is not None:
        speed_ms = np.nan_to_num(speed_kmh, nan=0.0) / 3.6
        dt = np.diff(time_s, prepend=time_s[0])
        dt[0] = 0
        dist_m = np.cumsum(speed_ms * dt)
    else:
        # Fallback: linear spacing
        dist_m = np.linspace(0, 1000, len(df))

    return nan_safe({
        "bpm":        df["bpm"].tolist(),
        "distance_m": dist_m.tolist(),
    })


@router.get("/{activity_id}/power")
def get_gps_power(activity_id: int, user: dict = Depends(get_current_user)):
    """Puissance (watts) alignée sur la distance (km) depuis le stream Strava."""
    stream_df = get_stream(activity_id, user["id"])
    if stream_df is None or "power_w" not in stream_df.columns:
        return {"error": "no_power", "power_w": [], "distance_m": []}

    import numpy as np

    df = stream_df.dropna(subset=["power_w"]).copy()
    if df.empty:
        return {"error": "no_power", "power_w": [], "distance_m": []}

    time_s = df["time_s"].values
    speed_kmh = df["speed_kmh"].values if "speed_kmh" in df.columns else None

    if speed_kmh is not None:
        speed_ms = np.nan_to_num(speed_kmh, nan=0.0) / 3.6
        dt = np.diff(time_s, prepend=time_s[0])
        dt[0] = 0
        dist_m = np.cumsum(speed_ms * dt)
    else:
        dist_m = np.linspace(0, 1000, len(df))

    return nan_safe({
        "power_w":    df["power_w"].tolist(),
        "distance_m": dist_m.tolist(),
    })
