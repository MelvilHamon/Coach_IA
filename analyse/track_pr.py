"""
track_pr.py — Consolide les records (PR) par stade à partir des séances piste
calculées par track_metrics.py.

Pour chaque stade ayant au moins 1 séance dans data/track_sessions/ :
  - meilleur tour absolu (et la séance correspondante)
  - meilleurs N tours consécutifs pour N ∈ {2, 3, 5, 10}
  - meilleure pace moyenne d'une séance complète
  - progression : best_lap et mean_lap par séance, ordonnés par date

Date des séances lue depuis data/activities_enriched.csv.
Sortie : data/track_pr.json (1 entrée par stade).
"""

import json
import os
import sys
from collections import defaultdict
from glob import glob

import pandas as pd

_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SESSIONS = os.path.join(_ROOT, "data", "track_sessions")
_ENRICHED = os.path.join(_ROOT, "data", "activities_enriched.csv")
_OUT      = os.path.join(_ROOT, "data", "track_pr.json")


def _load_dates():
    df = pd.read_csv(_ENRICHED, usecols=["ID", "Date"])
    return {str(row["ID"]): row["Date"] for _, row in df.iterrows()}


def main():
    dates = _load_dates()
    by_stadium = defaultdict(list)

    for path in sorted(glob(os.path.join(_SESSIONS, "*.json"))):
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        if not s.get("laps") or not s.get("summary"):
            continue
        s["date"] = dates.get(str(s["strava_id"]))
        by_stadium[s["stadium_id"]].append(s)

    results = {}
    for sid, sessions in by_stadium.items():
        sessions.sort(key=lambda x: x.get("date") or "")
        first = sessions[0]
        track_length = first["summary"]["track_length_m"]

        # PR meilleur tour
        pr_lap, pr_lap_sid = float("inf"), None
        # PR N consécutifs
        pr_n = {n: (float("inf"), None) for n in [2, 3, 5, 10]}
        # Meilleure pace moyenne (sur séance "propre" : > 50% tours non-partial)
        best_pace, best_pace_sid = float("inf"), None

        progression = []
        for s in sessions:
            summ = s["summary"]
            if summ["best_lap_s"] < pr_lap:
                pr_lap = summ["best_lap_s"]
                pr_lap_sid = s["strava_id"]
            for n in [2, 3, 5, 10]:
                key = f"best_{n}_consecutive_s"
                if key in summ and summ[key] < pr_n[n][0]:
                    pr_n[n] = (summ[key], s["strava_id"])
            if summ["mean_pace_min_per_km"] is not None and summ["mean_pace_min_per_km"] < best_pace:
                best_pace = summ["mean_pace_min_per_km"]
                best_pace_sid = s["strava_id"]
            progression.append({
                "date":        s.get("date"),
                "strava_id":   s["strava_id"],
                "best_lap_s":  summ["best_lap_s"],
                "mean_lap_s":  summ["mean_lap_s"],
                "n_laps":      summ["n_laps"],
                "cv":          summ["cv"],
            })

        entry = {
            "stadium_nom":     first["stadium_nom"],
            "commune":         first["commune"],
            "track_length_m":  track_length,
            "n_sessions":      len(sessions),
            "first_session":   sessions[0].get("date"),
            "last_session":    sessions[-1].get("date"),
            "pr_lap_s":        pr_lap if pr_lap != float("inf") else None,
            "pr_lap_session":  pr_lap_sid,
            "best_mean_pace":  best_pace if best_pace != float("inf") else None,
            "best_mean_pace_session": best_pace_sid,
            "progression":     progression,
        }
        for n in [2, 3, 5, 10]:
            v, src = pr_n[n]
            entry[f"pr_{n}_consec_s"] = v if v != float("inf") else None
            entry[f"pr_{n}_consec_session"] = src
        results[sid] = entry

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[OK] {len(results)} stades consolidés dans {_OUT}")
    for sid, e in results.items():
        pr = f"{e['pr_lap_s']}s" if e['pr_lap_s'] else "—"
        print(f"  {e['stadium_nom']} ({e['commune']}) | {e['n_sessions']} séances | PR tour: {pr}")


if __name__ == "__main__":
    sys.exit(main())
