"""
sync_garmin.py — Synchronise toutes les activités Garmin de façon autonome.

Récupère la liste complète des activités Garmin, stocke l'index et les streams
GPS dans data/garmin/. Aucune dépendance à Strava — l'association se fait
en aval.

Structure de sortie :
  data/garmin/
    activities.json          ← index de toutes les activités
    streams/
      {garmin_id}.json       ← points GPS par activité

Usage :
    python3 appelAPIs/sync_garmin.py                  # nouvelles activités uniquement
    python3 appelAPIs/sync_garmin.py --force-streams  # re-télécharge tous les streams
    python3 appelAPIs/sync_garmin.py --limit 10       # test sur les 10 dernières
"""

import io
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# ── Chemins ────────────────────────────────────────────────────────────────────

_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GARMIN_DIR  = os.path.join(_ROOT, "data", "garmin")
_STREAMS_DIR = os.path.join(_GARMIN_DIR, "streams")
_INDEX_PATH  = os.path.join(_GARMIN_DIR, "activities.json")
_SYNC_STATE  = os.path.join(_ROOT, "data", "sync_state.json")

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Réutilisation depuis get_garmin_gps.py ─────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from get_garmin_gps import _garmin_login, _unwrap_download  # noqa: E402


# ── Parser GPX local (inclut altitude_m) ──────────────────────────────────────

def _parse_gpx_full(gpx_bytes: bytes) -> list:
    """
    Parse des bytes GPX → liste de dicts {lat, lon, time_s, altitude_m}.

    Étend _parse_gpx() de get_garmin_gps.py en ajoutant l'extraction de
    l'élément <ele> (altitude). Ne modifie pas le fichier d'origine.
    """
    try:
        root = ET.fromstring(gpx_bytes)
    except ET.ParseError:
        return []

    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    trkpts = root.findall(".//gpx:trkpt", ns)
    if not trkpts:
        return []

    points = []
    t0 = None
    for pt in trkpts:
        try:
            lat = float(pt.get("lat"))
            lon = float(pt.get("lon"))
        except (TypeError, ValueError):
            continue

        # Temps relatif depuis le premier point
        time_el = pt.find("gpx:time", ns)
        t_s = None
        if time_el is not None and time_el.text:
            try:
                t = datetime.fromisoformat(time_el.text.replace("Z", "+00:00"))
                if t0 is None:
                    t0 = t
                t_s = int((t - t0).total_seconds())
            except ValueError:
                pass

        # Altitude
        ele_el = pt.find("gpx:ele", ns)
        alt_m = None
        if ele_el is not None and ele_el.text:
            try:
                alt_m = round(float(ele_el.text), 1)
            except ValueError:
                pass

        points.append({"lat": lat, "lon": lon, "time_s": t_s, "altitude_m": alt_m})

    return points


# ── Extraction des champs d'activité ──────────────────────────────────────────

def _parse_activity(act: dict) -> dict:
    """Extrait les champs normalisés depuis un dict brut de l'API garminconnect."""
    avg_speed_ms = float(act.get("averageSpeed", 0) or 0)
    return {
        "garmin_id":        int(act.get("activityId", 0)),
        "name":             act.get("activityName", ""),
        "start_time_utc":   act.get("startTimeGMT", ""),
        "duration_s":       float(act.get("duration", 0) or 0),
        "distance_m":       float(act.get("distance", 0) or 0),
        "sport_type":       (act.get("activityType") or {}).get("typeKey", ""),
        "avg_hr":           act.get("averageHR"),
        "max_hr":           act.get("maxHR"),
        "elevation_gain_m": act.get("elevationGain"),
        "avg_speed_kmh":    round(avg_speed_ms * 3.6, 2),
        "calories":         act.get("calories"),
        "has_gps":          True,   # mis à jour après tentative de stream
        "stream_fetched":   False,
    }


# ── Index ─────────────────────────────────────────────────────────────────────

def _load_index() -> dict:
    """Charge activities.json → dict keyed by garmin_id (int)."""
    return _load_index_from(_INDEX_PATH)


def _load_index_from(index_path: str) -> dict:
    """Charge activities.json → dict keyed by garmin_id (int)."""
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            entries = json.load(f)
        return {int(e["garmin_id"]): e for e in entries}
    return {}


def _save_index(index: dict) -> None:
    _save_index_to(_INDEX_PATH, _GARMIN_DIR, index)


