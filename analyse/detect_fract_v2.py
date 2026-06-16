"""
detect_fract_v2.py
------------------
Pipeline robuste de détection de séances de fractionné.

Architecture :
  raw signal
    → preprocess   (lissage gaussien, accélération, variance locale)
    → seuil adaptatif par GMM (bimodal lent / rapide)
    → machine à états (hystérésis temporelle en secondes réelles)
    → extraction métriques par bloc (incl. speed_cv_core sur noyau central 70%)
    → clustering DBSCAN sur [log(distance), log(durée)]
    → détection récupérations
    → validation fractionné structuré (5 critères cumulatifs)
    → détection pyramide si validation échoue
    → résumé "10 × 300m @ 3:40 min/km, récup ~90s"
"""

import json
import os
import sys

import numpy as np
import pandas as pd

# storage : abstraction R2/local pour la lecture des streams. En prod les
# streams vivent dans R2 (cf. api/storage.py).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
try:
    from api import storage as _storage
except Exception:
    _storage = None


def _read_stream_csv(path: str) -> pd.DataFrame:
    """Lecture d'un stream CSV : R2 si disponible, sinon filesystem local."""
    if _storage is not None:
        df = _storage.read_csv(path)
        if df is not None:
            return df
    return pd.read_csv(path)
from scipy.ndimage import gaussian_filter1d
from scipy.stats import spearmanr
from sklearn.mixture import GaussianMixture
from sklearn.cluster import DBSCAN
from typing import Optional


_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_ROOT, "config.json")


