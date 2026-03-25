"""
api/routes/sync.py — Synchronisation incrémentale intelligente.

POST /api/sync       → lance le pipeline en background, retourne 202
GET  /api/sync/status → état courant enrichi (pipeline_status par étape)

Le pipeline ne relance que les étapes nécessaires en comparant
sync_state.json avant/après chaque step.

── Clés canoniques de sync_state.json ──────────────────────────────────────────

Chaque script écrit uniquement ses propres clés :

  RecupDataStrava.py  → strava_last_sync, strava_activities_total
  get_streams.py      → streams_last_sync, streams_synced_count
  sync_garmin.py      → garmin_last_sync, garmin_activities_total, garmin_streams_synced
  sync_strava_gps.py  → strava_gps_last_sync, strava_gps_synced
  run_analysis.py     → analysis_last_run, analysis_activities_count
  run_gps_analysis.py → (pas de clé, écrit dans data/garmin/metrics/)
  sync.py (pipeline)  → matching_last_run, pipeline_last_full_run, pipeline_last_duration_s
"""

import json
import io
import os
import sys
import threading
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Rendre les modules pipeline importables
sys.path.insert(0, os.path.join(_ROOT, "appelAPIs"))
sys.path.insert(0, os.path.join(_ROOT, "analyse"))

_SYNC_STATE = os.path.join(_ROOT, "data", "sync_state.json")
_GARMIN_INDEX = os.path.join(_ROOT, "data", "garmin", "activities.json")
_GARMIN_STREAMS = os.path.join(_ROOT, "data", "garmin", "streams")
_STRAVA_CSV = os.path.join(_ROOT, "data", "mes_activites_strava.csv")
_GPS_DIR = os.path.join(_ROOT, "data", "gps")
_GARMIN_MAP = os.path.join(_ROOT, "data", "garmin", "strava_garmin_map.json")
_CONFIG_PATH = os.path.join(_ROOT, "config.json")

router = APIRouter(prefix="/api", tags=["sync"])

# ── État interne du sync ──────────────────────────────────────────────────────

_sync_lock = threading.Lock()
_sync_state = {
    "status": "idle",       # idle | running | error
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
    "steps_done": [],
}


# ── Lecture/écriture sync_state.json ─────────────────────────────────────────

