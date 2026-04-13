"""
api/routes/sync.py — Synchronisation incrémentale intelligente (multi-user).

POST /api/sync       → lance le pipeline en background, retourne 202
GET  /api/sync/status → état courant enrichi (pipeline_status par étape)

Le pipeline ne relance que les étapes nécessaires en comparant
sync_state.json avant/après chaque step.

Toutes les données sont lues et écrites dans data/users/{user_id}/.
"""

import json
import io
import logging
import os
import sys
import threading
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends

from api.dependencies import get_current_user
from api.user_data import UserPaths, get_user_paths
from api.auth import get_garmin_credentials, get_user_profile
from api.strava_oauth import get_valid_access_token
from api import storage

logger = logging.getLogger("coachagent.sync")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Rendre les modules pipeline importables
sys.path.insert(0, os.path.join(_ROOT, "appelAPIs"))
sys.path.insert(0, os.path.join(_ROOT, "analyse"))

router = APIRouter(prefix="/api", tags=["sync"])

# ── État interne du sync (per-user) ─────────────────────────────────────────

_sync_locks: dict[str, threading.Lock] = {}   # user_id → Lock
_sync_states: dict[str, dict] = {}            # user_id → state dict
_active_threads: list[threading.Thread] = []  # for graceful shutdown
_threads_lock = threading.Lock()


def _start_sync_thread(target, name: str = "sync") -> threading.Thread:
    """Start a non-daemon sync thread and track it for graceful shutdown."""
    thread = threading.Thread(target=target, name=name, daemon=False)
    with _threads_lock:
        # Prune finished threads
        _active_threads[:] = [t for t in _active_threads if t.is_alive()]
        _active_threads.append(thread)
    thread.start()
    return thread


def wait_for_sync_threads(timeout: float = 30.0):
    """Wait for all active sync threads to finish. Called during shutdown."""
    with _threads_lock:
        threads = list(_active_threads)
    if not threads:
        return
    logger.info("Waiting for %d sync thread(s) to finish (timeout=%ds)...", len(threads), timeout)
    deadline = time.time() + timeout
    for t in threads:
        remaining = max(0, deadline - time.time())
        t.join(timeout=remaining)
        if t.is_alive():
            logger.warning("Sync thread %s did not finish within timeout", t.name)

def _get_sync_lock(user_id: str) -> threading.Lock:
    if user_id not in _sync_locks:
        _sync_locks[user_id] = threading.Lock()
    return _sync_locks[user_id]

def _get_sync_state(user_id: str) -> dict:
    if user_id not in _sync_states:
        _sync_states[user_id] = {
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
            "steps_done": [],
            "user_id": user_id,
        }
    return _sync_states[user_id]


# ── Lecture/écriture sync_state.json (user-scoped) ──────────────────────────

def _load_file_state(paths: UserPaths) -> dict:
    p = paths.sync_state_json
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_file_state(paths: UserPaths, state: dict) -> None:
    p = paths.sync_state_json
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _load_config(paths: UserPaths) -> dict:
    p = paths.config_json
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _sync_age_minutes(state: dict, key: str) -> float | None:
    ts = state.get(key)
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60
    except (ValueError, TypeError):
        return None


def _count_csv_rows(paths: UserPaths) -> int:
    p = paths.strava_csv
    if not os.path.exists(p):
        return 0
    try:
        # Compter les lignes sans charger tout le DataFrame
        with open(p, encoding="utf-8-sig") as f:
            return sum(1 for _ in f) - 1  # -1 pour le header
    except Exception:
        return 0


# ── Génération CSV depuis Garmin (fallback sans Strava) ──────────────────────