def _load_det_config() -> dict:
    """Charge la section detection_fractionne de config.json (défauts si absent)."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("detection_fractionne", {})
    except Exception:
        return {}


# ──────────────────────────────────────────────
# 1. PREPROCESSING
# ──────────────────────────────────────────────

def preprocess(df: pd.DataFrame, sigma: float = 3.0) -> pd.DataFrame:
    """
    Lissage + features dynamiques.

    sigma=3 ≈ fenêtre de ~7s, bon compromis bruit/latence.
    L'accélération permet de détecter les transitions effort/récup,
    la variance locale est un proxy de régularité de l'effort.
    """
    df = df.copy().sort_values("time_s").reset_index(drop=True)
    df["speed_smooth"] = gaussian_filter1d(df["speed_kmh"].ffill().values, sigma=sigma)
    df["bpm_smooth"]   = gaussian_filter1d(df["bpm"].ffill().values,       sigma=sigma)

    dt = df["time_s"].diff().fillna(1).clip(lower=0.5).values
    df["accel"]      = np.gradient(df["speed_smooth"].values, dt)
    df["speed_var15"] = (
        df["speed_smooth"]
        .rolling(15, center=True, min_periods=5)
        .var()
        .fillna(0)
    )
    return df


# ──────────────────────────────────────────────
# 2. SEUIL ADAPTATIF PAR GMM
# ──────────────────────────────────────────────

def find_effort_threshold_gmm(speed: np.ndarray, walk_floor_kmh: float = 6.0) -> float:
    """
    Ajuste un GMM à 2 composantes sur la distribution des vitesses.
    Le seuil est placé à 60 % entre les deux modes (légèrement côté rapide).

    Pourquoi GMM plutôt que 0.75 * max ?
    - max est très sensible aux spikes GPS.
    - La distribution bimodale lent/rapide est une hypothèse solide
      pour toute séance structurée.
    - S'adapte automatiquement au niveau de l'athlète et au type de séance.

    Pourquoi exclure la marche/arrêt (< walk_floor_kmh) AVANT le GMM ?
    - Sur une séance avec échauffement/retour au calme (ex : 3×1km noyés dans
      16 km de footing), inclure la marche fait que le GMM sépare
      « marche/arrêt vs course » au lieu de « footing vs effort » : le seuil
      tombe ~8 km/h et tout le bloc roulant passe au-dessus → un seul gros bloc,
      les intervalles sont perdus. En ne gardant que les échantillons en course
      (>= 6 km/h), les deux modes deviennent footing vs allure rapide et le seuil
      se place correctement entre les deux.

    Fallback : si le GMM ne converge pas ou que les données sont trop courtes,
    on retourne le quantile 0.80 (raisonnable dans tous les cas).
    """
    # On ne garde que les échantillons « en course » pour que la bimodalité
    # capture footing vs effort. Repli sur > 1.0 (arrêt seul) si trop peu de
    # points en course (profil très lent, tapis, séance courte) pour garder le
    # GMM stable.
    speed_run = speed[speed >= walk_floor_kmh]
    speed_valid = speed_run if len(speed_run) >= 60 else speed[speed > 1.0]
    if len(speed_valid) < 60:
        return float(np.quantile(speed, 0.80))

    try:
        gmm = GaussianMixture(n_components=2, random_state=0, max_iter=200)
        gmm.fit(speed_valid.reshape(-1, 1))
        means = np.sort(gmm.means_.flatten())
        # 55 % côté lent, 45 % côté rapide → seuil plus bas = blocs plus longs.
        # Un seuil trop proche du mode rapide rogne les décélérations naturelles
        # en fin d'intervalle (derniers 10-15m). 0.55/0.45 est empiriquement meilleur.
        threshold = means[0] * 0.55 + means[-1] * 0.45
    except Exception:
        threshold = float(np.quantile(speed_valid, 0.70))

    return float(threshold)


# ──────────────────────────────────────────────
# 3. MACHINE À ÉTATS ROBUSTE (hystérésis temporelle)
# ──────────────────────────────────────────────

def segment_signal(
    df: pd.DataFrame,
    threshold: float,
    min_effort_s: float   = 15.0,
    min_recovery_s: float = 5.0,
    hold_on_s: float  = 2.0,
    hold_off_s: float = 6.0,
) -> list[dict]:
    """
    Machine à états : IDLE → EFFORT ↔ RECOVERY.

    Différences clés vs l'approche précédente :
    - hold_on / hold_off accumulent du TEMPS RÉEL (dt), pas des itérations.
      → robuste aux drops GPS et aux pauses Strava.
    - Quand on entre en EFFORT, on remonte le start au début du plateau
      (t[i] - above_acc) pour ne pas rater le début de l'intervalle.
    - min_effort_s / min_recovery_s filtrent les glitches courts.

    Retourne une liste de dicts {type, start, end} triée chronologiquement.
    """
    t  = df["time_s"].values
    v  = df["speed_smooth"].values
    dt = np.diff(t, prepend=t[0])
    dt = np.clip(dt, 0, 5)  # ignorer les pauses GPS > 5s

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

    # Fermer un effort encore ouvert à la fin du signal
    if state == "EFFORT" and t[-1] - seg_start >= min_effort_s:
        segments.append({"type": "effort", "start": seg_start, "end": t[-1]})

    return segments


# ──────────────────────────────────────────────
# 4. EXTRACTION DES MÉTRIQUES PAR BLOC
# ──────────────────────────────────────────────

def extract_block_metrics(df: pd.DataFrame, segments: list[dict]) -> pd.DataFrame:
    """
    Pour chaque segment d'effort : distance, durée, allure, stats BPM.

    - Distance intégrée sur speed_smooth (stable vs speed_kmh brut).
    - pace_sec_km en secondes/km → comparaison numérique directe, pas de string.
    - speed_cv : coefficient de variation de vitesse sur le bloc entier.
    - speed_cv_core : CV calculé uniquement sur le noyau central 70% du bloc
      (15% temporels ignorés au début et à la fin). Moins sensible aux
      accélérations/décélérations de transition, meilleur proxy de la
      régularité en milieu d'intervalle.
    """
    rows = []
    for seg in (s for s in segments if s["type"] == "effort"):
        block = df[(df["time_s"] >= seg["start"]) & (df["time_s"] <= seg["end"])].copy()
        if block.empty:
            continue

        block["dt"] = block["time_s"].diff().fillna(0).clip(lower=0, upper=5)
        distance_m = ((block["speed_smooth"] / 3.6) * block["dt"]).sum()
        duration_s = block["time_s"].iloc[-1] - block["time_s"].iloc[0]

        if duration_s < 10 or distance_m < 20:
            continue

        pace_sec_km = (duration_s / distance_m) * 1000
        speed_cv    = float(block["speed_smooth"].std() / (block["speed_smooth"].mean() + 1e-6))

        # Noyau central 70 % par temps (ignorer 15 % début + 15 % fin)
        t_s     = block["time_s"].iloc[0]
        t_e     = block["time_s"].iloc[-1]
        t_dur   = t_e - t_s
        core    = block[
            (block["time_s"] >= t_s + 0.15 * t_dur) &
            (block["time_s"] <= t_e - 0.15 * t_dur)
        ]
        if len(core) >= 3:
            speed_cv_core = float(core["speed_smooth"].std() / (core["speed_smooth"].mean() + 1e-6))
        else:
            speed_cv_core = speed_cv  # fallback si bloc trop court

        rows.append({
            "start":         seg["start"],
            "end":           seg["end"],
            "duration_s":    round(duration_s, 1),
            "distance_m":    round(distance_m, 1),
            "pace_sec_km":   round(pace_sec_km, 1),
            "mean_speed":    round(block["speed_smooth"].mean(), 2),
            "max_speed":     round(block["speed_smooth"].max(), 2),
            "mean_bpm":      round(block["bpm_smooth"].mean(), 1),
            "bpm_delta":     round(block["bpm_smooth"].iloc[-1] - block["bpm_smooth"].iloc[0], 1),
            "speed_cv":      round(speed_cv, 3),
            "speed_cv_core": round(speed_cv_core, 3),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ──────────────────────────────────────────────
# 5. CLUSTERING DBSCAN sur log(distance) × log(durée)
# ──────────────────────────────────────────────

def cluster_blocks(
    blocks: pd.DataFrame,
    eps: float = 0.35,
    min_samples: int = 2,
) -> pd.DataFrame:
    """
    Clustering DBSCAN sur [log(distance_m), log(duration_s)] SANS StandardScaler.

    Pourquoi supprimer StandardScaler ?
    - StandardScaler normalise par la variance interne du dataset.
    - Avec N blocs proches (ex: 190-245m), std_log ~ 0.09 → eps=0.30 devient
      équivalent à ±3% de variation réelle → trop strict, tout passe en noise.
    - Sans normalisation, eps est un log-ratio direct :
        eps=0.35 ↔ e^0.35 ≈ 1.42 → blocs acceptés si distance varie ≤ ±42%.
    - Séparation 300m vs 1000m = log(1000/300) ≈ 1.20 >> 0.35 → toujours séparés.
    - Stable quel que soit le nombre de blocs et leur dispersion absolue.
    """
    blocks = blocks.copy()

    if len(blocks) < 2:
        blocks["cluster"] = 0 if len(blocks) == 1 else -1
        return blocks

    features = np.column_stack([
        np.log1p(blocks["distance_m"].values),
        np.log1p(blocks["duration_s"].values),
    ])
    # Pas de StandardScaler : eps a une sémantique stable de log-ratio
    blocks["cluster"] = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(features)

    return blocks


# ──────────────────────────────────────────────
# 5.4 RÉATTACHEMENT DES BLOCS "NOISE" PROCHES D'UN CLUSTER
# ──────────────────────────────────────────────

def _reattach_noise_blocks(
    blocks: pd.DataFrame,
    pace_tol: float = 0.05,
    max_dist_ratio: float = 2.0,
) -> pd.DataFrame:
    """
    Rattache à un cluster valide les blocs marqués noise (cluster=-1) dont
    l'allure correspond à ce cluster (±pace_tol) et dont la distance est
    dans un ratio raisonnable (≤ max_dist_ratio) de la médiane du cluster.

    Cas typique : un tempo 2km + 2.7km + 2km où le bloc dégradé (2.7km à
    cause de la chaleur) tombe juste au-delà d'eps DBSCAN et finit en
    cluster=-1 alors que son allure est identique aux 2km.
    """
    if blocks.empty or "cluster" not in blocks.columns:
        return blocks

    noise_idxs = blocks.index[blocks["cluster"] == -1].tolist()
    if not noise_idxs:
        return blocks

    valid_clusters = [c for c in blocks["cluster"].unique() if c != -1]
    if not valid_clusters:
        return blocks

    blocks = blocks.copy()
    for cid in valid_clusters:
        grp = blocks[blocks["cluster"] == cid]
        pace_med = float(grp["pace_sec_km"].median())
        dist_med = float(grp["distance_m"].median())
        for idx in list(noise_idxs):
            if blocks.at[idx, "cluster"] != -1:
                continue
            pace = float(blocks.at[idx, "pace_sec_km"])
            dist = float(blocks.at[idx, "distance_m"])
            if pace_med <= 0 or dist_med <= 0:
                continue
            pace_ratio = pace / pace_med
            dist_ratio = max(dist, dist_med) / min(dist, dist_med)
            if abs(pace_ratio - 1.0) <= pace_tol and dist_ratio <= max_dist_ratio:
                blocks.at[idx, "cluster"] = cid

    return blocks


# ──────────────────────────────────────────────
# 5.45 FILTRAGE DES CLUSTERS SPURIOUS (échauffement / récup)
# ──────────────────────────────────────────────

def _filter_spurious_clusters(
    blocks: pd.DataFrame,
    min_real_distance_m: float = 200.0,
    pace_gap_ratio: float = 1.15,
    heavyweight_total_m: float = 1500.0,
) -> pd.DataFrame:
    """
    Élimine les clusters dont la distance médiane est très faible (< min_real_distance_m)
    ET dont l'allure est significativement plus lente (pace_sec_km × pace_gap_ratio)
    qu'un cluster « lourd » (total ≥ heavyweight_total_m).

    Cas typique : un tempo 3×2000m où l'échauffement et la récup ont brièvement
    franchi le seuil GMM, créant un faux cluster « 2 × 60m @ 4:39 » à côté du
    vrai « 2×2000m @ 3:44 ».
    """
    if blocks.empty or "cluster" not in blocks.columns:
        return blocks

    valid_clusters = [c for c in blocks["cluster"].unique() if c != -1]
    if len(valid_clusters) < 2:
        return blocks

    # Clusters lourds = candidats à être l'effort réel de la séance
    heavy_paces = []
    for cid in valid_clusters:
        grp = blocks[blocks["cluster"] == cid]
        if grp["distance_m"].sum() >= heavyweight_total_m:
            heavy_paces.append(float(grp["pace_sec_km"].median()))

    if not heavy_paces:
        return blocks

    fastest_heavy_pace = min(heavy_paces)  # plus petit pace_sec_km = plus rapide

    blocks = blocks.copy()
    for cid in valid_clusters:
        grp = blocks[blocks["cluster"] == cid]
        dist_med = float(grp["distance_m"].median())
        pace_med = float(grp["pace_sec_km"].median())
        if dist_med < min_real_distance_m and pace_med > fastest_heavy_pace * pace_gap_ratio:
            blocks.loc[blocks["cluster"] == cid, "cluster"] = -1

    return blocks


# ──────────────────────────────────────────────
# 5.5 TRIM DES "BONUS" APRÈS COUPURE STRUCTURELLE
# ──────────────────────────────────────────────

def _trim_bonus_reps(
    blocks: pd.DataFrame,
    outlier_factor: float = 2.5,
    min_outlier_s: float  = 180.0,
    min_group_reps: int   = 3,
) -> pd.DataFrame:
    """
    Détecte une coupure structurelle dans un cluster (récup ≥ outlier_factor ×
    médiane des récups du cluster ET ≥ min_outlier_s en absolu) suivie d'un
    petit groupe (< min_group_reps blocs). Ces blocs « bonus » sont retirés
    du cluster (cluster=-1) pour ne pas polluer la validation/résumé.

    Les vrais fractionnés mixtes (ex: 5×400 puis 5×1000 séparés par une
    transition longue) ne sont pas affectés : les deux sous-groupes ont
    chacun ≥ min_group_reps répétitions et restent dans leur cluster.
    """
    if blocks.empty or "cluster" not in blocks.columns:
        return blocks

    blocks = blocks.copy().sort_values("start").reset_index(drop=True)

    for cluster_id in blocks["cluster"].unique():
        if cluster_id == -1:
            continue
        cluster_idxs = blocks.index[blocks["cluster"] == cluster_id].tolist()
        if len(cluster_idxs) < 4:
            continue

        recups = [
            blocks.loc[cluster_idxs[i + 1], "start"]
            - blocks.loc[cluster_idxs[i], "end"]
            for i in range(len(cluster_idxs) - 1)
        ]
        median_recup = float(np.median(recups))
        if median_recup <= 0:
            continue

        # Parcours depuis la fin : on cherche une coupure tardive isolant
        # un petit groupe (typique d'un "bonus" après fin de séance).
        for i in range(len(recups) - 1, -1, -1):
            r = recups[i]
            if r >= outlier_factor * median_recup and r >= min_outlier_s:
                bonus_count = len(cluster_idxs) - (i + 1)
                if 0 < bonus_count < min_group_reps:
                    blocks.loc[cluster_idxs[i + 1:], "cluster"] = -1
                # Qu'on ait coupé ou non, on s'arrête à la première coupure
                # tardive trouvée pour ce cluster.
                break

    return blocks


# ──────────────────────────────────────────────
# 6. DÉTECTION DES RÉCUPÉRATIONS
# ──────────────────────────────────────────────

def extract_recoveries(df: pd.DataFrame, blocks: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule les phases de récupération entre répétitions consécutives
    du même cluster.

    Ne calcule la récup qu'entre deux blocs du MÊME cluster et consécutifs :
    si la séance est 300m/300m/1000m/1000m, les récups 300m et les récups 1000m
    sont calculées séparément.
    """
    if blocks.empty or "cluster" not in blocks.columns:
        return pd.DataFrame()

    blocks = blocks.sort_values("start").reset_index(drop=True)
    recups = []

    for i in range(len(blocks) - 1):
        curr = blocks.iloc[i]
        nxt  = blocks.iloc[i + 1]

        if curr["cluster"] != nxt["cluster"] or curr["cluster"] == -1:
            continue

        recup = df[(df["time_s"] > curr["end"]) & (df["time_s"] < nxt["start"])]
        if recup.empty:
            continue

        duration  = recup["time_s"].iloc[-1] - recup["time_s"].iloc[0]
        mean_spd  = recup["speed_smooth"].mean()
        mean_bpm  = recup["bpm_smooth"].mean()

        recups.append({
            "cluster":     int(curr["cluster"]),
            "recup_dur_s": round(duration),
            "mean_speed":  round(mean_spd, 1),
            "mean_bpm":    round(mean_bpm, 1),
        })

    return pd.DataFrame(recups) if recups else pd.DataFrame()


