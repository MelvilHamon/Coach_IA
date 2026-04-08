"""
metrics.py — Métriques d'intensité pour le suivi d'entraînement.

Références bibliographiques :
- TRIMP    : Banister EW (1991). Modeling elite athletic performance.
              In: MacDougall JD, Wenger HA, Green HJ (eds),
              Physiological Testing of the High Performance Athlete.
              Human Kinetics, Champaign IL. pp. 403-424.
- hrTSS    : Adaptation de Skiba PF (2006/2011) du TSS Coggan pour la FC.
              Formule : hrTSS = duration_h × IF² × 100
              où IF = hr_mean / hr_threshold.
              Voir aussi : Lucia A et al. (2003). Tour de France versus
              Vuelta a España: which is harder? Med Sci Sports Exerc.
- ACWR     : Hulin BT, Gabbett TJ, Lawson DW et al. (2016).
              The acute:chronic workload ratio predicts injury.
              Br J Sports Med 50(4):231-236.
              EWMA : Spore (2018) & Williams et al. (2017).
              λ = 2/(N+1) : formule EMA technique (analogie finance/sport).
- EF/Décop.: Friel J (2009). The Triathlete's Training Bible, 3rd ed.
              VeloPress. Concept "pa:HR decoupling" — seuil < 5%.
- Zones FC : Friel J (2009). The Cyclist's Training Bible & Running.
              Zones basées sur %FC_max (5 zones : Z1-Z5).
"""

import json
import os
from datetime import timedelta

import numpy as np
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_ROOT, "config.json")

def load_config(config_path: str = None) -> dict:
    _path = config_path or _CONFIG_PATH
    if not os.path.exists(_path):
        return {}
    with open(_path, encoding="utf-8") as f:
        return json.load(f)


# ── Zones FC (5 zones, %FC_max) ───────────────────────────────────────────────

_ZONE_BOUNDS = [
    ("z1", 0.00, 0.60),   # Récupération
    ("z2", 0.60, 0.70),   # Endurance fondamentale
    ("z3", 0.70, 0.80),   # Tempo
    ("z4", 0.80, 0.90),   # Seuil lactique
    ("z5", 0.90, 9.99),   # VO2max / anaérobie
]


def compute_hr_zones(stream_df: pd.DataFrame, hr_max: int, hr_zones_custom: list = None) -> dict:
    """
    Calcule le temps passé dans chaque zone FC depuis les données stream.

    Nécessite la colonne 'bpm' et 'time_s' dans stream_df.
    Retourne un dict avec {z1_min, z2_min, ..., z1_pct, ..., dominant_zone}.
    Retourne {} si données insuffisantes.

    Parameters
    ----------
    hr_zones_custom : liste de 5 BPM [z1_max, z2_max, z3_max, z4_max, z5_max]
                      Si fourni, utilise ces limites absolues au lieu de %FC_max.
    """
    if "bpm" not in stream_df.columns or stream_df["bpm"].isna().all():
        return {}

    bpm = stream_df["bpm"]
    dt  = stream_df["time_s"].diff().fillna(1).clip(0, 5)

    valid = bpm.notna()
    bpm_v = bpm[valid]
    dt_v  = dt[valid]
    total_s = float(dt_v.sum())
    if total_s == 0:
        return {}

    # Build zone bounds in absolute BPM
    if hr_zones_custom and len(hr_zones_custom) == 5:
        bounds = [
            ("z1", 0, hr_zones_custom[0]),
            ("z2", hr_zones_custom[0], hr_zones_custom[1]),
            ("z3", hr_zones_custom[1], hr_zones_custom[2]),
            ("z4", hr_zones_custom[2], hr_zones_custom[3]),
            ("z5", hr_zones_custom[3], hr_zones_custom[4]),
        ]
    else:
        bounds = [(name, lo * hr_max, hi * hr_max) for name, lo, hi in _ZONE_BOUNDS]

    result = {}
    for name, lo, hi in bounds:
        mask = (bpm_v >= lo) & (bpm_v < hi)
        zone_s = float(dt_v[mask].sum())
        result[f"{name}_min"] = round(zone_s / 60, 1)
        result[f"{name}_pct"] = round(zone_s / total_s * 100, 1)

    # Zone dominante (en % de temps)
    zone_names = ["z1", "z2", "z3", "z4", "z5"]
    pct_vals = {name: result[f"{name}_pct"] for name in zone_names}
    result["dominant_zone"] = max(pct_vals, key=pct_vals.get)

    return result


# ── TRIMP ─────────────────────────────────────────────────────────────────────

def compute_trimp(
    duration_min: float,
    hr_mean: float,
    hr_max: int,
    hr_rest: int,
    sex: str = "male",
) -> float:
    """
    TRIMP de Banister (1991) — Training Impulse.

    Formule :
        TRIMP = D × ΔHR × C × exp(k × ΔHR)
    où :
        D   = durée en minutes
        ΔHR = (FC_moy - FC_repos) / (FC_max - FC_repos)  ∈ [0, 1]
        C, k = coefficients sexe-dépendants :
                homme : C = 0.64, k = 1.92
                femme  : C = 0.86, k = 1.67

    Retourne NaN si données insuffisantes.
    """
    if any(v is None or (isinstance(v, float) and np.isnan(v))
           for v in (duration_min, hr_mean, hr_max, hr_rest)):
        return float("nan")

    dhr = (hr_mean - hr_rest) / (hr_max - hr_rest)
    dhr = float(np.clip(dhr, 0.0, 1.0))

    if sex == "female":
        c, k = 0.86, 1.67
    else:
        c, k = 0.64, 1.92

    return round(duration_min * dhr * c * np.exp(k * dhr), 1)


