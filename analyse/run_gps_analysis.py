"""
run_gps_analysis.py — Calcule les métriques GPS pour tous les streams Garmin disponibles.

Pour chaque fichier data/garmin/streams/{garmin_id}.json :
  1. Charger les points GPS
  2. Appeler summarize_gps() — métriques scalaires uniquement (pas les arrays)
  3. Chercher si une activité Strava correspond (via data/gps/ → garmin_id dedans)
     → Si oui : compare_with_strava() et log si qualité "suspect"
     → Si non : métriques GPS seules
  4. Stocker dans data/garmin/metrics/{garmin_id}.json
  5. Ne pas recalculer si le fichier existe déjà (sauf --force)

Format de sortie data/garmin/metrics/{garmin_id}.json :
  {
    "garmin_id":         int,
    "start_time_utc":    str,
    "distance_m":        float,
    "elevation_gain_m":  float,
    "elevation_loss_m":  float,
    "duration_s":        float,
    "avg_speed_kmh":     float,
    "max_speed_kmh":     float,
    "avg_pace_sec_km":   float | null,
    "strava_id":         int | null,
    "strava_comparison": {distance_diff_pct, duration_diff_s, elevation_diff_m, match_quality} | null
  }

Note : speed_array, pace_array, distance_array, altitude_array sont exclus —
déjà présents dans le stream, trop volumineux pour des métriques.

Usage :
    python3 analyse/run_gps_analysis.py           # nouvelles activités uniquement
    python3 analyse/run_gps_analysis.py --force   # recalcule tout
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

import pandas as pd

_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STREAMS_DIR = os.path.join(_ROOT, "data", "garmin", "streams")
_METRICS_DIR = os.path.join(_ROOT, "data", "garmin", "metrics")
_GPS_DIR     = os.path.join(_ROOT, "data", "gps")
_ENRICHED    = os.path.join(_ROOT, "data", "activities_enriched.csv")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from api import storage
from gps_metrics import summarize_gps, compare_with_strava


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nan_to_none(obj):
    """Convertit récursivement NaN/±Inf en None pour la sérialisation JSON."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nan_to_none(v) for v in obj]
    return obj


def _build_garmin_to_strava(gps_dir: str = None) -> dict:
    """
    Construit {garmin_id: strava_id} depuis gps/{strava_id}.json.
    """
    _dir = gps_dir or _GPS_DIR
    mapping = {}
    if not storage.isdir(_dir):
        return mapping
    for fname in storage.listdir(_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_dir, fname)
        data = storage.read_json(fpath)
        if data is None:
            continue
        try:
            g_id = data.get("garmin_id")
            s_id = data.get("strava_id")
            if g_id is not None and s_id is not None:
                mapping[int(g_id)] = int(s_id)
        except Exception:
            continue
    return mapping


def _load_strava_df(enriched_path: str = None) -> pd.DataFrame:
    """Charge activities_enriched.csv. Retourne DataFrame vide si absent."""
    _path = enriched_path or _ENRICHED
    if not os.path.exists(_path) or os.path.getsize(_path) == 0:
        return pd.DataFrame()
    df = pd.read_csv(_path)
    if "ID" in df.columns:
        df["ID"] = df["ID"].astype(int)
    return df


# ── Analyse principale ────────────────────────────────────────────────────────

