"""
api/deps.py — Chargement des données et dépendances partagées.

Cache en mémoire avec invalidation par mtime du fichier source.
Aucune logique métier — lecture de fichiers uniquement.
"""

import json
import os
import sys
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Chemins
ENRICHED_CSV    = os.path.join(_ROOT, "data", "activities_enriched.csv")
CONFIG_JSON     = os.path.join(_ROOT, "config.json")
SYNC_STATE_JSON = os.path.join(_ROOT, "data", "sync_state.json")
MEMOIRE_TXT     = os.path.join(_ROOT, "data", "memoire.txt")
REVIEWS_DIR     = os.path.join(_ROOT, "data", "reviews")
GPS_DIR         = os.path.join(_ROOT, "data", "gps")
STREAMS_DIR     = os.path.join(_ROOT, "data", "streams")
GARMIN_ACT_JSON = os.path.join(_ROOT, "data", "garmin", "activities.json")
GARMIN_STREAMS  = os.path.join(_ROOT, "data", "garmin", "streams")
GARMIN_METRICS  = os.path.join(_ROOT, "data", "garmin", "metrics")
GARMIN_MAP_JSON = os.path.join(_ROOT, "data", "garmin", "strava_garmin_map.json")

# Rend analyse/ importable
sys.path.insert(0, os.path.join(_ROOT, "analyse"))


# ── Cache avec invalidation par mtime ────────────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}


def _read_cached(path: str, loader) -> Any:
    """Charge un fichier, retourne le cache si le mtime n'a pas changé."""
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    data = loader(path)
    _cache[path] = (mtime, data)
    return data


# Mapping logique → fichiers cache pour invalidation ciblée
_CACHE_GROUPS: dict[str, list[str]] = {
    "activities": [ENRICHED_CSV, SYNC_STATE_JSON],
    "metrics":    [ENRICHED_CSV],
    "gps":        [GARMIN_MAP_JSON],
    "config":     [CONFIG_JSON],
}


def invalidate_cache(keys: list[str]) -> None:
    """
    Invalide le cache mtime pour les groupes demandés.

    Appelé par sync.py après chaque étape pour forcer le rechargement
    au prochain appel API sans attendre un changement de mtime.

    keys: liste de groupes logiques ("activities", "metrics", "gps", "config").
    """
    paths_to_clear = set()
    for key in keys:
        for path in _CACHE_GROUPS.get(key, []):
            paths_to_clear.add(path)
    for path in paths_to_clear:
        _cache.pop(path, None)


# ── Loaders ──────────────────────────────────────────────────────────────────

def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    if "Allure (min/km)" in df.columns:
        df["pace_display"] = df["Allure (min/km)"].apply(
            lambda x: f"{int(x)}:{int((x % 1) * 60):02d}" if pd.notna(x) else None
        )
    return df.sort_values("Date", ascending=False).reset_index(drop=True)


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── API publique ─────────────────────────────────────────────────────────────

def load_activities() -> pd.DataFrame:
    df = _read_cached(ENRICHED_CSV, _load_csv)
    return df if df is not None else pd.DataFrame()


def load_config() -> dict:
    cfg = _read_cached(CONFIG_JSON, _load_json)
    return cfg if cfg is not None else {}


def load_sync_state() -> dict:
    st = _read_cached(SYNC_STATE_JSON, _load_json)
    return st if st is not None else {}


def load_garmin_activities() -> list:
    acts = _read_cached(GARMIN_ACT_JSON, _load_json)
    return acts if acts is not None else []


def get_review(activity_id: int) -> dict | None:
    p = os.path.join(REVIEWS_DIR, f"{activity_id}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def get_gps_points(activity_id: int) -> dict | None:
    """
    Cherche les points GPS dans cet ordre de priorité :
    1. data/garmin/streams/{garmin_id}.json  ← via strava_garmin_map.json
    2. data/gps/{activity_id}.json           ← matching Garmin existant
    3. data/gps/strava_{activity_id}.json    ← fallback Strava
    4. None                                  ← pas de GPS disponible

    Normalise le format en sortie : {"points": [...], "source": "garmin"|"matched"|"strava"}.
    """
    # 1. Via garmin map → stream Garmin direct
    if os.path.exists(GARMIN_MAP_JSON):
        try:
            with open(GARMIN_MAP_JSON, encoding="utf-8") as f:
                garmin_map = json.load(f)
            garmin_id = garmin_map.get(str(activity_id))
            if garmin_id:
                p1 = os.path.join(GARMIN_STREAMS, f"{garmin_id}.json")
                if os.path.exists(p1):
                    with open(p1, encoding="utf-8") as f:
                        data = json.load(f)
                    data.setdefault("source", "garmin")
                    return data
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Fichier GPS matché (data/gps/{activity_id}.json)
    p2 = os.path.join(GPS_DIR, f"{activity_id}.json")
    if os.path.exists(p2):
        with open(p2, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("source", "matched")
        return data

    # 3. Fallback Strava (data/gps/strava_{activity_id}.json)
    p3 = os.path.join(GPS_DIR, f"strava_{activity_id}.json")
    if os.path.exists(p3):
        with open(p3, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("source", "strava")
        return data

    return None


def get_stream(activity_id: int) -> pd.DataFrame | None:
    """Charge le stream Strava (CSV) pour une activité."""
    p = os.path.join(STREAMS_DIR, f"{activity_id}.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p)


def get_garmin_metrics(garmin_id: int) -> dict | None:
    p = os.path.join(GARMIN_METRICS, f"{garmin_id}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def nan_safe(obj):
    """Convertit NaN/Inf en None pour la sérialisation JSON."""
    if isinstance(obj, float):
        if not np.isfinite(obj):
            return None
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if not np.isfinite(v) else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: nan_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [nan_safe(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if pd.isna(obj):
        return None
    return obj
