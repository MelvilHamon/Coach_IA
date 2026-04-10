"""
RecupDataStrava.py — Sync incrémental des activités Strava.

Toutes les fonctions acceptent un access_token pré-validé.
Le refresh des tokens est géré en amont par api/strava_oauth.py.
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timezone

from strava_rate_limiter import strava_get, get_rate_limit_status

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_PATH = os.path.join(DATA_DIR, "mes_activites_strava.csv")
SYNC_STATE_PATH = os.path.join(DATA_DIR, "sync_state.json")


# ── Fetch activités ───────────────────────────────────────────────────────────

def _fetch_page(token, page, per_page=100, before=None, after=None):
    headers = {"Authorization": f"Bearer {token}"}
    params = {"per_page": per_page, "page": page}
    if before is not None:
        params["before"] = int(before)
    if after is not None:
        params["after"] = int(after)
    response = strava_get(
        "https://www.strava.com/api/v3/athlete/activities",
        headers=headers,
        params=params,
    )
    response.raise_for_status()
    return response.json()


def get_all_new_activities(token, existing_ids, per_page=100):
    """
    Parcourt toutes les pages Strava et retourne uniquement les activités
    dont l'ID n'est pas encore dans existing_ids.
    S'arrête dès qu'une page ne contient que des activités déjà connues.
    """
    all_new = []
    page = 1
    while True:
        activities = _fetch_page(token, page=page, per_page=per_page)
        if not activities:
            break

        new = [a for a in activities if isinstance(a, dict) and a["id"] not in existing_ids]
        all_new.extend(new)

        # Si la page contenait au moins un ID déjà connu → on a rattrapé le retard
        if len(new) < len(activities):
            break

        page += 1
        # Le rate limiter gère le délai automatiquement

    return all_new


def backfill_activities(token, existing_ids, after_date="2023-01-01", per_page=100):
    """
    Récupère TOUTES les activités depuis after_date, même celles plus anciennes
    que les activités déjà connues.
    """
    after_epoch = int(datetime.strptime(after_date, "%Y-%m-%d")
                      .replace(tzinfo=timezone.utc).timestamp())

    all_new = []
    page = 1
    while True:
        activities = _fetch_page(token, page=page, per_page=per_page,
                                 after=after_epoch)
        if not activities:
            break

        new = [a for a in activities if isinstance(a, dict) and a["id"] not in existing_ids]
        all_new.extend(new)

        if len(activities) < per_page:
            break

        page += 1

    print(f"Backfill depuis {after_date} : {len(all_new)} nouvelles activités trouvées")
    return all_new


def get_activity_description(activity_id, token):
    headers = {"Authorization": f"Bearer {token}"}
    response = strava_get(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers=headers,
    )
    if response.status_code != 200:
        return ""
    return response.json().get("description", "") or ""


# ── Formatage ─────────────────────────────────────────────────────────────────

def format_activities(activities, token):
    if not activities:
        return pd.DataFrame()

    rows = []
    for act in activities:
        distance_km = act.get("distance", 0) / 1000
        moving_time_min = act.get("moving_time", 0) / 60
        pace = moving_time_min / distance_km if distance_km > 0 else None

        rows.append({
            "ID": act["id"],
            "Nom": act.get("name", ""),
            "Date": act.get("start_date_local", ""),
            "Distance (km)": round(distance_km, 2),
            "Temps (min)": round(moving_time_min, 1),
            "Allure (min/km)": round(pace, 2) if pace else None,
            "Dénivelé (m)": act.get("total_elevation_gain", 0),
            "Fréquence cardiaque (bpm)": act.get("average_heartrate"),
            "Type": act.get("sport_type") or act.get("type", ""),
            "Commentaire": "",
        })

    return pd.DataFrame(rows)


# ── Sync state ────────────────────────────────────────────────────────────────

def _load_sync_state_from(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_sync_state_to(path: str, state: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_sync_state():
    return _load_sync_state_from(SYNC_STATE_PATH)


def save_sync_state(state):
    _save_sync_state_to(SYNC_STATE_PATH, state)


# ── Entrypoints ──────────────────────────────────────────────────────────────

def sync_activities(data_dir: str = None, access_token: str = None):
    """
    Sync incrémental des activités Strava.

    Parameters
    ----------
    data_dir : répertoire de données utilisateur (défaut: module DATA_DIR)
    access_token : token Strava valide (obligatoire)
    """
    if not access_token:
        raise ValueError("access_token requis pour sync_activities")

    _data_dir = data_dir or DATA_DIR
    _csv_path = os.path.join(_data_dir, "mes_activites_strava.csv")
    _sync_state_path = os.path.join(_data_dir, "sync_state.json")

    os.makedirs(_data_dir, exist_ok=True)
    if os.path.exists(_csv_path):
        df_old = pd.read_csv(_csv_path)
        existing_ids = set(df_old["ID"].astype(int)) if "ID" in df_old.columns else set()
    else:
        df_old = pd.DataFrame()
        existing_ids = set()

    print(f"Activités connues : {len(existing_ids)}")
    new_activities = get_all_new_activities(access_token, existing_ids)

    if not new_activities:
        print("Aucune nouvelle activité.")
    else:
        df_new = format_activities(new_activities, access_token)
        df_combined = pd.concat([df_old, df_new], ignore_index=True)
        df_combined["Date"] = pd.to_datetime(df_combined["Date"], format="mixed", utc=True)
        df_combined = df_combined.sort_values("Date", ascending=True)
        df_combined.to_csv(_csv_path, index=False, encoding="utf-8-sig")
        print(f"{len(df_new)} nouvelles activités ajoutées → {_csv_path}")

    status = get_rate_limit_status()
    print(f"  Rate limits — 15min: {status['usage_15min']}/{status['limit_15min']}, "
          f"jour: {status['usage_daily']}/{status['limit_daily']}")

    state = _load_sync_state_from(_sync_state_path)
    state["strava_last_sync"] = datetime.now(timezone.utc).isoformat()
    state["strava_activities_total"] = len(existing_ids) + len(new_activities if new_activities else [])
    state["activities_last_sync"] = state["strava_last_sync"]
    state["activities_total"] = state["strava_activities_total"]
    _save_sync_state_to(_sync_state_path, state)

    return len(new_activities)


def sync_backfill(after_date="2023-01-01", data_dir: str = None, access_token: str = None):
    """Récupère les activités historiques depuis after_date."""
    if not access_token:
        raise ValueError("access_token requis pour sync_backfill")

    _data_dir = data_dir or DATA_DIR
    _csv_path = os.path.join(_data_dir, "mes_activites_strava.csv")
    _sync_state_path = os.path.join(_data_dir, "sync_state.json")

    os.makedirs(_data_dir, exist_ok=True)
    if os.path.exists(_csv_path):
        df_old = pd.read_csv(_csv_path)
        existing_ids = set(df_old["ID"].astype(int)) if "ID" in df_old.columns else set()
    else:
        df_old = pd.DataFrame()
        existing_ids = set()

    print(f"Activités connues : {len(existing_ids)}")
    new_activities = backfill_activities(access_token, existing_ids, after_date=after_date)

    if not new_activities:
        print("Aucune nouvelle activité trouvée dans la période.")
        return 0

    df_new = format_activities(new_activities, access_token)
    df_combined = pd.concat([df_old, df_new], ignore_index=True)
    df_combined["Date"] = pd.to_datetime(df_combined["Date"], format="mixed", utc=True)
    df_combined = df_combined.drop_duplicates(subset=["ID"], keep="first")
    df_combined = df_combined.sort_values("Date", ascending=True)
    df_combined.to_csv(_csv_path, index=False, encoding="utf-8-sig")
    print(f"{len(df_new)} activités ajoutées (backfill) → {_csv_path}")
    print(f"Total : {len(df_combined)} activités")

    state = _load_sync_state_from(_sync_state_path)
    state["strava_last_sync"] = datetime.now(timezone.utc).isoformat()
    state["strava_activities_total"] = len(df_combined)
    state["activities_last_sync"] = state["strava_last_sync"]
    state["activities_total"] = state["strava_activities_total"]
    _save_sync_state_to(_sync_state_path, state)

    return len(df_new)


if __name__ == "__main__":
    import sys
    print("Usage: ce module est appelé par le pipeline sync.py")
    print("Les tokens sont gérés par api/strava_oauth.py")
    sys.exit(1)
