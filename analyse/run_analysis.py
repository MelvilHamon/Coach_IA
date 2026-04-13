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
sys.path.insert(0, _ROOT)
from api import storage

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
from sport_mapping import get_sport


# ── Colonnes enrichies ────────────────────────────────────────────────────────

_ENRICHED_COLS = [
    "sport",
    "trimp", "hrtss", "avg_power_w",
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
_NAN_ROW["sport"] = "autre"  # sport is a string, not NaN


# ── Helpers ───────────────────────────────────────────────────────────────────

# Cache of known stream filenames (loaded once per run_analysis call)
_stream_files_cache: set | None = None


def _ensure_stream_cache(streams_dir: str = None):
    global _stream_files_cache
    if _stream_files_cache is None:
        _dir = streams_dir or _STREAMS_DIR
        _stream_files_cache = set(storage.listdir(_dir))


def _stream_path(activity_id: int, streams_dir: str = None) -> str | None:
    _dir = streams_dir or _STREAMS_DIR
    _ensure_stream_cache(_dir)
    fname = f"{activity_id}.csv"
    if fname not in _stream_files_cache:
        return None
    return os.path.join(_dir, fname)


def _load_stream(activity_id: int, streams_dir: str = None) -> pd.DataFrame | None:
    p = _stream_path(activity_id, streams_dir)
    if p is None:
        return None
    try:
        return storage.read_csv(p)
    except Exception:
        return None


# ── Calcul par activité ───────────────────────────────────────────────────────

def _compute_activity_metrics(row: pd.Series, config: dict, streams_dir: str = None) -> dict:
    """
    Calcule les métriques pour une seule activité.
    Retourne un dict avec les colonnes enrichies (NaN si données manquantes).
    """
    athlete = config.get("athlete", {})
    hr_max            = athlete.get("hr_max", 195)
    hr_rest           = athlete.get("hr_rest", 45)
    hr_threshold      = athlete.get("hr_threshold", 166)
    sex               = athlete.get("sex", "male")
    hr_zones_custom   = athlete.get("hr_zones_custom")  # list of 5 BPM or None

    result = dict(_NAN_ROW)  # valeurs par défaut NaN

    # Sport normalisé (run / velo / autre)
    result["sport"] = get_sport(str(row.get("Type", "Run")))

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
    stream_df = _load_stream(int(row["ID"]), streams_dir)
    stream_path = _stream_path(int(row["ID"]), streams_dir)

    if stream_df is not None:
        # Zones FC
        zones = compute_hr_zones(stream_df, hr_max, hr_zones_custom=hr_zones_custom)
        result.update(zones)

        # Découplag aérobie
        result["decoupling_pct"] = compute_decoupling(stream_df)

        # Puissance moyenne (vélo avec capteur de puissance)
        if "power_w" in stream_df.columns:
            valid_power = stream_df["power_w"].dropna()
            if len(valid_power) > 0:
                result["avg_power_w"] = round(float(valid_power.mean()), 1)

    # ── Type de séance ────────────────────────────────────────────────────────
    result["session_type"] = detect_session_type(row, stream_path=stream_path, config=config)

    return result


# ── Pipeline principale ───────────────────────────────────────────────────────

def run_analysis(force: bool = False, data_dir: str = None, config_path: str = None) -> None:
    """
    Pipeline d'analyse enrichie.

    Parameters
    ----------
    data_dir : répertoire de données utilisateur (défaut: data/)
    config_path : chemin vers config.json (défaut: config.json racine)
    """
    # Reset stream file cache for this run
    global _stream_files_cache
    _stream_files_cache = None

    # Resolve paths
    _data_dir = data_dir or os.path.join(_ROOT, "data")
    _csv_path = os.path.join(_data_dir, "mes_activites_strava.csv")
    _enriched = os.path.join(_data_dir, "activities_enriched.csv")
    _streams_dir = os.path.join(_data_dir, "streams")
    _gps_dir = os.path.join(_data_dir, "gps")
    _garmin_streams = os.path.join(_data_dir, "garmin", "streams")
    _pr_path = os.path.join(_data_dir, "personal_records.json")
    _sync_state = os.path.join(_data_dir, "sync_state.json")
    _cfg_path = config_path or _CONFIG_PATH

    print("=== run_analysis.py — Pipeline d'analyse enrichie ===\n")

    # ── Chargement config ─────────────────────────────────────────────────────
    config = load_config(_cfg_path)

    # ── Chargement activités de base ──────────────────────────────────────────
    if not os.path.exists(_csv_path) or os.path.getsize(_csv_path) == 0:
        print(f"ERREUR : fichier activités introuvable ou vide : {_csv_path}")
        sys.exit(1)

    df = pd.read_csv(_csv_path)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    df = df.sort_values("Date").reset_index(drop=True)
    print(f"Activités chargées : {len(df)}")

    # ── Chargement données enrichies existantes ───────────────────────────────
    already_computed_ids = set()
    enriched_cache = {}

    if not force and os.path.exists(_enriched) and os.path.getsize(_enriched) > 0:
        df_existing = pd.read_csv(_enriched)
        # IDs déjà calculés (session_type non vide)
        mask = df_existing["session_type"].notna()
        recompute_count = 0
        # Stocker les valeurs calculées par ID
        for _, r in df_existing[mask].iterrows():
            act_id = int(r["ID"])
            # Skip cache if zones are missing but a stream file now exists
            has_zones = pd.notna(r.get("z1_pct"))
            if not has_zones and _stream_path(act_id, _streams_dir) is not None:
                recompute_count += 1
                continue  # Force recomputation
            already_computed_ids.add(act_id)
            enriched_cache[act_id] = {
                col: r[col] for col in _ENRICHED_COLS
                if col in df_existing.columns and col not in _POST_PROCESSING_COLS
            }
        print(f"Activités déjà analysées : {len(already_computed_ids)} (sautées)")
        if recompute_count:
            print(f"Activités à recalculer (streams disponibles) : {recompute_count}")

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
            m = _compute_activity_metrics(row, config, _streams_dir)
            print(f"→ {m.get('session_type', '?')}")

        metrics_rows.append(m)

    df_metrics = pd.DataFrame(metrics_rows, index=df.index)

    # ── Métriques de séries temporelles PAR SPORT (toujours recalculées) ─────
    # Chaque sport (run, velo, autre) a ses propres ACWR, volume hebdo, etc.
    # pour ne pas mélanger course et vélo dans les indicateurs.
    print("\nCalcul ACWR et métriques hebdomadaires (par sport)…")

    df_metrics["trimp_filled"] = df_metrics["trimp"].fillna(0)

    # Colonnes à initialiser avant le groupby
    for _col in ["acwr_km", "weekly_km", "weekly_elevation_m", "load_variation_pct",
                 "injury_risk_score", "injury_risk_label",
                 "flag_acwr", "flag_monotony", "flag_load_spike", "flag_consecutive",
                 "pace_trend_28d", "ef_trend_28d", "vo2max_estimate",
                 "ctl", "atl", "tsb", "monotony", "strain"]:
        df_metrics[_col] = np.nan
    df_metrics["injury_risk_label"] = ""

    sports = df_metrics["sport"].unique()
    for _sport in sports:
        sport_mask = df_metrics["sport"] == _sport
        df_sport = df[sport_mask].copy()
        df_metrics_sport = df_metrics[sport_mask].copy()

        if df_sport.empty:
            continue

        print(f"  [{_sport}] {sport_mask.sum()} activités")

        # ACWR par sport
        df_metrics.loc[sport_mask, "acwr_km"] = compute_acwr(df_sport, metric="km").values

        # Volume hebdo par sport
        weekly = compute_weekly_metrics(df_sport)
        df_metrics.loc[sport_mask, "weekly_km"]          = weekly["weekly_km"].values
        df_metrics.loc[sport_mask, "weekly_elevation_m"] = weekly["weekly_elevation_m"].values
        df_metrics.loc[sport_mask, "load_variation_pct"] = weekly["load_variation_pct"].values

        # Assemblage intermédiaire par sport
        enriched_cols_before_injury = _ENRICHED_COLS[:_ENRICHED_COLS.index("injury_risk_score")]
        df_enriched_sport = pd.concat([df_sport, df_metrics.loc[sport_mask, enriched_cols_before_injury]], axis=1)

        # Risque blessure par sport
        injury = compute_injury_risk(df_enriched_sport, config=config)
        for col in ["injury_risk_score", "injury_risk_label",
                    "flag_acwr", "flag_monotony", "flag_load_spike", "flag_consecutive"]:
            df_metrics.loc[sport_mask, col] = injury[col].values

        # Progression par sport
        progression = compute_progression_metrics(df_enriched_sport, config=config)
        for col in ["pace_trend_28d", "ef_trend_28d", "vo2max_estimate"]:
            df_metrics.loc[sport_mask, col] = progression[col].values

        # Fitness/Fatigue/Form par sport
        ff = compute_fitness_fatigue(df_enriched_sport)
        for col in ["ctl", "atl", "tsb"]:
            df_metrics.loc[sport_mask, col] = ff[col].values

        # Monotony & Strain par sport
        ms = compute_monotony_strain(df_enriched_sport)
        for col in ["monotony", "strain"]:
            df_metrics.loc[sport_mask, col] = ms[col].values

    print("Calcul par sport terminé.")

    # ── Assemblage final ──────────────────────────────────────────────────────
    df_enriched = pd.concat([df, df_metrics[_ENRICHED_COLS]], axis=1)
    df_enriched.to_csv(_enriched, index=False, encoding="utf-8-sig")
    print(f"\nFichier enrichi sauvegardé : {_enriched}")

    # ── Personal Records (sliding window GPS) ──────────────────────────────────
    print("Calcul des records personnels (sliding window GPS)…")
    pr_run = compute_personal_records(_gps_dir, _garmin_streams, activities_df=df, sport_filter="run")
    pr_velo = compute_personal_records(_gps_dir, _garmin_streams, activities_df=df, sport_filter="velo")
    pr = {"run": pr_run, "velo": pr_velo}
    os.makedirs(os.path.dirname(_pr_path), exist_ok=True)
    with open(_pr_path, "w", encoding="utf-8") as f:
        json.dump(pr, f, indent=2, ensure_ascii=False)
    pr_run_dists = ", ".join(f"{k}: {v['pace']}/km" for k, v in pr_run.items())
    pr_velo_dists = ", ".join(f"{k}: {v['pace']}/km" for k, v in pr_velo.items())
    print(f"  Records run   : {pr_run_dists or 'aucun'}")
    print(f"  Records vélo  : {pr_velo_dists or 'aucun'}")

    # ── Profil de vitesse athlète → config.json ───────────────────────────────
    speed_profile = compute_athlete_speed_profile(df_enriched)
    config["athlete_speed_profile"] = speed_profile
    with open(_cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"Profil vitesse : p75={speed_profile['p75_kmh']} km/h "
          f"(calculé sur {speed_profile['computed_from_n_activities']} runs)")

    # ── Mise à jour sync_state.json ───────────────────────────────────────────
    state = {}
    if os.path.exists(_sync_state):
        with open(_sync_state) as f:
            state = json.load(f)
    state["analysis_last_run"] = datetime.now(timezone.utc).isoformat()
    state["analysis_activities_count"] = len(df_enriched)
    os.makedirs(os.path.dirname(_sync_state), exist_ok=True)
    with open(_sync_state, "w") as f:
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
    _lv = pd.to_numeric(df["load_variation_pct"], errors="coerce")
    alerts = df[_lv.notna() & (_lv.abs() > 30)]
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
    parser.add_argument("--user", type=str, default=None,
                        help="ID utilisateur spécifique (sinon tous les utilisateurs)")
    args = parser.parse_args()

    _users_dir = os.path.join(_ROOT, "data", "users")

    if args.user:
        # Un seul utilisateur
        user_dir = os.path.join(_users_dir, args.user)
        config_path = os.path.join(user_dir, "config.json")
        if not os.path.isdir(user_dir):
            print(f"ERREUR : répertoire utilisateur introuvable : {user_dir}")
            sys.exit(1)
        print(f"\n{'#' * 60}")
        print(f"# Utilisateur : {args.user}")
        print(f"{'#' * 60}\n")
        run_analysis(force=args.force, data_dir=user_dir, config_path=config_path)
    else:
        # Tous les utilisateurs
        if not os.path.isdir(_users_dir):
            print(f"Aucun répertoire utilisateurs trouvé ({_users_dir}), lancement legacy…")
            run_analysis(force=args.force)
        else:
            user_ids = sorted(d for d in os.listdir(_users_dir)
                              if os.path.isdir(os.path.join(_users_dir, d)))
            if not user_ids:
                print("Aucun utilisateur trouvé.")
                sys.exit(0)
            print(f"Utilisateurs trouvés : {len(user_ids)}\n")
            for uid in user_ids:
                user_dir = os.path.join(_users_dir, uid)
                config_path = os.path.join(user_dir, "config.json")
                csv_path = os.path.join(user_dir, "mes_activites_strava.csv")
                if not os.path.exists(csv_path):
                    print(f"[{uid}] Pas de données Strava, skip.")
                    continue
                print(f"\n{'#' * 60}")
                print(f"# Utilisateur : {uid}")
                print(f"{'#' * 60}\n")
                try:
                    run_analysis(force=args.force, data_dir=user_dir, config_path=config_path)
                except Exception as e:
                    print(f"ERREUR pour {uid} : {e}")
            print(f"\nTerminé pour {len(user_ids)} utilisateur(s).")
