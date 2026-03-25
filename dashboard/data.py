"""
dashboard/data.py — Chargement et cache des données CoachAgent.
"""

import functools
import json
import os
import sys

import pandas as pd

_ROOT              = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENRICHED          = os.path.join(_ROOT, "data", "activities_enriched.csv")
_REVIEWS_DIR       = os.path.join(_ROOT, "data", "reviews")
_GPS_DIR           = os.path.join(_ROOT, "data", "gps")
_STREAMS_DIR       = os.path.join(_ROOT, "data", "streams")
_GARMIN_STREAMS    = os.path.join(_ROOT, "data", "garmin", "streams")
_GARMIN_MAP_PATH   = os.path.join(_ROOT, "data", "garmin", "strava_garmin_map.json")

# Rend metrics.acwr_label importable depuis n'importe où
sys.path.insert(0, os.path.join(_ROOT, "analyse"))


@functools.lru_cache(maxsize=1)
def load_activities() -> pd.DataFrame:
    if not os.path.exists(_ENRICHED):
        return pd.DataFrame()
    df = pd.read_csv(_ENRICHED)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    if "Allure (min/km)" in df.columns:
        df["pace_display"] = df["Allure (min/km)"].apply(
            lambda x: f"{int(x)}:{int((x % 1) * 60):02d}" if pd.notna(x) else "—"
        )
    return df.sort_values("Date", ascending=False).reset_index(drop=True)


def get_review(activity_id: int) -> dict | None:
    p = os.path.join(_REVIEWS_DIR, f"{activity_id}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def gps_file(activity_id: int) -> str | None:
    p = os.path.join(_GPS_DIR, f"{activity_id}.json")
    return p if os.path.exists(p) else None


def stream_file(activity_id: int) -> str | None:
    p = os.path.join(_STREAMS_DIR, f"{activity_id}.csv")
    return p if os.path.exists(p) else None


def load_gps(activity_id: int) -> dict | None:
    """
    Cherche les points GPS dans cet ordre :
    1. data/gps/{activity_id}.json          (matching Strava→Garmin existant)
    2. data/garmin/strava_garmin_map.json → data/garmin/streams/{garmin_id}.json

    Retourne None si aucun fichier trouvé.
    """
    # 1. Fichier GPS du pipeline Strava→Garmin
    p1 = os.path.join(_GPS_DIR, f"{activity_id}.json")
    if os.path.exists(p1):
        with open(p1, encoding="utf-8") as f:
            return json.load(f)

    # 2. Via la map strava_id → garmin_id
    if os.path.exists(_GARMIN_MAP_PATH):
        try:
            with open(_GARMIN_MAP_PATH, encoding="utf-8") as f:
                garmin_map = json.load(f)
            garmin_id = garmin_map.get(str(activity_id))
            if garmin_id:
                p2 = os.path.join(_GARMIN_STREAMS, f"{garmin_id}.json")
                if os.path.exists(p2):
                    with open(p2, encoding="utf-8") as f:
                        return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    return None