# ── hrTSS ─────────────────────────────────────────────────────────────────────

def compute_hrtss(
    duration_min: float,
    hr_mean: float,
    hr_threshold: int,
) -> float:
    """
    hrTSS — Heart Rate Training Stress Score.

    Formule (adaptation Lucia/Skiba du TSS Coggan) :
        IF      = FC_moy / FC_seuil
        hrTSS   = duration_h × IF² × 100

    Interprétation :
        < 150 : récupération facile en 24 h
        150-300 : récupération 24-36 h
        > 300 : récupération 2-3 jours

    Retourne NaN si données insuffisantes.
    """
    if any(v is None or (isinstance(v, float) and np.isnan(v))
           for v in (duration_min, hr_mean, hr_threshold)):
        return float("nan")
    if hr_threshold == 0:
        return float("nan")

    duration_h = duration_min / 60.0
    intensity_factor = hr_mean / hr_threshold
    return round(duration_h * intensity_factor ** 2 * 100, 1)


# ── Efficiency Factor ─────────────────────────────────────────────────────────

def compute_efficiency_factor(
    distance_km: float,
    duration_min: float,
    hr_mean: float,
) -> float:
    """
    Efficiency Factor (Friel, Training Bible).

    EF = speed_kmh / hr_mean
       = (distance_km / (duration_min / 60)) / hr_mean

    Une valeur plus élevée = meilleure efficacité aérobie (même FC, plus vite).
    Utile pour suivre la progression sur le long terme à allure identique.

    Retourne NaN si données insuffisantes.
    """
    if any(v is None or (isinstance(v, float) and np.isnan(v))
           for v in (distance_km, duration_min, hr_mean)):
        return float("nan")
    if duration_min == 0 or hr_mean == 0:
        return float("nan")

    speed_kmh = distance_km / (duration_min / 60.0)
    return round(speed_kmh / hr_mean, 5)


# ── Decoupling aérobie ────────────────────────────────────────────────────────

def compute_decoupling(stream_df: pd.DataFrame) -> float:
    """
    Pa:HR Decoupling (Friel, Training Bible).

    Mesure la dérive cardiaque dans la 2e moitié de la sortie :
        EF_1 = vitesse_moy_1ère_moitié / FC_moy_1ère_moitié
        EF_2 = vitesse_moy_2ème_moitié / FC_moy_2ème_moitié
        découplag% = (EF_1 / EF_2 - 1) × 100

    Interprétation :
        < 5 %  : bonne base aérobie (FC stable)
        5-10 % : légère dérive, acceptable
        > 10 % : dérive marquée, endurance à travailler

    Une valeur positive signifie que l'efficacité baisse en 2e moitié
    (FC monte pour la même allure) — normal, mais doit rester < 5 %.

    Nécessite les colonnes 'time_s', 'speed_kmh', 'bpm' dans stream_df.
    Retourne NaN si données insuffisantes.
    """
    needed = {"time_s", "speed_kmh", "bpm"}
    if not needed.issubset(stream_df.columns):
        return float("nan")

    df = stream_df.dropna(subset=["speed_kmh", "bpm"]).copy()
    if len(df) < 20:
        return float("nan")

    mid = df["time_s"].median()
    first  = df[df["time_s"] <= mid]
    second = df[df["time_s"] >  mid]

    if first.empty or second.empty:
        return float("nan")

    bpm_1 = first["bpm"].mean()
    bpm_2 = second["bpm"].mean()
    spd_1 = first["speed_kmh"].mean()
    spd_2 = second["speed_kmh"].mean()

    if bpm_1 == 0 or bpm_2 == 0 or spd_2 == 0:
        return float("nan")

    ef1 = spd_1 / bpm_1
    ef2 = spd_2 / bpm_2

    if ef2 == 0:
        return float("nan")

    return round((ef1 / ef2 - 1) * 100, 2)


# ── ACWR (Acute:Chronic Workload Ratio) ───────────────────────────────────────

