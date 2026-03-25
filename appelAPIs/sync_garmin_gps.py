"""
sync_garmin_gps.py — Synchronise les traces GPS Garmin pour toutes les activités.

Parcourt data/mes_activites_strava.csv, récupère la trace GPS Garmin
pour les activités sans fichier dans data/gps/.
Met à jour data/sync_state.json avec "gps_last_sync" et "gps_synced_count".

Usage :
    python3 appelAPIs/sync_garmin_gps.py [--force]
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

_ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CSV_PATH   = os.path.join(_ROOT, "data", "mes_activites_strava.csv")
_GPS_DIR    = os.path.join(_ROOT, "data", "gps")
_SYNC_STATE = os.path.join(_ROOT, "data", "sync_state.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from get_garmin_gps import fetch_gps_stream


# ── Sync state ────────────────────────────────────────────────────────────────

def _load_sync_state() -> dict:
    if os.path.exists(_SYNC_STATE):
        with open(_SYNC_STATE) as f:
            return json.load(f)
    return {}


def _save_sync_state(state: dict) -> None:
    with open(_SYNC_STATE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _already_synced_ids() -> set:
    if not os.path.exists(_GPS_DIR):
        return set()
    synced = set()
    for fname in os.listdir(_GPS_DIR):
        stem, ext = os.path.splitext(fname)
        if ext == ".json" and stem.isdigit():
            synced.add(int(stem))
    return synced


# ── Sync principal ────────────────────────────────────────────────────────────

def sync_all_gps(force: bool = False) -> None:
    """
    Récupère les traces GPS Garmin de toutes les activités du CSV
    qui n'ont pas encore de fichier dans data/gps/.
    """
    if not os.path.exists(_CSV_PATH):
        print(f"Fichier activités introuvable : {_CSV_PATH}")
        return

    df = pd.read_csv(_CSV_PATH)

    required = {"ID", "Date", "Temps (min)", "Distance (km)"}
    missing  = required - set(df.columns)
    if missing:
        print(f"Colonnes manquantes dans le CSV : {missing}")
        return

    already_done = _already_synced_ids() if not force else set()
    to_fetch     = df[~df["ID"].astype(int).isin(already_done)].copy()
    total        = len(to_fetch)

    if total == 0:
        print("Toutes les traces GPS sont déjà synchronisées.")
        return

    print(f"{total} activité(s) à synchroniser (sur {len(df)} total)…")

    ok, skipped, errors = 0, 0, 0

    for i, (_, row) in enumerate(to_fetch.iterrows(), 1):
        aid    = int(row["ID"])
        date   = row["Date"]
        dur_s  = float(row["Temps (min)"]) * 60.0
        dist_m = float(row["Distance (km)"]) * 1000.0

        try:
            result = fetch_gps_stream(
                strava_activity_id=aid,
                date=date,
                duration_s=dur_s,
                distance_m=dist_m,
                force=force,
            )
            if result is None:
                print(
                    f"  [{i}/{total}] {aid} — non trouvé sur Garmin ou sans GPS, ignoré"
                )
                skipped += 1
            else:
                n_pts = len(result.get("points", []))
                print(
                    f"  [{i}/{total}] {aid} — {n_pts} points GPS "
                    f"(garmin={result['garmin_id']})"
                )
                ok += 1
        except Exception as e:
            print(f"  [{i}/{total}] {aid} — ERREUR : {e}")
            errors += 1

        time.sleep(0.5)  # rate-limit Garmin Connect

    print(
        f"\nSync GPS terminé : {ok} OK, {skipped} non trouvés, {errors} erreur(s)"
    )

    state = _load_sync_state()
    state["gps_last_sync"]    = datetime.now(timezone.utc).isoformat()
    state["gps_synced_count"] = len(already_done) + ok
    _save_sync_state(state)


if __name__ == "__main__":
    sync_all_gps(force="--force" in sys.argv)