def _generate_csv_from_garmin(garmin_index_path: str, csv_path: str):
    """
    Génère un CSV d'activités au format Strava depuis l'index Garmin.
    Utilisé quand l'utilisateur n'a pas connecté Strava mais a Garmin.
    """
    with open(garmin_index_path, encoding="utf-8") as f:
        garmin_acts = json.load(f)

    if not garmin_acts:
        return

    rows = []
    for act in garmin_acts:
        distance_km = act.get("distance_m", 0) / 1000
        duration_min = act.get("duration_s", 0) / 60
        pace = duration_min / distance_km if distance_km > 0 else None

        rows.append({
            "ID": act.get("garmin_id"),
            "Nom": act.get("name", ""),
            "Date": act.get("start_time_utc", ""),
            "Distance (km)": round(distance_km, 2),
            "Temps (min)": round(duration_min, 1),
            "Allure (min/km)": round(pace, 2) if pace else None,
            "Dénivelé (m)": act.get("elevation_gain_m", 0),
            "Fréquence cardiaque (bpm)": act.get("avg_hr"),
            "Type": act.get("sport_type", ""),
            "Commentaire": "",
        })

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"], format="mixed", utc=True)
    df = df.sort_values("Date", ascending=True)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[sync] Généré CSV depuis Garmin : {len(df)} activités → {csv_path}")


# ── Logique de décision ──────────────────────────────────────────────────────

def _needs_garmin_sync(state: dict, interval_min: float) -> tuple[bool, str]:
    age = _sync_age_minutes(state, "garmin_last_sync")
    if age is None:
        return True, "jamais synchronisé"
    if age > interval_min:
        return True, f"dernière sync il y a {age:.0f} min (seuil {interval_min:.0f})"
    return False, "à jour"


def _needs_strava_sync(state: dict, interval_min: float, paths: UserPaths) -> tuple[bool, str]:
    age = _sync_age_minutes(state, "strava_last_sync")
    if age is None:
        return True, "jamais synchronisé"
    if age > interval_min:
        return True, f"dernière sync il y a {age:.0f} min (seuil {interval_min:.0f})"
    csv_count = _count_csv_rows(paths)
    state_count = state.get("strava_activities_total", 0)
    if csv_count > state_count:
        return True, f"CSV a {csv_count} lignes vs {state_count} dans sync_state"
    return False, "à jour"


def _needs_matching(state: dict, prev_strava_total: int, prev_garmin_total: int) -> tuple[bool, str]:
    strava_total = state.get("strava_activities_total", 0)
    garmin_total = state.get("garmin_activities_total", 0)
    if strava_total != prev_strava_total:
        return True, f"strava {prev_strava_total} → {strava_total}"
    if garmin_total != prev_garmin_total:
        return True, f"garmin {prev_garmin_total} → {garmin_total}"
    if not state.get("matching_last_run"):
        return True, "jamais exécuté"
    return False, "aucun changement"


def _needs_strava_gps(state: dict, paths: UserPaths | None = None) -> tuple[bool, str]:
    total = state.get("strava_activities_total", 0)
    if total == 0:
        return False, "aucune activité"

    # Count actual GPS files on disk instead of relying on counters
    # (counters can double-count activities covered by both Garmin and Strava)
    if paths is not None:
        try:
            strava_csv = paths.strava_csv
            if os.path.exists(strava_csv):
                df = pd.read_csv(strava_csv)
                all_ids = df["ID"].astype(int).tolist()

                garmin_map = {}
                if os.path.exists(paths.garmin_map_json):
                    with open(paths.garmin_map_json, encoding="utf-8") as f:
                        garmin_map = json.load(f)

                # List all files once (1-2 R2 calls) instead of per-activity checks
                garmin_stream_files = set(storage.listdir(paths.garmin_streams_dir))
                gps_files = set(storage.listdir(paths.gps_dir))

                missing = 0
                for sid in all_ids:
                    has_garmin = False
                    garmin_id = garmin_map.get(str(sid))
                    if garmin_id:
                        has_garmin = f"{garmin_id}.json" in garmin_stream_files
                    has_matched = f"{sid}.json" in gps_files
                    has_strava = f"strava_{sid}.json" in gps_files
                    if not has_garmin and not has_matched and not has_strava:
                        missing += 1

                if missing > 0:
                    return True, f"{missing} activités sans GPS"
                return False, "toutes couvertes"
        except Exception:
            pass

    # Fallback to counter-based check
    garmin_streams = state.get("garmin_streams_synced", 0)
    strava_gps = state.get("strava_gps_synced", 0)
    covered = garmin_streams + strava_gps
    if total > covered:
        gap = total - covered
        return True, f"{gap} activités sans GPS"
    return False, "toutes couvertes"


