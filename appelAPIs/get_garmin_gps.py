"""
get_garmin_gps.py — Récupère la trace GPS d'une activité Strava depuis Garmin Connect.

Match Strava → Garmin par : date ±4h + durée ±120s + distance ±200m.
Stocke le résultat dans data/gps/{strava_activity_id}.json.

Format du fichier GPS :
  {
    "strava_id": int,
    "garmin_id": int,
    "points": [{"lat": float, "lon": float, "time_s": int | null}, ...]
  }

Usage CLI :
    python3 appelAPIs/get_garmin_gps.py <strava_activity_id> <date_iso> [--force]
    python3 appelAPIs/get_garmin_gps.py <strava_activity_id> <date_iso> <duration_s> <distance_m> [--force]
"""

import io
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

_ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GPS_DIR   = os.path.join(_ROOT, "data", "gps")
_GARTH_DIR = os.path.join(_ROOT, ".garth")


# ── Auth ───────────────────────────────────────────────────────────────────────

def _garmin_login():
    """
    Retourne une instance Garmin authentifiée depuis le token persisté.

    Ne fait jamais de login email/password — utilise exclusivement le token
    sauvegardé par garmin_auth.py. Charger un token depuis disque est une
    opération locale (aucune requête HTTP) : pas de risque de déclencher MFA,
    même appelé en boucle sur des centaines d'activités.

    Si le token est absent ou invalide, lève RuntimeError avec instruction.
    """
    from garminconnect import Garmin

    if not os.path.isdir(_GARTH_DIR):
        raise RuntimeError(
            f"Token Garmin introuvable ({_GARTH_DIR}/)\n"
            "Lancer une fois : python3 appelAPIs/garmin_auth.py"
        )

    try:
        api = Garmin()
        api.garth.load(_GARTH_DIR)
        return api
    except Exception as e:
        raise RuntimeError(
            f"Token Garmin invalide ou expiré : {e}\n"
            "Relancer : python3 appelAPIs/garmin_auth.py"
        ) from e


# ── GPX parsing ────────────────────────────────────────────────────────────────

def _parse_gpx(gpx_bytes: bytes) -> list:
    """Parse des bytes GPX → liste de dicts {lat, lon, time_s}."""
    root = ET.fromstring(gpx_bytes)
    ns   = {"gpx": "http://www.topografix.com/GPX/1/1"}

    trkpts = root.findall(".//gpx:trkpt", ns)
    if not trkpts:
        return []

    points = []
    t0     = None
    for pt in trkpts:
        try:
            lat = float(pt.get("lat"))
            lon = float(pt.get("lon"))
        except (TypeError, ValueError):
            continue

        time_el = pt.find("gpx:time", ns)
        t_s = None
        if time_el is not None and time_el.text:
            try:
                t = datetime.fromisoformat(time_el.text.replace("Z", "+00:00"))
                if t0 is None:
                    t0 = t
                t_s = int((t - t0).total_seconds())
            except ValueError:
                pass

        points.append({"lat": lat, "lon": lon, "time_s": t_s})

    return points


def _unwrap_download(raw: bytes) -> bytes:
    """Décompresse un ZIP si nécessaire pour extraire le GPX."""
    if raw[:2] == b"PK":  # magic ZIP
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            gpx_name = next(
                (n for n in zf.namelist() if n.lower().endswith(".gpx")), None
            )
            if gpx_name:
                return zf.read(gpx_name)
        return b""
    return raw


# ── Core fetch ────────────────────────────────────────────────────────────────

