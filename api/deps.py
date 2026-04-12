"""
api/deps.py — Chargement des données et dépendances partagées.

Cache en mémoire avec invalidation par mtime du fichier source.
Aucune logique métier — lecture de fichiers uniquement.

Toutes les fonctions publiques acceptent un user_id pour résoudre
les chemins via UserPaths. Sans user_id, les chemins legacy sont utilisés.
"""

import json
import os
import sys
from typing import Any

import numpy as np
import pandas as pd

from api.user_data import UserPaths
from api import storage

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Legacy paths (single-user fallback) ───────────────────────────────────────

_LEGACY_ENRICHED    = os.path.join(_ROOT, "data", "activities_enriched.csv")
_LEGACY_CONFIG      = os.path.join(_ROOT, "config.json")
_LEGACY_SYNC_STATE  = os.path.join(_ROOT, "data", "sync_state.json")
_LEGACY_MEMOIRE     = os.path.join(_ROOT, "data", "memoire.txt")
_LEGACY_REVIEWS     = os.path.join(_ROOT, "data", "reviews")
_LEGACY_GPS         = os.path.join(_ROOT, "data", "gps")
_LEGACY_STREAMS     = os.path.join(_ROOT, "data", "streams")
_LEGACY_GARMIN_ACT  = os.path.join(_ROOT, "data", "garmin", "activities.json")
_LEGACY_GARMIN_STR  = os.path.join(_ROOT, "data", "garmin", "streams")
_LEGACY_GARMIN_MET  = os.path.join(_ROOT, "data", "garmin", "metrics")
_LEGACY_GARMIN_MAP  = os.path.join(_ROOT, "data", "garmin", "strava_garmin_map.json")

# Public aliases kept for backward compat with sync.py imports
ENRICHED_CSV    = _LEGACY_ENRICHED
CONFIG_JSON     = _LEGACY_CONFIG
SYNC_STATE_JSON = _LEGACY_SYNC_STATE
MEMOIRE_TXT     = _LEGACY_MEMOIRE
REVIEWS_DIR     = _LEGACY_REVIEWS
GPS_DIR         = _LEGACY_GPS
STREAMS_DIR     = _LEGACY_STREAMS
GARMIN_ACT_JSON = _LEGACY_GARMIN_ACT
GARMIN_STREAMS  = _LEGACY_GARMIN_STR
GARMIN_METRICS  = _LEGACY_GARMIN_MET
GARMIN_MAP_JSON = _LEGACY_GARMIN_MAP

# Rend analyse/ importable
sys.path.insert(0, os.path.join(_ROOT, "analyse"))


# ── Path resolver ─────────────────────────────────────────────────────────────

def _paths(user_id: str | None) -> dict:
    """Return a dict of all paths, user-scoped or legacy."""
    if user_id:
        p = UserPaths(user_id)
        return {
            "enriched":     p.enriched_csv,
            "config":       p.config_json,
            "sync_state":   p.sync_state_json,
            "memoire":      p.memoire_txt,
            "reviews":      p.reviews_dir,
            "gps":          p.gps_dir,
            "streams":      p.streams_dir,
            "garmin_act":   p.garmin_activities_json,
            "garmin_str":   p.garmin_streams_dir,
            "garmin_met":   p.garmin_metrics_dir,
            "garmin_map":   p.garmin_map_json,
        }
    return {
        "enriched":     _LEGACY_ENRICHED,
        "config":       _LEGACY_CONFIG,
        "sync_state":   _LEGACY_SYNC_STATE,
        "memoire":      _LEGACY_MEMOIRE,
        "reviews":      _LEGACY_REVIEWS,
        "gps":          _LEGACY_GPS,
        "streams":      _LEGACY_STREAMS,
        "garmin_act":   _LEGACY_GARMIN_ACT,
        "garmin_str":   _LEGACY_GARMIN_STR,
        "garmin_met":   _LEGACY_GARMIN_MET,
        "garmin_map":   _LEGACY_GARMIN_MAP,
    }


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


def invalidate_cache(keys: list[str], user_id: str | None = None) -> None:
    """
    Invalide le cache mtime pour les groupes demandés.
    keys: liste de groupes logiques ("activities", "metrics", "gps", "config").
    """
    p = _paths(user_id)
    groups = {
        "activities": [p["enriched"], p["sync_state"]],
        "metrics":    [p["enriched"]],
        "gps":        [p["garmin_map"]],
        "config":     [p["config"]],
    }
    paths_to_clear = set()
    for key in keys:
        for path in groups.get(key, []):
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

def load_activities(user_id: str | None = None) -> pd.DataFrame:
    p = _paths(user_id)
    df = _read_cached(p["enriched"], _load_csv)
    return df if df is not None else pd.DataFrame()


def load_config(user_id: str | None = None) -> dict:
    p = _paths(user_id)
    cfg = _read_cached(p["config"], _load_json)
    return cfg if cfg is not None else {}


def load_sync_state(user_id: str | None = None) -> dict:
    p = _paths(user_id)
    st = _read_cached(p["sync_state"], _load_json)
    return st if st is not None else {}


def load_garmin_activities(user_id: str | None = None) -> list:
    p = _paths(user_id)
    acts = _read_cached(p["garmin_act"], _load_json)
    return acts if acts is not None else []


def get_review(activity_id: int, user_id: str | None = None) -> dict | None:
    p = _paths(user_id)
    path = os.path.join(p["reviews"], f"{activity_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_gps_points(activity_id: int, user_id: str | None = None) -> dict | None:
    """
    Cherche les points GPS dans cet ordre de priorité :
    1. garmin/streams/{garmin_id}.json  ← via strava_garmin_map.json
    2. gps/{activity_id}.json           ← matching Garmin existant
    3. gps/strava_{activity_id}.json    ← fallback Strava
    4. None
    """
    p = _paths(user_id)

    # 1. Via garmin map → stream Garmin direct
    if os.path.exists(p["garmin_map"]):
        try:
            with open(p["garmin_map"], encoding="utf-8") as f:
                garmin_map = json.load(f)
            garmin_id = garmin_map.get(str(activity_id))
            if garmin_id:
                p1 = os.path.join(p["garmin_str"], f"{garmin_id}.json")
                data = storage.read_json(p1)
                if data is not None:
                    data.setdefault("source", "garmin")
                    return data
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Fichier GPS matché
    p2 = os.path.join(p["gps"], f"{activity_id}.json")
    data = storage.read_json(p2)
    if data is not None:
        data.setdefault("source", "matched")
        return data

    # 3. Fallback Strava
    p3 = os.path.join(p["gps"], f"strava_{activity_id}.json")
    data = storage.read_json(p3)
    if data is not None:
        data.setdefault("source", "strava")
        return data

    return None


def get_stream(activity_id: int, user_id: str | None = None) -> pd.DataFrame | None:
    """Charge le stream Strava (CSV) pour une activité."""
    p = _paths(user_id)
    path = os.path.join(p["streams"], f"{activity_id}.csv")
    return storage.read_csv(path)


def get_garmin_metrics(garmin_id: int, user_id: str | None = None) -> dict | None:
    p = _paths(user_id)
    path = os.path.join(p["garmin_met"], f"{garmin_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
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