def compute_acwr(
    activities_df: pd.DataFrame,
    metric: str = "km",
) -> pd.Series:
    """
    ACWR via EWMA (Hulin et al. 2016 / Williams et al. 2017).

    Charge aiguë  : EWMA sur 7 jours  → λ_a = 2/(7+1)  = 0.250
    Charge chron. : EWMA sur 28 jours → λ_c = 2/(28+1) ≈ 0.069

    L'EWMA est calculée sur une série QUOTIDIENNE (jours sans activité = 0)
    pour que les jours de repos décroissent correctement la charge.
    Chaque activité reçoit la valeur ACWR de son jour.

    metric = 'km'    → utilise 'Distance (km)' (toujours disponible)
    metric = 'trimp' → utilise 'trimp' (NaN remplacé par 0)

    ACWR < 0.8  → sous-charge
    ACWR 0.8-1.3 → zone optimale
    ACWR > 1.5  → risque de surcharge

    Retourne une pd.Series alignée sur activities_df.index.
    """
    df = activities_df.copy()
    df["_date"] = pd.to_datetime(df["Date"], utc=True).dt.date

    if metric == "km":
        df["_load"] = df["Distance (km)"].fillna(0)
    elif metric == "trimp":
        df["_load"] = df["trimp"].fillna(0) if "trimp" in df.columns else 0
    else:
        raise ValueError(f"metric inconnu : {metric!r} — utiliser 'km' ou 'trimp'")

    # Série quotidienne (somme si plusieurs activités le même jour)
    daily = df.groupby("_date")["_load"].sum().reset_index()
    daily.columns = ["date", "load"]

    date_range = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    daily_full = (
        pd.DataFrame({"date": date_range.date})
        .merge(daily, on="date", how="left")
        .fillna(0)
    )

    λ_a = 2 / (7  + 1)   # 0.250
    λ_c = 2 / (28 + 1)   # ≈ 0.069

    ewma_a = np.empty(len(daily_full))
    ewma_c = np.empty(len(daily_full))
    loads  = daily_full["load"].values

    for i, ld in enumerate(loads):
        if i == 0:
            ewma_a[i] = ld
            ewma_c[i] = ld
        else:
            ewma_a[i] = λ_a * ld + (1 - λ_a) * ewma_a[i - 1]
            ewma_c[i] = λ_c * ld + (1 - λ_c) * ewma_c[i - 1]

    daily_full["acwr"] = np.where(ewma_c > 0, ewma_a / ewma_c, 0.0)
    acwr_map = dict(zip(daily_full["date"], daily_full["acwr"].round(3)))

    result = df["_date"].map(acwr_map)
    result.index = activities_df.index
    return result


# ── Volume hebdomadaire ────────────────────────────────────────────────────────

def compute_weekly_metrics(activities_df: pd.DataFrame) -> pd.DataFrame:
    """
    Pour chaque activité, calcule :
        weekly_km            : distance totale dans les 7 jours se terminant ce jour (inclus)
        weekly_elevation_m   : D+ total sur la même fenêtre
        load_variation_pct   : variation % vs les 7 jours précédents
                               alerte si > 30 % (règle des 10 %/semaine, seuil libéral)

    Retourne un DataFrame avec colonnes [weekly_km, weekly_elevation_m, load_variation_pct]
    aligné sur activities_df.index.
    """
    df = activities_df.copy()
    df["_dt"] = pd.to_datetime(df["Date"], utc=True)
    df["_km"]   = df["Distance (km)"].fillna(0)
    df["_elev"] = df["Dénivelé (m)"].fillna(0)

    results = []
    for idx, row in df.iterrows():
        end   = row["_dt"]
        start = end - timedelta(days=6)
        prev_end   = end - timedelta(days=7)
        prev_start = end - timedelta(days=13)

        cur_mask  = (df["_dt"] >= start)     & (df["_dt"] <= end)
        prev_mask = (df["_dt"] >= prev_start) & (df["_dt"] <= prev_end)

        w_km   = round(float(df.loc[cur_mask,  "_km"  ].sum()), 2)
        w_elev = round(float(df.loc[cur_mask,  "_elev"].sum()), 1)
        p_km   = float(df.loc[prev_mask, "_km"].sum())

        if p_km > 0:
            variation = round((w_km - p_km) / p_km * 100, 1)
        else:
            variation = None

        results.append({
            "weekly_km":          w_km,
            "weekly_elevation_m": w_elev,
            "load_variation_pct": variation,
        })

    out = pd.DataFrame(results, index=activities_df.index)
    return out


# ── Profil de vitesse athlète ─────────────────────────────────────────────────

def compute_athlete_speed_profile(activities_df: pd.DataFrame) -> dict:
    """
    Calcule les percentiles de vitesse de l'athlète depuis ses activités Run.
    Utilisé pour calibrer le seuil de détection de fractionné.

    Ne garde que les activités de type Run (pas Trail, pas récupération)
    avec distance > 3 km pour éviter les valeurs aberrantes.

    Retourne un dict :
      - p70_kmh                  : vitesse au 70e percentile (endurance poussée)
      - p75_kmh                  : vitesse au 75e percentile (proxy allure tempo/seuil)
      - p80_kmh                  : vitesse au 80e percentile (proxy fractionné moyen)
      - mean_kmh                 : vitesse moyenne toutes sorties Run retenues
      - computed_from_n_activities : nombre d'activités utilisées
      - last_updated             : horodatage ISO UTC
    """
    from datetime import timezone

    # Filtrer les runs plats de distance suffisante
    run_types = {"Run"}
    mask = (
        activities_df["Type"].isin(run_types)
        & (activities_df["Distance (km)"].fillna(0) > 3)
        & (activities_df["Temps (min)"].fillna(0) > 0)
    )
    runs = activities_df[mask].copy()

    if runs.empty:
        return {
            "p70_kmh": 0.0, "p75_kmh": 0.0, "p80_kmh": 0.0,
            "mean_kmh": 0.0, "computed_from_n_activities": 0,
            "last_updated": pd.Timestamp.now(tz=timezone.utc).isoformat(),
        }

    speeds = runs["Distance (km)"] / (runs["Temps (min)"] / 60.0)
    speeds = speeds.dropna()

    return {
        "p70_kmh":                   round(float(np.percentile(speeds, 70)), 2),
        "p75_kmh":                   round(float(np.percentile(speeds, 75)), 2),
        "p80_kmh":                   round(float(np.percentile(speeds, 80)), 2),
        "mean_kmh":                  round(float(speeds.mean()), 2),
        "computed_from_n_activities": int(len(speeds)),
        "last_updated":              pd.Timestamp.now(tz=timezone.utc).isoformat(),
    }


