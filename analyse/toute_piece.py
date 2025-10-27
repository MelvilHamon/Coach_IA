# analyse_seance.py — multi-lissages + détection robuste d'intervalles

import os
import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

# =========================================================
# 0) Configs multi-échelles (adapter si ton pas != 1 Hz)
# =========================================================
LISSAGES = {
    # sprints / 30"-1' / 200-400 m
    "short":  {"window": 11, "poly": 2, "min_dur": 20,  "max_pause": 6,  "seuil_rel": 0.82},
    # 1'-2' / 500-800 m
    "medium": {"window": 25, "poly": 2, "min_dur": 70,  "max_pause": 8,  "seuil_rel": 0.80},
    # 3'-6' / 1-2 km (ex: 4×4')
    "long":   {"window": 51, "poly": 3, "min_dur": 160, "max_pause": 12, "seuil_rel": 0.78},
}
# Règles d’aggrégation pour reconnaître des patterns (durées proches)
DURATION_GROUPING = {"short": 5, "medium": 10, "long": 15}  # arrondi (s) pour grouper des répétitions

# ======================
# 1) Chargement streams
# ======================
def load_stream(activity_path: str) -> pd.DataFrame:
    df = pd.read_csv(activity_path)
    # imputations simples
    for col in ("speed_kmh", "bpm"):
        if col in df.columns:
            df[col] = pd.Series(df[col]).ffill().bfill()
    # colonnes de lissage multi-échelles
    for name, cfg in LISSAGES.items():
        w, p = cfg["window"], cfg["poly"]
        # window doit être impair et <= len
        win = min(len(df) - (1 - len(df) % 2), w) if len(df) > w else (len(df) // 2) * 2 + 1
        df[f"speed_{name}"] = savgol_filter(df["speed_kmh"], window_length=win, polyorder=p, mode="interp")
        if "bpm" in df.columns and pd.api.types.is_numeric_dtype(df["bpm"]):
            df[f"bpm_{name}"] = savgol_filter(df["bpm"], window_length=win, polyorder=2 if p < 2 else p, mode="interp")
    return df

# =================================================
# 2) Détection d’efforts (fenêtre + micro-coupures)
# =================================================
def _find_efforts(time_s, speed, seuil, min_dur_s=60, max_pause_s=8):
    """
    Itère sur la série lissée et renvoie des (start, end) en secondes.
    Fusionne les micro-baisse < max_pause_s sous le seuil.
    """
    intervals = []
    inside, t_start, below = False, None, 0

    for i in range(len(speed)):
        t = time_s[i]
        if not inside and speed[i] >= seuil:
            inside, t_start, below = True, t, 0
        elif inside:
            if speed[i] < seuil:
                below += 1
                if below > max_pause_s:
                    t_end = t
                    if (t_end - t_start) >= min_dur_s:
                        intervals.append((t_start, t_end))
                    inside = False
            else:
                below = 0
    # si on finit "dedans"
    if inside:
        t_end = time_s.iloc[-1] if hasattr(time_s, "iloc") else time_s[-1]
        if (t_end - t_start) >= min_dur_s:
            intervals.append((t_start, t_end))
    return intervals

def detect_intervals_multiscale(df: pd.DataFrame):
    """
    Essaie plusieurs lissages (short/medium/long) et produit
    une liste d'intervalles avec l'échelle à l'origine de la détection.
    """
    all_intervals = []
    for name, cfg in LISSAGES.items():
        s = df[f"speed_{name}"]
        # seuil mixte : relatif au max + relatif à la moyenne
        threshold_rel = cfg["seuil_rel"] * np.nanmax(s)
        threshold_mean = 1.15 * np.nanmean(s)  # ~ ton trait rouge "moyenne*1.15"
        seuil = max(threshold_rel, threshold_mean)

        intervals = _find_efforts(
            time_s=df["time_s"],
            speed=s.values,
            seuil=seuil,
            min_dur_s=cfg["min_dur"],
            max_pause_s=cfg["max_pause"],
        )
        all_intervals += [(st, en, name) for (st, en) in intervals]

    # fusionner intervalles qui se recouvrent fortement (IoU > .5), garder celui le plus long
    merged = _merge_overlaps(all_intervals)
    return merged

def _merge_overlaps(intervals_with_scale, iou_thr=0.5):
    if not intervals_with_scale:
        return []
    # ordonner par début
    ivs = sorted(intervals_with_scale, key=lambda t: (t[0], t[1]))
    kept = []
    for st, en, scale in ivs:
        added = False
        for j, (kst, ken, kscale) in enumerate(kept):
            inter = max(0, min(en, ken) - max(st, kst))
            union = (en - st) + (ken - kst) - inter
            iou = inter / union if union > 0 else 0
            if iou >= iou_thr:
                # garder le plus long
                if (en - st) > (ken - kst):
                    kept[j] = (st, en, scale)
                added = True
                break
        if not added:
            kept.append((st, en, scale))
    return kept

# ==============================
# 3) Affinage + extraction blocs
# ==============================
def refine_intervals(df, intervals_with_scale):
    refined = []
    for st, en, scale in intervals_with_scale:
        col = f"speed_{scale}"
        block = df[(df["time_s"] >= st) & (df["time_s"] <= en)]
        if block.empty:
            continue
        mean_s = block[col].mean()
        # on resserre la fin sur la partie >= 90% de la moyenne du bloc
        tail = block[block[col] >= 0.9 * mean_s]
        if not tail.empty:
            en = float(tail["time_s"].iloc[-1])
        refined.append((float(st), float(en), scale))
    return refined

def extract_blocks(df, intervals_with_scale):
    rows = []
    for st, en, scale in intervals_with_scale:
        block = df[(df["time_s"] >= st) & (df["time_s"] <= en)].copy()
        if block.empty:
            continue
        block["dt"] = block["time_s"].diff().fillna(0)
        distance = ((block[f"speed_{scale}"] / 3.6) * block["dt"]).sum()
        duration = block["time_s"].iloc[-1] - block["time_s"].iloc[0]
        if duration < 8:
            continue
        effort_cardio = (block.get(f"bpm_{scale}", block["bpm"])).iloc[-1] - \
                        (block.get(f"bpm_{scale}", block["bpm"])).iloc[0]
        rows.append({
            "scale": scale,
            "start": float(block["time_s"].iloc[0]),
            "end": float(block["time_s"].iloc[-1]),
            "duration_s": float(duration),
            "distance_m": float(distance),
            "mean_speed": float(block[f"speed_{scale}"].mean()),
            "mean_bpm": float(block.get(f"bpm_{scale}", block["bpm"]).mean()) if "bpm" in block else np.nan,
            "effort_cardio": float(effort_cardio),
        })
    return pd.DataFrame(rows)

# ===========================================
# 4) Classement par distance ET par durée
# ===========================================
def format_allure(min_per_km):
    minutes = int(min_per_km)
    seconds = round((min_per_km - minutes) * 60)
    return f"{minutes}:{seconds:02d} min/km"

def summarize_clusters(blocks: pd.DataFrame, round_dist=50, round_dur=5):
    if blocks.empty:
        return pd.DataFrame()
    df = blocks.copy()
    df["distance_round"] = (df["distance_m"] / round_dist).round() * round_dist
    df["duration_round"] = (df["duration_s"] / round_dur).round() * round_dur

    summaries = []
    for (dist, dur), grp in df.groupby(["distance_round", "duration_round"]):
        summaries.append({
            "pattern": f"{len(grp)} × {int(dur)} s  (~{int(dist)} m)",
            "allure": format_allure(60 / grp["mean_speed"].mean()),
            "durée moyenne": f"{round(grp['duration_s'].mean())} s",
            "distance moyenne": f"{int(grp['distance_m'].mean())} m",
            "bpm moyen": round(grp["mean_bpm"].mean(), 1) if "mean_bpm" in grp else "N/A",
            "effort_cardio moyen": round(grp["effort_cardio"].mean(), 1),
            "échelle": ", ".join(sorted(grp["scale"].unique())),
        })
    return pd.DataFrame(summaries).sort_values("pattern").reset_index(drop=True)

# =================================================
# 5) Analyse des récupérations entre blocs similaires
# =================================================
def analyze_recups(df, blocks, key="duration_round", tol_map=DURATION_GROUPING):
    if blocks.empty:
        return pd.DataFrame()
    recups = []
    tmp = blocks.copy()
    # clé de regroupement par échelle de durée (tolérance différente selon scale)
    tmp["grp_key"] = tmp.apply(lambda r: _round_with_scale(r["duration_s"], r["scale"], tol_map), axis=1)
    tmp = tmp.sort_values("start").reset_index(drop=True)

    for i in range(len(tmp) - 1):
        cur, nxt = tmp.iloc[i], tmp.iloc[i + 1]
        if cur["grp_key"] == nxt["grp_key"]:
            seg = df[(df["time_s"] >= cur["end"]) & (df["time_s"] <= nxt["start"])]
            if seg.empty:
                continue
            dur = seg["time_s"].iloc[-1] - seg["time_s"].iloc[0]
            spd = seg[f"speed_{cur['scale']}"].mean()
            bpm = seg.get(f"bpm_{cur['scale']}", seg["bpm"]).mean()
            recups.append({
                "entre": f"{int(round(cur['duration_s']))}s",
                "durée": f"{int(round(dur))} s",
                "allure": format_allure(60 / spd) if spd > 0 else "N/A",
                "bpm moyen": round(bpm, 1) if pd.notna(bpm) else "N/A",
            })
    return pd.DataFrame(recups)

def _round_with_scale(value, scale, tol_map):
    step = tol_map.get(scale, 10)
    return int(round(value / step) * step)

# =========
# 6) Main
# =========
def main():
    # 👉 adapte le chemin si besoin
    df = load_stream("data/streams/15940410865.csv")

    raw_intervals = detect_intervals_multiscale(df)
    refined = refine_intervals(df, raw_intervals)
    blocks = extract_blocks(df, refined)

    if blocks.empty:
        print("Aucun effort détecté.")
        return

    # résumés par distance+durée
    print("\n=== RÉSUMÉ DES BLOCS (groupés par durée & distance) ===")
    # tolérance d'arrondi durée selon l’échelle
    summary = summarize_clusters(blocks,
                                 round_dist=50,
                                 round_dur=10)  # affichage neutre
    print(summary)

    # récupérations entre blocs répétitifs (par durée)
    recups = analyze_recups(df, blocks)
    if not recups.empty:
        print("\nRécupérations associées :")
        print(recups)

    # heuristique « reconnaissance de pattern » (ex 4×4 min)
    # on cherche un groupe "long" avec >=3 répétitions ~240 s
    longs = blocks[blocks["scale"] == "long"].copy()
    if not longs.empty:
        longs["dur_round"] = longs["duration_s"].apply(lambda x: int(round(x / 15) * 15))
        best = longs["dur_round"].value_counts().idxtop if hasattr(longs["dur_round"], "idxtop") else longs["dur_round"].mode()[0]
        nrep = (longs["dur_round"] == best).sum()
        if nrep >= 3 and 210 <= best <= 270:
            print(f"\n✅ Pattern détecté : {nrep} × ~{best}s (≈ 4′) — probable 4×4′")

if __name__ == "__main__":
    main()