def fetch_gps_stream(
    strava_activity_id: int,
    date,
    duration_s: float = None,
    distance_m: float = None,
    force: bool = False,
    verbose_match: bool = False,
) -> dict | None:
    """
    Récupère et stocke la trace GPS Garmin pour une activité Strava.

    Paramètres
    ----------
    strava_activity_id : ID Strava de l'activité
    date               : date/datetime de l'activité (ISO string ou datetime, UTC)
    duration_s         : durée en secondes (matching optionnel)
    distance_m         : distance en mètres (matching optionnel)
    force              : recalculer même si le fichier GPS existe déjà
    verbose_match      : affiche le détail du matching pour chaque candidat Garmin

    Retourne
    --------
    dict {strava_id, garmin_id, points} ou None si non trouvé / pas de GPS.
    """
    out_path = os.path.join(_GPS_DIR, f"{strava_activity_id}.json")
    if not force and os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)

    # Normalise la date en datetime UTC
    if isinstance(date, str):
        date = pd.to_datetime(date, utc=True)
    if hasattr(date, "tzinfo") and date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)

    # Fenêtre de requête : jour -1 à jour +1 (absorbe les décalages UTC/local)
    q_start = (date - timedelta(days=1)).strftime("%Y-%m-%d")
    q_end   = (date + timedelta(days=1)).strftime("%Y-%m-%d")

    api = _garmin_login()
    activities = api.get_activities_by_date(q_start, q_end)

    # Matching par date ±4h, puis durée ±120s, puis distance ±200m
    # Fenêtre élargie car Garmin peut envoyer startTimeGMT en heure locale
    # (UTC+1 hiver, UTC+2 été) créant un écart de 1-2h avec les dates UTC Strava.
    garmin_id = None
    for act in activities:
        raw_start = act.get("startTimeGMT") or act.get("startTimeLocal", "")
        try:
            act_dt = pd.to_datetime(raw_start, utc=True)
        except Exception:
            if verbose_match:
                print(f"  [skip] activityId={act.get('activityId')} — date non parseable : {raw_start!r}")
            continue

        dt_diff = (act_dt - date).total_seconds()

        if verbose_match:
            print(
                f"  [candidat] activityId={act.get('activityId')}"
                f"  startTimeGMT={raw_start}"
                f"  écart={dt_diff:+.0f}s ({dt_diff/3600:+.2f}h)"
            )

        if abs(dt_diff) > 14400:
            if verbose_match:
                print(f"    → rejeté : écart date {abs(dt_diff):.0f}s > 14400s (±4h)")
            continue

        if duration_s is not None:
            act_dur = float(act.get("duration", 0))
            if abs(act_dur - duration_s) > 120:
                if verbose_match:
                    print(f"    → rejeté : écart durée {abs(act_dur - duration_s):.0f}s > 120s")
                continue

        if distance_m is not None:
            act_dist = float(act.get("distance", 0))
            if abs(act_dist - distance_m) > 200:
                if verbose_match:
                    print(f"    → rejeté : écart distance {abs(act_dist - distance_m):.0f}m > 200m")
                continue

        if verbose_match:
            print(f"    → RETENU (activityId={act.get('activityId')})")
        garmin_id = int(act["activityId"])
        break

    if garmin_id is None:
        return None

    # Télécharge le GPX
    from garminconnect import Garmin as _G
    raw = api.download_activity(garmin_id, dl_fmt=_G.ActivityDownloadFormat.GPX)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    gpx_bytes = _unwrap_download(raw)
    points    = _parse_gpx(gpx_bytes)
    if not points:
        return None

    result = {
        "strava_id": strava_activity_id,
        "garmin_id": garmin_id,
        "points":    points,
    }
    os.makedirs(_GPS_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python3 appelAPIs/get_garmin_gps.py "
            "<strava_id> <date_iso> [duration_s] [distance_m] [--force]"
        )
        sys.exit(1)

    _aid    = int(sys.argv[1])
    _date   = sys.argv[2]
    _dur    = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "--force" else None
    _dist   = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != "--force" else None
    _force  = "--force" in sys.argv

    res = fetch_gps_stream(_aid, _date, _dur, _dist, force=_force)
    if res:
        print(f"OK — {len(res['points'])} points GPS (garmin_id={res['garmin_id']})")
        print(f"Fichier : {os.path.join(_GPS_DIR, str(_aid) + '.json')}")
    else:
        print("Activité Garmin non trouvée ou pas de trace GPS.")