# ── Risque blessure ───────────────────────────────────────────────────────────

def compute_injury_risk(
    activities_df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Score de risque de blessure composite (0-100) par activité.

    Colonnes retournées :
      - injury_risk_score  : int 0-100
      - injury_risk_label  : 'faible' / 'modéré' / 'élevé' / 'critique'
      - flag_acwr          : bool, ACWR > seuil overload
      - flag_monotony      : bool, Training Monotony (Foster 1998) > 2.0
      - flag_load_spike    : bool, variation semaine > 30 %
      - flag_consecutive   : bool, >= 4 jours consécutifs sans repos

    Score composite (somme plafonnée à 100) :
      ACWR > 1.5           → +40 pts
      ACWR 1.3-1.5         → +20 pts
      Variation > 50 %     → +35 pts
      Variation > 30 %     → +20 pts  (remplacé si > 50 %)
      Monotonie > 2.0      → +20 pts
      ≥ 6 jours consécutifs → +25 pts
      ≥ 4 jours consécutifs → +15 pts (remplacé si ≥ 6)

    Training Monotony (Foster 1998) :
      mean(TRIMP_quotidien_7j) / std(TRIMP_quotidien_7j)
      > 2.0 = intensité trop homogène, risque de surmenage chronique.
    """
    cfg = (config or {}).get("injury_risk", {})
    acwr_overload    = cfg.get("acwr_overload", 1.5)
    acwr_high        = cfg.get("acwr_high", 1.3)
    spike_pct        = cfg.get("load_spike_pct", 30)
    spike_crit_pct   = cfg.get("load_spike_critical_pct", 50)
    monotony_thr     = cfg.get("monotony_threshold", 2.0)
    consec_high      = cfg.get("consecutive_days_high", 4)
    consec_crit      = cfg.get("consecutive_days_critical", 6)

    df = activities_df.copy()
    df["_date"] = pd.to_datetime(df["Date"], utc=True).dt.date
    df["_trimp"] = df["trimp"].fillna(0) if "trimp" in df.columns else 0.0
    df["_load_var"] = df["load_variation_pct"] if "load_variation_pct" in df.columns else np.nan
    df["_acwr"]     = df["acwr_km"] if "acwr_km" in df.columns else np.nan

    # ── Jours consécutifs sans repos (fenêtre glissante) ──────────────────────
    all_dates = sorted(df["_date"].unique())
    date_set  = set(all_dates)

    def _consec_before(d) -> int:
        """Nombre de jours consécutifs avec activité jusqu'à d inclus."""
        count = 0
        cur   = d
        while cur in date_set:
            count += 1
            cur = (pd.Timestamp(cur) - pd.Timedelta(days=1)).date()
        return count

    consec_map = {d: _consec_before(d) for d in all_dates}

    # ── Training Monotony sur 7 jours glissants ───────────────────────────────
    daily_trimp = df.groupby("_date")["_trimp"].sum().reset_index()
    daily_trimp.columns = ["date", "trimp"]
    date_range  = pd.date_range(
        pd.Timestamp(daily_trimp["date"].min()),
        pd.Timestamp(daily_trimp["date"].max()),
        freq="D",
    )
    daily_full = (
        pd.DataFrame({"date": date_range.date})
        .merge(daily_trimp, on="date", how="left")
        .fillna(0)
    )
    daily_full["date"] = pd.to_datetime(daily_full["date"])

    def _monotony(d) -> float:
        end   = pd.Timestamp(d)
        start = end - pd.Timedelta(days=6)
        window = daily_full[(daily_full["date"] >= start) & (daily_full["date"] <= end)]["trimp"]
        if len(window) < 3 or window.std() == 0:
            return 0.0
        return float(window.mean() / window.std())

    monotony_map = {d: _monotony(d) for d in daily_full["date"].dt.date}

    # ── Calcul par activité ───────────────────────────────────────────────────
    results = []
    for _, row in df.iterrows():
        d         = row["_date"]
        acwr      = row["_acwr"]
        load_var  = row["_load_var"]
        consec    = consec_map.get(d, 1)
        monotony  = monotony_map.get(d, 0.0)

        # Flags
        flag_acwr       = bool(not pd.isna(acwr) and acwr > acwr_overload)
        flag_monotony   = bool(monotony > monotony_thr)
        flag_load_spike = bool(not pd.isna(load_var) and abs(load_var) > spike_pct)
        flag_consecutive = bool(consec >= consec_high)

        # Score
        score = 0
        if not pd.isna(acwr):
            if acwr > acwr_overload:
                score += 40
            elif acwr > acwr_high:
                score += 20
        if not pd.isna(load_var):
            if abs(load_var) > spike_crit_pct:
                score += 35
            elif abs(load_var) > spike_pct:
                score += 20
        if monotony > monotony_thr:
            score += 20
        if consec >= consec_crit:
            score += 25
        elif consec >= consec_high:
            score += 15

        score = min(score, 100)

        if score >= 75:
            label = "critique"
        elif score >= 50:
            label = "élevé"
        elif score >= 25:
            label = "modéré"
        else:
            label = "faible"

        results.append({
            "injury_risk_score":  score,
            "injury_risk_label":  label,
            "flag_acwr":          flag_acwr,
            "flag_monotony":      flag_monotony,
            "flag_load_spike":    flag_load_spike,
            "flag_consecutive":   flag_consecutive,
        })

    return pd.DataFrame(results, index=activities_df.index)


# ── Progression long terme ────────────────────────────────────────────────────

def compute_progression_metrics(
    activities_df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Métriques de progression sur fenêtres glissantes.

    Colonnes retournées :
      - pace_trend_28d  : variation allure moy. sur 28j (s/km, négatif = progrès)
      - ef_trend_28d    : variation EF moy. sur 28j (positif = progrès)
      - vo2max_estimate : estimation VO2max (Daniels simplifié), NaN si non calculable

    VO2max (Daniels simplifié, applicable allure + FC) :
      %VO2max = %FC_max² × 0.8 + %FC_max × 0.2
      VO2max  = speed_m_min / (0.000104 × speed² + 0.182258 × speed - 4.6) / %VO2max
    Calculé uniquement si FC disponible et session_type ∈ endurance fondamentale,
    tempo / seuil, sortie longue.
    """
    hr_max = (config or {}).get("athlete", {}).get("hr_max", 195)
    _VO2_TYPES = {"endurance fondamentale", "tempo / seuil", "sortie longue"}

    df = activities_df.copy()
    df["_dt"]    = pd.to_datetime(df["Date"], utc=True)
    df["_trimp"] = df["trimp"].fillna(0) if "trimp" in df.columns else 0.0
    df["_pace"]  = df["Allure (min/km)"] * 60 if "Allure (min/km)" in df.columns else np.nan  # → s/km
    df["_ef"]    = df["efficiency_factor"] if "efficiency_factor" in df.columns else np.nan

    # ── VO2max par activité ───────────────────────────────────────────────────
    vo2max_vals = []
    for _, row in df.iterrows():
        stype    = str(row.get("session_type", ""))
        dist_km  = float(row.get("Distance (km)", 0) or 0)
        dur_min  = float(row.get("Temps (min)", 0) or 0)
        hr_raw   = row.get("Fréquence cardiaque (bpm)")
        hr_mean  = float(hr_raw) if hr_raw and not (isinstance(hr_raw, float) and np.isnan(hr_raw)) else None

        if stype not in _VO2_TYPES or hr_mean is None or dist_km <= 0 or dur_min <= 0:
            vo2max_vals.append(float("nan"))
            continue

        speed_kmh    = dist_km / (dur_min / 60.0)
        speed_m_min  = speed_kmh * 1000.0 / 60.0
        pct_fc_max   = hr_mean / hr_max
        pct_vo2max   = pct_fc_max ** 2 * 0.8 + pct_fc_max * 0.2
        # VO2 au rythme actuel (formule Daniels, v en m/min → mL/kg/min)
        vo2_at_pace = 0.000104 * speed_m_min ** 2 + 0.182258 * speed_m_min - 4.6

        if vo2_at_pace <= 0 or pct_vo2max <= 0:
            vo2max_vals.append(float("nan"))
            continue

        vo2max = vo2_at_pace / pct_vo2max
        vo2max_vals.append(round(float(np.clip(vo2max, 20, 90)), 1))

    df["_vo2max"] = vo2max_vals

    # ── Calcul par activité (fenêtres glissantes) ─────────────────────────────
    results = []
    for idx, row in df.iterrows():
        end28 = row["_dt"]
        st28  = end28 - pd.Timedelta(days=27)
        st42  = end28 - pd.Timedelta(days=41)
        st7   = end28 - pd.Timedelta(days=6)

        w28 = df[(df["_dt"] >= st28) & (df["_dt"] <= end28)]
        w42 = df[(df["_dt"] >= st42) & (df["_dt"] <= end28)]
        w7  = df[(df["_dt"] >= st7)  & (df["_dt"] <= end28)]

        # Pace trend : différence entre allure moy. de la 2e et 1e moitié de la fenêtre 28j
        pace_trend = float("nan")
        pace_vals  = w28.dropna(subset=["_pace"])
        if len(pace_vals) >= 4:
            mid  = pace_vals["_dt"].median()
            p1   = pace_vals[pace_vals["_dt"] <= mid]["_pace"].mean()
            p2   = pace_vals[pace_vals["_dt"] >  mid]["_pace"].mean()
            if not (np.isnan(p1) or np.isnan(p2)):
                pace_trend = round(float(p2 - p1), 1)  # négatif = progrès

        # EF trend
        ef_trend = float("nan")
        ef_vals  = w28.dropna(subset=["_ef"])
        if len(ef_vals) >= 4:
            mid  = ef_vals["_dt"].median()
            e1   = ef_vals[ef_vals["_dt"] <= mid]["_ef"].mean()
            e2   = ef_vals[ef_vals["_dt"] >  mid]["_ef"].mean()
            if not (np.isnan(e1) or np.isnan(e2)):
                ef_trend = round(float(e2 - e1), 5)  # positif = progrès

        results.append({
            "pace_trend_28d":  pace_trend,
            "ef_trend_28d":    ef_trend,
            "vo2max_estimate": row["_vo2max"],
        })

    return pd.DataFrame(results, index=activities_df.index)


# ── Fitness / Fatigue / Form (Banister EWMA) ─────────────────────────────────

def compute_fitness_fatigue(
    activities_df: pd.DataFrame,
    ctl_days: int = 42,
    atl_days: int = 7,
) -> pd.DataFrame:
    """
    Modèle Banister impulse-response via EWMA (Banister 1991, Calvert 1976).

    CTL (Chronic Training Load)  = EWMA du TRIMP sur ctl_days (42j par défaut)
    ATL (Acute Training Load)    = EWMA du TRIMP sur atl_days (7j par défaut)
    TSB (Training Stress Balance) = CTL - ATL

    Formule EWMA :
        λ = 2 / (N + 1)
        EMA[i] = λ × load[i] + (1 - λ) × EMA[i-1]

    La série est construite sur un calendrier quotidien (jours sans séance = 0)
    pour que le decay fonctionne correctement.

    Retourne un DataFrame avec colonnes [ctl, atl, tsb] aligné sur activities_df.index.
    """
    df = activities_df.copy()
    df["_date"] = pd.to_datetime(df["Date"], utc=True).dt.date
    df["_trimp"] = df["trimp"].fillna(0) if "trimp" in df.columns else 0.0

    # Série quotidienne
    daily = df.groupby("_date")["_trimp"].sum().reset_index()
    daily.columns = ["date", "trimp"]

    date_range = pd.date_range(
        pd.Timestamp(daily["date"].min()),
        pd.Timestamp(daily["date"].max()),
        freq="D",
    )
    daily_full = (
        pd.DataFrame({"date": date_range.date})
        .merge(daily, on="date", how="left")
        .fillna(0)
    )

    λ_ctl = 2 / (ctl_days + 1)
    λ_atl = 2 / (atl_days + 1)

    loads = daily_full["trimp"].values
    n = len(loads)
    ctl = np.empty(n)
    atl = np.empty(n)

    for i, ld in enumerate(loads):
        if i == 0:
            ctl[i] = ld
            atl[i] = ld
        else:
            ctl[i] = λ_ctl * ld + (1 - λ_ctl) * ctl[i - 1]
            atl[i] = λ_atl * ld + (1 - λ_atl) * atl[i - 1]

    daily_full["ctl"] = np.round(ctl, 1)
    daily_full["atl"] = np.round(atl, 1)
    daily_full["tsb"] = np.round(ctl - atl, 1)

    ctl_map = dict(zip(daily_full["date"], daily_full["ctl"]))
    atl_map = dict(zip(daily_full["date"], daily_full["atl"]))
    tsb_map = dict(zip(daily_full["date"], daily_full["tsb"]))

    result = pd.DataFrame({
        "ctl": df["_date"].map(ctl_map),
        "atl": df["_date"].map(atl_map),
        "tsb": df["_date"].map(tsb_map),
    }, index=activities_df.index)
    return result


# ── Monotony & Strain (Foster 1998) ─────────────────────────────────────────

def compute_monotony_strain(activities_df: pd.DataFrame) -> pd.DataFrame:
    """
    Training Monotony & Strain (Foster 1998).

    Monotony = mean(TRIMP_quotidien_7j) / std(TRIMP_quotidien_7j)
    Strain   = Monotony × sum(TRIMP_quotidien_7j)

    Interprétation :
        Monotony > 2.0 : intensité trop homogène, risque de surmenage
        Strain > 4000  : charge globale élevée, nécessite récupération

    Retourne un DataFrame avec colonnes [monotony, strain] aligné sur activities_df.index.
    """
    df = activities_df.copy()
    df["_date"] = pd.to_datetime(df["Date"], utc=True).dt.date
    df["_trimp"] = df["trimp"].fillna(0) if "trimp" in df.columns else 0.0

    # Série quotidienne complète
    daily = df.groupby("_date")["_trimp"].sum().reset_index()
    daily.columns = ["date", "trimp"]

    date_range = pd.date_range(
        pd.Timestamp(daily["date"].min()),
        pd.Timestamp(daily["date"].max()),
        freq="D",
    )
    daily_full = (
        pd.DataFrame({"date": date_range.date})
        .merge(daily, on="date", how="left")
        .fillna(0)
    )
    daily_full["date"] = pd.to_datetime(daily_full["date"])

    def _ms(d):
        end = pd.Timestamp(d)
        start = end - pd.Timedelta(days=6)
        window = daily_full[(daily_full["date"] >= start) & (daily_full["date"] <= end)]["trimp"]
        if len(window) < 3 or window.std() == 0:
            return 0.0, 0.0
        m = float(window.mean() / window.std())
        s = float(m * window.sum())
        return round(m, 2), round(s, 1)

    mono_map = {}
    strain_map = {}
    for d in daily_full["date"].dt.date:
        m, s = _ms(d)
        mono_map[d] = m
        strain_map[d] = s

    result = pd.DataFrame({
        "monotony": df["_date"].map(mono_map),
        "strain":   df["_date"].map(strain_map),
    }, index=activities_df.index)
    return result


# ── Personal Records (sliding window sur GPS) ───────────────────────────────

_PR_DISTANCES_RUN = {
    "400m":  400,
    "1km":   1000,
    "1mi":   1609,
    "5km":   5000,
    "10km":  10000,
    "semi":  21097,
    "marathon": 42195,
}

_PR_DISTANCES_VELO = {
    "1km":   1000,
    "5km":   5000,
    "10km":  10000,
    "20km":  20000,
    "50km":  50000,
    "100km": 100000,
}

# Keep backward compat alias
_PR_DISTANCES = _PR_DISTANCES_RUN


def compute_personal_records(
    gps_dir: str,
    garmin_streams_dir: str,
    activities_df: pd.DataFrame | None = None,
    sport_filter: str = "run",
) -> dict:
    """
    Records personnels via sliding window sur les traces GPS.

    Pour chaque distance cible, parcourt tous les fichiers GPS et cherche
    le meilleur temps sur une fenêtre glissante :
        pour chaque i, trouver le plus petit j tel que dist_cum[j] - dist_cum[i] >= target_dist
        temps = time_s[j] - time_s[i]
        garder le min global.

    sport_filter : "run" ou "velo" — filtre les activités et adapte les distances cibles.

    Retourne un dict { "400m": { time_s, pace, date, activity_id, source }, ... }
    """
    from gps_metrics import compute_distances
    from sport_mapping import get_sport

    pr_distances = _PR_DISTANCES_VELO if sport_filter == "velo" else _PR_DISTANCES_RUN
    # Vitesse max plausible : 22 km/h running, 70 km/h vélo
    max_speed_kmh = 70.0 if sport_filter == "velo" else 22.0

    # Map activity dates if available
    date_map = {}
    id_map = {}  # garmin_id → strava_id
    if activities_df is not None:
        for _, row in activities_df.iterrows():
            act_id = str(int(row["ID"]))
            date_map[act_id] = pd.to_datetime(row["Date"]).isoformat()

    # Charger la garmin map pour associer garmin_id → strava_id
    garmin_map_path = os.path.join(os.path.dirname(garmin_streams_dir), "strava_garmin_map.json")
    strava_garmin_map = {}
    if os.path.exists(garmin_map_path):
        with open(garmin_map_path, encoding="utf-8") as f:
            strava_garmin_map = json.load(f)
        for sid, gid in strava_garmin_map.items():
            id_map[str(gid)] = sid

    # Filtrer les activités par sport
    sport_ids = set()
    if activities_df is not None:
        sport_mask = activities_df["Type"].apply(lambda t: get_sport(str(t)) == sport_filter)
        sport_ids = set(activities_df.loc[sport_mask, "ID"].astype(int).astype(str))

    # Collecter tous les fichiers GPS
    gps_files = []

    # Fichiers data/gps/ — ne garder que les running
    # Noms possibles : {strava_id}.json (matched Garmin) ou strava_{strava_id}.json (Strava fallback)
    if os.path.isdir(gps_dir):
        for fname in os.listdir(gps_dir):
            if fname.endswith(".json"):
                stem = fname.replace(".json", "")
                # Extraire le strava_id réel (supprime le prefix "strava_" s'il existe)
                act_id = stem.replace("strava_", "") if stem.startswith("strava_") else stem
                if sport_ids and act_id not in sport_ids:
                    continue
                gps_files.append((os.path.join(gps_dir, fname), act_id, "gps"))

    # Fichiers garmin/streams/ — ne garder que ceux mappés à des activités running
    if os.path.isdir(garmin_streams_dir):
        for fname in os.listdir(garmin_streams_dir):
            if fname.endswith(".json"):
                gid = fname.replace(".json", "")
                strava_id = id_map.get(gid)
                if sport_ids and strava_id and strava_id not in sport_ids:
                    continue
                if sport_ids and not strava_id:
                    continue
                gps_files.append((os.path.join(garmin_streams_dir, fname), gid, "garmin"))

    records = {dist_name: None for dist_name in pr_distances}

    for fpath, file_id, source in gps_files:
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        points = data.get("points", data) if isinstance(data, dict) else data
        if not isinstance(points, list) or len(points) < 2:
            continue

        # Vérifier qu'on a time_s
        if not any(p.get("time_s") is not None for p in points):
            continue

        dists = compute_distances(points)
        dist_cum = np.cumsum(dists)
        times = np.array([p.get("time_s", np.nan) for p in points], dtype=float)

        # Interpoler les time_s manquants
        valid_mask = ~np.isnan(times)
        if valid_mask.sum() < 2:
            continue
        times = np.interp(np.arange(len(times)),
                          np.where(valid_mask)[0],
                          times[valid_mask])

        total_dist = dist_cum[-1]

        # Résoudre l'activity_id pour les dates
        if source == "garmin":
            strava_id = id_map.get(file_id)
            act_id = strava_id or file_id
        else:
            act_id = file_id

        act_date = date_map.get(str(act_id), "")

        for dist_name, target_m in pr_distances.items():
            if total_dist < target_m:
                continue

            # Sliding window
            j = 0
            best_time = None
            for i in range(len(dist_cum)):
                while j < len(dist_cum) and (dist_cum[j] - dist_cum[i]) < target_m:
                    j += 1
                if j >= len(dist_cum):
                    break
                elapsed = times[j] - times[i]
                if elapsed > 0 and (best_time is None or elapsed < best_time):
                    best_time = elapsed

            if best_time is not None:
                # Sanity check: speed must be plausible for the sport
                speed_kmh = (target_m / 1000) / (best_time / 3600)
                if speed_kmh > max_speed_kmh:
                    continue

                current = records[dist_name]
                if current is None or best_time < current["time_s"]:
                    pace_s_km = best_time / (target_m / 1000)
                    pace_min = int(pace_s_km // 60)
                    pace_sec = int(pace_s_km % 60)
                    records[dist_name] = {
                        "time_s": round(best_time, 1),
                        "pace": f"{pace_min}:{pace_sec:02d}",
                        "date": act_date,
                        "activity_id": act_id,
                    }

    # Retirer les None (distances non couvertes)
    return {k: v for k, v in records.items() if v is not None}


# ── Gradient Adjusted Pace ───────────────────────────────────────────────────

# Lookup table empirique Strava : (gradient_pct, facteur).
# Le facteur multiplie l'allure réelle (ou divise la vitesse) pour obtenir
# l'équivalent plat.  Interpolation linéaire entre les points.
# Source : Robb D. (2017), Strava Engineering — ajusté sur ~6M runs.
_GAP_TABLE = [
    (-50, 2.40),
    (-30, 1.10),
    (-20, 0.96),
    (-15, 0.94),
    (-10, 0.92),
    (-7,  0.93),
    (-5,  0.95),
    (-3,  0.97),
    ( 0,  1.00),
    ( 3,  1.07),
    ( 5,  1.15),
    ( 7,  1.23),
    (10,  1.33),
    (15,  1.55),
    (20,  1.75),
    (30,  2.20),
    (50,  3.00),
]

_GAP_GRADS  = np.array([g for g, _ in _GAP_TABLE], dtype=float)
_GAP_FACTORS = np.array([f for _, f in _GAP_TABLE], dtype=float)


def _gap_factor(gradient_pct: float) -> float:
    """Facteur GAP par interpolation linéaire sur _GAP_TABLE, clippé à [-50, 50]."""
    g = np.clip(gradient_pct, -50.0, 50.0)
    return float(np.interp(g, _GAP_GRADS, _GAP_FACTORS))


def compute_gap(points: list[dict]) -> dict:
    """
    Gradient Adjusted Pace — modèle empirique Strava (Robb 2017).

    Remplace la formule linéaire Minetti (0.033 × gradient) par une lookup
    table interpolée ajustée sur ~6 millions de runs avec FC et élévation.
    Corrige la sous-estimation du bénéfice des descentes douces.

    Formule :
        gradient_pct = (alt[i+1] - alt[i]) / distance_segment × 100
        facteur      = interp(_GAP_TABLE, gradient_pct)
        GAP_speed    = speed / facteur

    Cas limites :
    - distance_segment < 1 m → gradient = 0 (évite division par zéro)
    - altitude None → interpolation linéaire depuis les voisins
    - gradient clippé à [-50%, +50%] avant lookup (spikes GPS)

    Référence : Strava Engineering, Robb D. (2017). An Improved GAP Model.

    Retourne {gap_avg_kmh, gap_avg_pace, gap_speed_array, gap_pace_array,
              distance_m, reference}.
    """
    from gps_metrics import compute_distances, compute_speed

    if len(points) < 2:
        return {"error": "insufficient_points"}

    # Vérifier qu'on a de l'altitude
    alts = [p.get("altitude_m") for p in points]
    if all(a is None for a in alts):
        return {"error": "no_altitude"}

    # Interpoler les altitudes manquantes
    alt_series = pd.Series([float(a) if a is not None else float("nan") for a in alts])
    alt_interp = alt_series.interpolate(method="linear", limit_direction="both").values

    dists = compute_distances(points)
    speeds = compute_speed(points, smooth=True)  # km/h
    dist_cum = np.cumsum(dists)

    gap_speeds = np.full(len(points), np.nan)
    gap_speeds[0] = speeds[0]

    for i in range(1, len(points)):
        d = dists[i]
        if d < 1.0:
            gap_speeds[i] = speeds[i]
        else:
            gradient_pct = (alt_interp[i] - alt_interp[i - 1]) / d * 100
            facteur = _gap_factor(gradient_pct)
            gap_speeds[i] = speeds[i] / facteur

    # Allure GAP en s/km
    with np.errstate(divide="ignore", invalid="ignore"):
        gap_pace = np.where(gap_speeds > 0, 3600.0 / gap_speeds, np.nan)
    gap_pace = np.where(gap_pace > 1200, np.nan, gap_pace)

    moving = gap_speeds[np.isfinite(gap_speeds) & (gap_speeds > 0)]
    avg_gap_kmh = float(moving.mean()) if len(moving) > 0 else 0.0

    pace_finite = gap_pace[np.isfinite(gap_pace)]
    avg_pace_s = float(pace_finite.mean()) if len(pace_finite) > 0 else float("nan")

    if not np.isnan(avg_pace_s):
        pm = int(avg_pace_s // 60)
        ps = int(avg_pace_s % 60)
        avg_pace_str = f"{pm}:{ps:02d}"
    else:
        avg_pace_str = "—"

    return {
        "gap_avg_kmh": round(avg_gap_kmh, 2),
        "gap_avg_pace": avg_pace_str,
        "gap_speed_array": [float(v) if np.isfinite(v) else None for v in gap_speeds],
        "gap_pace_array": [float(v) if np.isfinite(v) else None for v in gap_pace],
        "distance_m": dist_cum.tolist(),
        "reference": "Modèle empirique Strava Engineering (Robb D., 2017) — ajusté sur ~6M runs avec FC et élévation. Corrige Minetti 2002 sur les descentes. https://medium.com/strava-engineering/an-improved-gap-model-8b07ae8886c3",
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def acwr_label(acwr: float) -> str:
    """Étiquette textuelle de l'ACWR."""
    if acwr < 0.8:
        return "sous-charge"
    if acwr <= 1.3:
        return "zone optimale"
    if acwr <= 1.5:
        return "charge élevée"
    return "surcharge — risque blessure"
