"""
stadium_pipeline.py — Détection stade par utilisateur, branchée dans le pipeline
de sync (api/routes/sync.py).

Remplace, pour un utilisateur donné, la chaîne CLI historique
detect_stadium.main → track_metrics.main → track_pr.main (qui opère sur des
chemins globaux data/*) par une exécution en mémoire qui :

  1. charge le référentiel national bundlé (data/stades_athle.json, lecture seule)
     + les longueurs inférées accumulées pour CET utilisateur
     ({base}/track/inferred.json) ;
  2. parcourt les traces GPS du user ({base}/gps/strava_*.json) via la couche
     `storage` (R2 en prod, local en dev) ;
  3. matche chaque trace à un stade, calcule les tours/splits, et consolide les
     records par stade ;
  4. écrit le résultat via `storage` : {base}/track/track_pr.json,
     {base}/track/sessions/{strava_id}.json et {base}/track/inferred.json.

Réutilise les fonctions pures de detect_stadium.py et track_metrics.py (matching
géométrique, inférence de longueur, découpage en tours) pour ne pas dupliquer la
logique métier.
"""

import os
from collections import defaultdict

# Réutilisation des helpers purs existants (aucune I/O au niveau module).
from detect_stadium import (
    _match_stadium,
    _distance_in_zone,
    _infer_lap_length,
    MATCH_RADIUS_M,
    MIN_LAPS_EQUIVALENT,
)
from track_metrics import (
    _filter_in_zone,
    _detect_laps,
    _summary,
    _direction,
)

from api import storage

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STADES_REF = os.path.join(_ROOT, "data", "stades_athle.json")

_N_CONSECUTIVE = [2, 3, 5, 10]


# ── Chargement référentiel ───────────────────────────────────────────────────

def _load_reference() -> list[dict]:
    """Charge le référentiel national bundlé (data/stades_athle.json)."""
    data = storage.read_json(_STADES_REF)
    return data if isinstance(data, list) else []


def _merge_inferred(stadiums: list[dict], inferred: dict) -> list[dict]:
    """Applique les longueurs inférées par GPS aux stades de longueur inconnue."""
    for s in stadiums:
        sid = s.get("installation_id")
        if sid in inferred and s.get("length_source") == "unknown":
            s["piste_longueur_m"] = inferred[sid]["length_m"]
            s["length_source"] = "inferred_from_gps"
    return stadiums


# ── Chargement métadonnées activités (sport + date) ──────────────────────────

def _load_run_meta(data_dir: str) -> tuple[set[str], dict[str, str]]:
    """Retourne (ids des activités sport=='run', {id: Date}) depuis le CSV enrichi."""
    enriched = os.path.join(data_dir, "activities_enriched.csv")
    df = storage.read_csv(enriched)
    if df is None or "ID" not in df.columns:
        return set(), {}
    run_ids: set[str] = set()
    dates: dict[str, str] = {}
    has_sport = "sport" in df.columns
    has_date = "Date" in df.columns
    for _, row in df.iterrows():
        sid = str(row["ID"])
        dates[sid] = str(row["Date"]) if has_date else None
        if not has_sport or row.get("sport") == "run":
            run_ids.add(sid)
    return run_ids, dates


# ── Consolidation des PR par stade (port de track_pr.main, en mémoire) ───────

def _consolidate(sessions_by_stadium: dict[str, list[dict]]) -> dict:
    results = {}
    for sid, sessions in sessions_by_stadium.items():
        sessions.sort(key=lambda x: x.get("date") or "")
        first = sessions[0]
        track_length = first["summary"]["track_length_m"]

        pr_lap, pr_lap_sid = float("inf"), None
        pr_n = {n: (float("inf"), None) for n in _N_CONSECUTIVE}
        best_pace, best_pace_sid = float("inf"), None
        progression = []

        for s in sessions:
            summ = s["summary"]
            if summ["best_lap_s"] < pr_lap:
                pr_lap = summ["best_lap_s"]
                pr_lap_sid = s["strava_id"]
            for n in _N_CONSECUTIVE:
                key = f"best_{n}_consecutive_s"
                if key in summ and summ[key] < pr_n[n][0]:
                    pr_n[n] = (summ[key], s["strava_id"])
            if summ["mean_pace_min_per_km"] is not None and summ["mean_pace_min_per_km"] < best_pace:
                best_pace = summ["mean_pace_min_per_km"]
                best_pace_sid = s["strava_id"]
            progression.append({
                "date":       s.get("date"),
                "strava_id":  s["strava_id"],
                "best_lap_s": summ["best_lap_s"],
                "mean_lap_s": summ["mean_lap_s"],
                "n_laps":     summ["n_laps"],
                "cv":         summ["cv"],
            })

        entry = {
            "stadium_nom":            first["stadium_nom"],
            "commune":                first["commune"],
            "track_length_m":         track_length,
            "n_sessions":             len(sessions),
            "first_session":          sessions[0].get("date"),
            "last_session":           sessions[-1].get("date"),
            "pr_lap_s":               pr_lap if pr_lap != float("inf") else None,
            "pr_lap_session":         pr_lap_sid,
            "best_mean_pace":         best_pace if best_pace != float("inf") else None,
            "best_mean_pace_session": best_pace_sid,
            "progression":            progression,
        }
        for n in _N_CONSECUTIVE:
            v, src = pr_n[n]
            entry[f"pr_{n}_consec_s"] = v if v != float("inf") else None
            entry[f"pr_{n}_consec_session"] = src
        results[sid] = entry
    return results


