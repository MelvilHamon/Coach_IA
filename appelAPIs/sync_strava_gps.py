"""
sync_strava_gps.py — Sync GPS Strava pour les activités sans stream Garmin.

Toutes les fonctions acceptent un access_token pré-validé.

Boucle sur toutes les activités du CSV Strava :
1. Si Garmin stream existe (via strava_garmin_map.json) → skip
2. Si data/gps/strava_{id}.json existe déjà → skip
3. Sinon → fetch depuis l'API Strava
4. Sleep 0.5s entre chaque requête
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

_ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from api import storage

from get_strava_gps import fetch_strava_gps  # noqa: E402


def _has_garmin_stream(strava_id: int, garmin_map: dict, garmin_streams_dir: str) -> bool:
    garmin_id = garmin_map.get(str(strava_id))
    if not garmin_id:
        return False
    return storage.exists(os.path.join(garmin_streams_dir, f"{garmin_id}.json"))


def _has_garmin_gps(strava_id: int, gps_dir: str) -> bool:
    return storage.exists(os.path.join(gps_dir, f"{strava_id}.json"))


def _has_strava_gps(strava_id: int, gps_dir: str) -> bool:
    return storage.exists(os.path.join(gps_dir, f"strava_{strava_id}.json"))


def sync_all(force: bool = False, data_dir: str = None, access_token: str = None) -> dict:
    """
    Sync GPS Strava pour les activités non couvertes par Garmin.

    Parameters
    ----------
    force : re-télécharger même si les fichiers existent
    data_dir : répertoire de données utilisateur
    access_token : token Strava valide (obligatoire si des activités à fetch)
    """
    _data_dir = data_dir or os.path.join(_ROOT, "data")
    _csv_path = os.path.join(_data_dir, "mes_activites_strava.csv")
    _gps_dir = os.path.join(_data_dir, "gps")
    _garmin_map = os.path.join(_data_dir, "garmin", "strava_garmin_map.json")
    _garmin_streams = os.path.join(_data_dir, "garmin", "streams")
    _sync_state = os.path.join(_data_dir, "sync_state.json")

    if not os.path.exists(_csv_path):
        print(f"Fichier activités introuvable : {_csv_path}")
        return {"total": 0, "garmin_covered": 0, "strava_fetched": 0,
                "strava_existing": 0, "no_gps": 0, "errors": 0}

    df = pd.read_csv(_csv_path)
    all_ids = df["ID"].astype(int).tolist()

    # Charger le mapping Garmin
    garmin_map = {}
    if os.path.exists(_garmin_map):
        with open(_garmin_map, encoding="utf-8") as f:
            garmin_map = json.load(f)

    garmin_covered = 0
    strava_existing = 0
    strava_fetched = 0
    no_gps = 0
    errors = 0

    to_fetch = []
    for sid in all_ids:
        if _has_garmin_stream(sid, garmin_map, _garmin_streams) or _has_garmin_gps(sid, _gps_dir):
            garmin_covered += 1
        elif _has_strava_gps(sid, _gps_dir) and not force:
            strava_existing += 1
        else:
            to_fetch.append(sid)

    if to_fetch and not access_token:
        print("Pas de token Strava — impossible de récupérer les GPS.")
        return {"total": len(all_ids), "garmin_covered": garmin_covered,
                "strava_fetched": 0, "strava_existing": strava_existing,
                "no_gps": len(to_fetch), "errors": 0}

    for i, sid in enumerate(to_fetch, 1):
        try:
            result = fetch_strava_gps(sid, access_token=access_token, force=force,
                                       gps_dir=_gps_dir)
            if result:
                strava_fetched += 1
                print(f"  [{i}/{len(to_fetch)}] {sid} — {len(result['points'])} points GPS")
            else:
                no_gps += 1
                print(f"  [{i}/{len(to_fetch)}] {sid} — pas de GPS Strava")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(to_fetch)}] {sid} — ERREUR : {e}")

        # Le rate limiter dans get_strava_gps gère le délai automatiquement

    # Mise à jour sync_state.json
    state = {}
    if os.path.exists(_sync_state):
        with open(_sync_state, encoding="utf-8") as f:
            state = json.load(f)
    state["strava_gps_last_sync"] = datetime.now(timezone.utc).isoformat()
    state["strava_gps_synced"] = strava_fetched + strava_existing
    os.makedirs(os.path.dirname(_sync_state), exist_ok=True)
    with open(_sync_state, "w", encoding="utf-8") as f:
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
""")

    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Usage: ce module est appelé par le pipeline sync.py")
    print("Les tokens sont gérés par api/strava_oauth.py")