def _needs_analysis(state: dict, paths: UserPaths) -> tuple[bool, str]:
    csv_count = _count_csv_rows(paths)
    analysis_count = state.get("analysis_activities_count", 0)
    if csv_count > analysis_count:
        return True, f"{csv_count - analysis_count} nouvelles activités (CSV={csv_count}, analysées={analysis_count})"
    if not state.get("analysis_last_run"):
        return True, "jamais exécuté"
    return False, "à jour"


# ── Matching local Garmin ↔ Strava (user-scoped) ────────────────────────────

def match_strava_garmin(paths: UserPaths) -> dict:
    """
    Match Garmin → Strava en mémoire (aucun appel API).
    Toutes les données sont lues/écrites dans les chemins de l'utilisateur.
    """
    garmin_index = paths.garmin_activities_json
    strava_csv = paths.strava_csv
    garmin_streams = paths.garmin_streams_dir
    gps_dir = paths.gps_dir
    garmin_map_path = paths.garmin_map_json

    if not os.path.exists(garmin_index) or not os.path.exists(strava_csv):
        return {"matched": 0, "already_matched": 0, "unmatched_garmin": 0}

    with open(garmin_index, encoding="utf-8") as f:
        garmin_acts = json.load(f)

    strava_df = pd.read_csv(strava_csv)
    if strava_df.empty:
        return {"matched": 0, "already_matched": 0, "unmatched_garmin": 0}

    strava_df["_date"] = pd.to_datetime(strava_df["Date"], utc=True)
    strava_df["_dur_s"] = strava_df["Temps (min)"].astype(float) * 60.0
    strava_df["_dist_m"] = strava_df["Distance (km)"].astype(float) * 1000.0

    garmin_map = {}
    if os.path.exists(garmin_map_path):
        with open(garmin_map_path, encoding="utf-8") as f:
            garmin_map = json.load(f)

    existing_gps = set()
    for fname in storage.listdir(gps_dir):
        stem, ext = os.path.splitext(fname)
        if ext == ".json" and stem.isdigit():
            existing_gps.add(int(stem))

    matched = 0
    already_matched = 0
    os.makedirs(gps_dir, exist_ok=True)

    used_strava_ids = set(existing_gps)

    # Pre-load garmin stream filenames (1 R2 call instead of N)
    garmin_stream_files = set(storage.listdir(garmin_streams))

    # Pré-calculer les arrays numpy pour le matching vectorisé
    strava_ids = strava_df["ID"].astype(int).values
    strava_dates_epoch = strava_df["_date"].astype("int64").values // 10**9  # epoch seconds
    strava_dur = strava_df["_dur_s"].values
    strava_dist = strava_df["_dist_m"].values

    for gact in garmin_acts:
        gid = int(gact.get("garmin_id", 0))
        if gid == 0:
            continue

        if f"{gid}.json" not in garmin_stream_files:
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
        g_epoch = int(g_date.timestamp())

        # Matching vectorisé : filtrer d'un coup au lieu de boucler
        mask_available = np.array([sid not in used_strava_ids for sid in strava_ids])
        dt_diffs = np.abs(strava_dates_epoch - g_epoch)
        dur_diffs = np.abs(strava_dur - g_dur_s)
        dist_diffs = np.abs(strava_dist - g_dist_m)

        mask = mask_available & (dt_diffs <= 14400) & (dur_diffs <= 120) & (dist_diffs <= 200)

        if not mask.any():
            continue

        # Parmi les candidats, prendre celui avec le plus petit écart temporel
        candidates_idx = np.where(mask)[0]
        best_idx = candidates_idx[np.argmin(dt_diffs[candidates_idx])]
        best_strava_id = int(strava_ids[best_idx])

        if best_strava_id in existing_gps:
            already_matched += 1
            continue

        stream_data = storage.read_json(stream_path)
        if stream_data is None:
            continue

        gps_data = {
            "strava_id": best_strava_id,
            "garmin_id": gid,
            "points": stream_data.get("points", []),
        }
        gps_path = os.path.join(gps_dir, f"{best_strava_id}.json")
        storage.write_json(gps_path, gps_data)

        garmin_map[str(best_strava_id)] = gid
        used_strava_ids.add(best_strava_id)
        matched += 1

    os.makedirs(os.path.dirname(garmin_map_path), exist_ok=True)
    with open(garmin_map_path, "w", encoding="utf-8") as f:
        json.dump(garmin_map, f, indent=2, ensure_ascii=False)

    unmatched = sum(
        1 for g in garmin_acts
        if int(g.get("garmin_id", 0)) != 0
        and f"{int(g['garmin_id'])}.json" in garmin_stream_files
        and str(int(g["garmin_id"])) not in {str(v) for v in garmin_map.values()}
    )

    file_state = _load_file_state(paths)
    file_state["matching_last_run"] = datetime.now(timezone.utc).isoformat()
    _save_file_state(paths, file_state)

    return {"matched": matched, "already_matched": already_matched, "unmatched_garmin": unmatched}


