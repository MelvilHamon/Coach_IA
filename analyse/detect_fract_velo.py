"""
detect_fract_velo.py
--------------------
Détection de fractionné vélo, en deux modes :

  - Mode "power"  : signal principal = puissance (capteur watts présent).
                    Insensible au terrain/vent/descentes, validation stricte.
  - Mode "speed"  : fallback sans capteur, signal = vitesse, validation
                    appuyée sur la FC (∆ effort/récup) + garde-fou descentes.
                    Tolérant aux faux positifs (cf. exigence produit).

Pas de détection pyramide en vélo (volonté produit).

Architecture identique à detect_fract_v2 : preprocess → seuil GMM →
machine à états → blocs → DBSCAN → validation.
"""

import json
import os

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from sklearn.mixture import GaussianMixture

from detect_fract_v2 import cluster_blocks, extract_recoveries

_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_ROOT, "config.json")


def _load_velo_det_cfg() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("detection_fractionne_velo", {})
    except Exception:
        return {}


# ──────────────────────────────────────────────
# 1. PREPROCESSING
# ──────────────────────────────────────────────

def preprocess_velo(df: pd.DataFrame,
                    sigma_power: float = 2.0,
                    sigma_speed: float = 4.0,
                    sigma_alt:   float = 10.0) -> pd.DataFrame:
    """
    Lisse les signaux disponibles.

    - Puissance lissée plus court (σ=2 ≈ 5s) : la puissance répond très vite
      aux changements d'effort, lisser trop gomme les transitions.
    - Vitesse lissée un peu plus que la course (σ=4 ≈ 9s) : inertie du vélo
      + bruit GPS plus marqué à haute vitesse.
    - Altitude fortement lissée (σ=10) pour stabiliser le signe du dénivelé.
    """
    df = df.copy().sort_values("time_s").reset_index(drop=True)
    df["speed_smooth"] = gaussian_filter1d(df["speed_kmh"].ffill().values, sigma=sigma_speed)
    df["bpm_smooth"]   = gaussian_filter1d(df["bpm"].ffill().values,       sigma=sigma_speed)

    if "altitude_m" in df.columns and df["altitude_m"].notna().sum() > 10:
        df["altitude_smooth"] = gaussian_filter1d(
            df["altitude_m"].ffill().bfill().values, sigma=sigma_alt
        )

    if "power_w" in df.columns and df["power_w"].notna().sum() > 30:
        df["power_smooth"] = gaussian_filter1d(
            df["power_w"].fillna(0).clip(lower=0).values, sigma=sigma_power
        )
    return df


def has_power(df: pd.DataFrame) -> bool:
    return "power_smooth" in df.columns


# ──────────────────────────────────────────────
# 2. SEUIL ADAPTATIF GMM (puissance ou vitesse)
# ──────────────────────────────────────────────

def find_threshold_gmm(values: np.ndarray,
                       low_floor_q: float = 0.10,
                       mix: tuple[float, float] = (0.55, 0.45)) -> float:
    """
    GMM bimodal sur le signal d'effort. Identique à detect_fract_v2 mais
    paramétrable. low_floor_q écarte le bas de la distribution (arrêts feux,
    coast à 0 W) qui pollueraient la composante "lente".
    """
    if len(values) == 0:
        return 0.0
    floor = float(np.quantile(values, low_floor_q))
    valid = values[values > floor]
    if len(valid) < 60:
        return float(np.quantile(values, 0.80))

    try:
        gmm = GaussianMixture(n_components=2, random_state=0, max_iter=200)
        gmm.fit(valid.reshape(-1, 1))
        means = np.sort(gmm.means_.flatten())
        return float(means[0] * mix[0] + means[-1] * mix[1])
    except Exception:
        return float(np.quantile(valid, 0.70))


# ──────────────────────────────────────────────
# 3. MACHINE À ÉTATS (signal-agnostique)
# ──────────────────────────────────────────────

