"""
detect_cotes_test.py — Détecteur expérimental "séance côtes".

Script standalone à passer sur les activités existantes pour calibrer
les seuils avant intégration dans session_classifier.py.

Heuristique :
  - Pré-filtre running, D+/km ∈ [12, 50] (en-dessous = plat, au-dessus = trail).
  - Lissage altitude → pente instantanée.
  - Repère segments en montée soutenue : pente ≥ pente_min, durée ≥ 20s.
  - Pour chaque montée : effort si vitesse moy ≥ seuil_actif athlète
    (le seuil est abaissé selon la pente — on ne court pas vite à 10%).
  - Score séance côtes = nb segments effortés ≥ 3 ET D+ cumulé dans efforts
    représente ≥ 40% du D+ total ET D+ global ≥ 80 m.

Usage :
  python scripts/detect_cotes_test.py            # parcourt toutes les activités
  python scripts/detect_cotes_test.py --id 123   # une seule activité
  python scripts/detect_cotes_test.py --top 20   # n meilleurs candidats
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CSV_ACT = DATA / "mes_activites_strava.csv"
STREAMS = DATA / "streams"
CONFIG = ROOT / "config.json"


# ── Paramètres détection (à calibrer) ─────────────────────────────────────────
SLOPE_MIN_PCT       = 4.0    # pente min pour considérer une montée (%)
CLIMB_MIN_DUR_S     = 20.0   # durée min d'une montée
CLIMB_MAX_DUR_S     = 360.0  # au-dessus → plutôt long faux-plat / trail
CLIMB_MIN_GAIN_M    = 8.0    # gain altitude min sur la montée
CLIMB_MAX_SLOPE_PCT = 25.0   # plafond pente (au-delà : artefact GPS)
SMOOTH_ALT_WIN_S    = 15     # fenêtre lissage altitude (s)
GAP_MERGE_S         = 5.0    # fusionne 2 montées séparées par <5s de plat
ELEV_PER_KM_MIN     = 12.0   # pré-filtre : exclut le plat
ELEV_PER_KM_MAX     = 50.0   # au-dessus : trail/montagne
MIN_EFFORT_CLIMBS   = 3      # nb min de montées effortées
MIN_CLIMB_EFFORT_SHARE = 0.40  # part du D+ total dans les montées effortées
MIN_TOTAL_GAIN_M    = 80.0   # D+ min de la séance


def _load_config() -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text())
    return {}


def _read_stream(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if "altitude_m" not in df.columns or "time_s" not in df.columns:
        return None
    if df["altitude_m"].isna().all():
        return None
    return df


def _smooth(arr: np.ndarray, win: int) -> np.ndarray:
    if win <= 1 or len(arr) < win:
        return arr
    k = np.ones(win) / win
    return np.convolve(arr, k, mode="same")


def _detect_climbs(df: pd.DataFrame) -> list[dict]:
    """Retourne la liste des montées soutenues détectées."""
    t = df["time_s"].values.astype(float)
    alt_raw = df["altitude_m"].ffill().bfill().values.astype(float)
    spd = df["speed_kmh"].ffill().fillna(0).values.astype(float) if "speed_kmh" in df else np.zeros(len(t))
    bpm = df["bpm"].ffill().values.astype(float) if "bpm" in df else np.full(len(t), np.nan)

    # Lissage altitude par fenêtre temporelle
    dt = np.diff(t)
    median_dt = float(np.median(dt)) if len(dt) else 1.0
    win = max(3, int(round(SMOOTH_ALT_WIN_S / max(median_dt, 0.5))))
    alt = _smooth(alt_raw, win)

    # Pente en % : dz/dx où dx = vitesse * dt (m). Fallback dt=1m si vitesse nulle.
    # Pour stabilité on calcule la pente sur fenêtre glissante de ~10s.
    horiz_m = np.zeros(len(t))
    horiz_m[1:] = (spd[1:] / 3.6) * np.diff(t)  # m parcourus entre 2 samples
    horiz_cum = np.cumsum(horiz_m)

    # Pente instantanée sur fenêtre ~10s
    pente_win = max(3, int(round(10.0 / max(median_dt, 0.5))))
    slopes = np.zeros(len(t))
    for i in range(len(t)):
        a = max(0, i - pente_win)
        b = min(len(t) - 1, i + pente_win)
        dh = alt[b] - alt[a]
        dx = horiz_cum[b] - horiz_cum[a]
        if dx > 5.0:
            slopes[i] = 100.0 * dh / dx

    # Repère segments slope >= SLOPE_MIN_PCT
    is_up = slopes >= SLOPE_MIN_PCT
    climbs = []
    i = 0
    n = len(t)
    while i < n:
        if not is_up[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and is_up[j + 1]:
            j += 1
        # fusion avec montée suivante si gap court
        k = j
        while k + 1 < n:
            # cherche prochain départ
            m = k + 1
            while m < n and not is_up[m]:
                m += 1
            if m >= n or (t[m] - t[k]) > GAP_MERGE_S:
                break
            end = m
            while end + 1 < n and is_up[end + 1]:
                end += 1
            k = end
        j = k

        dur = t[j] - t[i]
        gain = alt[j] - alt[i]
        dist_m = horiz_cum[j] - horiz_cum[i]
        avg_slope = 100.0 * gain / dist_m if dist_m > 0 else 0.0
        if (dur >= CLIMB_MIN_DUR_S and dur <= CLIMB_MAX_DUR_S
                and gain >= CLIMB_MIN_GAIN_M and dist_m > 20
                and avg_slope <= CLIMB_MAX_SLOPE_PCT):
            seg_spd = spd[i:j + 1]
            seg_bpm = bpm[i:j + 1]
            valid_bpm = seg_bpm[np.isfinite(seg_bpm) & (seg_bpm > 0)]
            climbs.append({
                "t_start": float(t[i]),
                "t_end": float(t[j]),
                "duration_s": float(dur),
                "gain_m": float(gain),
                "dist_m": float(dist_m),
                "avg_slope_pct": float(100.0 * gain / dist_m),
                "avg_speed_kmh": float(np.mean(seg_spd)) if len(seg_spd) else 0.0,
                "max_speed_kmh": float(np.max(seg_spd)) if len(seg_spd) else 0.0,
                "avg_bpm": float(np.mean(valid_bpm)) if len(valid_bpm) else None,
            })
        i = j + 1
    return climbs


def _is_effort(climb: dict, athlete_p70: float, hr_max: int) -> bool:
    """Un effort en côte : vitesse soutenue malgré la pente OU FC élevée.

    Seuil vitesse ajusté à la pente : on ne court pas à p70 à 10%.
    Règle empirique : on perd ~0.4 km/h par % de pente au-delà de 4%.
    """
    pente = climb["avg_slope_pct"]
    penalty = max(0.0, (pente - 4.0) * 0.4)
    spd_target = max(6.0, athlete_p70 - penalty)
    fast_enough = climb["avg_speed_kmh"] >= spd_target
    hr = climb.get("avg_bpm")
    hr_high = (hr is not None) and (hr / hr_max >= 0.85)
    return fast_enough or hr_high


def analyze_activity(act_id: str, sport_type: str, dist_km: float, elev_m: float,
                     athlete_p70: float, hr_max: int) -> dict | None:
    stream_path = STREAMS / f"{act_id}.csv"
    if not stream_path.exists():
        return None
    df = _read_stream(stream_path)
    if df is None or len(df) < 60:
        return None

    elev_per_km = elev_m / dist_km if dist_km > 0 else 0.0
    if not (ELEV_PER_KM_MIN <= elev_per_km <= ELEV_PER_KM_MAX):
        return {"id": act_id, "is_cote": False, "reason": f"D+/km={elev_per_km:.1f} hors plage"}
    if elev_m < MIN_TOTAL_GAIN_M:
        return {"id": act_id, "is_cote": False, "reason": f"D+ trop faible ({elev_m:.0f}m)"}

    climbs = _detect_climbs(df)
    if not climbs:
        return {"id": act_id, "is_cote": False, "reason": "aucune montée soutenue"}

    efforts = [c for c in climbs if _is_effort(c, athlete_p70, hr_max)]
    gain_total = sum(c["gain_m"] for c in climbs)
    gain_effort = sum(c["gain_m"] for c in efforts)
    effort_share = gain_effort / gain_total if gain_total > 0 else 0.0

    is_cote = (
        len(efforts) >= MIN_EFFORT_CLIMBS
        and effort_share >= MIN_CLIMB_EFFORT_SHARE
    )

    return {
        "id": act_id,
        "sport_type": sport_type,
        "dist_km": dist_km,
        "elev_m": elev_m,
        "elev_per_km": elev_per_km,
        "n_climbs": len(climbs),
        "n_efforts": len(efforts),
        "gain_in_efforts_m": round(gain_effort, 1),
        "effort_share": round(effort_share, 2),
        "avg_climb_dur_s": round(np.mean([c["duration_s"] for c in efforts]), 1) if efforts else None,
        "avg_climb_slope_pct": round(np.mean([c["avg_slope_pct"] for c in efforts]), 1) if efforts else None,
        "avg_climb_speed_kmh": round(np.mean([c["avg_speed_kmh"] for c in efforts]), 1) if efforts else None,
        "is_cote": is_cote,
        "climbs": climbs,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Analyser une seule activité")
    ap.add_argument("--top", type=int, default=30, help="Nb candidats à afficher")
    ap.add_argument("--all-candidates", action="store_true",
                    help="Liste aussi les activités proches du seuil (rejetées)")
    ap.add_argument("--verbose", action="store_true", help="Détail des montées")
    args = ap.parse_args()

    cfg = _load_config()
    athlete_p70 = float(cfg.get("athlete_speed_profile", {}).get("p70_kmh", 10.0))
    hr_max = int(cfg.get("athlete", {}).get("hr_max", 195))

    df_act = pd.read_csv(CSV_ACT)
    # Type running uniquement
    df_run = df_act[df_act["Type"].isin(["Run", "TrailRun"])].copy()
    if args.id:
        df_run = df_run[df_run["ID"].astype(str) == str(args.id)]

    results = []
    for _, row in df_run.iterrows():
        try:
            res = analyze_activity(
                act_id=str(row["ID"]),
                sport_type=str(row["Type"]),
                dist_km=float(row["Distance (km)"] or 0),
                elev_m=float(row["Dénivelé (m)"] or 0),
                athlete_p70=athlete_p70,
                hr_max=hr_max,
            )
        except Exception as e:
            res = {"id": str(row["ID"]), "error": str(e)}
        if res:
            res["name"] = str(row.get("Nom", ""))
            res["date"] = str(row.get("Date", ""))[:10]
            results.append(res)

    # Trie : is_cote=True d'abord, puis par effort_share desc
    cotes = sorted([r for r in results if r.get("is_cote")],
                   key=lambda r: (r.get("effort_share", 0), r.get("n_efforts", 0)),
                   reverse=True)
    near_miss = sorted([r for r in results if r.get("n_climbs", 0) >= 2 and not r.get("is_cote")
                        and r.get("n_efforts", 0) >= 1],
                       key=lambda r: (r.get("effort_share", 0), r.get("n_efforts", 0)),
                       reverse=True)

    print(f"\n=== {len(cotes)} séances détectées comme 'séance côtes' ===\n")
    cols = ["date", "id", "name", "dist_km", "elev_m", "elev_per_km",
            "n_climbs", "n_efforts", "effort_share",
            "avg_climb_dur_s", "avg_climb_slope_pct", "avg_climb_speed_kmh"]
    for r in cotes[:args.top]:
        print(" | ".join(f"{r.get(c, '')}" for c in ["date", "id", "name"]))
        print(f"    dist={r['dist_km']:.1f}km  D+={r['elev_m']:.0f}m  D+/km={r['elev_per_km']:.1f}"
              f"  montées={r['n_climbs']} (effortées={r['n_efforts']})  share={r['effort_share']:.0%}"
              f"  durée_moy={r['avg_climb_dur_s']}s  pente_moy={r['avg_climb_slope_pct']}%"
              f"  v_moy={r['avg_climb_speed_kmh']}km/h")
        if args.verbose:
            for c in r["climbs"]:
                eff = "✓" if _is_effort(c, athlete_p70, hr_max) else " "
                bpm = f" bpm={c['avg_bpm']:.0f}" if c.get("avg_bpm") else ""
                print(f"      [{eff}] t={c['t_start']:.0f}→{c['t_end']:.0f}s  "
                      f"d={c['duration_s']:.0f}s  +{c['gain_m']:.0f}m  "
                      f"pente={c['avg_slope_pct']:.1f}%  v={c['avg_speed_kmh']:.1f}km/h{bpm}")
        print()

    if args.all_candidates:
        print(f"\n=== {len(near_miss)} candidates rejetées proches du seuil (top {args.top}) ===\n")
        for r in near_miss[:args.top]:
            print(f"  {r['date']} {r['id']} {r['name']}")
            print(f"    D+/km={r['elev_per_km']:.1f}  montées={r['n_climbs']}"
                  f" effortées={r['n_efforts']} share={r['effort_share']:.0%}")


if __name__ == "__main__":
    main()
