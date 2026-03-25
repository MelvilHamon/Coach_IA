"""
run_analysis.py — Pipeline d'analyse enrichie des activités.

Charge toutes les activités du CSV, calcule les métriques pour chacune,
et exporte data/activities_enriched.csv.

Optimisation : ne recalcule les métriques par activité (TRIMP, zones, EF, découplag, session_type)
que pour les IDs absents du fichier enrichi existant.
ACWR et métriques hebdomadaires sont toujours recalculés (séries temporelles complètes).

Usage :
    python3 analyse/run_analysis.py
    python3 analyse/run_analysis.py --force   # recalculer tout
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ── Chemins ───────────────────────────────────────────────────────────────────

_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CSV_PATH    = os.path.join(_ROOT, "data", "mes_activites_strava.csv")
_ENRICHED    = os.path.join(_ROOT, "data", "activities_enriched.csv")
_STREAMS_DIR = os.path.join(_ROOT, "data", "streams")
_CONFIG_PATH = os.path.join(_ROOT, "config.json")
_SYNC_STATE  = os.path.join(_ROOT, "data", "sync_state.json")
_GPS_DIR     = os.path.join(_ROOT, "data", "gps")
_GARMIN_STREAMS = os.path.join(_ROOT, "data", "garmin", "streams")
_PR_PATH     = os.path.join(_ROOT, "data", "personal_records.json")

# Ajouter le dossier analyse/ au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics import (
    compute_trimp,
    compute_hrtss,
    compute_hr_zones,
    compute_efficiency_factor,
    compute_decoupling,
    compute_acwr,
    compute_weekly_metrics,
    compute_athlete_speed_profile,
    compute_injury_risk,
    compute_progression_metrics,
    compute_fitness_fatigue,
    compute_monotony_strain,
    compute_personal_records,
    acwr_label,
    load_config,
)
from session_classifier import detect_session_type


# ── Colonnes enrichies ────────────────────────────────────────────────────────

_ENRICHED_COLS = [
    "trimp", "hrtss",
    "z1_min", "z2_min", "z3_min", "z4_min", "z5_min",
    "z1_pct", "z2_pct", "z3_pct", "z4_pct", "z5_pct",
    "dominant_zone",
    "efficiency_factor", "decoupling_pct",
    "session_type",
    # post-processing séries temporelles :
    "acwr_km", "weekly_km", "weekly_elevation_m", "load_variation_pct",
    # post-processing risque blessure :
    "injury_risk_score", "injury_risk_label",
    "flag_acwr", "flag_monotony", "flag_load_spike", "flag_consecutive",
    # post-processing progression long terme :
    "pace_trend_28d", "ef_trend_28d", "vo2max_estimate",
    # post-processing Banister EWMA :
    "ctl", "atl", "tsb",
    # post-processing Monotony & Strain :
    "monotony", "strain",
]

# Colonnes toujours recalculées en post-processing (jamais mises en cache)
_POST_PROCESSING_COLS = {
    "acwr_km", "weekly_km", "weekly_elevation_m", "load_variation_pct",
    "injury_risk_score", "injury_risk_label",
    "flag_acwr", "flag_monotony", "flag_load_spike", "flag_consecutive",
    "pace_trend_28d", "ef_trend_28d", "vo2max_estimate",
    "ctl", "atl", "tsb",
    "monotony", "strain",
}

_NAN_ROW = {col: float("nan") for col in _ENRICHED_COLS}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stream_path(activity_id: int) -> str | None:
    p = os.path.join(_STREAMS_DIR, f"{activity_id}.csv")
    return p if os.path.exists(p) else None


def _load_stream(activity_id: int) -> pd.DataFrame | None:
    p = _stream_path(activity_id)
    if p is None:
        return None
    try:
        return pd.read_csv(p)
    except Exception:
        return None


# ── Calcul par activité ───────────────────────────────────────────────────────

def _compute_activity_metrics(row: pd.Series, config: dict) -> dict:
    """
    Calcule les métriques pour une seule activité.
    Retourne un dict avec les colonnes enrichies (NaN si données manquantes).
    """
    athlete = config.get("athlete", {})
    hr_max       = athlete.get("hr_max", 195)
    hr_rest      = athlete.get("hr_rest", 45)
    hr_threshold = athlete.get("hr_threshold", 166)
    sex          = athlete.get("sex", "male")

    result = dict(_NAN_ROW)  # valeurs par défaut NaN

    distance_km  = float(row.get("Distance (km)", 0) or 0)
    duration_min = float(row.get("Temps (min)", 0) or 0)
    hr_raw       = row.get("Fréquence cardiaque (bpm)")
    hr_mean = float(hr_raw) if hr_raw and not (isinstance(hr_raw, float) and np.isnan(hr_raw)) else None

    # ── TRIMP & hrTSS (nécessite FC) ─────────────────────────────────────────
    if hr_mean:
        result["trimp"] = compute_trimp(duration_min, hr_mean, hr_max, hr_rest, sex)
        result["hrtss"] = compute_hrtss(duration_min, hr_mean, hr_threshold)

    # ── EF (nécessite FC) ────────────────────────────────────────────────────
    if hr_mean and distance_km > 0 and duration_min > 0:
        result["efficiency_factor"] = compute_efficiency_factor(distance_km, duration_min, hr_mean)

    # ── Stream-based metrics ──────────────────────────────────────────────────
    stream_df = _load_stream(int(row["ID"]))
    stream_path = _stream_path(int(row["ID"]))

    if stream_df is not None:
        # Zones FC
        zones = compute_hr_zones(stream_df, hr_max)
        result.update(zones)

        # Découplag aérobie
        result["decoupling_pct"] = compute_decoupling(stream_df)

    # ── Type de séance ────────────────────────────────────────────────────────
    result["session_type"] = detect_session_type(row, stream_path=stream_path, config=config)

    return result


# ── Pipeline principale ───────────────────────────────────────────────────────

def run_analysis(force: bool = False) -> None:
    print("=== run_analysis.py — Pipeline d'analyse enrichie ===\n")

    # ── Chargement config ─────────────────────────────────────────────────────
    config = load_config()

    # ── Chargement activités de base ──────────────────────────────────────────
    if not os.path.exists(_CSV_PATH):
        print(f"ERREUR : fichier activités introuvable : {_CSV_PATH}")
        sys.exit(1)

    df = pd.read_csv(_CSV_PATH)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    df = df.sort_values("Date").reset_index(drop=True)
    print(f"Activités chargées : {len(df)}")

    # ── Chargement données enrichies existantes ───────────────────────────────
    already_computed_ids = set()
    enriched_cache = {}

    if not force and os.path.exists(_ENRICHED):
        df_existing = pd.read_csv(_ENRICHED)
        # IDs déjà calculés (session_type non vide)
        mask = df_existing["session_type"].notna()
        already_computed_ids = set(df_existing.loc[mask, "ID"].astype(int))
        # Stocker les valeurs calculées par ID
        for _, r in df_existing[mask].iterrows():
            enriched_cache[int(r["ID"])] = {
                col: r[col] for col in _ENRICHED_COLS
                if col in df_existing.columns and col not in _POST_PROCESSING_COLS
            }
        print(f"Activités déjà analysées : {len(already_computed_ids)} (sautées)")

    new_ids = [int(i) for i in df["ID"] if int(i) not in already_computed_ids]
    print(f"Activités à analyser     : {len(new_ids)}\n")

    # ── Calcul des métriques par activité ─────────────────────────────────────
    metrics_rows = []
    for _, row in df.iterrows():
        act_id = int(row["ID"])

        if act_id in enriched_cache:
            m = dict(enriched_cache[act_id])
        else:
            print(f"  [{act_id}] {str(row['Nom'])[:40]:<40} ", end="", flush=True)
            m = _compute_activity_metrics(row, config)
            print(f"→ {m.get('session_type', '?')}")

        metrics_rows.append(m)

    df_metrics = pd.DataFrame(metrics_rows, index=df.index)

    # ── Métriques de séries temporelles (toujours recalculées) ───────────────
    print("\nCalcul ACWR et métriques hebdomadaires…")

    df_metrics["trimp_filled"] = df_metrics["trimp"].fillna(0)
    df_for_acwr = df.copy()
    df_for_acwr["trimp"] = df_metrics["trimp_filled"].values

    df_metrics["acwr_km"] = compute_acwr(df, metric="km").values

    weekly = compute_weekly_metrics(df)
    df_metrics["weekly_km"]          = weekly["weekly_km"].values
    df_metrics["weekly_elevation_m"] = weekly["weekly_elevation_m"].values
    df_metrics["load_variation_pct"] = weekly["load_variation_pct"].values

    # Assemblage intermédiaire : nécessaire pour injury_risk et progression
    # qui consomment acwr_km, load_variation_pct, trimp, session_type
    df_enriched_tmp = pd.concat([df, df_metrics[_ENRICHED_COLS[:_ENRICHED_COLS.index("injury_risk_score")]]], axis=1)

    print("Calcul risque blessure et métriques de progression…")
    injury = compute_injury_risk(df_enriched_tmp, config=config)
    for col in ["injury_risk_score", "injury_risk_label",
                "flag_acwr", "flag_monotony", "flag_load_spike", "flag_consecutive"]:
        df_metrics[col] = injury[col].values

    progression = compute_progression_metrics(df_enriched_tmp, config=config)
    for col in ["pace_trend_28d", "ef_trend_28d", "vo2max_estimate"]:
        df_metrics[col] = progression[col].values

    print("Calcul Fitness/Fatigue/Form (Banister EWMA)…")
    ff = compute_fitness_fatigue(df_enriched_tmp)
    for col in ["ctl", "atl", "tsb"]:
        df_metrics[col] = ff[col].values

    print("Calcul Monotony & Strain (Foster 1998)…")
    ms = compute_monotony_strain(df_enriched_tmp)
    for col in ["monotony", "strain"]:
        df_metrics[col] = ms[col].values

    # ── Assemblage final ──────────────────────────────────────────────────────
    df_enriched = pd.concat([df, df_metrics[_ENRICHED_COLS]], axis=1)
    df_enriched.to_csv(_ENRICHED, index=False, encoding="utf-8-sig")
    print(f"\nFichier enrichi sauvegardé : {_ENRICHED}")

    # ── Personal Records (sliding window GPS) ──────────────────────────────────
    print("Calcul des records personnels (sliding window GPS)…")
    pr = compute_personal_records(_GPS_DIR, _GARMIN_STREAMS, activities_df=df)
    with open(_PR_PATH, "w", encoding="utf-8") as f:
        json.dump(pr, f, indent=2, ensure_ascii=False)
    pr_dists = ", ".join(f"{k}: {v['pace']}/km" for k, v in pr.items())
    print(f"  Records trouvés : {pr_dists or 'aucun'}")

    # ── Profil de vitesse athlète → config.json ───────────────────────────────
    speed_profile = compute_athlete_speed_profile(df_enriched)
    config["athlete_speed_profile"] = speed_profile
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"Profil vitesse : p75={speed_profile['p75_kmh']} km/h "
          f"(calculé sur {speed_profile['computed_from_n_activities']} runs)")

    # ── Mise à jour sync_state.json ───────────────────────────────────────────
    state = {}
    if os.path.exists(_SYNC_STATE):
        with open(_SYNC_STATE) as f:
            state = json.load(f)
    state["analysis_last_run"] = datetime.now(timezone.utc).isoformat()
    state["analysis_activities_count"] = len(df_enriched)
    with open(_SYNC_STATE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    # ── Résumé console ────────────────────────────────────────────────────────
    _print_summary(df_enriched, config)


def _print_summary(df: pd.DataFrame, config: dict) -> None:
    print("\n" + "=" * 60)
    print("  RÉSUMÉ ANALYSE")
    print("=" * 60)

    total = len(df)
    with_fc  = df["trimp"].notna().sum()
    with_str = df["decoupling_pct"].notna().sum()
    print(f"  Activités analysées   : {total}")
    print(f"  Avec FC               : {with_fc} ({with_fc/total*100:.0f}%)")
    print(f"  Avec stream           : {with_str}")

    # ACWR actuel (dernière activité running)
    running_mask = df["session_type"].notna()
    if running_mask.any():
        last = df[running_mask].iloc[-1]
        acwr = last.get("acwr_km")
        if acwr and not (isinstance(acwr, float) and np.isnan(acwr)):
            label = acwr_label(float(acwr))
            alert = "  ⚠️  ALERTE SURCHARGE" if float(acwr) > 1.5 else ""
            print(f"\n  ACWR actuel (km)      : {acwr:.2f} — {label}{alert}")
        last_date = pd.to_datetime(last["Date"]).strftime("%d/%m/%Y")
        print(f"  Dernière séance       : {last_date} [{last.get('session_type', '?')}]")
        print(f"  Volume 7 jours        : {last.get('weekly_km', 0):.1f} km, "
              f"{last.get('weekly_elevation_m', 0):.0f} m D+")
        ctl_v = last.get("ctl")
        atl_v = last.get("atl")
        tsb_v = last.get("tsb")
        if ctl_v and not (isinstance(ctl_v, float) and np.isnan(ctl_v)):
            print(f"  CTL / ATL / TSB       : {ctl_v:.1f} / {atl_v:.1f} / {tsb_v:.1f}")

    # Répartition types de séances
    print("\n  Répartition types de séances :")
    counts = df["session_type"].value_counts()
    for stype, n in counts.items():
        print(f"    {stype:<30} {n:>3} séances")

    # Alertes volume
    alerts = df[df["load_variation_pct"].notna() & (df["load_variation_pct"].abs() > 30)]
    if not alerts.empty:
        print(f"\n  ⚠️  {len(alerts)} semaine(s) avec variation de charge > 30% :")
        for _, r in alerts.tail(3).iterrows():
            d = pd.to_datetime(r["Date"]).strftime("%d/%m")
            print(f"    {d} : {r['load_variation_pct']:+.0f}% ({r['weekly_km']:.0f} km)")

    print("=" * 60)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyse enrichie des activités Strava")
    parser.add_argument("--force", action="store_true",
                        help="Recalculer toutes les métriques (ignore le cache)")
    args = parser.parse_args()
    run_analysis(force=args.force)