def segment_signal(df: pd.DataFrame,
                   signal_col: str,
                   threshold: float,
                   min_effort_s: float   = 20.0,
                   min_recovery_s: float = 10.0,
                   hold_on_s: float      = 3.0,
                   hold_off_s: float     = 8.0) -> list[dict]:
    """
    State machine identique à detect_fract_v2.segment_signal mais
    paramétrée sur le nom de colonne. Hold plus long (3s/8s vs 2s/6s)
    car en vélo les transitions effort/récup sont plus progressives.
    """
    t  = df["time_s"].values
    v  = df[signal_col].values
    dt = np.diff(t, prepend=t[0])
    dt = np.clip(dt, 0, 5)

    state     = "IDLE"
    seg_start = t[0]
    above_acc = 0.0
    below_acc = 0.0
    segments  = []

    for i in range(len(t)):
        above = v[i] >= threshold

        if state == "IDLE":
            if above:
                above_acc += dt[i]
                if above_acc >= hold_on_s:
                    seg_start = t[i] - above_acc
                    state     = "EFFORT"
                    below_acc = 0.0
            else:
                above_acc = 0.0

        elif state == "EFFORT":
            if not above:
                below_acc += dt[i]
                if below_acc >= hold_off_s:
                    end_t = t[i] - below_acc
                    if end_t - seg_start >= min_effort_s:
                        segments.append({"type": "effort", "start": seg_start, "end": end_t})
                    state     = "RECOVERY"
                    seg_start = end_t
                    above_acc = 0.0
            else:
                below_acc = 0.0

        elif state == "RECOVERY":
            if above:
                above_acc += dt[i]
                if above_acc >= hold_on_s:
                    recup_end = t[i] - above_acc
                    if recup_end - seg_start >= min_recovery_s:
                        segments.append({"type": "recovery", "start": seg_start, "end": recup_end})
                    seg_start = t[i] - above_acc
                    state     = "EFFORT"
                    below_acc = 0.0
            else:
                above_acc = 0.0

    if state == "EFFORT" and t[-1] - seg_start >= min_effort_s:
        segments.append({"type": "effort", "start": seg_start, "end": t[-1]})

    return segments


# ──────────────────────────────────────────────
# 4. MÉTRIQUES PAR BLOC
# ──────────────────────────────────────────────