# ── Pipeline sync incrémental (user-scoped) ─────────────────────────────────

def _run_pipeline(user_id: str):
    """Exécute le pipeline en background — ne relance que les étapes nécessaires."""
    ss = _get_sync_state(user_id)

    paths = get_user_paths(user_id)
    data_dir = paths.base

    # Per-user credentials
    access_token = get_valid_access_token(user_id)  # str or None
    garmin_creds = get_garmin_credentials(user_id)   # dict or None

    if access_token:
        print(f"[sync:{user_id}] Strava token OK (via OAuth)")
    else:
        print(f"[sync:{user_id}] WARNING: No valid Strava token — Strava steps will be skipped")

    ss["status"] = "running"
    ss["started_at"] = datetime.now(timezone.utc).isoformat()
    ss["finished_at"] = None
    ss["result"] = None
    ss["error"] = None
    ss["steps_done"] = []

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

    config = _load_config(paths)
    interval_min = config.get("auto_sync_interval_minutes", 30)

    try:
        state_before = _load_file_state(paths)
        prev_strava_total = state_before.get("strava_activities_total", 0)
        prev_garmin_total = state_before.get("garmin_activities_total", 0)

        # ── Étape 1 : Garmin sync ────────────────────────────────────────
        if not garmin_creds:
            result["steps_skipped"].append({"step": "garmin", "reason": "pas de credentials Garmin configurées"})
        else:
            need, reason = _needs_garmin_sync(state_before, interval_min)
            if need:
                try:
                    from sync_garmin import sync_all
                    with redirect_stdout(buf):
                        sync_all(data_dir=data_dir, garth_dir=paths.garth_dir,
                                 garmin_creds=garmin_creds)
                    ss["steps_done"].append("garmin")
                    result["steps_run"].append("garmin")
                    from api.deps import invalidate_cache
                    invalidate_cache(["gps"], user_id=user_id)
                except SystemExit:
                    ss["steps_done"].append("garmin:auth_failed")
                    result["steps_run"].append("garmin")
                except Exception as e:
                    logger.error("[sync:%s] Garmin error: %s", user_id, e, exc_info=True)
                    ss["steps_done"].append(f"garmin:error:{e}")
                    result["steps_run"].append("garmin")
            else:
                result["steps_skipped"].append({"step": "garmin", "reason": reason})

        state_after_garmin = _load_file_state(paths)

        # ── Étape 2 : Matching Garmin → Strava ──────────────────────────
        need, reason = _needs_matching(state_after_garmin, prev_strava_total, prev_garmin_total)
        if need:
            try:
                match_result = match_strava_garmin(paths)
                result["new_gps_matches"] = match_result["matched"]
                ss["steps_done"].append("matching")
                result["steps_run"].append("matching")
                from api.deps import invalidate_cache
                invalidate_cache(["gps"], user_id=user_id)
            except Exception as e:
                logger.error("[sync:%s] Matching error: %s", user_id, e, exc_info=True)
                ss["steps_done"].append(f"matching:error:{e}")
                result["steps_run"].append("matching")
        else:
            result["steps_skipped"].append({"step": "matching", "reason": reason})

        # ── Étape 2b : Générer CSV depuis Garmin si pas de Strava ET pas de CSV existant
        if not access_token:
            garmin_index = paths.garmin_activities_json
            csv_exists = os.path.exists(paths.strava_csv) and os.path.getsize(paths.strava_csv) > 100
            if os.path.exists(garmin_index) and not csv_exists:
                try:
                    _generate_csv_from_garmin(garmin_index, paths.strava_csv)
                    ss["steps_done"].append("garmin_to_csv")
                    result["steps_run"].append("garmin_to_csv")
                    from api.deps import invalidate_cache
                    invalidate_cache(["activities"], user_id=user_id)
                except Exception as e:
                    ss["steps_done"].append(f"garmin_to_csv:error:{e}")
            elif csv_exists:
                result["steps_skipped"].append({"step": "garmin_to_csv", "reason": "CSV déjà existant (ne pas écraser les données Strava)"})

        # ── Étape 3 : Strava activités ───────────────────────────────────
        if not access_token:
            result["steps_skipped"].append({"step": "strava", "reason": "pas de token Strava (connecter Strava dans Settings)"})
        else:
            need, reason = _needs_strava_sync(state_before, interval_min, paths)
            if need:
                try:
                    from RecupDataStrava import sync_activities, StravaAuthError
                    with redirect_stdout(buf):
                        n_new = sync_activities(data_dir=data_dir, access_token=access_token)
                    result["new_activities"] = n_new or 0
                    ss["steps_done"].append("strava")
                    result["steps_run"].append("strava")
                    if n_new:
                        from api.deps import invalidate_cache
                        invalidate_cache(["activities"], user_id=user_id)
                except StravaAuthError:
                    logger.warning("[sync:%s] Strava token expired/revoked — activities skipped", user_id)
                    ss["steps_done"].append("strava:auth_expired")
                    result["steps_run"].append("strava")
                    result["strava_auth_error"] = (
                        "Votre connexion Strava a expiré. "
                        "Veuillez reconnecter Strava dans les paramètres de votre compte."
                    )
                    # Token invalide → inutile de continuer les étapes Strava
                    access_token = None
                except Exception as e:
                    logger.error("[sync:%s] Strava error: %s", user_id, e, exc_info=True)
                    ss["steps_done"].append(f"strava:error:{e}")
                    result["steps_run"].append("strava")
            else:
                result["steps_skipped"].append({"step": "strava", "reason": reason})

        # ── Étape 4 : Strava streams (FC, allure) ────────────────────────
        if not access_token:
            result["steps_skipped"].append({"step": "strava_streams", "reason": "pas de token Strava"})
        else:
            try:
                # Count streams before to detect new ones
                streams_before = len([f for f in storage.listdir(paths.streams_dir) if f.endswith('.csv')])
                from get_streams import sync_all_streams, StravaAuthError
                with redirect_stdout(buf):
                    sync_all_streams(data_dir=data_dir, access_token=access_token)
                streams_after = len([f for f in storage.listdir(paths.streams_dir) if f.endswith('.csv')])
                ss["steps_done"].append("strava_streams")
                result["steps_run"].append("strava_streams")
                result["new_streams"] = streams_after - streams_before
                # Force re-analysis if new streams were fetched (zones FC need recomputation)
                if streams_after > streams_before:
                    file_state = _load_file_state(paths)
                    file_state["analysis_activities_count"] = 0
                    _save_file_state(paths, file_state)
                    print(f"[sync:{user_id}] {streams_after - streams_before} new streams → forcing re-analysis")
            except StravaAuthError:
                logger.warning("[sync:%s] Strava token expired/revoked — streams skipped", user_id)
                ss["steps_done"].append("strava_streams:auth_expired")
                result["steps_run"].append("strava_streams")
                result["strava_auth_error"] = (
                    "Votre connexion Strava a expiré. "
                    "Veuillez reconnecter Strava dans les paramètres de votre compte."
                )
            except Exception as e:
                logger.error("[sync:%s] Strava streams error: %s", user_id, e, exc_info=True)
                ss["steps_done"].append(f"strava_streams:error:{e}")
                result["steps_run"].append("strava_streams")

        # ── Étape 5 : Re-match si nouvelles activités Strava ─────────────
        if result["new_activities"] > 0:
            try:
                match2 = match_strava_garmin(paths)
                result["new_gps_matches"] += match2["matched"]
                ss["steps_done"].append("rematch")
                result["steps_run"].append("rematch")
                if match2["matched"] > 0:
                    from api.deps import invalidate_cache
                    invalidate_cache(["gps"], user_id=user_id)
            except Exception as e:
                ss["steps_done"].append(f"rematch:error:{e}")

        # ── Étape 6 : GPS Strava fallback ────────────────────────────────
        if not access_token:
            result["steps_skipped"].append({"step": "strava_gps", "reason": "pas de token Strava"})
        else:
            state_now = _load_file_state(paths)
            need, reason = _needs_strava_gps(state_now, paths)
            if need:
                try:
                    from sync_strava_gps import sync_all as sync_strava_gps_all
                    with redirect_stdout(buf):
                        strava_gps_result = sync_strava_gps_all(data_dir=data_dir, access_token=access_token)
                    result["strava_gps_fetched"] = strava_gps_result.get("strava_fetched", 0)
                    ss["steps_done"].append("strava_gps")
                    result["steps_run"].append("strava_gps")
                    if result["strava_gps_fetched"] > 0:
                        from api.deps import invalidate_cache
                        invalidate_cache(["gps"], user_id=user_id)
                except Exception as e:
                    logger.error("[sync:%s] Strava GPS error: %s", user_id, e, exc_info=True)
                    ss["steps_done"].append(f"strava_gps:error:{e}")
                    result["steps_run"].append("strava_gps")
            else:
                result["steps_skipped"].append({"step": "strava_gps", "reason": reason})

        # ── Étape 7 : Analyse GPS (métriques Garmin) ─────────────────────
        try:
            from run_gps_analysis import run_gps_analysis
            with redirect_stdout(buf):
                run_gps_analysis(data_dir=data_dir)
            ss["steps_done"].append("gps_analysis")
            result["steps_run"].append("gps_analysis")
        except Exception as e:
            logger.error("[sync:%s] GPS analysis error: %s", user_id, e, exc_info=True)
            ss["steps_done"].append(f"gps_analysis:error:{e}")
            result["steps_run"].append("gps_analysis")

        # ── Étape 7b : Sync profil utilisateur → config.json ──────────
        try:
            config = _load_config(paths)
            athlete = config.get("athlete", {})

            user_profile = get_user_profile(user_id) or {}
            if user_profile.get("hr_max"):
                athlete["hr_max"] = user_profile["hr_max"]
            if user_profile.get("hr_rest"):
                athlete["hr_rest"] = user_profile["hr_rest"]
            if user_profile.get("hr_threshold"):
                athlete["hr_threshold"] = user_profile["hr_threshold"]
            if user_profile.get("gender"):
                athlete["sex"] = user_profile["gender"]
            if user_profile.get("weight_kg"):
                athlete["weight_kg"] = user_profile["weight_kg"]

            # Custom zones
            custom_zones = []
            for i in range(1, 6):
                val = user_profile.get(f"hr_z{i}_max")
                if val:
                    custom_zones.append(val)
            if len(custom_zones) == 5:
                athlete["hr_zones_custom"] = custom_zones

            config["athlete"] = athlete
            os.makedirs(os.path.dirname(paths.config_json), exist_ok=True)
            with open(paths.config_json, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Non-blocking

        # ── Étape 8 : Analyse enrichie ───────────────────────────────────
        state_now = _load_file_state(paths)
        need, reason = _needs_analysis(state_now, paths)
        if need:
            try:
                from run_analysis import run_analysis
                with redirect_stdout(buf):
                    run_analysis(data_dir=data_dir, config_path=paths.config_json)
                ss["steps_done"].append("analysis")
                result["steps_run"].append("analysis")
                from api.deps import invalidate_cache
                invalidate_cache(["activities", "metrics"], user_id=user_id)
            except SystemExit:
                ss["steps_done"].append("analysis:exit")
                result["steps_run"].append("analysis")
            except Exception as e:
                logger.error("[sync:%s] Analysis error: %s", user_id, e, exc_info=True)
                ss["steps_done"].append(f"analysis:error:{e}")
                result["steps_run"].append("analysis")
        else:
            result["steps_skipped"].append({"step": "analysis", "reason": reason})

        # ── Finalisation ─────────────────────────────────────────────────
        result["duration_s"] = round(time.time() - t_start, 1)

        file_state = _load_file_state(paths)
        file_state["pipeline_last_full_run"] = datetime.now(timezone.utc).isoformat()
        file_state["pipeline_last_duration_s"] = result["duration_s"]
        _save_file_state(paths, file_state)

        ss["status"] = "idle"
        ss["result"] = result
        logger.info("[sync:%s] Pipeline finished in %.1fs — steps_run=%s, steps_skipped=%s",
                     user_id, result["duration_s"],
                     [s for s in result["steps_run"]],
                     [s.get("step", s) if isinstance(s, dict) else s for s in result["steps_skipped"]])
        logger.info("[sync:%s] Result: new_activities=%s, new_streams=%s, gps=%s",
                     user_id, result["new_activities"], result["new_streams"], result["strava_gps_fetched"])
        # Log captured stdout from sub-modules
        captured = buf.getvalue()
        if captured:
            for line in captured.strip().splitlines()[:50]:
                logger.info("[sync:%s] %s", user_id, line)

    except Exception as e:
        ss["status"] = "error"
        ss["error"] = str(e)
        result["duration_s"] = round(time.time() - t_start, 1)
        ss["result"] = result
        logger.error("[sync:%s] Pipeline CRASHED: %s", user_id, e, exc_info=True)

    finally:
        ss["finished_at"] = datetime.now(timezone.utc).isoformat()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/sync", status_code=202)
def trigger_sync(user: dict = Depends(get_current_user)):
    """Lance le pipeline de synchronisation en background."""
    user_id = user["id"]
    ss = _get_sync_state(user_id)
    lock = _get_sync_lock(user_id)

    if ss["status"] == "running":
        return {"status": "already_running", "started_at": ss["started_at"]}

    if not lock.acquire(blocking=False):
        return {"status": "already_running", "started_at": ss["started_at"]}

    def _run():
        try:
            _run_pipeline(user_id)
        finally:
            lock.release()

    _start_sync_thread(_run, name=f"sync-{user_id}")
    return {"status": "running"}


@router.post("/sync/backfill", status_code=202)
def trigger_backfill(after_date: str = "2023-01-01", user: dict = Depends(get_current_user)):
    """Lance un backfill Strava pour récupérer les activités anciennes."""
    user_id = user["id"]
    ss = _get_sync_state(user_id)
    lock = _get_sync_lock(user_id)

    if ss["status"] == "running":
        return {"status": "already_running", "started_at": ss["started_at"]}

    if not lock.acquire(blocking=False):
        return {"status": "already_running", "started_at": ss["started_at"]}

    paths = get_user_paths(user_id)
    data_dir = paths.base
    access_token = get_valid_access_token(user_id)

    if not access_token:
        lock.release()
        return {"error": "Pas de token Strava valide — connecter Strava dans Settings"}

    def _run():
        ss["status"] = "running"
        ss["started_at"] = datetime.now(timezone.utc).isoformat()
        ss["finished_at"] = None
        ss["result"] = None
        ss["error"] = None
        ss["steps_done"] = []
        t_start = time.time()

        try:
            from RecupDataStrava import sync_backfill
            n_new = sync_backfill(after_date=after_date, data_dir=data_dir, access_token=access_token)
            ss["steps_done"].append("backfill")

            if n_new:
                from api.deps import invalidate_cache
                invalidate_cache(["activities"], user_id=user_id)

                try:
                    from run_analysis import run_analysis
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        run_analysis(data_dir=data_dir, config_path=paths.config_json)
                    ss["steps_done"].append("analysis")
                    invalidate_cache(["activities", "metrics"], user_id=user_id)
                except Exception as e:
                    ss["steps_done"].append(f"analysis:error:{e}")

            duration = round(time.time() - t_start, 1)
            ss["status"] = "idle"
            ss["result"] = {
                "new_activities": n_new,
                "steps_run": ["backfill", "analysis"],
                "duration_s": duration,
            }
        except Exception as e:
            ss["status"] = "error"
            ss["error"] = str(e)
            ss["result"] = {"duration_s": round(time.time() - t_start, 1)}
        finally:
            ss["finished_at"] = datetime.now(timezone.utc).isoformat()
            lock.release()

    _start_sync_thread(_run, name=f"backfill-{user_id}")
    return {"status": "running", "after_date": after_date}


@router.get("/sync/status")
def sync_status(user: dict = Depends(get_current_user)):
    """Retourne l'état courant enrichi de la synchronisation."""
    paths = get_user_paths(user["id"])

    file_state = _load_file_state(paths)
    config = _load_config(paths)
    interval_min = config.get("auto_sync_interval_minutes", 30)

    last_sync_ago_minutes = None
    last_sync = file_state.get("pipeline_last_full_run") or file_state.get("analysis_last_run")
    if last_sync:
        try:
            last_dt = datetime.fromisoformat(last_sync)
            now = datetime.now(timezone.utc)
            last_sync_ago_minutes = round((now - last_dt).total_seconds() / 60, 1)
        except (ValueError, TypeError):
            pass

    garmin_needs, garmin_reason = _needs_garmin_sync(file_state, interval_min)
    strava_needs, strava_reason = _needs_strava_sync(file_state, interval_min, paths)
    matching_needs, matching_reason = _needs_matching(
        file_state,
        file_state.get("strava_activities_total", 0),
        file_state.get("garmin_activities_total", 0),
    )
    gps_needs, gps_reason = _needs_strava_gps(file_state, paths)
    analysis_needs, analysis_reason = _needs_analysis(file_state, paths)

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

    ss = _get_sync_state(user["id"])
    return {
        "sync_in_progress": ss["status"] == "running",
        "status": ss["status"],
        "last_sync": last_sync,
        "last_sync_ago_minutes": last_sync_ago_minutes,
        "activities_total": file_state.get("strava_activities_total"),
        "garmin_activities_total": file_state.get("garmin_activities_total"),
        "pipeline_status": pipeline_status,
        "last_result": ss["result"],
        "last_error": ss["error"],
        "steps_done": ss["steps_done"],
        "started_at": ss["started_at"],
        "finished_at": ss["finished_at"],
    }


# ── Auto-sync au démarrage ────────────────────────────────────────────────────

def _get_all_user_ids() -> list[str]:
    """Return all user IDs that have a data directory."""
    from api.user_data import _USERS_DIR
    if not os.path.isdir(_USERS_DIR):
        return []
    return [
        name for name in os.listdir(_USERS_DIR)
        if os.path.isdir(os.path.join(_USERS_DIR, name))
    ]


def maybe_auto_sync(config: dict) -> bool:
    """
    Vérifie si un sync automatique est nécessaire pour chaque utilisateur
    (dernier sync > seuil). Lance le sync en background pour ceux qui en ont besoin.
    Retourne True si au moins un sync a été lancé.
    """
    interval = config.get("auto_sync_interval_minutes", 30)
    if interval <= 0:
        return False

    launched_any = False
    for user_id in _get_all_user_ids():
        paths = UserPaths(user_id)
        if not paths.exists():
            continue

        file_state = _load_file_state(paths)
        last = file_state.get("pipeline_last_full_run") or file_state.get("analysis_last_run")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                if age_min < interval:
                    continue
            except (ValueError, TypeError):
                pass

        ss = _get_sync_state(user_id)
        lock = _get_sync_lock(user_id)
        if ss["status"] == "running":
            continue
        if not lock.acquire(blocking=False):
            continue

        def _run(uid=user_id, lk=lock):
            try:
                _run_pipeline(uid)
            finally:
                lk.release()

        _start_sync_thread(_run, name=f"autosync-{user_id}")
        launched_any = True

    return launched_any
