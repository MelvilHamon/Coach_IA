"""
detect_stadium.py — Détecte si une activité s'est déroulée dans un stade
d'athlétisme connu, et infère la longueur de piste depuis les traces GPS
quand elle est inconnue.

Entrées :
  - data/stades_athle.json           (référentiel issu de scripts/extract_stades_athle.py)
  - data/stades_athle_inferred.json  (longueurs inférées par GPS, accumulées)
  - data/gps/strava_{id}.json        (traces GPS)

Sorties :
  - data/stadium_matches.json        ({strava_id: {stadium_id, nom, match_ratio,
                                                   piste_longueur_m, length_source}})
  - data/stades_athle_inferred.json  (mis à jour avec nouvelles inférences)

Critères de matching :
  - rayon 80 m autour du centre du stade
  - >= 60 % des points GPS dans ce rayon

Inférence de longueur (quand length_source == "unknown") :
  - filtrer les points GPS à l'intérieur du stade
  - trouver les retours successifs à < 25 m du point de départ après >= 100 m
  - longueur = médiane des distances cumulées entre retours
  - rejet si < 3 tours détectés
"""

import json
import math
import os
import sys
from glob import glob

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STADES         = os.path.join(_ROOT, "data", "stades_athle.json")
_INFERRED       = os.path.join(_ROOT, "data", "stades_athle_inferred.json")
_GPS_DIR        = os.path.join(_ROOT, "data", "gps")
_MATCHES        = os.path.join(_ROOT, "data", "stadium_matches.json")
_ENRICHED       = os.path.join(_ROOT, "data", "activities_enriched.csv")

MATCH_RADIUS_M  = 120.0          # taille piste 400m + marge GPS urbain
MATCH_FRACTION  = 0.60           # fallback : séance 100% piste
MIN_TIME_IN_ZONE_S = 300         # 5 min continues dans le stade
MIN_LAPS_EQUIVALENT = 3          # distance dans la zone >= 3 tours (filtre passage)
EXCURSION_TOLERANCE_S = 30       # tolérance brève sortie (couloir externe, GPS aberrant)
RUN_SPORT = "run"                # filtre sur la colonne `sport` de activities_enriched
BBOX_PREFILTER_M = 2000.0
LAP_RETURN_RADIUS_M = 25.0
LAP_MIN_DISTANCE_M  = 100.0
MIN_LAPS_FOR_INFERENCE = 3
STANDARD_LENGTHS = [200, 250, 300, 333, 400]


def _equirect_m(lat1, lon1, lat2, lon2):
    """Distance équirectangulaire en mètres (rapide, ok pour <10 km)."""
    mean_lat = math.radians((lat1 + lat2) / 2)
    dlat = math.radians(lat2 - lat1) * 6371000
    dlon = math.radians(lon2 - lon1) * 6371000 * math.cos(mean_lat)
    return math.sqrt(dlat * dlat + dlon * dlon)