def _load_file_state() -> dict:
    if os.path.exists(_SYNC_STATE):
        try:
            with open(_SYNC_STATE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_file_state(state: dict) -> None:
    os.makedirs(os.path.dirname(_SYNC_STATE), exist_ok=True)
    with open(_SYNC_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _load_config() -> dict:
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _sync_age_minutes(state: dict, key: str) -> float | None:
    """Retourne l'âge en minutes d'un timestamp dans sync_state, ou None si absent."""
    ts = state.get(key)
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60
    except (ValueError, TypeError):
        return None


def _count_csv_rows() -> int:
    """Compte le nombre réel d'activités dans le CSV Strava."""
    if not os.path.exists(_STRAVA_CSV):
        return 0
    try:
        df = pd.read_csv(_STRAVA_CSV)
        return len(df)
    except Exception:
        return 0


# ── Logique de décision ──────────────────────────────────────────────────────

def _needs_garmin_sync(state: dict, interval_min: float) -> tuple[bool, str]:
    """Garmin sync nécessaire ?"""
    age = _sync_age_minutes(state, "garmin_last_sync")
    if age is None:
        return True, "jamais synchronisé"
    if age > interval_min:
        return True, f"dernière sync il y a {age:.0f} min (seuil {interval_min:.0f})"
    return False, "à jour"


def _needs_strava_sync(state: dict, interval_min: float) -> tuple[bool, str]:
    """Strava sync nécessaire ?"""
    # Lire la clé canonique écrite par RecupDataStrava.py
    age = _sync_age_minutes(state, "strava_last_sync")
    if age is None:
        return True, "jamais synchronisé"
    if age > interval_min:
        return True, f"dernière sync il y a {age:.0f} min (seuil {interval_min:.0f})"
    # Vérification de cohérence : le CSV peut avoir plus de lignes que ce qui est
    # enregistré dans sync_state (ajouts manuels, sync externe, etc.)
    csv_count = _count_csv_rows()
    state_count = state.get("strava_activities_total", 0)
    if csv_count > state_count:
        return True, f"CSV a {csv_count} lignes vs {state_count} dans sync_state"
    return False, "à jour"


def _needs_matching(state: dict, prev_strava_total: int, prev_garmin_total: int) -> tuple[bool, str]:
    """Matching nécessaire seulement si le nombre d'activités a changé."""
    strava_total = state.get("strava_activities_total", 0)
    garmin_total = state.get("garmin_activities_total", 0)
    if strava_total != prev_strava_total:
        return True, f"strava {prev_strava_total} → {strava_total}"
    if garmin_total != prev_garmin_total:
        return True, f"garmin {prev_garmin_total} → {garmin_total}"
    if not state.get("matching_last_run"):
        return True, "jamais exécuté"
    return False, "aucun changement"


def _needs_strava_gps(state: dict) -> tuple[bool, str]:
    """GPS Strava nécessaire si des activités n'ont ni Garmin ni Strava GPS."""
    total = state.get("strava_activities_total", 0)
    garmin_streams = state.get("garmin_streams_synced", 0)
    strava_gps = state.get("strava_gps_synced", 0)
    covered = garmin_streams + strava_gps
    if total > covered:
        gap = total - covered
        return True, f"{gap} activités sans GPS"
    return False, "toutes couvertes"


def _needs_analysis(state: dict) -> tuple[bool, str]:
    """Analyse nécessaire si nouvelles activités non encore analysées."""
    # Comparer avec le nombre réel de lignes du CSV, pas sync_state
    csv_count = _count_csv_rows()
    analysis_count = state.get("analysis_activities_count", 0)
    if csv_count > analysis_count:
        return True, f"{csv_count - analysis_count} nouvelles activités (CSV={csv_count}, analysées={analysis_count})"
    if not state.get("analysis_last_run"):
        return True, "jamais exécuté"
    return False, "à jour"


# ── Matching local Garmin ↔ Strava ────────────────────────────────────────────

def match_strava_garmin() -> dict:
    """
    Match Garmin → Strava en mémoire (aucun appel API).

    Critères : date ±4h, durée ±120s, distance ±200m.
    Écrit data/gps/{strava_id}.json pour chaque match trouvé.
    Met à jour data/garmin/strava_garmin_map.json.

    Retourne {"matched": int, "already_matched": int, "unmatched_garmin": int}.
    """
    # Charger les index
    if not os.path.exists(_GARMIN_INDEX) or not os.path.exists(_STRAVA_CSV):
        return {"matched": 0, "already_matched": 0, "unmatched_garmin": 0}

    with open(_GARMIN_INDEX, encoding="utf-8") as f:
        garmin_acts = json.load(f)

    strava_df = pd.read_csv(_STRAVA_CSV)
    if strava_df.empty:
        return {"matched": 0, "already_matched": 0, "unmatched_garmin": 0}

    strava_df["_date"] = pd.to_datetime(strava_df["Date"], utc=True)
    strava_df["_dur_s"] = strava_df["Temps (min)"].astype(float) * 60.0
    strava_df["_dist_m"] = strava_df["Distance (km)"].astype(float) * 1000.0

    # Charger le map existant
    garmin_map = {}
    if os.path.exists(_GARMIN_MAP):
        with open(_GARMIN_MAP, encoding="utf-8") as f:
            garmin_map = json.load(f)

    # IDs Strava déjà matchés (fichiers GPS existants)
    existing_gps = set()
    if os.path.exists(_GPS_DIR):
        for fname in os.listdir(_GPS_DIR):
            stem, ext = os.path.splitext(fname)
            if ext == ".json" and stem.isdigit():
                existing_gps.add(int(stem))

    matched = 0
    already_matched = 0
    os.makedirs(_GPS_DIR, exist_ok=True)

    used_strava_ids = set(existing_gps)

    for gact in garmin_acts:
        gid = int(gact.get("garmin_id", 0))
        if gid == 0:
            continue

        stream_path = os.path.join(_GARMIN_STREAMS, f"{gid}.json")
        if not os.path.exists(stream_path):
            continue

        raw_start = gact.get("start_time_utc", "")
        if not raw_start:
            continue
        try:
            g_date = pd.to_datetime(raw_start, utc=True)
        except Exception:
            continue

        g_dur_s = float(gact.get("duration_s", 0))
        g_dist_m = float(gact.get("distance_m", 0))

        best_strava_id = None
        best_dt = float("inf")

        for _, srow in strava_df.iterrows():
            sid = int(srow["ID"])
            if sid in used_strava_ids:
                continue

            dt_diff = abs((srow["_date"] - g_date).total_seconds())
            if dt_diff > 14400:
                continue
            if abs(srow["_dur_s"] - g_dur_s) > 120:
                continue
            if abs(srow["_dist_m"] - g_dist_m) > 200:
                continue

            if dt_diff < best_dt:
                best_dt = dt_diff
                best_strava_id = sid

        if best_strava_id is None:
            continue

        if best_strava_id in existing_gps:
            already_matched += 1
            continue

        with open(stream_path, encoding="utf-8") as f:
            stream_data = json.load(f)

        gps_data = {
            "strava_id": best_strava_id,
            "garmin_id": gid,
            "points": stream_data.get("points", []),
        }
        gps_path = os.path.join(_GPS_DIR, f"{best_strava_id}.json")
        with open(gps_path, "w", encoding="utf-8") as f:
            json.dump(gps_data, f, indent=2, ensure_ascii=False)

        garmin_map[str(best_strava_id)] = gid
        used_strava_ids.add(best_strava_id)
        matched += 1

    os.makedirs(os.path.dirname(_GARMIN_MAP), exist_ok=True)
    with open(_GARMIN_MAP, "w", encoding="utf-8") as f:
        json.dump(garmin_map, f, indent=2, ensure_ascii=False)

    unmatched = sum(
        1 for g in garmin_acts
        if int(g.get("garmin_id", 0)) != 0
        and os.path.exists(os.path.join(_GARMIN_STREAMS, f"{int(g['garmin_id'])}.json"))
        and str(int(g["garmin_id"])) not in {str(v) for v in garmin_map.values()}
    )

    file_state = _load_file_state()
    file_state["matching_last_run"] = datetime.now(timezone.utc).isoformat()
    _save_file_state(file_state)

    return {"matched": matched, "already_matched": already_matched, "unmatched_garmin": unmatched}


# ── Pipeline sync incrémental ────────────────────────────────────────────────

def _run_pipeline():
    """Exécute le pipeline en background — ne relance que les étapes nécessaires."""
    global _sync_state
    _sync_state["status"] = "running"
    _sync_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _sync_state["finished_at"] = None
    _sync_state["result"] = None
    _sync_state["error"] = None
    _sync_state["steps_done"] = []

    result = {
        "new_activities": 0,
        "new_streams": 0,
        "new_gps_matches": 0,
        "strava_gps_fetched": 0,
        "steps_run": [],
        "steps_skipped": [],
        "duration_s": 0,
    }
    t_start = time.time()
    buf = io.StringIO()

    config = _load_config()
    interval_min = config.get("auto_sync_interval_minutes", 30)

    try:
        # Snapshot de l'état avant le pipeline
        state_before = _load_file_state()
        prev_strava_total = state_before.get("strava_activities_total", 0)
        prev_garmin_total = state_before.get("garmin_activities_total", 0)

        # ── Étape 1 : Garmin sync (source GPS principale) ────────────────
        need, reason = _needs_garmin_sync(state_before, interval_min)
        if need:
            try:
                from sync_garmin import sync_all
                with redirect_stdout(buf):
                    sync_all()
                _sync_state["steps_done"].append("garmin")
                result["steps_run"].append("garmin")
                from api.deps import invalidate_cache
                invalidate_cache(["gps"])
            except SystemExit:
                _sync_state["steps_done"].append("garmin:auth_failed")
                result["steps_run"].append("garmin")
            except Exception as e:
                _sync_state["steps_done"].append(f"garmin:error:{e}")
                result["steps_run"].append("garmin")
        else:
            result["steps_skipped"].append({"step": "garmin", "reason": reason})

        # Recharger l'état (garmin sync l'a peut-être mis à jour)
        state_after_garmin = _load_file_state()

        # ── Étape 2 : Matching Garmin → Strava ───────────────────────────
        need, reason = _needs_matching(state_after_garmin, prev_strava_total, prev_garmin_total)
        if need:
            try:
                match_result = match_strava_garmin()
                result["new_gps_matches"] = match_result["matched"]
                _sync_state["steps_done"].append("matching")
                result["steps_run"].append("matching")
                from api.deps import invalidate_cache
                invalidate_cache(["gps"])
            except Exception as e:
                _sync_state["steps_done"].append(f"matching:error:{e}")
                result["steps_run"].append("matching")
        else:
            result["steps_skipped"].append({"step": "matching", "reason": reason})

        # ── Étape 3 : Strava activités (métadonnées) ─────────────────────
        need, reason = _needs_strava_sync(state_before, interval_min)
        if need:
            try:
                from RecupDataStrava import sync_activities
                with redirect_stdout(buf):
                    n_new = sync_activities()
                result["new_activities"] = n_new or 0
                _sync_state["steps_done"].append("strava")
                result["steps_run"].append("strava")
                if n_new:
                    from api.deps import invalidate_cache
                    invalidate_cache(["activities"])
            except Exception as e:
                _sync_state["steps_done"].append(f"strava:error:{e}")
                result["steps_run"].append("strava")
        else:
            result["steps_skipped"].append({"step": "strava", "reason": reason})

        # ── Étape 4 : Strava streams (FC, allure) ────────────────────────
        # Toujours exécuter — le script interne skip les activités déjà synced
        try:
            from get_streams import sync_all_streams
            with redirect_stdout(buf):
                sync_all_streams()
            _sync_state["steps_done"].append("strava_streams")
            result["steps_run"].append("strava_streams")
        except Exception as e:
            _sync_state["steps_done"].append(f"strava_streams:error:{e}")
            result["steps_run"].append("strava_streams")

        # ── Étape 5 : Re-match si nouvelles activités Strava ─────────────
        if result["new_activities"] > 0:
            try:
                match2 = match_strava_garmin()
                result["new_gps_matches"] += match2["matched"]
                _sync_state["steps_done"].append("rematch")
                result["steps_run"].append("rematch")
                if match2["matched"] > 0:
                    from api.deps import invalidate_cache
                    invalidate_cache(["gps"])
            except Exception as e:
                _sync_state["steps_done"].append(f"rematch:error:{e}")

        # ── Étape 6 : GPS Strava fallback ─────────────────────────────────
        state_now = _load_file_state()
        need, reason = _needs_strava_gps(state_now)
        if need:
            try:
                from sync_strava_gps import sync_all as sync_strava_gps_all
                with redirect_stdout(buf):
                    strava_gps_result = sync_strava_gps_all()
                result["strava_gps_fetched"] = strava_gps_result.get("strava_fetched", 0)
                _sync_state["steps_done"].append("strava_gps")
                result["steps_run"].append("strava_gps")
                if result["strava_gps_fetched"] > 0:
                    from api.deps import invalidate_cache
                    invalidate_cache(["gps"])
            except Exception as e:
                _sync_state["steps_done"].append(f"strava_gps:error:{e}")
                result["steps_run"].append("strava_gps")
        else:
            result["steps_skipped"].append({"step": "strava_gps", "reason": reason})

        # ── Étape 7 : Analyse GPS (métriques Garmin) ──────────────────────
        try:
            from run_gps_analysis import run_gps_analysis
            with redirect_stdout(buf):
                run_gps_analysis()
            _sync_state["steps_done"].append("gps_analysis")
            result["steps_run"].append("gps_analysis")
        except Exception as e:
            _sync_state["steps_done"].append(f"gps_analysis:error:{e}")
            result["steps_run"].append("gps_analysis")

        # ── Étape 8 : Analyse enrichie ────────────────────────────────────
        state_now = _load_file_state()
        need, reason = _needs_analysis(state_now)
        if need:
            try:
                from run_analysis import run_analysis
                with redirect_stdout(buf):
                    run_analysis()
                _sync_state["steps_done"].append("analysis")
                result["steps_run"].append("analysis")
                from api.deps import invalidate_cache
                invalidate_cache(["activities", "metrics"])
            except SystemExit:
                _sync_state["steps_done"].append("analysis:exit")
                result["steps_run"].append("analysis")
            except Exception as e:
                _sync_state["steps_done"].append(f"analysis:error:{e}")
                result["steps_run"].append("analysis")
        else:
            result["steps_skipped"].append({"step": "analysis", "reason": reason})

        # ── Finalisation ──────────────────────────────────────────────────
        result["duration_s"] = round(time.time() - t_start, 1)

        file_state = _load_file_state()
        file_state["pipeline_last_full_run"] = datetime.now(timezone.utc).isoformat()
        file_state["pipeline_last_duration_s"] = result["duration_s"]
        _save_file_state(file_state)

        _sync_state["status"] = "idle"
        _sync_state["result"] = result

    except Exception as e:
        _sync_state["status"] = "error"
        _sync_state["error"] = str(e)
        result["duration_s"] = round(time.time() - t_start, 1)
        _sync_state["result"] = result

    finally:
        _sync_state["finished_at"] = datetime.now(timezone.utc).isoformat()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/sync", status_code=202)
def trigger_sync():
    """Lance le pipeline de synchronisation en background."""
    if _sync_state["status"] == "running":
        return {"status": "already_running", "started_at": _sync_state["started_at"]}

    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running", "started_at": _sync_state["started_at"]}

    def _run():
        try:
            _run_pipeline()
        finally:
            _sync_lock.release()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"status": "running"}


@router.post("/sync/backfill", status_code=202)
def trigger_backfill(after_date: str = "2023-01-01"):
    """Lance un backfill Strava pour récupérer les activités anciennes."""
    if _sync_state["status"] == "running":
        return {"status": "already_running", "started_at": _sync_state["started_at"]}

    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running", "started_at": _sync_state["started_at"]}

    def _run():
        global _sync_state
        _sync_state["status"] = "running"
        _sync_state["started_at"] = datetime.now(timezone.utc).isoformat()
        _sync_state["finished_at"] = None
        _sync_state["result"] = None
        _sync_state["error"] = None
        _sync_state["steps_done"] = []
        t_start = time.time()

        try:
            from RecupDataStrava import sync_backfill
            n_new = sync_backfill(after_date=after_date)
            _sync_state["steps_done"].append("backfill")

            if n_new:
                from api.deps import invalidate_cache
                invalidate_cache(["activities"])

                # Relancer l'analyse sur les nouvelles activités
                try:
                    from run_analysis import run_analysis
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        run_analysis()
                    _sync_state["steps_done"].append("analysis")
                    invalidate_cache(["activities", "metrics"])
                except Exception as e:
                    _sync_state["steps_done"].append(f"analysis:error:{e}")

            duration = round(time.time() - t_start, 1)
            _sync_state["status"] = "idle"
            _sync_state["result"] = {
                "new_activities": n_new,
                "steps_run": ["backfill", "analysis"],
                "duration_s": duration,
            }
        except Exception as e:
            _sync_state["status"] = "error"
            _sync_state["error"] = str(e)
            _sync_state["result"] = {"duration_s": round(time.time() - t_start, 1)}
        finally:
            _sync_state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _sync_lock.release()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"status": "running", "after_date": after_date}


