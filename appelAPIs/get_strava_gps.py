"""
get_strava_gps.py — Récupère les coordonnées GPS depuis l'API Strava.

Fallback pour les activités sans stream Garmin.
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
from dotenv import load_dotenv

load_dotenv()

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GPS_DIR  = os.path.join(_ROOT, "data", "gps")

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")


def _get_access_token() -> str:
    """Rafraîchit le token Strava OAuth2 — même pattern que RecupDataStrava.py."""
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
    return response.json()["access_token"]


def fetch_strava_gps(
    activity_id: int,
    access_token: str | None = None,
    force: bool = False,
) -> dict | None:
    """
    Récupère lat/lon/altitude/time depuis l'API Strava.
    Stocke dans data/gps/strava_{activity_id}.json.

    Retourne le dict GPS ou None si pas de données latlng.
    """
    out_path = os.path.join(_GPS_DIR, f"strava_{activity_id}.json")
    if not force and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)

    if access_token is None:
        access_token = _get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(
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

    os.makedirs(_GPS_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 appelAPIs/get_strava_gps.py <strava_activity_id> [--force]")
        sys.exit(1)

    _aid = int(sys.argv[1])
    _force = "--force" in sys.argv

    res = fetch_strava_gps(_aid, force=_force)
    if res:
        print(f"OK — {len(res['points'])} points GPS (source=strava)")
        print(f"Fichier : {os.path.join(_GPS_DIR, f'strava_{_aid}.json')}")
    else:
        print("Pas de données GPS latlng disponibles sur Strava pour cette activité.")