def _load_run_ids():
    """Retourne l'ensemble des IDs d'activités dont sport == 'run'."""
    import csv
    run_ids = set()
    with open(_ENRICHED, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("sport") == RUN_SPORT:
                run_ids.add(str(row["ID"]))
    return run_ids


def _distance_in_zone(points, center_lat, center_lon, radius):
    """Distance cumulée parcourue par la trace à l'intérieur du rayon."""
    cum = 0.0
    inside_prev = False
    prev = None
    for p in points:
        d = _equirect_m(p["lat"], p["lon"], center_lat, center_lon)
        in_zone = d <= radius
        if in_zone and inside_prev and prev is not None:
            cum += _equirect_m(prev["lat"], prev["lon"], p["lat"], p["lon"])
        inside_prev = in_zone
        prev = p
    return cum


def _load_inferred():
    if os.path.exists(_INFERRED):
        with open(_INFERRED, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _merged_stadiums():
    """Charge le référentiel et applique les inférences accumulées."""
    with open(_STADES, encoding="utf-8") as f:
        stadiums = json.load(f)
    inferred = _load_inferred()
    for s in stadiums:
        sid = s["installation_id"]
        if sid in inferred and s["length_source"] == "unknown":
            s["piste_longueur_m"] = inferred[sid]["length_m"]
            s["length_source"] = "inferred_from_gps"
            s["inferred_from_n_sessions"] = inferred[sid]["n_sessions"]
    return stadiums


def _time_in_zone(points, target_lat, target_lon, radius):
    """Retourne (durée_totale_s, durée_plus_long_segment_s, fraction_points)
    pour les points GPS dans la zone, avec tolérance aux brèves excursions."""
    n = len(points)
    if n == 0:
        return 0.0, 0.0, 0.0
    n_inside = 0
    segments = []  # list of (start_t, end_t)
    start_t = None
    last_in_t = None
    for p in points:
        t = p["time_s"]
        d = _equirect_m(p["lat"], p["lon"], target_lat, target_lon)
        if d <= radius:
            n_inside += 1
            if start_t is None:
                start_t = t
            last_in_t = t
        else:
            if start_t is not None and (t - last_in_t) > EXCURSION_TOLERANCE_S:
                segments.append((start_t, last_in_t))
                start_t = None
    if start_t is not None:
        segments.append((start_t, last_in_t))
    total = sum(e - s for s, e in segments)
    longest = max((e - s for s, e in segments), default=0.0)
    return total, longest, n_inside / n


def _match_stadium(points, stadiums):
    """Match si: temps continu dans la zone >= 5min OU fraction des points >= 60%."""
    if not points:
        return None
    mid_lat = sum(p["lat"] for p in points) / len(points)
    mid_lon = sum(p["lon"] for p in points) / len(points)

    deg_lat = BBOX_PREFILTER_M / 111320
    deg_lon = BBOX_PREFILTER_M / (111320 * math.cos(math.radians(mid_lat)))
    candidates = [
        s for s in stadiums
        if abs(s["lat"] - mid_lat) < deg_lat and abs(s["lon"] - mid_lon) < deg_lon
    ]
    if not candidates:
        return None

    best = None
    for s in candidates:
        total, longest, frac = _time_in_zone(points, s["lat"], s["lon"], MATCH_RADIUS_M)
        score = longest  # priorité au plus long segment continu
        if best is None or score > best["score"]:
            best = {
                "stadium": s, "score": score,
                "time_in_zone_s": total, "longest_segment_s": longest,
                "match_ratio": frac,
            }
    if best and (best["longest_segment_s"] >= MIN_TIME_IN_ZONE_S
                 or best["match_ratio"] >= MATCH_FRACTION):
        return best
    return None


def _infer_lap_length(points, stadium):
    """Infère la longueur d'un tour en détectant les retours périodiques."""
    inside = [
        p for p in points
        if _equirect_m(p["lat"], p["lon"], stadium["lat"], stadium["lon"]) <= MATCH_RADIUS_M
    ]
    if len(inside) < 50:
        return None

    laps = []
    cum = 0.0
    start_idx = 0
    for i in range(1, len(inside)):
        cum += _equirect_m(
            inside[i - 1]["lat"], inside[i - 1]["lon"],
            inside[i]["lat"], inside[i]["lon"],
        )
        if cum >= LAP_MIN_DISTANCE_M:
            d_to_start = _equirect_m(
                inside[start_idx]["lat"], inside[start_idx]["lon"],
                inside[i]["lat"], inside[i]["lon"],
            )
            if d_to_start <= LAP_RETURN_RADIUS_M:
                laps.append(cum)
                start_idx = i
                cum = 0.0

    if len(laps) < MIN_LAPS_FOR_INFERENCE:
        return None

    laps.sort()
    median = laps[len(laps) // 2]
    snapped = min(STANDARD_LENGTHS, key=lambda x: abs(x - median))
    if abs(snapped - median) / median <= 0.05:
        return float(snapped)
    return round(median, 1)


def _save_inferred(inferred):
    with open(_INFERRED, "w", encoding="utf-8") as f:
        json.dump(inferred, f, ensure_ascii=False, indent=2)


def main():
    stadiums = _merged_stadiums()
    inferred = _load_inferred()
    run_ids = _load_run_ids()
    matches = {}

    gps_files = sorted(glob(os.path.join(_GPS_DIR, "strava_*.json")))
    n_total = len(gps_files)
    n_matched = 0
    n_inferred = 0
    n_skipped_nonrun = 0
    n_rejected_distance = 0

    for path in gps_files:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            strava_id = str(data.get("strava_id"))
            points = [p for p in data.get("points", []) if "lat" in p and "lon" in p]
            if not points:
                continue
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] {path}: {e}", file=sys.stderr)
            continue

        if strava_id not in run_ids:
            n_skipped_nonrun += 1
            continue

        result = _match_stadium(points, stadiums)
        if result is None:
            continue

        s = result["stadium"]

        # Filtre passage : exiger une distance cumulée dans la zone >= 3 tours
        # (seulement si la longueur de piste est connue)
        track_length = s["piste_longueur_m"]
        if track_length:
            dist_in_zone = _distance_in_zone(points, s["lat"], s["lon"], MATCH_RADIUS_M)
            if dist_in_zone < MIN_LAPS_EQUIVALENT * track_length:
                n_rejected_distance += 1
                continue

        n_matched += 1
        match_entry = {
            "stadium_id": s["installation_id"],
            "stadium_nom": s["nom"],
            "commune": s["commune"],
            "match_ratio": round(result["match_ratio"], 3),
            "time_in_zone_min": round(result["time_in_zone_s"] / 60, 1),
            "longest_segment_min": round(result["longest_segment_s"] / 60, 1),
            "piste_longueur_m": s["piste_longueur_m"],
            "length_source": s["length_source"],
        }

        if s["length_source"] == "unknown":
            lap_len = _infer_lap_length(points, s)
            if lap_len is not None:
                sid = s["installation_id"]
                prev = inferred.get(sid)
                if prev is None:
                    inferred[sid] = {
                        "length_m": lap_len,
                        "n_sessions": 1,
                        "samples": [lap_len],
                    }
                else:
                    samples = prev["samples"] + [lap_len]
                    samples_sorted = sorted(samples)
                    median = samples_sorted[len(samples_sorted) // 2]
                    inferred[sid] = {
                        "length_m": median,
                        "n_sessions": len(samples),
                        "samples": samples,
                    }
                match_entry["piste_longueur_m"] = inferred[sid]["length_m"]
                match_entry["length_source"] = "inferred_from_gps"
                n_inferred += 1

        matches[strava_id] = match_entry

    with open(_MATCHES, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)
    _save_inferred(inferred)

    print(f"[OK] {n_total} activités GPS analysées")
    print(f"     {n_skipped_nonrun} ignorées (sport != 'run')")
    print(f"     {n_rejected_distance} rejetées (distance dans zone < 3 tours)")
    print(f"     {n_matched} matchées avec un stade")
    print(f"     {n_inferred} longueurs inférées depuis GPS")
    print(f"     -> {_MATCHES}")
    print(f"     -> {_INFERRED}")


if __name__ == "__main__":
    main()
