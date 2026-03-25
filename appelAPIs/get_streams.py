import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "mes_activites_strava.csv")
STREAMS_DIR = os.path.join(DATA_DIR, "streams")
SYNC_STATE_PATH = os.path.join(DATA_DIR, "sync_state.json")


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_access_token():
    response = requests.post(
        url="https://www.strava.com/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
        },
    )
    response.raise_for_status()
    return response.json().get("access_token")


# ── Fetch & conversion ────────────────────────────────────────────────────────

def get_streams(activity_id, access_token):
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    params = {"keys": "time,velocity_smooth,heartrate,altitude", "key_by_type": "true"}
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 404:
        return None  # activité sans stream GPS (ex : activité manuelle)
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


def save_streams(df, activity_id):
    os.makedirs(STREAMS_DIR, exist_ok=True)
    path = os.path.join(STREAMS_DIR, f"{activity_id}.csv")
    df.to_csv(path, index=False)
    return path


# ── État de sync ──────────────────────────────────────────────────────────────

def _load_sync_state():
    if os.path.exists(SYNC_STATE_PATH):
        with open(SYNC_STATE_PATH) as f:
            return json.load(f)
    return {}


def _save_sync_state(state):
    with open(SYNC_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _already_synced_ids():
    """IDs numériques dont le fichier stream existe déjà."""
    if not os.path.exists(STREAMS_DIR):
        return set()
    synced = set()
    for fname in os.listdir(STREAMS_DIR):
        stem, ext = os.path.splitext(fname)
        if ext == ".csv" and stem.isdigit():
            synced.add(int(stem))
    return synced


# ── Sync principal ────────────────────────────────────────────────────────────

def sync_all_streams():
    """
    Récupère les streams de toutes les activités du CSV
    qui n'ont pas encore de fichier dans data/streams/.
    """
    if not os.path.exists(CSV_PATH):
        print(f"Fichier activités introuvable : {CSV_PATH}")
        return

    df_acts = pd.read_csv(CSV_PATH)
    all_ids = df_acts["ID"].astype(int).tolist()
    already_done = _already_synced_ids()
    to_fetch = [aid for aid in all_ids if aid not in already_done]

    if not to_fetch:
        print("Tous les streams sont déjà synchronisés.")
        return

    print(f"{len(to_fetch)} activité(s) à synchroniser (sur {len(all_ids)} total)…")
    access_token = get_access_token()

    ok, skipped, errors = 0, 0, 0
    for i, activity_id in enumerate(to_fetch, 1):
        try:
            streams_json = get_streams(activity_id, access_token)
            if streams_json is None:
                print(f"  [{i}/{len(to_fetch)}] {activity_id} — pas de stream GPS, ignoré")
                skipped += 1
            else:
                df_s = streams_to_df(streams_json)
                path = save_streams(df_s, activity_id)
                print(f"  [{i}/{len(to_fetch)}] {activity_id} — {len(df_s)} points → {os.path.basename(path)}")
                ok += 1
        except Exception as e:
            print(f"  [{i}/{len(to_fetch)}] {activity_id} — ERREUR : {e}")
            errors += 1

        time.sleep(0.5)  # rate-limit Strava

    print(f"\nSync streams terminé : {ok} OK, {skipped} sans GPS, {errors} erreur(s)")

    state = _load_sync_state()
    state["streams_last_sync"] = datetime.now(timezone.utc).isoformat()
    state["streams_synced_count"] = len(already_done) + ok
    _save_sync_state(state)


if __name__ == "__main__":
    sync_all_streams()
