"""
api/routes/stadiums.py — Endpoint stades d'athlétisme fréquentés (PR par stade).
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from api import storage
from api.dependencies import get_current_user
from api.user_data import UserPaths

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Référentiel national bundlé dans l'image (lecture seule, partagé entre users).
_STADES_REF = os.path.join(_ROOT, "data", "stades_athle.json")

logger = logging.getLogger("coachagent")

router = APIRouter(prefix="/api/stadiums", tags=["stadiums"])


def reference_available() -> bool:
    """Le référentiel national est-il présent dans l'image ?

    Absent = build Docker parti sans data/stades_athle.json : la détection ne
    peut rien matcher et l'onglet reste vide. On distingue ce cas de "l'athlète
    n'a couru dans aucun stade", qui produirait sinon la même réponse vide.
    """
    return storage.exists(_STADES_REF)


def _track_dir(user_id: str) -> str:
    return os.path.join(UserPaths(user_id).base, "track")


def _track_pr_path(user_id: str) -> str:
    return os.path.join(_track_dir(user_id), "track_pr.json")


def _load_ref_index() -> dict:
    data = storage.read_json(_STADES_REF)
    if not isinstance(data, list):
        logger.error(
            "Référentiel des stades illisible ou absent (%s) — les stades ne "
            "seront pas enrichis. Vérifier que le Dockerfile embarque bien ce fichier.",
            _STADES_REF,
        )
        return {}
    try:
        return {s["installation_id"]: s for s in data}
    except (KeyError, TypeError):
        return {}


def _load_session(user_id: str, strava_id: str) -> dict | None:
    path = os.path.join(_track_dir(user_id), "sessions", f"{strava_id}.json")
    return storage.read_json(path)


def _compute_consecutive_prs(laps: list[dict], windows: list[int]) -> dict:
    """Best sum of N consecutive lap times for each N in windows."""
    times = [l.get("time_s") for l in laps if l.get("time_s") is not None and not l.get("partial")]
    out = {}
    for n in windows:
        if len(times) >= n:
            best = min(sum(times[i:i + n]) for i in range(len(times) - n + 1))
            out[n] = best
    return out


def _enrich_stadium(user_id: str, sid: str, s: dict, ref: dict) -> dict:
    """Merge progression + reference + cross-session PRs."""
    ref_info = ref.get(sid, {})
    out = {
        "id": sid,
        "nom": s.get("stadium_nom"),
        "commune": s.get("commune"),
        "track_length_m": s.get("track_length_m"),
        "n_sessions": s.get("n_sessions"),
        "first_session": s.get("first_session"),
        "last_session": s.get("last_session"),
        "pr_lap_s": s.get("pr_lap_s"),
        "pr_lap_session": s.get("pr_lap_session"),
        "best_mean_pace": s.get("best_mean_pace"),
        "best_mean_pace_session": s.get("best_mean_pace_session"),
        "progression": s.get("progression", []),
        "lat": ref_info.get("lat"),
        "lon": ref_info.get("lon"),
        "surface": ref_info.get("surface"),
        "eclairage": ref_info.get("eclairage"),
        "couloirs_nb": ref_info.get("couloirs_nb"),
    }

    # Compute multi-lap PRs across all sessions of this stadium
    pr_windows = {2: None, 3: None, 5: None, 10: None}
    pr_sessions = {2: None, 3: None, 5: None, 10: None}
    for p in s.get("progression", []):
        sess = _load_session(user_id, p.get("strava_id"))
        if not sess:
            continue
        summary = sess.get("summary", {}) or {}
        for n in (2, 3):
            key = f"best_{n}_consecutive_s"
            if summary.get(key) is not None:
                v = summary[key]
                if pr_windows[n] is None or v < pr_windows[n]:
                    pr_windows[n] = v
                    pr_sessions[n] = p.get("strava_id")
        for n in (5, 10):
            laps = sess.get("laps", [])
            comp = _compute_consecutive_prs(laps, [n])
            if n in comp:
                v = comp[n]
                if pr_windows[n] is None or v < pr_windows[n]:
                    pr_windows[n] = v
                    pr_sessions[n] = p.get("strava_id")

    out["pr_multi"] = {
        str(n): {"time_s": pr_windows[n], "strava_id": pr_sessions[n]}
        for n in pr_windows if pr_windows[n] is not None
    }
    return out


@router.get("")
def list_stadiums(user: dict = Depends(get_current_user)):
    """Liste des stades fréquentés avec PR et progression enrichis."""
    if not reference_available():
        return {"stadiums": [], "global": {}, "error": "no_reference"}

    data = storage.read_json(_track_pr_path(user["id"]))
    if not data:
        return {"stadiums": [], "global": {}}

    ref = _load_ref_index()
    stadiums = [_enrich_stadium(user["id"], sid, s, ref) for sid, s in data.items()]
    stadiums.sort(key=lambda s: s.get("n_sessions", 0), reverse=True)

    # Global aggregates across all stadiums
    total_sessions = sum(s.get("n_sessions", 0) or 0 for s in stadiums)

    # PRs are only meaningful on a normalized track length → 400 m only
    s400 = [s for s in stadiums if s.get("track_length_m") and abs(s["track_length_m"] - 400) < 1]
    pr_lap_all = min((s["pr_lap_s"] for s in s400 if s.get("pr_lap_s")), default=None)
    pr_multi_all = {}
    for n in ("2", "3", "5", "10"):
        vals = [s["pr_multi"][n]["time_s"] for s in s400 if s.get("pr_multi", {}).get(n)]
        if vals:
            pr_multi_all[n] = min(vals)

    glob = {
        "n_stadiums": len(stadiums),
        "n_sessions": total_sessions,
        "n_stadiums_400m": len(s400),
        "pr_track_length_m": 400,
        "pr_lap_s": pr_lap_all,
        "pr_multi": pr_multi_all,
    }

    return {"stadiums": stadiums, "global": glob}


@router.get("/{stadium_id}/sessions")
def stadium_sessions(stadium_id: str, user: dict = Depends(get_current_user)):
    """Détail de toutes les séances réalisées dans un stade."""
    data = storage.read_json(_track_pr_path(user["id"]))
    if not data:
        raise HTTPException(404, "no track data")

    s = data.get(stadium_id)
    if not s:
        raise HTTPException(404, "stadium not found")

    sessions = []
    for p in s.get("progression", []):
        sess = _load_session(user["id"], p.get("strava_id"))
        item = {
            "date": p.get("date"),
            "strava_id": p.get("strava_id"),
            "best_lap_s": p.get("best_lap_s"),
            "mean_lap_s": p.get("mean_lap_s"),
            "n_laps": p.get("n_laps"),
            "cv": p.get("cv"),
        }
        if sess:
            summary = sess.get("summary", {}) or {}
            item["laps"] = sess.get("laps", [])
            item["total_distance_m"] = summary.get("total_distance_m")
            item["total_time_s"] = summary.get("total_time_s")
            item["mean_pace_min_per_km"] = summary.get("mean_pace_min_per_km")
        sessions.append(item)

    sessions.sort(key=lambda x: x.get("date", ""), reverse=True)
    return {"sessions": sessions}