def run_gps_analysis(force: bool = False, data_dir: str = None) -> None:
    """
    Pour chaque stream dans garmin/streams/ :
    - calcule les métriques GPS scalaires via summarize_gps()
    - compare avec Strava si le matching est disponible
    - stocke dans garmin/metrics/{garmin_id}.json
    - ignore les fichiers déjà calculés (sauf --force)

    Parameters
    ----------
    data_dir : répertoire de données utilisateur (défaut: data/)
    """
    _data_dir = data_dir or os.path.join(_ROOT, "data")
    _streams_dir = os.path.join(_data_dir, "garmin", "streams")
    _metrics_dir = os.path.join(_data_dir, "garmin", "metrics")
    _gps_dir = os.path.join(_data_dir, "gps")
    _enriched = os.path.join(_data_dir, "activities_enriched.csv")

    os.makedirs(_metrics_dir, exist_ok=True)

    if not storage.isdir(_streams_dir):
        print(f"Répertoire streams introuvable : {_streams_dir}")
        print("Lancer d'abord : python3 appelAPIs/sync_garmin.py")
        return

    stream_files = sorted(
        f for f in storage.listdir(_streams_dir) if f.endswith(".json")
    )
    if not stream_files:
        print("Aucun stream disponible dans", _streams_dir)
        return

    total = len(stream_files)
    print(f"{total} stream(s) trouvé(s) dans {_streams_dir}")

    # Mapping garmin_id → strava_id (depuis les GPS déjà matchés)
    garmin_to_strava = _build_garmin_to_strava(_gps_dir)
    print(f"Mapping Garmin→Strava : {len(garmin_to_strava)} activité(s) matchée(s)")

    # CSV Strava enrichi
    strava_df  = _load_strava_df(_enriched)
    has_strava = not strava_df.empty and "ID" in strava_df.columns
    if not has_strava:
        print("activities_enriched.csv absent — comparaison Strava désactivée")

    n_done = n_skipped = n_matched = n_errors = 0
    suspects = []

    for fname in stream_files:
        garmin_id = int(fname.replace(".json", ""))
        out_path  = os.path.join(_metrics_dir, fname)

        # Skip si déjà calculé
        if not force and os.path.exists(out_path):
            n_skipped += 1
            continue

        # Chargement du stream
        stream_path = os.path.join(_streams_dir, fname)
        stream = storage.read_json(stream_path)
        if stream is None:
            print(f"  [{garmin_id}] Erreur lecture ou fichier absent")
            n_errors += 1
            continue

        points = stream.get("points", [])
        if not points:
            print(f"  [{garmin_id}] Aucun point GPS, ignoré")
            n_errors += 1
            continue

        # Calcul des métriques
        try:
            summary = summarize_gps(points)
        except Exception as e:
            print(f"  [{garmin_id}] Erreur summarize_gps : {e}")
            n_errors += 1
            continue

        # Métriques scalaires uniquement (exclut les arrays déjà dans le stream)
        _ARRAY_KEYS = {"speed_array", "pace_array", "distance_array", "altitude_array"}
        metrics = {k: v for k, v in summary.items() if k not in _ARRAY_KEYS}
        metrics["garmin_id"]        = garmin_id
        metrics["start_time_utc"]   = stream.get("start_time_utc", "")
        metrics["strava_id"]        = None
        metrics["strava_comparison"] = None

        # Comparaison Strava si mapping disponible
        strava_id = garmin_to_strava.get(garmin_id)
        if strava_id and has_strava:
            mask = strava_df["ID"] == strava_id
            if mask.any():
                strava_row = strava_df[mask].iloc[0]
                try:
                    comparison = compare_with_strava(summary, strava_row)
                    metrics["strava_id"]         = strava_id
                    metrics["strava_comparison"] = comparison
                    n_matched += 1
                    if comparison.get("match_quality") == "suspect":
                        suspects.append((garmin_id, strava_id, comparison))
                except Exception as e:
                    print(f"  [{garmin_id}] Erreur compare_with_strava : {e}")

        # Sérialisation — NaN/Inf → null
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(_nan_to_none(metrics), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [{garmin_id}] Erreur écriture : {e}")
            n_errors += 1
            continue

        n_done += 1

    # Rapport des suspects
    if suspects:
        print("\nMatches suspects (écart distance > 10 %) :")
        for gid, sid, cmp in suspects:
            print(
                f"  garmin={gid} strava={sid}"
                f"  dist_diff={cmp.get('distance_diff_pct', '?'):.1f}%"
                f"  dur_diff={cmp.get('duration_diff_s', '?'):.0f}s"
            )

    print(f"""
=== Analyse GPS terminée ===
  Streams total     : {total}
  Calculés          : {n_done}
  Avec match Strava : {n_matched}
  Déjà à jour       : {n_skipped}
  Erreurs           : {n_errors}
""")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_gps_analysis(force="--force" in sys.argv)
