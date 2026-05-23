"""
track_metrics.py — Calcule les métriques piste pour chaque activité matchée
par detect_stadium.py.

Pour chaque match dans data/stadium_matches.json, si la longueur de piste
est connue :
  - filtrer les points GPS à l'intérieur du stade (r = 120 m)
  - détecter les tours par retour près du point de départ
  - calculer splits, meilleur tour, régularité, meilleurs N tours consécutifs,
    sens de course
  - écrire data/track_sessions/{strava_id}.json

Une séance peut contenir des pauses (fractionné avec récup) : les "tours"
détectés sont alors des reps. Le champ `pause_before_s` permet de
distinguer un tour continu d'une rep après pause.
"""

import json
import math
import os
import sys
from glob import glob

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MATCHES  = os.path.join(_ROOT, "data", "stadium_matches.json")
_GPS_DIR  = os.path.join(_ROOT, "data", "gps")
_OUT_DIR  = os.path.join(_ROOT, "data", "track_sessions")
_STADES   = os.path.join(_ROOT, "data", "stades_athle.json")

ZONE_RADIUS_M   = 120.0
PAUSE_GAP_S     = 5.0       # gap GPS > 5s = pause (exclu du cumul)
N_CONSECUTIVE   = [2, 3, 5, 10]


def _equirect_m(lat1, lon1, lat2, lon2):
    mean_lat = math.radians((lat1 + lat2) / 2)
    dlat = math.radians(lat2 - lat1) * 6371000
    dlon = math.radians(lon2 - lon1) * 6371000 * math.cos(mean_lat)
    return math.sqrt(dlat * dlat + dlon * dlon)


def _load_stadiums():
    with open(_STADES, encoding="utf-8") as f:
        return {s["installation_id"]: s for s in json.load(f) if s["installation_id"]}


def _filter_in_zone(points, center_lat, center_lon):
    return [
        p for p in points
        if _equirect_m(p["lat"], p["lon"], center_lat, center_lon) <= ZONE_RADIUS_M
    ]


def _detect_laps(points, track_length):
    """Découpe la trace en tours par cumul de distance.
    Chaque tour = track_length mètres parcourus (pauses GPS > 5s exclues).
    Le dernier tour partiel (< 70% de la longueur) est ignoré."""
    if len(points) < 10:
        return []
    laps = []
    start_idx = 0
    cum = 0.0
    pause = 0.0
    for i in range(1, len(points)):
        prev, curr = points[i - 1], points[i]
        gap = curr["time_s"] - prev["time_s"]
        if gap > PAUSE_GAP_S:
            pause += gap
            continue
        cum += _equirect_m(prev["lat"], prev["lon"], curr["lat"], curr["lon"])
        if cum >= track_length:
            elapsed = curr["time_s"] - points[start_idx]["time_s"]
            laps.append({
                "n": len(laps) + 1,
                "time_s": round(elapsed - pause, 1),
                "distance_m": round(cum, 1),
                "pause_internal_s": round(pause, 1),
            })
            start_idx = i
            cum = 0.0
            pause = 0.0
    # Tour partiel final
    if cum >= track_length * 0.7:
        last = points[-1]
        elapsed = last["time_s"] - points[start_idx]["time_s"]
        laps.append({
            "n": len(laps) + 1,
            "time_s": round(elapsed - pause, 1),
            "distance_m": round(cum, 1),
            "pause_internal_s": round(pause, 1),
            "partial": True,
        })
    return laps


def _direction(points, center_lat, center_lon):
    """Sens horaire/antihoraire via somme des produits vectoriels."""
    cross_sum = 0.0
    for i in range(len(points) - 1):
        dx1 = points[i]["lon"] - center_lon
        dy1 = points[i]["lat"] - center_lat
        dx2 = points[i + 1]["lon"] - center_lon
        dy2 = points[i + 1]["lat"] - center_lat
        cross_sum += dx1 * dy2 - dy1 * dx2
    if abs(cross_sum) < 1e-12:
        return None
    return "counterclockwise" if cross_sum > 0 else "clockwise"


def _summary(laps, track_length):
    """Statistiques agrégées sur les tours."""
    if not laps:
        return {}
    # "Clean lap" = tour complet (non partiel) sans pause interne significative.
    clean = [l for l in laps if not l.get("partial") and l["pause_internal_s"] < 5]
    times = [l["time_s"] for l in laps if not l.get("partial")]
    if not times:
        return {}

    best = min(times)
    mean = sum(times) / len(times)
    var = sum((t - mean) ** 2 for t in times) / len(times)
    std = math.sqrt(var)
    cv = std / mean if mean > 0 else 0

    best_n = {}
    for n in N_CONSECUTIVE:
        if len(times) < n:
            continue
        best_n[f"best_{n}_consecutive_s"] = round(
            min(sum(times[i:i + n]) for i in range(len(times) - n + 1)), 1
        )

    total_dist_m = sum(l["distance_m"] for l in laps)
    total_time_s = sum(l["time_s"] for l in laps)
    return {
        "n_laps":          len(laps),
        "n_laps_clean":    len(clean),
        "best_lap_s":      round(best, 1),
        "mean_lap_s":      round(mean, 1),
        "std_lap_s":       round(std, 1),
        "cv":              round(cv, 3),
        "total_distance_m": round(total_dist_m, 1),
        "total_time_s":    round(total_time_s, 1),
        "mean_pace_min_per_km": round((total_time_s / 60) / (total_dist_m / 1000), 2) if total_dist_m > 0 else None,
        "track_length_m":  track_length,
        **best_n,
    }


def main():
    os.makedirs(_OUT_DIR, exist_ok=True)
    with open(_MATCHES, encoding="utf-8") as f:
        matches = json.load(f)
    stadiums = _load_stadiums()

    n_ok = 0
    n_skip_nolen = 0
    n_skip_nogps = 0

    for strava_id, m in matches.items():
        track_length = m.get("piste_longueur_m")
        if not track_length:
            n_skip_nolen += 1
            continue

        gps_path = os.path.join(_GPS_DIR, f"strava_{strava_id}.json")
        if not os.path.exists(gps_path):
            n_skip_nogps += 1
            continue
        try:
            with open(gps_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            n_skip_nogps += 1
            continue

        stadium = stadiums.get(m["stadium_id"])
        if stadium is None:
            continue

        points = [p for p in data.get("points", []) if "lat" in p and "lon" in p]
        in_zone = _filter_in_zone(points, stadium["lat"], stadium["lon"])
        if len(in_zone) < 10:
            continue

        laps = _detect_laps(in_zone, track_length)
        summary = _summary(laps, track_length)
        direction = _direction(in_zone, stadium["lat"], stadium["lon"])

        out = {
            "strava_id":    strava_id,
            "stadium_id":   m["stadium_id"],
            "stadium_nom":  m["stadium_nom"],
            "commune":      m["commune"],
            "direction":    direction,
            "summary":      summary,
            "laps":         laps,
        }
        out_path = os.path.join(_OUT_DIR, f"{strava_id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        n_ok += 1

    print(f"[OK] {n_ok} séances piste calculées dans {_OUT_DIR}")
    if n_skip_nolen: print(f"     {n_skip_nolen} ignorées (longueur piste inconnue)")
    if n_skip_nogps: print(f"     {n_skip_nogps} ignorées (GPS manquant ou corrompu)")


if __name__ == "__main__":
    sys.exit(main())