@router.get("/sync/status")
def sync_status():
    """Retourne l'état courant enrichi de la synchronisation."""
    file_state = _load_file_state()
    config = _load_config()
    interval_min = config.get("auto_sync_interval_minutes", 30)

    # Âge du dernier sync
    last_sync_ago_minutes = None
    last_sync = file_state.get("pipeline_last_full_run") or file_state.get("analysis_last_run")
    if last_sync:
        try:
            last_dt = datetime.fromisoformat(last_sync)
            now = datetime.now(timezone.utc)
            last_sync_ago_minutes = round((now - last_dt).total_seconds() / 60, 1)
        except (ValueError, TypeError):
            pass

    # Pipeline status par étape
    garmin_needs, garmin_reason = _needs_garmin_sync(file_state, interval_min)
    strava_needs, strava_reason = _needs_strava_sync(file_state, interval_min)
    matching_needs, matching_reason = _needs_matching(
        file_state,
        file_state.get("strava_activities_total", 0),
        file_state.get("garmin_activities_total", 0),
    )
    gps_needs, gps_reason = _needs_strava_gps(file_state)
    analysis_needs, analysis_reason = _needs_analysis(file_state)

    pipeline_status = {
        "garmin": {
            "last_run": file_state.get("garmin_last_sync"),
            "needs_update": garmin_needs,
            "reason": garmin_reason,
        },
        "strava": {
            "last_run": file_state.get("strava_last_sync"),
            "needs_update": strava_needs,
            "reason": strava_reason,
        },
        "matching": {
            "last_run": file_state.get("matching_last_run"),
            "needs_update": matching_needs,
            "reason": matching_reason,
        },
        "strava_gps": {
            "last_run": file_state.get("strava_gps_last_sync"),
            "needs_update": gps_needs,
            "reason": gps_reason,
        },
        "analysis": {
            "last_run": file_state.get("analysis_last_run"),
            "needs_update": analysis_needs,
            "reason": analysis_reason,
        },
    }

    return {
        "sync_in_progress": _sync_state["status"] == "running",
        "status": _sync_state["status"],
        "last_sync": last_sync,
        "last_sync_ago_minutes": last_sync_ago_minutes,
        "activities_total": file_state.get("strava_activities_total"),
        "garmin_activities_total": file_state.get("garmin_activities_total"),
        "pipeline_status": pipeline_status,
        "last_result": _sync_state["result"],
        "last_error": _sync_state["error"],
        "steps_done": _sync_state["steps_done"],
        "started_at": _sync_state["started_at"],
        "finished_at": _sync_state["finished_at"],
    }


# ── Auto-sync au démarrage ────────────────────────────────────────────────────

def maybe_auto_sync(config: dict) -> bool:
    """
    Vérifie si un sync automatique est nécessaire (dernier sync > seuil).
    Si oui, lance le sync en background et retourne True.
    """
    interval = config.get("auto_sync_interval_minutes", 30)
    if interval <= 0:
        return False

    file_state = _load_file_state()
    last = file_state.get("pipeline_last_full_run") or file_state.get("analysis_last_run")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            if age_min < interval:
                return False
        except (ValueError, TypeError):
            pass

    if _sync_state["status"] == "running":
        return False
    if not _sync_lock.acquire(blocking=False):
        return False

    def _run():
        try:
            _run_pipeline()
        finally:
            _sync_lock.release()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return True
