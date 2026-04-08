"""
get_streams.py — Sync des streams Strava (FC, vitesse, altitude).

Toutes les fonctions acceptent un access_token pré-validé.
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "mes_activites_strava.csv")
STREAMS_DIR = os.path.join(DATA_DIR, "streams")
SYNC_STATE_PATH = os.path.join(DATA_DIR, "sync_state.json")


# ── Fetch & conversion ────────────────────────────────────────────────────────

def get_streams(activity_id, access_token):
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    params = {"keys": "time,velocity_smooth,heartrate,altitude", "key_by_type": "true"}
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def streams_to_df(streams_json):
    time_data = streams_json.get("time", {}).get("data", [])
    speed = streams_json.get("velocity_smooth", {}).get("data", [])
    hr = streams_json.get("heartrate", {}).get("data", [])
    alt = streams_json.get("altitude", {}).get("data", [])
    n = len(time_data)
    return pd.DataFrame({
        "time_s": time_data,
        "speed_kmh": [v * 3.6 for v in speed] if speed else [None] * n,
        "bpm": hr if hr else [None] * n,
        "altitude_m": alt if alt else [None] * n,
    })


def save_streams(df, activity_id, streams_dir: str = None):
    _dir = streams_dir or STREAMS_DIR
    os.makedirs(_dir, exist_ok=True)
    path = os.path.join(_dir, f"{activity_id}.csv")
    df.to_csv(path, index=False)
    return path


# ── État de sync ──────────────────────────────────────────────────────────────

def _already_synced_ids(streams_dir: str = None):
    _dir = streams_dir or STREAMS_DIR
    if not os.path.exists(_dir):
        return set()
    synced = set()
    for fname in os.listdir(_dir):
        stem, ext = os.path.splitext(fname)
        if ext == ".csv" and stem.isdigit():
            synced.add(int(stem))
    return synced


def _load_sync_state_from(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_sync_state_to(path: str, state: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Sync principal ────────────────────────────────────────────────────────────

def sync_all_streams(data_dir: str = None, access_token: str = None):
    """
    Récupère les streams de toutes les activités du CSV
    qui n'ont pas encore de fichier dans streams/.

    Parameters
    ----------
    data_dir : répertoire de données utilisateur
    access_token : token Strava valide (obligatoire)
    """
    if not access_token:
        raise ValueError("access_token requis pour sync_all_streams")

    _data_dir = data_dir or DATA_DIR
    _csv_path = os.path.join(_data_dir, "mes_activites_strava.csv")
    _streams_dir = os.path.join(_data_dir, "streams")
    _sync_state_path = os.path.join(_data_dir, "sync_state.json")

    if not os.path.exists(_csv_path):
        print(f"Fichier activités introuvable : {_csv_path}")
        return

    df_acts = pd.read_csv(_csv_path)
    all_ids = df_acts["ID"].astype(int).tolist()
    already_done = _already_synced_ids(_streams_dir)
    to_fetch = [aid for aid in all_ids if aid not in already_done]

    if not to_fetch:
        print("Tous les streams sont déjà synchronisés.")
        return

    print(f"{len(to_fetch)} activité(s) à synchroniser (sur {len(all_ids)} total)…")

    ok, skipped, errors = 0, 0, 0
    for i, activity_id in enumerate(to_fetch, 1):
        try:
            streams_json = get_streams(activity_id, access_token)
            if streams_json is None:
                print(f"  [{i}/{len(to_fetch)}] {activity_id} — pas de stream GPS, ignoré")
                skipped += 1
            else:
                df_s = streams_to_df(streams_json)
                path = save_streams(df_s, activity_id, _streams_dir)
                print(f"  [{i}/{len(to_fetch)}] {activity_id} — {len(df_s)} points → {os.path.basename(path)}")
                ok += 1
        except Exception as e:
            print(f"  [{i}/{len(to_fetch)}] {activity_id} — ERREUR : {e}")
            errors += 1

        time.sleep(0.5)

    print(f"\nSync streams terminé : {ok} OK, {skipped} sans GPS, {errors} erreur(s)")

    state = _load_sync_state_from(_sync_state_path)
    state["streams_last_sync"] = datetime.now(timezone.utc).isoformat()
    state["streams_synced_count"] = len(already_done) + ok
    _save_sync_state_to(_sync_state_path, state)
