"""
get_strava_gps.py — Récupère les coordonnées GPS depuis l'API Strava.

Toutes les fonctions acceptent un access_token pré-validé.

Endpoint : GET /activities/{id}/streams?keys=latlng,altitude,time&key_by_type=true

Format de sortie identique au format Garmin :
  {
    "source": "strava",
    "strava_id": int,
    "points": [{"lat", "lon", "time_s", "altitude_m"}, ...]
  }

Stocke dans data/gps/strava_{activity_id}.json.
"""

import json
import os
import sys

import requests

from strava_rate_limiter import strava_get

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from api import storage
_GPS_DIR  = os.path.join(_ROOT, "data", "gps")


def fetch_strava_gps(
    activity_id: int,
    access_token: str,
    force: bool = False,
    gps_dir: str = None,
) -> dict | None:
    """
    Récupère lat/lon/altitude/time depuis l'API Strava.
    Stocke dans gps_dir/strava_{activity_id}.json.

    Parameters
    ----------
    activity_id : ID de l'activité Strava
    access_token : token Strava valide (obligatoire)
    force : re-télécharger même si le fichier existe
    gps_dir : répertoire de sortie GPS

    Retourne le dict GPS ou None si pas de données latlng.
    """
    if not access_token:
        raise ValueError("access_token requis pour fetch_strava_gps")

    _gps_dir = gps_dir or _GPS_DIR
    out_path = os.path.join(_gps_dir, f"strava_{activity_id}.json")
    if not force and storage.exists(out_path):
        return storage.read_json(out_path)

    headers = {"Authorization": f"Bearer {access_token}"}
    r = strava_get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        headers=headers,
        params={"keys": "latlng,altitude,time", "key_by_type": "true"},
    )

    if r.status_code == 404:
        return None
    r.raise_for_status()

    data = r.json()

    latlng_data = data.get("latlng", {}).get("data", [])
    if not latlng_data:
        return None

    time_data = data.get("time", {}).get("data", [])
    alt_data  = data.get("altitude", {}).get("data", [])

    n = len(latlng_data)
    points = []
    for i in range(n):
        lat, lon = latlng_data[i]
        points.append({
            "lat": lat,
            "lon": lon,
            "time_s": time_data[i] if i < len(time_data) else None,
            "altitude_m": round(alt_data[i], 1) if i < len(alt_data) and alt_data[i] is not None else None,
        })

    if not points:
        return None

    result = {
        "source": "strava",
        "strava_id": activity_id,
        "points": points,
    }

    storage.write_json(out_path, result)

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Usage: ce module est appelé par le pipeline sync.py")
    print("Les tokens sont gérés par api/strava_oauth.py")
    sys.exit(1)
