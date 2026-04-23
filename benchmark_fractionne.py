"""
benchmark_fractionne.py — Diagnostic complet de la détection fractionné.

Teste chaque run ayant un stream et affiche :
- Le session_type actuel (depuis activities_enriched.csv)
- Le résultat du détecteur (is_fractionne, session_type détecté)
- Les valeurs de chaque critère de validation vs le seuil
- Quel critère bloque la détection quand elle échoue

Usage :
    python benchmark_fractionne.py                     # tous les runs
    python benchmark_fractionne.py --only-failures     # seulement les non-détectés
    python benchmark_fractionne.py --simulate-speed 8  # simule un coureur à 8 km/h
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyse"))

from analyse.detect_fract_v2 import (
    analyze_fractionne,
    preprocess,
    find_effort_threshold_gmm,
    segment_signal,
    extract_block_metrics,
    cluster_blocks,
    extract_recoveries,
    summarize_session,
)

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_config():
    with open(os.path.join(_ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def diagnose_one(stream_path: str, activity_id, sport_type: str = "Run",
                 athlete_mean_speed: float = 0.0, config: dict = None):
    """
    Lance la détection ET retourne les valeurs diagnostiques de chaque critère.
    """
    cfg = config or _load_config()
    det_cfg = cfg.get("detection_fractionne", {})
    speed_profile = cfg.get("athlete_speed_profile", {})

    min_effort_spd = float(speed_profile.get("p75_kmh", 0.0))
    mean_spd = athlete_mean_speed if athlete_mean_speed > 0 else float(speed_profile.get("mean_kmh", 0.0))

    if sport_type == "TrailRun":
        max_block_cv = det_cfg.get("max_block_cv_trail", 0.20)
    else:
        max_block_cv = det_cfg.get("max_block_cv_run", 0.12)
    max_recup_cv = det_cfg.get("max_recup_cv", 0.45)

    # Seuils de base
    min_cv_base = 0.17
    min_ef_ratio_base = 1.35
    min_ef_vs_mean = 1.03

    # Adaptation coureur lent
    if mean_spd > 0:
        speed_factor = max(0.6, min(1.0, mean_spd / 12.0))
        max_block_cv_adj = min(0.20, max_block_cv / speed_factor)
        min_ef_ratio_adj = max(1.20, min_ef_ratio_base - 0.12 * (1 - speed_factor))
        min_cv_adj = max(0.12, min_cv_base - 0.05 * (1 - speed_factor))
    else:
        speed_factor = 1.0
        max_block_cv_adj = max_block_cv
        min_ef_ratio_adj = min_ef_ratio_base
        min_cv_adj = min_cv_base

    # Run detection pipeline manually for diagnostics
    try:
        df = pd.read_csv(stream_path)
        df = preprocess(df)
    except Exception as e:
        return {"error": str(e)}

    threshold = find_effort_threshold_gmm(df["speed_smooth"].values)
    segments = segment_signal(df, threshold)
    blocks = extract_block_metrics(df, segments)

    cv_speed = float(df["speed_smooth"].std() / (df["speed_smooth"].mean() + 1e-6))
    session_mean_spd = float(df["speed_smooth"].mean())

    effort_segs = [s for s in segments if s["type"] == "effort"]
    recovery_segs = [s for s in segments if s["type"] == "recovery"]

    def _mean_spd(segs):
        speeds = []
        for s in segs:
            b = df[(df["time_s"] >= s["start"]) & (df["time_s"] <= s["end"])]
            if not b.empty:
                speeds.append(float(b["speed_smooth"].mean()))
        return float(np.mean(speeds)) if speeds else 0.0

    effort_spd = _mean_spd(effort_segs)
    recovery_spd = _mean_spd(recovery_segs)
    ef_ratio = effort_spd / (recovery_spd + 1e-6) if recovery_spd > 0 else 0.0

    # Cluster + block CV
    cv_core_median = None
    recup_cv = None
    n_reps = 0
    if not blocks.empty:
        blocks_cl = cluster_blocks(blocks)
        recoveries = extract_recoveries(df, blocks_cl)
        patterns = summarize_session(blocks_cl, recoveries)
        n_reps = max((p["reps"] for p in patterns), default=0)

        if "cluster" in blocks_cl.columns and "speed_cv_core" in blocks_cl.columns:
            valid_blks = blocks_cl[blocks_cl["cluster"] != -1]
            if not valid_blks.empty:
                best_cluster = valid_blks.groupby("cluster").size().idxmax()
                cv_core_median = float(
                    valid_blks[valid_blks["cluster"] == best_cluster]["speed_cv_core"].median()
                )
                cluster_recups = recoveries[recoveries["cluster"] == best_cluster] if not recoveries.empty else pd.DataFrame()
                if len(cluster_recups) >= 2:
                    recup_cv = float(
                        cluster_recups["recup_dur_s"].std()
                        / (cluster_recups["recup_dur_s"].mean() + 1e-6)
                    )
    else:
        patterns = []

    # Run the actual detection (with adaptation)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = analyze_fractionne(
            stream_path, verbose=False,
            sport_type=sport_type,
            min_effort_speed_kmh=min_effort_spd,
            athlete_mean_speed_kmh=mean_spd,
            max_block_cv=det_cfg.get("max_block_cv_trail" if sport_type == "TrailRun" else "max_block_cv_run", None),
            max_recup_cv=det_cfg.get("max_recup_cv", None),
        )

    # Build diagnostic
    criteria = {
        "1_cv_global":    {"value": round(cv_speed, 4), "seuil_base": min_cv_base, "seuil_adapte": round(min_cv_adj, 4), "pass": cv_speed >= min_cv_adj},
        "2_ef_ratio":     {"value": round(ef_ratio, 3), "seuil_base": min_ef_ratio_base, "seuil_adapte": round(min_ef_ratio_adj, 3), "pass": ef_ratio >= min_ef_ratio_adj},
        "3_block_cv":     {"value": round(cv_core_median, 4) if cv_core_median is not None else None, "seuil_base": max_block_cv, "seuil_adapte": round(max_block_cv_adj, 4), "pass": cv_core_median is None or cv_core_median <= max_block_cv_adj},
        "4_recup_cv":     {"value": round(recup_cv, 3) if recup_cv is not None else None, "seuil": max_recup_cv, "pass": recup_cv is None or recup_cv < max_recup_cv},
        "5_ef_vs_mean":   {"value": round(effort_spd / (session_mean_spd + 1e-6), 3), "seuil": min_ef_vs_mean, "pass": session_mean_spd > 0 and effort_spd >= session_mean_spd * min_ef_vs_mean},
        "6_min_speed":    {"value": round(effort_spd, 2), "seuil": round(min_effort_spd, 2), "pass": min_effort_spd <= 0 or effort_spd >= min_effort_spd},
    }

    return {
        "activity_id": activity_id,
        "is_fractionne": result.get("is_fractionne", False),
        "detected_type": result.get("session_type", "indéterminé"),
        "threshold_gmm": round(threshold, 2),
        "effort_speed": round(effort_spd, 2),
        "recovery_speed": round(recovery_spd, 2),
        "session_mean_speed": round(session_mean_spd, 2),
        "n_reps": n_reps,
        "n_effort_segments": len(effort_segs),
        "speed_factor": round(speed_factor, 3),
        "athlete_mean_speed": round(mean_spd, 2),
        "criteria": criteria,
        "blocking": [k for k, v in criteria.items() if not v["pass"]],
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark détection fractionné")
    parser.add_argument("--only-failures", action="store_true", help="N'afficher que les runs non détectés comme fractionné")
    parser.add_argument("--only-detected", action="store_true", help="N'afficher que les fractionnés détectés")
    parser.add_argument("--simulate-speed", type=float, default=0.0, help="Simuler un coureur à cette vitesse moyenne (km/h)")
    parser.add_argument("--limit", type=int, default=0, help="Limiter le nombre de runs testés")
    parser.add_argument("--activity-id", type=str, default="", help="Tester un seul activity ID")
    parser.add_argument("--user", type=str, default="", help="User ID (dossier dans data/users/)")
    args = parser.parse_args()

    if args.user:
        user_dir = os.path.join(_ROOT, "data", "users", args.user)
        config_path = os.path.join(user_dir, "config.json")
        enriched_path = os.path.join(user_dir, "activities_enriched.csv")
        streams_dir = os.path.join(user_dir, "streams")
        if not os.path.exists(enriched_path):
            print(f"Erreur: {enriched_path} introuvable")
            return
        config = json.load(open(config_path, encoding="utf-8")) if os.path.exists(config_path) else _load_config()
        enriched = pd.read_csv(enriched_path)
    else:
        config = _load_config()
        enriched = pd.read_csv(os.path.join(_ROOT, "data", "activities_enriched.csv"))
        streams_dir = os.path.join(_ROOT, "data", "streams")

    # Filtrer les runs
    runs = enriched[enriched["sport"] == "run"].copy()
    runs["speed_kmh"] = runs["Distance (km)"] / (runs["Temps (min)"] / 60)

    if args.activity_id:
        runs = runs[runs["ID"].astype(str) == args.activity_id]

    results = []
    tested = 0

    for _, row in runs.iterrows():
        aid = row["ID"]
        stream_path = os.path.join(streams_dir, f"{int(aid)}.csv")
        if not os.path.exists(stream_path):
            continue

        sport_type = str(row.get("Type", "Run"))
        if sport_type in ("Hike", "Soccer", "Workout"):
            continue

        diag = diagnose_one(stream_path, aid, sport_type=sport_type,
                           athlete_mean_speed=args.simulate_speed, config=config)

        if "error" in diag:
            continue

        current_type = str(row.get("session_type", ""))

        if args.only_failures and diag["is_fractionne"]:
            continue
        if args.only_detected and not diag["is_fractionne"]:
            continue

        results.append({**diag, "current_type": current_type, "avg_speed": round(float(row["speed_kmh"]), 1) if pd.notna(row["speed_kmh"]) and np.isfinite(row["speed_kmh"]) else 0})
        tested += 1
        if args.limit and tested >= args.limit:
            break

    # Display
    print(f"\n{'='*80}")
    print(f"  BENCHMARK DÉTECTION FRACTIONNÉ")
    print(f"  Runs testés : {len(results)}")
    if args.simulate_speed > 0:
        print(f"  Simulation vitesse athlète : {args.simulate_speed} km/h")
    print(f"{'='*80}\n")

    detected = [r for r in results if r["is_fractionne"]]
    not_detected = [r for r in results if not r["is_fractionne"]]

    print(f"Fractionnés détectés : {len(detected)} / {len(results)}")
    print()

    # Summary of blocking criteria for non-detected
    if not_detected:
        blocking_counts = {}
        for r in not_detected:
            for b in r["blocking"]:
                blocking_counts[b] = blocking_counts.get(b, 0) + 1
        print("=== Critères bloquants (runs NON détectés) ===")
        for k, v in sorted(blocking_counts.items(), key=lambda x: -x[1]):
            print(f"  {k:20s} : bloque {v:3d} / {len(not_detected)} runs ({100*v/len(not_detected):.0f}%)")
        print()

    # Detail per activity
    for r in sorted(results, key=lambda x: (not x["is_fractionne"], x["activity_id"])):
        icon = "V" if r["is_fractionne"] else "X"
        print(f"[{icon}] ID={r['activity_id']}  current={r['current_type']:25s}  detected={r['detected_type']:25s}  speed={r['avg_speed']}km/h  reps={r['n_reps']}")
        for cname, cdata in r["criteria"].items():
            val = cdata["value"]
            if "seuil_adapte" in cdata:
                seuil = cdata["seuil_adapte"]
                base = cdata["seuil_base"]
                seuil_str = f"seuil={seuil}" if seuil == base else f"seuil={seuil} (base={base})"
            else:
                seuil_str = f"seuil={cdata['seuil']}"
            icon_c = "OK" if cdata["pass"] else "XX"
            print(f"    [{icon_c}] {cname:18s} : val={val}  {seuil_str}")
        print()


if __name__ == "__main__":
    main()