# ── Orchestrateur principal ──────────────────────────────────────────────────

def run_stadium_analysis(data_dir: str) -> dict:
    """
    Détecte les séances en stade pour l'utilisateur dont les données sont sous
    `data_dir` (= UserPaths.base) et écrit track_pr.json / track/sessions/* via
    la couche storage.

    Retourne un petit récap {n_matched, n_sessions, n_stadiums}.
    """
    gps_dir = os.path.join(data_dir, "gps")
    track_dir = os.path.join(data_dir, "track")
    inferred_path = os.path.join(track_dir, "inferred.json")
    track_pr_path = os.path.join(track_dir, "track_pr.json")

    stadiums = _load_reference()
    if not stadiums:
        return {"n_matched": 0, "n_sessions": 0, "n_stadiums": 0, "error": "no_reference"}

    inferred = storage.read_json(inferred_path) or {}
    stadiums = _merge_inferred(stadiums, inferred)

    run_ids, dates = _load_run_meta(data_dir)

    gps_files = [f for f in storage.listdir(gps_dir) if f.startswith("strava_") and f.endswith(".json")]

    sessions_by_stadium: dict[str, list[dict]] = defaultdict(list)
    n_matched = 0
    n_sessions = 0

    for fname in sorted(gps_files):
        data = storage.read_json(os.path.join(gps_dir, fname))
        if not data:
            continue
        strava_id = str(data.get("strava_id"))
        if run_ids and strava_id not in run_ids:
            continue
        points = [p for p in data.get("points", []) if "lat" in p and "lon" in p]
        if not points:
            continue

        result = _match_stadium(points, stadiums)
        if result is None:
            continue
        s = result["stadium"]
        n_matched += 1

        track_length = s.get("piste_longueur_m")

        # Filtre passage : >= 3 tours de distance cumulée dans la zone.
        if track_length:
            dist_in_zone = _distance_in_zone(points, s["lat"], s["lon"], MATCH_RADIUS_M)
            if dist_in_zone < MIN_LAPS_EQUIVALENT * track_length:
                continue

        # Inférence de longueur si inconnue (accumulée par utilisateur).
        if s.get("length_source") == "unknown":
            lap_len = _infer_lap_length(points, s)
            if lap_len is not None:
                sid = s["installation_id"]
                prev = inferred.get(sid)
                if prev is None:
                    inferred[sid] = {"length_m": lap_len, "n_sessions": 1, "samples": [lap_len]}
                else:
                    samples = prev["samples"] + [lap_len]
                    samples_sorted = sorted(samples)
                    inferred[sid] = {
                        "length_m": samples_sorted[len(samples_sorted) // 2],
                        "n_sessions": len(samples),
                        "samples": samples,
                    }
                track_length = inferred[sid]["length_m"]
                s["piste_longueur_m"] = track_length
                s["length_source"] = "inferred_from_gps"

        if not track_length:
            continue  # longueur toujours inconnue → pas de métriques tours

        in_zone = _filter_in_zone(points, s["lat"], s["lon"])
        if len(in_zone) < 10:
            continue

        laps = _detect_laps(in_zone, track_length)
        summary = _summary(laps, track_length)
        if not laps or not summary:
            continue
        direction = _direction(in_zone, s["lat"], s["lon"])

        session = {
            "strava_id":   strava_id,
            "stadium_id":  s["installation_id"],
            "stadium_nom": s["nom"],
            "commune":     s["commune"],
            "direction":   direction,
            "summary":     summary,
            "laps":        laps,
        }
        storage.write_json(os.path.join(track_dir, "sessions", f"{strava_id}.json"), session)
        n_sessions += 1

        session_with_date = dict(session)
        session_with_date["date"] = dates.get(strava_id)
        sessions_by_stadium[s["installation_id"]].append(session_with_date)

    results = _consolidate(sessions_by_stadium)
    storage.write_json(track_pr_path, results)
    storage.write_json(inferred_path, inferred)

    return {"n_matched": n_matched, "n_sessions": n_sessions, "n_stadiums": len(results)}