def _extract_all_recoveries(df: pd.DataFrame, blocks: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule toutes les phases de récupération entre blocs consécutifs,
    indépendamment du cluster. Utilisé pour la validation CV récup.
    """
    if blocks.empty:
        return pd.DataFrame()

    blocks_sorted = blocks.sort_values("start").reset_index(drop=True)
    recups = []

    for i in range(len(blocks_sorted) - 1):
        curr = blocks_sorted.iloc[i]
        nxt  = blocks_sorted.iloc[i + 1]

        recup = df[(df["time_s"] > curr["end"]) & (df["time_s"] < nxt["start"])]
        if recup.empty:
            continue

        duration = recup["time_s"].iloc[-1] - recup["time_s"].iloc[0]
        recups.append({"recup_dur_s": round(duration)})

    return pd.DataFrame(recups) if recups else pd.DataFrame()


# ──────────────────────────────────────────────
# 7. RÉSUMÉ STRUCTURÉ + DÉTECTION DU TYPE DE SÉANCE
# ──────────────────────────────────────────────

def _sec_to_pace(sec_km: float) -> str:
    """Convertit des secondes/km en mm:ss min/km (numérique → string uniquement pour l'affichage)."""
    m = int(sec_km // 60)
    s = int(sec_km % 60)
    return f"{m}:{s:02d} min/km"


def summarize_session(blocks: pd.DataFrame, recoveries: pd.DataFrame) -> list[dict]:
    """
    Pour chaque cluster valide (cluster != -1), génère :
      - description lisible : "10 × 300m @ 3:40 min/km, récup ~90s"
      - métriques numériques pour exploitation downstream

    L'arrondi de distance est à 10m (médiane du cluster) :
    plus précis que le round(/ 50) * 50 précédent sans être sensible au bruit.
    """
    if blocks.empty:
        return []

    patterns = []
    valid = blocks[blocks["cluster"] != -1]

    for cluster_id, grp in valid.groupby("cluster"):
        grp = grp.sort_values("start")
        n        = len(grp)
        dist_med = int(round(grp["distance_m"].median(), -1))   # arrondi à 10m
        # Si les distances varient (CV > 12%), on liste la séquence réelle
        # (ex: 2000m + 2600m + 2000m @ 3:43) au lieu de "3 × 2000m".
        dist_cv  = float(grp["distance_m"].std() / (grp["distance_m"].mean() + 1e-6))
        seq_dists = [int(round(d, -1)) for d in grp["distance_m"].tolist()]
        pace_med = grp["pace_sec_km"].median()
        bpm_med  = round(grp["mean_bpm"].median(), 1)
        cv_med   = round(grp["speed_cv"].median(), 3)
        cv_core_med = round(grp["speed_cv_core"].median(), 3) if "speed_cv_core" in grp.columns else cv_med

        recup_str = ""
        if not recoveries.empty:
            r = recoveries[recoveries["cluster"] == cluster_id]
            if not r.empty:
                recup_med = round(r["recup_dur_s"].median())
                recup_spd = r["mean_speed"].median()  # km/h
                if recup_spd and recup_spd > 1.0:
                    recup_pace_s = 3600.0 / recup_spd
                    rm = int(recup_pace_s // 60)
                    rs = int(recup_pace_s % 60)
                    recup_str = f", récup ~{recup_med}s @ {rm}:{rs:02d} min/km"
                else:
                    recup_str = f", récup ~{recup_med}s"

        if dist_cv > 0.12 and n >= 2:
            seq_str = " + ".join(f"{d}m" for d in seq_dists)
            desc = f"{seq_str} @ {_sec_to_pace(pace_med)}{recup_str}"
        else:
            desc = f"{n} × {dist_med}m @ {_sec_to_pace(pace_med)}{recup_str}"

        patterns.append({
            "cluster":      cluster_id,
            "description":  desc,
            "reps":         n,
            "distance_m":   dist_med,
            "pace_sec_km":  round(pace_med, 1),
            "pace_str":     _sec_to_pace(pace_med),
            "mean_bpm":     bpm_med,
            "speed_cv":     cv_med,
            "speed_cv_core": cv_core_med,
        })

    patterns.sort(key=lambda x: x["distance_m"])
    return patterns


def classify_session_type(patterns: list[dict]) -> str:
    """
    Détermine le type de séance à partir des patterns détectés.

    Règles :
    - court  : distance médiane < 500m
    - moyen  : 500m ≤ distance < 1200m
    - long   : distance ≥ 1200m
    - mixte  : plusieurs clusters avec distances très différentes (ratio > 2.5)
    - tempo  : 1 seul bloc long (>= 2000m), peu de reps
    """
    if not patterns:
        return "indéterminé"

    valid = [p for p in patterns if p["reps"] >= 3]
    if not valid:
        return "indéterminé"

    distances = [p["distance_m"] for p in valid]

    if len(valid) > 1 and max(distances) / (min(distances) + 1) > 2.5:
        return "mixte"

    dist_med = np.median(distances)

    if dist_med < 500:
        return "fractionné court"
    elif dist_med < 1200:
        return "fractionné moyen"
    elif dist_med < 2500:
        return "fractionné long"
    else:
        return "tempo / allure"


# ──────────────────────────────────────────────
# 7.5 VALIDATION FRACTIONNÉ STRUCTURÉ
# ──────────────────────────────────────────────

def _validate_fractionne(
    df: pd.DataFrame,
    segments: list[dict],
    blocks: pd.DataFrame,
    recoveries: pd.DataFrame,
    patterns: list[dict],
    min_cv: float              = 0.17,
    min_ef_ratio: float        = 1.35,
    max_block_cv: float        = 0.12,
    max_recup_cv: float        = 0.45,
    min_ef_vs_mean: float      = 1.03,
    min_effort_speed_kmh: float = 0.0,
    athlete_mean_speed_kmh: float = 0.0,
    min_recup_abs_s: float     = 15.0,
    min_recup_effort_ratio: float = 0.10,
) -> bool:
    """
    Valide qu'une séance est un fractionné STRUCTURÉ, pas une simple variation de terrain.

    Critères cumulatifs :

    1. CV global de vitesse lissée >= min_cv (défaut : 0.17)
       Mesure l'amplitude des oscillations vitesse sur toute la séance.
       Endurance avec terrain : CV ≈ 0.08-0.15 / Fractionné structuré : CV ≥ 0.17.

    2. Ratio vitesse effort / vitesse récupération >= min_ef_ratio (défaut : 1.35)
       Vérifie que les "blocs rapides" sont vraiment rapides par rapport aux récups.
       Variation de terrain : ratio ≈ 1.10-1.30 / Fractionné : ratio ≥ 1.35-2.50.

    3. Speed_cv_core médian intra-bloc <= max_block_cv (défaut : 0.12 Run, 0.20 Trail)
       Pendant un intervalle structuré, l'athlète maintient une allure constante.
       Calculé sur le noyau central 70% du bloc (hors 15% début/fin) pour ignorer
       les transitions. Fractionné réel ≈ 0.04-0.10 / Terrain ≈ 0.12-0.25.

    4. CV des durées de récupération < max_recup_cv (défaut : 0.45)
       Un fractionné structuré a des récupérations régulières.
       Dips GPS ou variations de terrain : récups très irrégulières (CV > 0.45).
       Même un 30"/30" a des récupérations cohérentes entre elles.

    5. Vitesse effort >= moyenne session × min_ef_vs_mean (défaut : 1.03)
       Les blocs "effort" doivent être plus rapides que la moyenne de la séance.
       Si l'effort est aussi lent ou plus lent que la moyenne, c'est que le GMM
       a détecté des segments "rapides" qui ne sont en réalité que des segments
       normaux, et a pris les segments lents (côtes, stops) comme "récup".

    6. Vitesse effort >= min_effort_speed_kmh (défaut : 0.0 = inactif)
       Seuil absolu calibré sur le profil de l'athlète (p75 de ses runs).
       Élimine les runs d'endurance "rapides" pour cet athlète qui passeraient
       les critères structurels mais dont l'allure est en réalité de l'endurance.
       Inactif (0.0) si athlete_speed_profile absent de config.json.

    Adaptation automatique pour coureurs lents :
       Quand athlete_mean_speed_kmh > 0, les seuils max_block_cv et min_ef_ratio
       sont ajustés proportionnellement. Le bruit GPS (~0.5 km/h) a un impact relatif
       plus fort à basse vitesse, et l'écart effort/récup est naturellement plus faible.
       Référence : seuils calibrés à ~12 km/h.

    Note : le DBSCAN (reps >= 3) reste nécessaire mais pas suffisant seul.
    """
    # ── Adaptation des seuils selon le niveau de l'athlète ───────────────────
    # Le bruit GPS est ~constant en absolu, donc son impact sur le CV intra-bloc
    # augmente quand la vitesse baisse. L'écart effort/récup est aussi plus faible
    # en absolu pour un coureur lent → ratio naturellement plus bas.
    # Référence : seuils calibrés à ~12 km/h (coureur « rapide »).
    # Graduation linéaire : speed_factor=1 à 12 km/h (aucune adaptation pour les
    # profils rapides), plancher à 0.5 pour les profils très lents.
    speed_factor = 1.0
    slowness = 0.0
    if athlete_mean_speed_kmh > 0:
        speed_factor = max(0.5, min(1.0, athlete_mean_speed_kmh / 12.0))
        slowness = 1.0 - speed_factor  # 0 = rapide, jusqu'à 0.5 = très lent

        # CV intra-bloc : bruit GPS relativement plus élevé à basse vitesse
        max_block_cv = min(0.22, max_block_cv / speed_factor)
        # Écart effort/récup plus faible en absolu (moins de « marge » disponible)
        min_ef_ratio = max(1.18, min_ef_ratio - 0.18 * slowness)
        # Oscillations globales atténuées par le bruit
        min_cv = max(0.10, min_cv - 0.08 * slowness)
        # Récupérations plus variables chez les coureurs lents (pauses, feux,
        # terrain) — à allure faible le bruit GPS affecte aussi la détection de
        # fin de bloc, donc la durée de « récup » mesurée fluctue.
        max_recup_cv = min(1.00, max_recup_cv + 0.60 * slowness)

    # Prérequis : au moins un cluster avec 3+ répétitions
    if not any(p["reps"] >= 3 for p in patterns):
        return False

    # ── Détection précoce d'une structure forte (utilisé pour bypasser des
    #    critères ratio-based qui sous-performent à allure lente) ─────────────
    # À allure lente, le bruit GPS et l'inertie limitent l'écart absolu entre
    # effort et récup, ce qui fait échouer les critères CV global et ef_ratio
    # même sur des fractionnés évidents (20-40 répétitions claires). Quand la
    # structure est très nette, on fait confiance au signal structurel et on
    # skippe les ratios.
    #
    # Pour éviter les faux positifs sur des sorties longues à pace variable
    # (qu'un DBSCAN avide pourrait clusteriser en 30+ "blocs" purement bruités),
    # on impose deux conditions strictes :
    # 1. Forte structure interne : ≥ 8 répétitions OU (≥ 5 reps + cv_core < 0.05)
    # 2. Garde-fou ef_ratio : effort/récup ≥ 1.10 (vrai fractionné même lent
    #    a au moins 10% d'écart entre effort et récup ; une oscillation pure
    #    de bruit GPS reste sous 1.05).
    #
    # Réservé aux profils lents (slowness > 0.1 ~ mean < 10.8 km/h) pour ne pas
    # ouvrir la porte aux faux positifs sur les profils rapides où un run
    # vallonné peut facilement produire ces conditions.
    max_reps = max((p.get("reps", 0) for p in patterns), default=0)
    core_cv_value = None
    if not blocks.empty and "cluster" in blocks.columns and "speed_cv_core" in blocks.columns:
        _valid = blocks[blocks["cluster"] != -1]
        if not _valid.empty:
            _best = _valid.groupby("cluster").size().idxmax()
            core_cv_value = float(
                _valid[_valid["cluster"] == _best]["speed_cv_core"].median()
            )

    structure_strong = (
        core_cv_value is not None
        and (
            max_reps >= 8
            or (max_reps >= 5 and core_cv_value < 0.05)
        )
    )
    # On retient le flag historique pour la condition simple (≥ 5 reps + 0.07)
    # qui sert encore au bypass critère 6 (vitesse absolue p75) — moins risqué
    # car celui-ci n'est qu'un floor de plausibilité.
    core_cv_strong = core_cv_value is not None and core_cv_value < 0.07
    slow_profile_bypass = slowness > 0.1 and max_reps >= 5 and core_cv_strong

    # ── Critère 1 : CV global de vitesse ─────────────────────────────────────
    cv = float(df["speed_smooth"].std() / (df["speed_smooth"].mean() + 1e-6))
    if cv < min_cv and not (slowness > 0.1 and structure_strong):
        return False

    # ── Critère 2 : ratio effort / récupération ───────────────────────────────
    effort_segs   = [s for s in segments if s["type"] == "effort"]
    recovery_segs = [s for s in segments if s["type"] == "recovery"]

    if not effort_segs or not recovery_segs:
        return False

    def _mean_spd(segs: list[dict]) -> float:
        speeds = []
        for s in segs:
            block = df[(df["time_s"] >= s["start"]) & (df["time_s"] <= s["end"])]
            if not block.empty:
                speeds.append(float(block["speed_smooth"].mean()))
        return float(np.mean(speeds)) if speeds else 0.0

    effort_spd   = _mean_spd(effort_segs)
    recovery_spd = _mean_spd(recovery_segs)

    if recovery_spd <= 0:
        return False
    ef_ratio = effort_spd / recovery_spd
    # Floor anti-bruit pour le bypass profils lents (cf. block ci-dessus).
    soft_ratio_ok = ef_ratio >= 1.10
    if ef_ratio < min_ef_ratio and not (slowness > 0.1 and structure_strong and soft_ratio_ok):
        return False

    # ── Critère 3 : régularité intra-bloc sur noyau central (speed_cv_core) ──
    if not blocks.empty and "cluster" in blocks.columns and "speed_cv_core" in blocks.columns:
        valid_blks = blocks[blocks["cluster"] != -1]
        if not valid_blks.empty:
            best_cluster = valid_blks.groupby("cluster").size().idxmax()
            cv_core_median = float(
                valid_blks[valid_blks["cluster"] == best_cluster]["speed_cv_core"].median()
            )
            if cv_core_median > max_block_cv:
                return False

    # ── Critère 3bis : plausibilité physiologique récup vs effort ────────────
    # Une récup beaucoup plus courte que l'effort est physiologiquement
    # impossible : ex. récup ~7-10s entre des efforts de ~4 min. C'est la
    # signature d'un run CONTINU (tempo, footing soutenu) que DBSCAN a
    # sur-segmenté en lisant des micro-creux GPS comme des « récups ». On rejette
    # quand la récup médiane du cluster dominant est implausiblement courte par
    # rapport à la durée d'effort médiane. Garde-fou demandé : il filtre les faux
    # positifs introduits par un seuil GMM plus sélectif (footing vs effort).
    if (not recoveries.empty and not blocks.empty
            and "cluster" in blocks.columns):
        valid_blks = blocks[blocks["cluster"] != -1]
        if not valid_blks.empty:
            best_cluster = valid_blks.groupby("cluster").size().idxmax()
            cl_blocks = valid_blks[valid_blks["cluster"] == best_cluster]
            cl_recups = recoveries[recoveries["cluster"] == best_cluster]
            if len(cl_blocks) >= 2 and not cl_recups.empty:
                med_effort = float((cl_blocks["end"] - cl_blocks["start"]).median())
                med_recup  = float(cl_recups["recup_dur_s"].median())
                min_plausible = max(min_recup_abs_s, min_recup_effort_ratio * med_effort)
                if med_effort > 0 and med_recup < min_plausible:
                    return False

    # ── Critère 4 : cohérence des récupérations du cluster dominant ──────────
    # Bypassé quand les signaux structurels sont forts :
    # - (tous profils) CV global ≥ 2× seuil ET ratio effort/récup ≥ 1.5 ;
    # - (profils lents) slow_profile_bypass déjà calculé plus haut.
    strong_structural_signal = (
        (cv >= min_cv * 2 and effort_spd / (recovery_spd + 1e-6) >= 1.5)
        or slow_profile_bypass
    )
    if not strong_structural_signal:
        if not recoveries.empty and not blocks.empty and "cluster" in blocks.columns:
            valid_blks = blocks[blocks["cluster"] != -1]
            if not valid_blks.empty:
                best_cluster   = valid_blks.groupby("cluster").size().idxmax()
                cluster_recups = recoveries[recoveries["cluster"] == best_cluster]
                if len(cluster_recups) >= 2:
                    recup_cv = float(
                        cluster_recups["recup_dur_s"].std()
                        / (cluster_recups["recup_dur_s"].mean() + 1e-6)
                    )
                    if recup_cv >= max_recup_cv:
                        return False

    # ── Critère 5 : vitesse effort > moyenne session × seuil ─────────────────
    session_mean_spd = float(df["speed_smooth"].mean())
    if session_mean_spd > 0 and effort_spd < session_mean_spd * min_ef_vs_mean:
        return False

    # ── Critère 6 : vitesse effort > seuil profil athlète (p75) ─────────────
    # Chez les profils lents (slowness > 0.1), la distribution de vitesses est
    # resserrée (p75 proche de la moyenne), donc un vrai fractionné peut avoir
    # un effort à peine au-dessus du p75. Bypass si structure très nette
    # (≥ 5 reps + speed_cv_core < 0.07). Non appliqué aux profils rapides
    # pour éviter de classer en fractionné des runs vallonnés réguliers.
    if min_effort_speed_kmh > 0 and effort_spd < min_effort_speed_kmh:
        if not slow_profile_bypass:
            return False

    return True


# ──────────────────────────────────────────────
# 7.55 GATE D'INTENSITÉ SESSION (filtre rétroactif)
# ──────────────────────────────────────────────

def _check_session_intensity(
    df: pd.DataFrame,
    session_type: str,
    blocks: pd.DataFrame,
    hr_max: float = 0.0,
    athlete_speed_profile: Optional[dict] = None,
) -> bool:
    """
    Filtre rétroactif : un run avec pauses (feu, photo) peut faire émerger une
    structure pseudo-fractionnée sans que les efforts soient réellement intenses.
    On exige que la FC OU l'allure DES BLOCS D'EFFORT atteigne un palier cohérent
    avec le type détecté.

    Why mesurer sur les blocs et non sur la session entière :
    un vrai fractionné (ex : 3×1km à allure 10K) noyé dans 16 km de footing a une
    FC et une allure MOYENNES de session d'endurance (diluées par l'échauffement /
    retour au calme), mais ses blocs d'effort sont clairement intenses. À l'inverse,
    un footing-avec-pauses a des « blocs » à allure normale entre deux arrêts :
    leur intensité reste celle de l'endurance → toujours rejeté. Mesurer sur les
    blocs distingue donc proprement les deux cas. Repli sur la moyenne de session
    si aucun bloc clusterisé n'est disponible (ex : pyramide en blocs « noise »).

    OU logique (pas ET) : couvre les runs sans FC et les athlètes qui ne
    poussent pas en FC mais clairement en allure.

    Bypass : structure forte (≥ 8 reps, ou ≥ 5 reps + cv_core < 0.05).

    Retourne True si l'intensité est cohérente OU si aucune donnée disponible.
    """
    profile = athlete_speed_profile or {}

    if session_type == "fractionné court":
        hr_pct_min = 0.82
        spd_key    = "p80_kmh"
    elif session_type in ("fractionné moyen", "mixte"):
        hr_pct_min = 0.80
        spd_key    = "p75_kmh"
    else:  # long, tempo / allure, pyramide *
        # 0.82 (et non 0.78) car un tempo continu à allure seuil hit
        # naturellement 78-81% FCmax sans être fractionné. À ce niveau de durée
        # de bloc, l'écart d'intensité entre vrai fractionné et tempo continu
        # se joue surtout sur la FC moyenne (effort soutenu > effort intermittent).
        hr_pct_min = 0.82
        spd_key    = "p70_kmh"

    # Mesures structurelles (pour bypass éventuel)
    max_reps  = 0
    cv_core   = None
    if not blocks.empty and "cluster" in blocks.columns and "speed_cv_core" in blocks.columns:
        valid = blocks[blocks["cluster"] != -1]
        if not valid.empty:
            sizes    = valid.groupby("cluster").size()
            max_reps = int(sizes.max())
            best     = sizes.idxmax()
            cv_core  = float(valid[valid["cluster"] == best]["speed_cv_core"].median())

    # Adaptation profil lent : seuils légèrement abaissés
    athlete_mean = float(profile.get("mean_kmh", 0.0))
    if 0 < athlete_mean < 10.8:
        hr_pct_min -= 0.03

    # Fenêtre de mesure : les blocs d'effort (cluster != -1) plutôt que toute la
    # session. Repli sur la session entière si aucun bloc clusterisé.
    effort_df = df
    if not blocks.empty and "cluster" in blocks.columns:
        valid_blocks = blocks[blocks["cluster"] != -1]
        if not valid_blocks.empty:
            mask = pd.Series(False, index=df.index)
            for _, b in valid_blocks.iterrows():
                mask |= (df["time_s"] >= b["start"]) & (df["time_s"] <= b["end"])
            if mask.any():
                effort_df = df[mask]

    hr_ok = None
    if hr_max > 0 and "bpm_smooth" in effort_df.columns:
        bpm_valid = effort_df["bpm_smooth"].dropna()
        bpm_valid = bpm_valid[bpm_valid > 30]
        if len(bpm_valid) > 0:
            hr_mean = float(bpm_valid.mean())
            hr_ok   = (hr_mean / hr_max) >= hr_pct_min

    spd_ok = None
    spd_min = float(profile.get(spd_key, 0.0))
    if spd_min > 0:
        spd_mean = float(effort_df["speed_smooth"].mean())
        spd_ok   = spd_mean >= spd_min

    # Aucune donnée d'intensité → on ne filtre pas
    if hr_ok is None and spd_ok is None:
        return True

    # Au moins l'un des deux signaux dit "intense" → OK
    if hr_ok or spd_ok:
        return True

    # Aucun signal ne dit "intense". On bypass sur la structure, avec un seuil
    # qui dépend de la disponibilité de la FC :
    # - FC disponible : la FC est un signal fiable ; si elle dit endurance,
    #   on n'invalide que sur structure extrême (≥10 reps ou ≥8 + cv_core<0.04).
    #   Un endurance avec pauses peut produire 5-7 blocs cv_core ~0.05.
    # - FC indisponible (vieilles activités sans cardio) : on doit se fier
    #   davantage à la structure. Seuil aligné sur l'ancienne logique pour
    #   ne pas perdre les vrais fractionnés sans FC.
    if cv_core is not None:
        if hr_ok is None:
            if max_reps >= 8 or (max_reps >= 5 and cv_core < 0.06):
                return True
        else:
            if max_reps >= 10 or (max_reps >= 8 and cv_core < 0.04):
                return True
    return False


# ──────────────────────────────────────────────
# 7.6 DÉTECTION DU FRACTIONNÉ EN PYRAMIDE
# ──────────────────────────────────────────────

def detect_pyramid(
    blocks: pd.DataFrame,
    df: pd.DataFrame | None = None,
    config: dict | None = None,
) -> dict | None:
    """
    Détecte une séance en pyramide à partir des blocs d'effort.

    Une pyramide est caractérisée par :
    - 3 à 9 blocs (tailles toutes différentes → DBSCAN les met en noise)
    - Anti-corrélation Spearman(durée, vitesse) < seuil (défaut -0.40)
      → les blocs longs sont plus lents, les blocs courts plus rapides
    - Monotonie avec ≤ 1 changement de direction dans les durées
      (tolérance ±15% pour ignorer les variations GPS mineures)

    Garde-fous (nécessitent df) :
    - CV(durées_récup) ≤ pyramid_max_recov_cv (défaut 0.50)
      Un vrai fractionné pyramide a des récupérations intentionnelles donc régulières.
      Des micro-pauses GPS ou des ralentissements de terrain produisent CV > 0.50.
    - median(récup) / median(effort) ≥ pyramid_min_recov_ratio (défaut 0.15)
      Les récupérations doivent représenter au moins 15% des durées d'effort.
      Un ratio < 0.15 signale des micro-ralentissements sur un run continu.

    Types retournés :
    - 'fractionné pyramide symétrique'   : 1 changement de direction (ex: ↑↑↑↓↓↓)
    - 'fractionné pyramide ascendante'   : 0 changement, durées croissantes (↑↑↑↑)
    - 'fractionné pyramide descendante'  : 0 changement, durées décroissantes (↓↓↓↓)

    Paramètres
    ----------
    blocks : DataFrame des blocs d'effort (sortie de extract_block_metrics),
             SANS filtrage par cluster (on prend tous les blocs).
    df     : DataFrame préprocessé de la séance (pour calculer les récupérations).
             Si None, les garde-fous récupération sont ignorés.
    config : dict de la section 'detection_fractionne' de config.json.

    Retourne
    --------
    dict ou None si aucune pyramide détectée.
    """
    cfg          = config or _load_det_config()
    min_blocs    = cfg.get("pyramid_min_blocs", 3)
    max_blocs    = cfg.get("pyramid_max_blocs", 9)
    spearman_max = cfg.get("pyramid_spearman_max", -0.40)
    max_inflect  = cfg.get("pyramid_max_inflections", 1)
    tolerance    = cfg.get("pyramid_duration_tolerance", 0.15)
    max_recov_cv = cfg.get("pyramid_max_recov_cv", 0.50)
    min_recov_ratio = cfg.get("pyramid_min_recov_ratio", 0.15)

    if blocks.empty:
        return None

    blks = blocks.sort_values("start").reset_index(drop=True)
    n    = len(blks)

    if not (min_blocs <= n <= max_blocs):
        return None

    durations = blks["duration_s"].values
    speeds    = blks["mean_speed"].values

    # ── Critère Spearman : anti-corrélation durée ↔ vitesse ──────────────────
    corr, _ = spearmanr(durations, speeds)
    if corr >= spearman_max:
        return None

    # ── Critère monotonie avec tolérance ─────────────────────────────────────
    # On calcule les différences relatives entre durées consécutives.
    # Un changement n'est significatif que si |diff| > tolerance × durée courante.
    signs = []
    for i in range(n - 1):
        diff_rel = (durations[i + 1] - durations[i]) / (durations[i] + 1e-6)
        if abs(diff_rel) > tolerance:
            signs.append(1 if diff_rel > 0 else -1)

    if not signs:
        # Toutes les variations sont dans la tolérance → pas de structure claire
        return None

    sign_changes = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i - 1])

    if sign_changes > max_inflect:
        return None

    # ── Garde-fous récupération (nécessitent df) ──────────────────────────────
    if df is not None:
        recup_df = _extract_all_recoveries(df, blks)

        if not recup_df.empty and len(recup_df) >= 2:
            recup_durs = recup_df["recup_dur_s"].values.astype(float)
            recov_mean = float(np.mean(recup_durs))

            # Garde-fou 1 : cohérence des récupérations
            recov_cv = float(np.std(recup_durs) / (recov_mean + 1e-6))
            if recov_cv > max_recov_cv:
                return None

            # Garde-fou 2 : ratio durée récup / durée effort
            effort_med = float(np.median(durations))
            recov_med  = float(np.median(recup_durs))
            if effort_med > 0 and recov_med / effort_med < min_recov_ratio:
                return None

    # ── Détermination du sous-type ────────────────────────────────────────────
    if sign_changes == 1:
        session_type = "fractionné pyramide symétrique"
    elif signs[0] == 1:
        session_type = "fractionné pyramide ascendante"
    else:
        session_type = "fractionné pyramide descendante"

    return {
        "is_fractionne":  True,
        "session_type":   session_type,
        "spearman_corr":  round(float(corr), 3),
        "n_blocs":        n,
        "sign_changes":   sign_changes,
        "durations_s":    [round(float(d), 1) for d in durations],
        "mean_speeds":    [round(float(s), 2) for s in speeds],
    }


# ──────────────────────────────────────────────
# 7.7 DÉTECTION DE SÉANCE SPRINT (pics courts et violents)
# ──────────────────────────────────────────────

def detect_sprints(
    activity_path: str,
    walk_threshold_kmh: float = 6.0,
    sigma: float              = 1.0,
    min_spike_s: float        = 2.0,
    max_spike_s: float        = 30.0,
    speed_factor: float       = 1.40,
    peak_factor: float        = 1.50,
    min_spikes: int           = 3,
    min_mean_peak_ratio: float = 1.70,
) -> dict:
    """
    Détecte une séance de sprints (pics courts et violents) que le pipeline
    fractionné standard rate parce que ses min_effort_s=15s coupe les blocs
    courts et son lissage sigma=3 écrase les pics de quelques secondes.

    Approche :
    - lissage léger (sigma=1, ~3s) pour conserver les pics
    - seuil dynamique = max(speed_factor × vitesse_moy_active, p95)
    - un sprint = plateau de min_spike_s à max_spike_s au-dessus du seuil
    - validation : ≥ min_spikes ET au moins un pic ≥ peak_factor × moy active

    Retourne {is_sprint, n_sprints, max_speed_kmh, mean_peak_kmh, threshold_kmh}.
    """
    df = _read_stream_csv(activity_path)
    if "speed_kmh" not in df.columns or len(df) < 30:
        return {"is_sprint": False, "n_sprints": 0}

    df = df.sort_values("time_s").reset_index(drop=True)
    v_raw = df["speed_kmh"].ffill().values.astype(float)
    t     = df["time_s"].values.astype(float)
    v_sm  = gaussian_filter1d(v_raw, sigma=sigma)

    active = v_raw[v_raw >= walk_threshold_kmh]
    if len(active) < 30:
        return {"is_sprint": False, "n_sprints": 0}
    mean_active = float(active.mean())

    threshold = max(speed_factor * mean_active, float(np.percentile(v_raw, 95)))

    mask = v_sm > threshold
    spikes = []
    i = 0
    while i < len(v_sm):
        if mask[i]:
            j = i
            while j < len(v_sm) and mask[j]:
                j += 1
            dur  = float(t[j - 1] - t[i])
            peak = float(v_raw[i:j].max())
            if min_spike_s <= dur <= max_spike_s and peak >= peak_factor * mean_active:
                spikes.append({"start": float(t[i]), "end": float(t[j - 1]),
                               "duration_s": dur, "peak_kmh": peak,
                               "mean_kmh": float(v_sm[i:j].mean())})
            i = j
        else:
            i += 1

    if len(spikes) < min_spikes:
        return {"is_sprint": False, "n_sprints": len(spikes),
                "threshold_kmh": round(threshold, 2)}

    max_peak = max(s["peak_kmh"] for s in spikes)
    mean_peak = float(np.mean([s["mean_kmh"] for s in spikes]))

    # Garde-fou anti faux positif : une sortie d'endurance peut contenir 3-4
    # accélérations légères (fin de run, traversées). Un vrai sprint dépasse
    # nettement la vitesse de croisière — on exige un ratio mean_peak/active
    # élevé pour distinguer "effort violent" d'"accélération modérée".
    if mean_peak / max(mean_active, 1e-6) < min_mean_peak_ratio:
        return {"is_sprint": False, "n_sprints": len(spikes),
                "threshold_kmh": round(threshold, 2),
                "mean_peak_ratio": round(mean_peak / max(mean_active, 1e-6), 2)}

    return {
        "is_sprint":     True,
        "session_type":  "fractionné sprint",
        "n_sprints":     len(spikes),
        "threshold_kmh": round(threshold, 2),
        "max_speed_kmh": round(max_peak, 2),
        "mean_peak_kmh": round(mean_peak, 2),
        "mean_active_kmh": round(mean_active, 2),
        "spikes":        spikes,
    }


# ──────────────────────────────────────────────
# 8. PIPELINE COMPLÈTE
# ──────────────────────────────────────────────

def analyze_fractionne(
    activity_path: str,
    sigma: float              = 3.0,
    min_effort_s: float       = 15.0,
    dbscan_eps: float         = 0.35,
    min_cv: float             = 0.17,
    min_ef_ratio: float       = 1.35,
    max_block_cv: float       | None = None,   # None = chargé depuis config selon sport_type
    max_recup_cv: float       | None = None,   # None = chargé depuis config
    min_ef_vs_mean: float     = 1.03,
    min_effort_speed_kmh: float = 0.0,         # 0.0 = inactif ; fourni par session_classifier
    athlete_mean_speed_kmh: float = 0.0,       # vitesse moyenne athlète pour adaptation seuils
    hr_max: float             = 0.0,           # 0.0 = inactif ; pour gate d'intensité session
    athlete_speed_profile: Optional[dict] = None,  # {p70_kmh, p75_kmh, p80_kmh, mean_kmh}
    sport_type: str           = "Run",
    verbose: bool             = True,
) -> dict:
    """
    Pipeline complète : CSV → résumé structuré.

    Paramètres ajustables :
    - sigma           : lissage gaussien (augmenter si signal très bruité)
    - min_effort_s    : durée minimale d'un bloc pour être retenu (secondes)
    - dbscan_eps      : rayon DBSCAN (augmenter pour fusionner des distances proches)
    - min_cv          : seuil CV vitesse globale pour valider le fractionné (défaut 0.17)
    - min_ef_ratio    : ratio effort/récup minimum pour valider (défaut 1.35)
    - max_block_cv    : CV intra-bloc max sur noyau central 70% ; None = depuis config
                        (0.12 Run, 0.20 TrailRun)
    - max_recup_cv    : CV max des durées de récupération ; None = depuis config (0.45)
    - min_ef_vs_mean  : ratio vitesse effort / moyenne session (défaut 1.03)
    - sport_type      : 'Run' ou 'TrailRun' — détermine max_block_cv depuis config
    - verbose         : afficher le résumé dans le terminal

    Retourne un dict :
    - 'df'            : DataFrame préprocessé
    - 'blocks'        : DataFrame des blocs d'effort avec cluster
    - 'recoveries'    : DataFrame des récupérations par cluster
    - 'patterns'      : liste de dicts avec descriptions lisibles
    - 'session_type'  : str (fractionné court / moyen / long / mixte / pyramide / tempo)
    - 'threshold'     : seuil GMM utilisé (km/h)
    - 'is_fractionne' : bool
    - 'cv_speed'      : CV de vitesse de la session (diagnostic)
    - 'ef_ratio'      : ratio effort/récup mesuré (diagnostic)
    - 'pyramid'       : dict pyramide si détectée, sinon None
    """
    # ── Chargement des seuils depuis config ───────────────────────────────────
    det_cfg = _load_det_config()
    if max_block_cv is None:
        if sport_type == "TrailRun":
            max_block_cv = det_cfg.get("max_block_cv_trail", 0.20)
        else:
            max_block_cv = det_cfg.get("max_block_cv_run", 0.12)
    if max_recup_cv is None:
        max_recup_cv = det_cfg.get("max_recup_cv", 0.45)
    min_recup_abs_s = det_cfg.get("min_recup_abs_s", 15.0)
    min_recup_effort_ratio = det_cfg.get("min_recup_effort_ratio", 0.10)

    df = _read_stream_csv(activity_path)
    df = preprocess(df, sigma=sigma)

    threshold = find_effort_threshold_gmm(df["speed_smooth"].values)

    segments = segment_signal(df, threshold, min_effort_s=min_effort_s)
    blocks   = extract_block_metrics(df, segments)

    # Valeurs de diagnostic (toujours calculées)
    cv_speed = float(df["speed_smooth"].std() / (df["speed_smooth"].mean() + 1e-6))
    effort_segs   = [s for s in segments if s["type"] == "effort"]
    recovery_segs = [s for s in segments if s["type"] == "recovery"]
    if effort_segs and recovery_segs:
        def _ms(segs):
            vals = []
            for s in segs:
                b = df[(df["time_s"] >= s["start"]) & (df["time_s"] <= s["end"])]
                if not b.empty:
                    vals.append(float(b["speed_smooth"].mean()))
            return float(np.mean(vals)) if vals else 0.0
        ef_ratio = _ms(effort_segs) / (_ms(recovery_segs) + 1e-6)
    else:
        ef_ratio = 0.0

    _no_frac = {
        "df": df, "blocks": blocks if not blocks.empty else pd.DataFrame(),
        "recoveries": pd.DataFrame(),
        "patterns": [], "session_type": "indéterminé",
        "threshold": threshold, "is_fractionne": False,
        "cv_speed": round(cv_speed, 3), "ef_ratio": round(ef_ratio, 2),
        "pyramid": None,
        "mountain_interval_candidate": False,
    }

    if blocks.empty:
        if verbose:
            print("Aucun bloc d'effort significatif détecté.")
        return _no_frac

    blocks_clustered = cluster_blocks(blocks, eps=dbscan_eps)
    blocks_clustered = _reattach_noise_blocks(blocks_clustered)
    blocks_clustered = _filter_spurious_clusters(blocks_clustered)
    blocks_clustered = _trim_bonus_reps(blocks_clustered)
    recoveries       = extract_recoveries(df, blocks_clustered)
    patterns         = summarize_session(blocks_clustered, recoveries)
    stype            = classify_session_type(patterns)

    is_frac = _validate_fractionne(
        df, segments, blocks_clustered, recoveries, patterns,
        min_cv=min_cv,
        min_ef_ratio=min_ef_ratio,
        max_block_cv=max_block_cv,
        max_recup_cv=max_recup_cv,
        min_ef_vs_mean=min_ef_vs_mean,
        min_effort_speed_kmh=min_effort_speed_kmh,
        athlete_mean_speed_kmh=athlete_mean_speed_kmh,
        min_recup_abs_s=min_recup_abs_s,
        min_recup_effort_ratio=min_recup_effort_ratio,
    )

    pyramid = None
    mountain_candidate = False
    if not is_frac:
        # Tente la détection pyramide sur tous les blocs (sans filtrage cluster)
        pyramid = detect_pyramid(blocks, df=df, config=det_cfg)
        if pyramid:
            is_frac = True
            stype   = pyramid["session_type"]
        elif sport_type == "TrailRun" and cv_speed >= min_cv:
            # CV élevé sur un trail mais ni fractionné standard ni pyramide :
            # pourrait être du fractionné en montagne (montées répétées).
            # Flaggé pour traitement futur, classé en "indéterminé" pour l'instant.
            mountain_candidate = True

    # Gate d'intensité session : invalidation rétroactive si la FC moyenne ET
    # l'allure moyenne sont d'endurance pour ce type de fractionné détecté.
    # Filtre principalement les runs avec pauses (feux, photos) qui font émerger
    # une pseudo-structure sans intensité réelle.
    if is_frac:
        if not _check_session_intensity(
            df, stype, blocks_clustered,
            hr_max=hr_max,
            athlete_speed_profile=athlete_speed_profile,
        ):
            is_frac = False
            stype   = "indéterminé"
            pyramid = None

    if verbose:
        _print_summary(activity_path, threshold, patterns, stype, is_frac,
                       cv_speed, ef_ratio, pyramid)

    return {
        "df":                        df,
        "blocks":                    blocks_clustered,
        "recoveries":                recoveries,
        "patterns":                  patterns,
        "session_type":              stype,
        "threshold":                 threshold,
        "is_fractionne":             is_frac,
        "cv_speed":                  round(cv_speed, 3),
        "ef_ratio":                  round(ef_ratio, 2),
        "pyramid":                   pyramid,
        "mountain_interval_candidate": mountain_candidate,
    }


def _print_summary(path, threshold, patterns, stype, is_frac,
                   cv_speed=None, ef_ratio=None, pyramid=None):
    sep = "=" * 55
    print(f"\n{sep}")
    print(f"  {path}")
    print(f"  Seuil GMM : {threshold:.2f} km/h", end="")
    if cv_speed is not None:
        print(f"  |  CV={cv_speed:.3f}  ratio={ef_ratio:.2f}", end="")
    print()
    print(sep)
    if is_frac:
        print(f"  TYPE : {stype.upper()}\n")
        if pyramid:
            print(f"    Pyramide détectée : {pyramid['n_blocs']} blocs")
            print(f"    Spearman={pyramid['spearman_corr']:.3f}  "
                  f"changements de direction={pyramid['sign_changes']}")
            print(f"    Durées (s): {pyramid['durations_s']}")
        else:
            for p in patterns:
                if p["reps"] >= 3:
                    cv_note = " [allure reguliere]" if p["speed_cv_core"] < 0.07 else ""
                    print(f"    {p['description']}  (BPM moy. {p['mean_bpm']:.0f}){cv_note}")
            noise = blocks_noise_count(patterns)
            if noise:
                print(f"\n    ({noise} bloc(s) atypique(s) ignorés par DBSCAN)")
    else:
        print("  Pas de fractionné structuré détecté.")
    print(f"{sep}\n")


def blocks_noise_count(patterns):
    """Placeholder : retourne 0 car le compte des outliers est dans blocks['cluster']==-1."""
    return 0


# ──────────────────────────────────────────────
# UTILITAIRES
# ──────────────────────────────────────────────

def format_allure(min_per_km: float) -> str:
    """Formatage allure numérique → mm:ss min/km."""
    minutes = int(min_per_km)
    seconds = round((min_per_km - minutes) * 60)
    return f"{minutes}:{seconds:02d} min/km"


def load_stream(path: str) -> pd.DataFrame:
    """Charge et préprocesse directement."""
    df = _read_stream_csv(path)
    return preprocess(df)


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    path       = sys.argv[1] if len(sys.argv) > 1 else "data/streams/10*300.csv"
    sport      = sys.argv[2] if len(sys.argv) > 2 else "Run"
    result     = analyze_fractionne(path, sport_type=sport, verbose=True)

    blocks = result["blocks"]
    if not blocks.empty:
        print("\nBlocs détectés :")
        cols = ["start", "end", "duration_s", "distance_m", "pace_sec_km",
                "mean_bpm", "speed_cv", "speed_cv_core", "cluster"]
        available = [c for c in cols if c in blocks.columns]
        print(blocks[available].to_string(index=False))
