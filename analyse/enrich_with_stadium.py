"""
enrich_with_stadium.py — Ajoute les colonnes stade à data/activities_enriched.csv.

Colonnes ajoutées :
  - stadium_name      : "Nom du stade (commune)" ou vide
  - stadium_id        : installation_id ou vide
  - track_length_m    : longueur de piste en m
  - n_laps            : nombre de tours détectés (depuis track_sessions)
  - best_lap_s        : meilleur tour en secondes
  - mean_lap_s        : tour moyen en secondes
  - track_cv          : coefficient de variation des tours

Lit data/stadium_matches.json + data/track_sessions/{id}.json
et réécrit data/activities_enriched.csv en préservant les autres colonnes.
"""

import json
import os
import sys

import pandas as pd

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENRICHED = os.path.join(_ROOT, "data", "activities_enriched.csv")
_MATCHES  = os.path.join(_ROOT, "data", "stadium_matches.json")
_SESSIONS = os.path.join(_ROOT, "data", "track_sessions")

NEW_COLS = ["stadium_name", "stadium_id", "track_length_m",
            "n_laps", "best_lap_s", "mean_lap_s", "track_cv"]


def _session_metrics(strava_id):
    path = os.path.join(_SESSIONS, f"{strava_id}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    summ = s.get("summary") or {}
    return {
        "n_laps":     summ.get("n_laps"),
        "best_lap_s": summ.get("best_lap_s"),
        "mean_lap_s": summ.get("mean_lap_s"),
        "track_cv":   summ.get("cv"),
    }


def main():
    df = pd.read_csv(_ENRICHED)
    id_col = df.columns[0]  # "ID" (potentiellement avec BOM)

    with open(_MATCHES, encoding="utf-8") as f:
        matches = json.load(f)

    # Drop anciennes colonnes pour idempotence
    df = df.drop(columns=[c for c in NEW_COLS if c in df.columns])

    rows = []
    for strava_id, m in matches.items():
        rows.append({
            id_col:           int(strava_id),
            "stadium_name":   f"{m['stadium_nom']} ({m['commune']})",
            "stadium_id":     m["stadium_id"],
            "track_length_m": m["piste_longueur_m"],
            **_session_metrics(strava_id),
        })

    if rows:
        merge_df = pd.DataFrame(rows)
        df = df.merge(merge_df, on=id_col, how="left")
    else:
        for c in NEW_COLS:
            df[c] = None

    df.to_csv(_ENRICHED, index=False)
    n_enriched = df["stadium_name"].notna().sum()
    print(f"[OK] {n_enriched} activités enrichies avec données stade")
    print(f"     {len(df)} lignes totales -> {_ENRICHED}")


if __name__ == "__main__":
    sys.exit(main())