def extract_block_metrics(df: pd.DataFrame,
                          segments: list[dict],
                          signal_col: str) -> pd.DataFrame:
    """
    Métriques par bloc effort. signal_col = 'power_smooth' ou 'speed_smooth'
    selon le mode. alt_delta_m = variation d'altitude lissée sur le bloc,
    utilisée par le garde-fou descentes en mode fallback.
    """
    rows = []
    for seg in (s for s in segments if s["type"] == "effort"):
        block = df[(df["time_s"] >= seg["start"]) & (df["time_s"] <= seg["end"])].copy()
        if block.empty:
            continue

        block["dt"] = block["time_s"].diff().fillna(0).clip(lower=0, upper=5)
        distance_m = ((block["speed_smooth"] / 3.6) * block["dt"]).sum()
        duration_s = block["time_s"].iloc[-1] - block["time_s"].iloc[0]

        if duration_s < 15 or distance_m < 50:
            continue

        t_s   = block["time_s"].iloc[0]
        t_e   = block["time_s"].iloc[-1]
        t_dur = t_e - t_s
        core  = block[
            (block["time_s"] >= t_s + 0.15 * t_dur) &
            (block["time_s"] <= t_e - 0.15 * t_dur)
        ]

        sig          = block[signal_col]
        sig_mean     = float(sig.mean())
        sig_cv       = float(sig.std() / (sig_mean + 1e-6))
        sig_cv_core  = (
            float(core[signal_col].std() / (core[signal_col].mean() + 1e-6))
            if len(core) >= 3 else sig_cv
        )

        alt_delta = 0.0
        if "altitude_smooth" in block.columns and len(block) >= 2:
            alt_delta = float(block["altitude_smooth"].iloc[-1] - block["altitude_smooth"].iloc[0])

        rows.append({
            "start":          seg["start"],
            "end":            seg["end"],
            "duration_s":     round(duration_s, 1),
            "distance_m":     round(distance_m, 1),
            "mean_speed":     round(block["speed_smooth"].mean(), 2),
            "mean_bpm":       round(block["bpm_smooth"].mean(), 1),
            "mean_signal":    round(sig_mean, 1),
            "signal_cv":      round(sig_cv, 3),
            "signal_cv_core": round(sig_cv_core, 3),
            "alt_delta_m":    round(alt_delta, 1),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ──────────────────────────────────────────────
# 5. RÉSUMÉ
# ──────────────────────────────────────────────

def summarize_velo(blocks: pd.DataFrame,
                   recoveries: pd.DataFrame,
                   mode: str) -> list[dict]:
    """
    Résumé adapté au vélo : on décrit en durée plutôt qu'en distance,
    car les fractionnés vélo sont typiquement définis en temps
    (4×4', 30/30, 8×30"…). On affiche aussi la puissance moyenne en mode power.
    """
    if blocks.empty:
        return []

    patterns = []
    valid = blocks[blocks["cluster"] != -1]

    for cluster_id, grp in valid.groupby("cluster"):
        grp      = grp.sort_values("start")
        n        = len(grp)
        dur_med  = float(grp["duration_s"].median())
        dist_med = int(round(grp["distance_m"].median(), -1))
        spd_med  = float(grp["mean_speed"].median())
        bpm_med  = round(float(grp["mean_bpm"].median()), 1)
        sig_med  = round(float(grp["mean_signal"].median()), 1)

        recup_str = ""
        if not recoveries.empty:
            r = recoveries[recoveries["cluster"] == cluster_id]
            if not r.empty:
                recup_med = round(float(r["recup_dur_s"].median()))
                recup_str = f", récup ~{recup_med}s"

        if mode == "power":
            head = f"{n} × {int(round(dur_med))}s @ {sig_med:.0f}W"
        else:
            head = f"{n} × {int(round(dur_med))}s @ {spd_med:.1f} km/h"

        patterns.append({
            "cluster":      int(cluster_id),
            "description":  head + recup_str,
            "reps":         n,
            "duration_s":   round(dur_med, 1),
            "distance_m":   dist_med,
            "mean_speed":   round(spd_med, 2),
            "mean_bpm":     bpm_med,
            "mean_signal":  sig_med,
        })

    patterns.sort(key=lambda x: x["duration_s"])
    return patterns


# ──────────────────────────────────────────────
# 6. VALIDATIONS
# ──────────────────────────────────────────────

def _mean_signal_in_segs(df: pd.DataFrame, segs: list[dict], col: str) -> float:
    vals = []
    for s in segs:
        b = df[(df["time_s"] >= s["start"]) & (df["time_s"] <= s["end"])]
        if not b.empty:
            vals.append(float(b[col].mean()))
    return float(np.mean(vals)) if vals else 0.0


def _validate_power_mode(df, segments, blocks, patterns,
                         min_cv: float          = 0.20,
                         min_ef_ratio: float    = 1.50,
                         max_block_cv: float    = 0.20,
                         min_ef_vs_mean: float  = 1.10) -> bool:
    """
    Validation stricte (capteur de puissance fiable).

    1. CV global puissance ≥ 0.20 (la puissance est plus volatile que la
       vitesse run, mais un fractionné a un CV nettement supérieur à une
       sortie continue qui tourne autour de 0.10-0.15).
    2. Ratio P_effort / P_recup ≥ 1.50 (un vrai bloc d'effort tape ≥ 1.5×
       la puissance de récup ; une oscillation de terrain reste sous 1.3).
    3. CV intra-bloc puissance ≤ 0.20 sur noyau central 70%.
    4. P_effort ≥ moyenne session × 1.10 (évite les "blocs rapides" qui
       seraient en fait des coups de pédale dans la moyenne).
    """
    if not any(p["reps"] >= 3 for p in patterns):
        return False

    sig = df["power_smooth"]
    cv = float(sig.std() / (sig.mean() + 1e-6))
    if cv < min_cv:
        return False

    eff = [s for s in segments if s["type"] == "effort"]
    rec = [s for s in segments if s["type"] == "recovery"]
    if not eff or not rec:
        return False

    pw_eff = _mean_signal_in_segs(df, eff, "power_smooth")
    pw_rec = _mean_signal_in_segs(df, rec, "power_smooth")
    if pw_rec <= 1 or pw_eff / pw_rec < min_ef_ratio:
        return False

    if not blocks.empty and "cluster" in blocks.columns:
        valid_blks = blocks[blocks["cluster"] != -1]
        if not valid_blks.empty:
            best = valid_blks.groupby("cluster").size().idxmax()
            cv_core = float(
                valid_blks[valid_blks["cluster"] == best]["signal_cv_core"].median()
            )
            if cv_core > max_block_cv:
                return False

    sess_mean = float(sig.mean())
    if sess_mean > 0 and pw_eff < sess_mean * min_ef_vs_mean:
        return False

    return True


def _validate_speed_mode(df, segments, blocks, patterns,
                         min_cv: float            = 0.18,
                         min_ef_ratio: float      = 1.30,
                         min_hr_delta: float      = 8.0,
                         max_descent_share: float = 0.40) -> bool:
    """
    Validation fallback (vitesse + FC). Modérément tolérante.

    1. CV global vitesse ≥ 0.18 (un peu plus haut qu'en course car vélo
       continu en plat tourne facilement à CV ~0.10).
    2. Ratio vitesse_effort / vitesse_recup ≥ 1.30 — un vrai intervalle
       a un écart net même avec l'inertie du vélo. Sous 1.30, c'est
       typiquement de la variation de terrain ou des feux rouges.
    3. ∆ FC effort vs récup ≥ 8 bpm. Signal FC robuste contre les
       descentes (FC ne monte pas en descente même si vitesse haute).
       Lag FC ~15-25s : 8 bpm exclut les sorties libres dont la FC
       oscille naturellement de quelques battements.
    4. Garde-fou descentes : ≤ 40% des blocs effort en perte d'altitude
       nette (alt_delta < -3m). Au-delà, la séance est probablement
       une descente répétée plutôt qu'un fractionné.
    """
    if not any(p["reps"] >= 3 for p in patterns):
        return False

    sig = df["speed_smooth"]
    cv = float(sig.std() / (sig.mean() + 1e-6))
    if cv < min_cv:
        return False

    eff = [s for s in segments if s["type"] == "effort"]
    rec = [s for s in segments if s["type"] == "recovery"]
    if not eff or not rec:
        return False

    spd_eff = _mean_signal_in_segs(df, eff, "speed_smooth")
    spd_rec = _mean_signal_in_segs(df, rec, "speed_smooth")
    if spd_rec <= 0 or spd_eff / spd_rec < min_ef_ratio:
        return False

    bpm_eff = _mean_signal_in_segs(df, eff, "bpm_smooth")
    bpm_rec = _mean_signal_in_segs(df, rec, "bpm_smooth")
    if (bpm_eff - bpm_rec) < min_hr_delta:
        return False

    if not blocks.empty and "alt_delta_m" in blocks.columns and len(blocks) > 0:
        descent = (blocks["alt_delta_m"] < -3.0).sum()
        if descent / len(blocks) > max_descent_share:
            return False

    return True


# ──────────────────────────────────────────────
# 7. PIPELINE
# ──────────────────────────────────────────────

def analyze_fractionne_velo(activity_path: str,
                            verbose: bool = False,
                            config: dict | None = None) -> dict:
    """
    Pipeline complète vélo. Détecte automatiquement le mode (power/speed)
    selon la disponibilité de la colonne `power_w` dans le stream.

    Retourne :
        mode            : 'power' | 'speed'
        is_fractionne   : bool
        session_type    : 'intervalles vélo' | 'indéterminé'
        threshold       : seuil GMM (W ou km/h)
        patterns        : list[dict] descriptions lisibles
        blocks          : DataFrame des blocs avec cluster
        recoveries      : DataFrame des récups par cluster
        cv_signal       : CV global du signal (diagnostic)
    """
    cfg = config if config is not None else _load_velo_det_cfg()

    df = pd.read_csv(activity_path)
    df = preprocess_velo(df)

    mode       = "power" if has_power(df) else "speed"
    signal_col = "power_smooth" if mode == "power" else "speed_smooth"

    min_eff_s = cfg.get(f"min_effort_s_{mode}",   20.0 if mode == "power" else 30.0)
    min_rec_s = cfg.get(f"min_recovery_s_{mode}", 10.0 if mode == "power" else 15.0)
    eps       = cfg.get("dbscan_eps", 0.40)

    threshold = find_threshold_gmm(df[signal_col].values)
    segments  = segment_signal(df, signal_col, threshold,
                               min_effort_s=min_eff_s, min_recovery_s=min_rec_s)
    blocks    = extract_block_metrics(df, segments, signal_col)

    cv_signal = float(df[signal_col].std() / (df[signal_col].mean() + 1e-6))

    base = {
        "mode":          mode,
        "is_fractionne": False,
        "session_type":  "indéterminé",
        "threshold":     round(threshold, 2),
        "patterns":      [],
        "blocks":        blocks if not blocks.empty else pd.DataFrame(),
        "recoveries":    pd.DataFrame(),
        "cv_signal":     round(cv_signal, 3),
    }

    if blocks.empty:
        if verbose:
            print(f"[velo/{mode}] aucun bloc d'effort détecté")
        return base

    blocks_clustered = cluster_blocks(blocks, eps=eps)
    recoveries       = extract_recoveries(df, blocks_clustered)
    patterns         = summarize_velo(blocks_clustered, recoveries, mode)

    if mode == "power":
        is_frac = _validate_power_mode(
            df, segments, blocks_clustered, patterns,
            min_cv         = cfg.get("power_min_cv",         0.20),
            min_ef_ratio   = cfg.get("power_min_ef_ratio",   1.50),
            max_block_cv   = cfg.get("power_max_block_cv",   0.20),
            min_ef_vs_mean = cfg.get("power_min_ef_vs_mean", 1.10),
        )
    else:
        is_frac = _validate_speed_mode(
            df, segments, blocks_clustered, patterns,
            min_cv            = cfg.get("speed_min_cv",            0.18),
            min_ef_ratio      = cfg.get("speed_min_ef_ratio",      1.30),
            min_hr_delta      = cfg.get("speed_min_hr_delta",      8.0),
            max_descent_share = cfg.get("speed_max_descent_share", 0.40),
        )

    if verbose:
        print(f"\n[velo/{mode}] seuil={threshold:.2f}  CV={cv_signal:.3f}  "
              f"fractionné={is_frac}")
        for p in patterns:
            if p["reps"] >= 3:
                print(f"  {p['description']}  (BPM {p['mean_bpm']:.0f})")

    return {
        **base,
        "blocks":        blocks_clustered,
        "recoveries":    recoveries,
        "patterns":      patterns,
        "is_fractionne": is_frac,
        "session_type":  "intervalles vélo" if is_frac else "indéterminé",
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    analyze_fractionne_velo(path, verbose=True)