def _save_index_to(index_path: str, garmin_dir: str, index: dict) -> None:
    os.makedirs(garmin_dir, exist_ok=True)
    entries = sorted(index.values(), key=lambda e: e.get("start_time_utc", ""), reverse=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


# ── Sync state ────────────────────────────────────────────────────────────────

def _load_sync_state() -> dict:
    return _load_sync_state_from(_SYNC_STATE)


def _load_sync_state_from(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_sync_state(state: dict) -> None:
    _save_sync_state_to(_SYNC_STATE, state)


def _save_sync_state_to(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Pagination Garmin ─────────────────────────────────────────────────────────

def _fetch_all_activities(api, max_activities: int) -> list:
    """Récupère toutes les activités par blocs de 100."""
    all_acts = []
    start = 0
    while len(all_acts) < max_activities:
        limit = min(100, max_activities - len(all_acts))
        log.info("Récupération activités %d–%d…", start, start + limit - 1)
        try:
            batch = api.get_activities(start, limit)
        except Exception as e:
            log.error("Erreur lors de la récupération de la page %d : %s", start, e)
            break
        if not batch:
            break
        all_acts.extend(batch)
        start += len(batch)
        if len(batch) < limit:
            break
        time.sleep(0.3)
    return all_acts


# ── Téléchargement d'un stream ────────────────────────────────────────────────

def _fetch_stream(api, garmin_id: int, start_time_utc: str) -> list | None:
    """
    Télécharge le GPX d'une activité et retourne les points parsés.
    Retourne None si téléchargement impossible ou pas de trace GPS.
    """
    from garminconnect import Garmin as _G
    try:
        raw = api.download_activity(garmin_id, dl_fmt=_G.ActivityDownloadFormat.GPX)
    except Exception as e:
        log.warning("  garmin_id=%d — échec téléchargement GPX : %s", garmin_id, e)
        return None

    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    gpx_bytes = _unwrap_download(raw)
    if not gpx_bytes:
        return None

    return _parse_gpx_full(gpx_bytes) or None


# ── Sync principal ─────────────────────────────────────────────────────────────

def sync_all(max_activities: int = 1000, force_streams: bool = False,
             data_dir: str = None, garth_dir: str = None,
             garmin_creds: dict = None) -> None:
    """
    1. Charge l'index existant garmin/activities.json
    2. Récupère toutes les activités Garmin (pagination par blocs de 100)
    3. Pour chaque activité :
       a. Ajoute à l'index si absente
       b. Télécharge le stream GPS si absent (ou force_streams=True) et has_gps=True
       c. sleep(0.5) entre chaque téléchargement
    4. Sauvegarde l'index et sync_state.json

    Parameters
    ----------
    data_dir : répertoire de données utilisateur (défaut: data/)
    garth_dir : répertoire des tokens garth (défaut: .garth/)
    garmin_creds : dict avec email/password (optionnel, pour login initial)
    """
    # Resolve paths
    _garmin_dir = os.path.join(data_dir, "garmin") if data_dir else _GARMIN_DIR
    _streams_dir = os.path.join(_garmin_dir, "streams")
    _index_path = os.path.join(_garmin_dir, "activities.json")
    _sync_state = os.path.join(data_dir, "sync_state.json") if data_dir else _SYNC_STATE

    t_start = time.time()

    # Auth
    try:
        api = _garmin_login(garth_dir=garth_dir, garmin_creds=garmin_creds)
    except Exception as e:
        raise RuntimeError(f"Échec de l'authentification Garmin : {e}") from e

    # Création des répertoires
    os.makedirs(_streams_dir, exist_ok=True)

    # Chargement index existant
    index = _load_index_from(_index_path)
    known_ids = set(index.keys())
    log.info("Index existant : %d activités", len(known_ids))

    # Récupération de toutes les activités depuis l'API
    raw_activities = _fetch_all_activities(api, max_activities)
    log.info("%d activités récupérées depuis Garmin Connect", len(raw_activities))

    n_new = 0
    n_streams = 0
    n_no_gps = 0
    n_already_ok = 0

    for raw in raw_activities:
        parsed = _parse_activity(raw)
        gid = parsed["garmin_id"]
        if gid == 0:
            continue

        stream_path = os.path.join(_streams_dir, f"{gid}.json")

        # Nouvelle activité → ajout à l'index
        if gid not in known_ids:
            index[gid] = parsed
            n_new += 1

        entry = index[gid]

        # Décider si on tente le stream
        stream_exists = os.path.exists(stream_path)
        should_fetch = (
            entry.get("has_gps", True)
            and (not entry.get("stream_fetched", False) or force_streams)
            and not stream_exists
        ) or (force_streams and entry.get("has_gps", True))

        if not should_fetch:
            if stream_exists or not entry.get("has_gps", True):
                n_already_ok += 1
            continue

        # Téléchargement du stream GPS
        log.info("  Téléchargement stream garmin_id=%d (%s)…", gid, entry.get("name", ""))
        points = _fetch_stream(api, gid, entry.get("start_time_utc", ""))

        if points:
            stream_data = {
                "garmin_id":      gid,
                "start_time_utc": entry.get("start_time_utc", ""),
                "points":         points,
            }
            with open(stream_path, "w", encoding="utf-8") as f:
                json.dump(stream_data, f, indent=2, ensure_ascii=False)
            entry["has_gps"] = True
            entry["stream_fetched"] = True
            n_streams += 1
            log.info("    → %d points GPS stockés", len(points))
        else:
            entry["has_gps"] = False
            entry["stream_fetched"] = True
            n_no_gps += 1
            log.info("    → pas de trace GPS")

        time.sleep(0.5)

    # Sauvegarde index
    _save_index_to(_index_path, _garmin_dir, index)

    # Mise à jour sync_state.json
    n_streams_total = sum(1 for e in index.values() if e.get("stream_fetched") and e.get("has_gps"))
    state = _load_sync_state_from(_sync_state)
    state["garmin_activities_total"] = len(index)
    state["garmin_streams_synced"]   = n_streams_total
    state["garmin_last_sync"]        = datetime.now(timezone.utc).isoformat()
    _save_sync_state_to(_sync_state, state)

    elapsed = time.time() - t_start
    print(f"""
=== Sync Garmin terminé ===
  Activités total     : {len(index)}
  Nouvelles           : {n_new}
  Streams récupérés   : {n_streams}
  Sans GPS            : {n_no_gps}
  Déjà à jour         : {n_already_ok}
  Durée               : {elapsed:.0f}s
""")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Synchronise toutes les activités Garmin (index + streams GPS)."
    )
    parser.add_argument(
        "--force-streams",
        action="store_true",
        help="Re-télécharge les streams même s'ils existent déjà.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        metavar="N",
        help="Limite aux N dernières activités (défaut : 1000).",
    )
    args = parser.parse_args()

    sync_all(max_activities=args.limit, force_streams=args.force_streams)
