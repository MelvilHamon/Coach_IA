"""
sync_strava_gps.py — Sync GPS Strava pour les activités sans stream Garmin.

Boucle sur toutes les activités du CSV Strava :
1. Si Garmin stream existe (via strava_garmin_map.json) → skip
2. Si data/gps/strava_{id}.json existe déjà → skip
3. Sinon → fetch depuis l'API Strava
4. Sleep 0.5s entre chaque requête

Usage :
    python3 appelAPIs/sync_strava_gps.py
    python3 appelAPIs/sync_strava_gps.py --force   # re-télécharge tout
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

_ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CSV_PATH      = os.path.join(_ROOT, "data", "mes_activites_strava.csv")
_GPS_DIR       = os.path.join(_ROOT, "data", "gps")
_GARMIN_MAP    = os.path.join(_ROOT, "data", "garmin", "strava_garmin_map.json")
_GARMIN_STREAMS = os.path.join(_ROOT, "data", "garmin", "streams")
_SYNC_STATE    = os.path.join(_ROOT, "data", "sync_state.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from get_strava_gps import fetch_strava_gps, _get_access_token  # noqa: E402


def _has_garmin_stream(strava_id: int, garmin_map: dict) -> bool:
    """Vérifie si l'activité a un stream Garmin disponible."""
    garmin_id = garmin_map.get(str(strava_id))
    if not garmin_id:
        return False
    return os.path.exists(os.path.join(_GARMIN_STREAMS, f"{garmin_id}.json"))


def _has_garmin_gps(strava_id: int) -> bool:
    """Vérifie si un fichier GPS matché depuis Garmin existe."""
    return os.path.exists(os.path.join(_GPS_DIR, f"{strava_id}.json"))


def _has_strava_gps(strava_id: int) -> bool:
    """Vérifie si un fichier GPS Strava existe déjà."""
    return os.path.exists(os.path.join(_GPS_DIR, f"strava_{strava_id}.json"))


def sync_all(force: bool = False) -> dict:
    """
    Sync GPS Strava pour les activités non couvertes par Garmin.

    Retourne {"total", "garmin_covered", "strava_fetched", "strava_existing",
              "no_gps", "errors"}.
    """
    if not os.path.exists(_CSV_PATH):
        print(f"Fichier activités introuvable : {_CSV_PATH}")
        return {"total": 0, "garmin_covered": 0, "strava_fetched": 0,
                "strava_existing": 0, "no_gps": 0, "errors": 0}

    df = pd.read_csv(_CSV_PATH)
    all_ids = df["ID"].astype(int).tolist()

    # Charger le mapping Garmin
    garmin_map = {}
    if os.path.exists(_GARMIN_MAP):
        with open(_GARMIN_MAP, encoding="utf-8") as f:
            garmin_map = json.load(f)

    garmin_covered = 0
    strava_existing = 0
    strava_fetched = 0
    no_gps = 0
    errors = 0

    # Token Strava (un seul refresh pour tout le batch)
    access_token = None
    needs_token = False

    # Premier passage : compter et identifier ceux qui ont besoin d'un fetch
    to_fetch = []
    for sid in all_ids:
        if _has_garmin_stream(sid, garmin_map) or _has_garmin_gps(sid):
            garmin_covered += 1
        elif _has_strava_gps(sid) and not force:
            strava_existing += 1
        else:
            to_fetch.append(sid)

    # Token seulement si on a des activités à fetch
    if to_fetch:
        try:
            access_token = _get_access_token()
        except Exception as e:
            print(f"Erreur auth Strava : {e}")
            return {"total": len(all_ids), "garmin_covered": garmin_covered,
                    "strava_fetched": 0, "strava_existing": strava_existing,
                    "no_gps": len(to_fetch), "errors": 1}

    for i, sid in enumerate(to_fetch, 1):
        try:
            result = fetch_strava_gps(sid, access_token=access_token, force=force)
            if result:
                strava_fetched += 1
                print(f"  [{i}/{len(to_fetch)}] {sid} — {len(result['points'])} points GPS")
            else:
                no_gps += 1
                print(f"  [{i}/{len(to_fetch)}] {sid} — pas de GPS Strava")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(to_fetch)}] {sid} — ERREUR : {e}")

        time.sleep(0.5)

    # Mise à jour sync_state.json
    state = {}
    if os.path.exists(_SYNC_STATE):
        with open(_SYNC_STATE, encoding="utf-8") as f:
            state = json.load(f)
    state["strava_gps_last_sync"] = datetime.now(timezone.utc).isoformat()
    state["strava_gps_synced"] = strava_fetched + strava_existing
    with open(_SYNC_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    summary = {
        "total": len(all_ids),
        "garmin_covered": garmin_covered,
        "strava_fetched": strava_fetched,
        "strava_existing": strava_existing,
        "no_gps": no_gps,
        "errors": errors,
    }

    print(f"""
=== Sync GPS Strava ===
  Activités total         : {len(all_ids)}
  Déjà couvertes (Garmin) : {garmin_covered}
  Strava GPS récupérés    : {strava_fetched}
  Strava GPS existants    : {strava_existing}
  Sans GPS disponible     : {no_gps}
  Erreurs                 : {errors}
  → data/gps/strava_*.json
""")

    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _force = "--force" in sys.argv
    sync_all(force=_force)
