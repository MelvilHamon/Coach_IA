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
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from api import storage

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

    # Filtrer les runs plats de distance suffisante.
    # Exclut aussi les activités étiquetées "Run" mais à allure < 4 km/h
    # (= > 15 min/km) qui sont en réalité de la marche, des pauses techniques
    # ou des erreurs GPS — sinon elles tirent les percentiles vers le bas et
    # faussent à la fois la détection fractionné et les courbes de progression.
    run_types = {"Run"}
    distances = activities_df["Distance (km)"].fillna(0)
    durations = activities_df["Temps (min)"].fillna(0)
    speeds_all = distances / (durations / 60.0).replace(0, pd.NA)
    mask = (
        activities_df["Type"].isin(run_types)
        & (distances > 3)
        & (durations > 0)
        & (speeds_all >= 4.0)  # exclut marche & pauses anormales
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


# ── Profil FC athlète (auto-détection depuis les streams) ────────────────────

def compute_athlete_hr_profile(activities_df: pd.DataFrame, streams_dir: str) -> dict:
    """
    Estime hr_max de l'athlète à partir des streams FC.

    Pour chaque activité avec stream valide :
      - hr_peak = 99ᵉ percentile de FC (robuste aux spikes capteur isolés)

    hr_max_observed = max des hr_peak (sur activités running/velo).

    Filtres anti-artefact :
      - FC dans [50, 220] bpm (hors plage = capteur pété)
      - Activité de ≥ 10 min de données FC valides
      - hr_peak doit être sustained : on prend le 99ᵉ pctile, pas le max brut
      - hr_max_observed borné à [150, 215] pour éviter les estimés aberrants

    Note : hr_rest n'est PAS estimé ici. La FC la plus basse observée DURANT
    une activité reflète la phase d'échauffement (FC 70-90 bpm typiquement),
    pas la vraie FC au repos. Une estimation fiable de hr_rest demande des
    mesures hors activité (ex. Garmin Body Battery) indisponibles ici.

    Retourne un dict :
      - hr_max_observed       : FC max robuste observée (int ou None)
      - computed_from_n_activities : nombre d'activités exploitées
      - last_updated          : horodatage ISO UTC

    Si aucun stream exploitable → valeurs None et n_activities=0.
    """
    from datetime import timezone
    import os

    result = {
        "hr_max_observed":            None,
        "computed_from_n_activities": 0,
        "last_updated":               pd.Timestamp.now(tz=timezone.utc).isoformat(),
    }

    if not os.path.isdir(streams_dir) or activities_df.empty:
        return result

    # On ne considère que les activités Run/Ride/Virtual (cardio endurance)
    # Exclure randos (FC rarement élevée) et workouts statiques (FC peu fiable)
    cardio_types = {"Run", "TrailRun", "Ride", "VirtualRun", "VirtualRide"}
    cardio = activities_df[activities_df["Type"].isin(cardio_types)]
    if cardio.empty:
        return result

    peaks = []
    n_used = 0

    for _, row in cardio.iterrows():
        try:
            act_id = int(row["ID"])
        except (KeyError, ValueError, TypeError):
            continue

        stream_path = os.path.join(streams_dir, f"{act_id}.csv")
        if not os.path.exists(stream_path):
            continue

        try:
            stream = pd.read_csv(stream_path, usecols=["time_s", "bpm"])
        except (ValueError, FileNotFoundError):
            continue

        bpm = stream["bpm"].dropna()
        bpm = bpm[(bpm >= 50) & (bpm <= 220)]
        if len(bpm) < 600:  # < 10 min de FC valide → activité trop courte
            continue

        peaks.append(float(np.percentile(bpm, 99)))
        n_used += 1

    if not peaks:
        return result

    # Borner pour éviter les estimés aberrants (capteur pété qui n'a pas été
    # filtré, ou athlète qui ne pousse jamais → sous-estimé à <150).
    hr_max_observed = int(round(max(150, min(215, max(peaks)))))

    result.update({
        "hr_max_observed":            hr_max_observed,
        "computed_from_n_activities": n_used,
    })
    return result


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
      - vo2max_estimate : estimation VO2max, NaN si non calculable

    VO2max Course (Daniels simplifié, applicable allure + FC) :
      %VO2max = %FC_max² × 0.8 + %FC_max × 0.2
      VO2max  = speed_m_min / (0.000104 × speed² + 0.182258 × speed - 4.6) / %VO2max
    Calculé uniquement si FC disponible et session_type ∈ endurance fondamentale,
    tempo / seuil, sortie longue.

    VO2max Vélo (ACSM metabolic equation) :
      VO2 = (power_w / weight_kg) × 10.8 + 7   (mL/kg/min)
      VO2max = VO2 / %VO2max
    Calculé uniquement si puissance moyenne et poids disponibles.
    """
    athlete = (config or {}).get("athlete", {})
    hr_max = athlete.get("hr_max", 195)
    weight_kg = athlete.get("weight_kg")
    _VO2_RUN_TYPES = {"endurance fondamentale", "tempo / seuil", "sortie longue"}
    _VO2_VELO_TYPES = {"endurance vélo", "sortie longue vélo", "tempo vélo"}

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
        sport    = str(row.get("sport", ""))
        avg_pow  = row.get("avg_power_w")
        has_power = avg_pow is not None and not (isinstance(avg_pow, float) and np.isnan(avg_pow)) and avg_pow > 0

        # ── VO2max Course (Daniels) ──
        if stype in _VO2_RUN_TYPES and hr_mean and dist_km > 0 and dur_min > 0:
            speed_kmh    = dist_km / (dur_min / 60.0)
            speed_m_min  = speed_kmh * 1000.0 / 60.0
            pct_fc_max   = hr_mean / hr_max
            pct_vo2max   = pct_fc_max ** 2 * 0.8 + pct_fc_max * 0.2
            vo2_at_pace  = 0.000104 * speed_m_min ** 2 + 0.182258 * speed_m_min - 4.6

            if vo2_at_pace > 0 and pct_vo2max > 0:
                vo2max = vo2_at_pace / pct_vo2max
                vo2max_vals.append(round(float(np.clip(vo2max, 20, 90)), 1))
                continue

        # ── VO2max Vélo (ACSM: power/weight) ──
        if stype in _VO2_VELO_TYPES and has_power and weight_kg and weight_kg > 0 and hr_mean:
            pct_fc_max = hr_mean / hr_max
            pct_vo2max = pct_fc_max ** 2 * 0.8 + pct_fc_max * 0.2
            # ACSM metabolic equation for cycling (mL/kg/min)
            vo2_at_power = (float(avg_pow) / weight_kg) * 10.8 + 7.0
            if pct_vo2max > 0:
                vo2max = vo2_at_power / pct_vo2max
                vo2max_vals.append(round(float(np.clip(vo2max, 20, 100)), 1))
                continue

        vo2max_vals.append(float("nan"))

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


def _pr_compute_one_file(args):
    """
    Worker pour ThreadPoolExecutor : lit un fichier GPS et calcule ses meilleurs
    temps sur les distances cibles. Renvoie (key, {act_id, distances{...}}) ou None.
    """
    fpath, file_id, source, fname, pr_distances, max_speed_kmh, id_map = args
    try:
        from gps_metrics import compute_distances
        data = storage.read_json(fpath)
    except Exception:
        return None
    if data is None:
        return None
    points = data.get("points", data) if isinstance(data, dict) else data
    if not isinstance(points, list) or len(points) < 2:
        return None
    if not any(p.get("time_s") is not None for p in points):
        return None
    try:
        dists = compute_distances(points)
    except Exception:
        return None
    dist_cum = np.cumsum(dists)
    times = np.array([p.get("time_s", np.nan) for p in points], dtype=float)
    valid_mask = ~np.isnan(times)
    if valid_mask.sum() < 2:
        return None
    times = np.interp(np.arange(len(times)),
                      np.where(valid_mask)[0],
                      times[valid_mask])
    total_dist = float(dist_cum[-1])

    if source == "garmin":
        strava_id = id_map.get(file_id)
        act_id = strava_id or file_id
    else:
        act_id = file_id

    per_dist: dict = {}
    for dist_name, target_m in pr_distances.items():
        if total_dist < target_m:
            continue
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
        if best_time is None:
            continue
        speed_kmh = (target_m / 1000) / (best_time / 3600)
        if speed_kmh > max_speed_kmh:
            continue
        per_dist[dist_name] = round(float(best_time), 1)

    return (f"{source}:{fname}", {"act_id": act_id, "distances": per_dist})


def compute_personal_records(
    gps_dir: str,
    garmin_streams_dir: str,
    activities_df: pd.DataFrame | None = None,
    sport_filter: str = "run",
    cache_path: str | None = None,
    max_workers: int = 16,
) -> dict:
    """
    Records personnels via sliding window sur les traces GPS — incrémental + parallèle.

    Cache par activité dans `pr_cache_{sport_filter}.json` à côté de `personal_records.json` :
    on ne recalcule que les fichiers GPS absents du cache, on lit R2 en parallèle.

    sport_filter : "run" ou "velo" — filtre les activités et adapte les distances cibles.
    cache_path   : surcharge l'emplacement du cache (sinon dérivé de gps_dir).
    max_workers  : taille du pool de threads pour les GETs R2 parallèles.

    Retourne un dict { "400m": { time_s, pace, date, activity_id }, ... }.
    """
    from concurrent.futures import ThreadPoolExecutor
    from sport_mapping import get_sport

    pr_distances = _PR_DISTANCES_VELO if sport_filter == "velo" else _PR_DISTANCES_RUN
    # Vitesse max plausible : 22 km/h running, 70 km/h vélo
    max_speed_kmh = 70.0 if sport_filter == "velo" else 22.0

    if cache_path is None:
        parent = os.path.dirname(os.path.abspath(gps_dir.rstrip(os.sep) or gps_dir))
        cache_path = os.path.join(parent, f"pr_cache_{sport_filter}.json")

    # ── Map dates / IDs activité ─────────────────────────────────────────────
    date_map: dict = {}
    id_map: dict = {}
    sport_ids: set = set()
    if activities_df is not None and not activities_df.empty:
        for _, row in activities_df.iterrows():
            act_id = str(int(row["ID"]))
            date_map[act_id] = pd.to_datetime(row["Date"]).isoformat()
        sport_mask = activities_df["Type"].apply(lambda t: get_sport(str(t)) == sport_filter)
        sport_ids = set(activities_df.loc[sport_mask, "ID"].astype(int).astype(str))

    garmin_map_path = os.path.join(os.path.dirname(garmin_streams_dir), "strava_garmin_map.json")
    if os.path.exists(garmin_map_path):
        try:
            with open(garmin_map_path, encoding="utf-8") as f:
                strava_garmin_map = json.load(f)
            for sid, gid in strava_garmin_map.items():
                id_map[str(gid)] = sid
        except (json.JSONDecodeError, OSError):
            pass

    # ── Charger cache existant ───────────────────────────────────────────────
    cache: dict = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            cache = {}

    # ── Lister les fichiers GPS pertinents ───────────────────────────────────
    gps_files: list = []  # (full_path, file_id, source, fname)

    if storage.isdir(gps_dir):
        for fname in storage.listdir(gps_dir):
            if not fname.endswith(".json"):
                continue
            stem = fname.replace(".json", "")
            act_id = stem.replace("strava_", "") if stem.startswith("strava_") else stem
            if sport_ids and act_id not in sport_ids:
                continue
            gps_files.append((os.path.join(gps_dir, fname), act_id, "gps", fname))

    if storage.isdir(garmin_streams_dir):
        for fname in storage.listdir(garmin_streams_dir):
            if not fname.endswith(".json"):
                continue
            gid = fname.replace(".json", "")
            strava_id = id_map.get(gid)
            if sport_ids and strava_id and strava_id not in sport_ids:
                continue
            if sport_ids and not strava_id:
                continue
            gps_files.append((os.path.join(garmin_streams_dir, fname), gid, "garmin", fname))

    # ── Diff cache / fichiers présents ───────────────────────────────────────
    current_keys = {f"{src}:{fname}" for (_, _, src, fname) in gps_files}
    stale_keys = [k for k in list(cache.keys()) if k not in current_keys]
    for k in stale_keys:
        cache.pop(k, None)

    new_files = [
        (p, fid, src, fname, pr_distances, max_speed_kmh, id_map)
        for (p, fid, src, fname) in gps_files
        if f"{src}:{fname}" not in cache
    ]

    # ── Lecture parallèle des nouveaux fichiers ──────────────────────────────
    if new_files:
        print(f"  [PR {sport_filter}] {len(new_files)} nouveaux GPS à analyser "
              f"(cache: {len(cache)}, stale purgés: {len(stale_keys)})")
        workers = max(1, min(max_workers, len(new_files)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_pr_compute_one_file, new_files):
                if res is None:
                    continue
                key, entry = res
                cache[key] = entry
    elif stale_keys:
        print(f"  [PR {sport_filter}] cache à jour ({len(cache)} entrées, "
              f"{len(stale_keys)} stale purgés)")
    else:
        print(f"  [PR {sport_filter}] cache à jour ({len(cache)} entrées)")

    # ── Persister cache ──────────────────────────────────────────────────────
    if new_files or stale_keys:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except OSError:
            pass

    # ── Aggrégation : meilleur temps global par distance ─────────────────────
    records: dict = {}
    for entry in cache.values():
        act_id = entry.get("act_id")
        for dist_name, time_s in (entry.get("distances") or {}).items():
            if time_s is None:
                continue
            target_m = pr_distances.get(dist_name)
            if target_m is None:
                continue
            current = records.get(dist_name)
            if current is None or time_s < current["time_s"]:
                pace_s_km = time_s / (target_m / 1000)
                pace_min = int(pace_s_km // 60)
                pace_sec = int(pace_s_km % 60)
                records[dist_name] = {
                    "time_s": round(float(time_s), 1),
                    "pace": f"{pace_min}:{pace_sec:02d}",
                    "date": date_map.get(str(act_id), ""),
                    "activity_id": act_id,
                }

    return records


# ── Personal Power Records (vélo) ───────────────────────────────────────────

_PR_POWER_DURATIONS = {
    "5s":    5,
    "1min":  60,
    "5min":  300,
    "10min": 600,
    "20min": 1200,
    "30min": 1800,
    "60min": 3600,
}


def _power_compute_one_file(args):
    """Worker : meilleur pic de puissance moyenne sur chaque fenêtre cible."""
    fpath, act_id, durations = args
    try:
        df = storage.read_csv(fpath)
    except Exception:
        return None
    if df is None or "power_w" not in df.columns:
        return None
    pw = pd.to_numeric(df["power_w"], errors="coerce").fillna(0).to_numpy(dtype=float)
    if len(pw) < 5 or float(pw.max()) <= 0:
        return None
    # Sampling : on suppose 1 Hz (cohérent avec time_s entier croissant).
    # Si time_s présent et non-régulier, on ré-échantillonne en repère 1 s.
    if "time_s" in df.columns:
        ts = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float)
        if np.isfinite(ts).sum() >= 2:
            t0 = int(np.nanmin(ts))
            t1 = int(np.nanmax(ts))
            if t1 - t0 >= 5 and t1 - t0 < 24 * 3600:
                grid = np.arange(t0, t1 + 1, dtype=float)
                mask = np.isfinite(ts)
                pw = np.interp(grid, ts[mask], pw[mask], left=0.0, right=0.0)
    n = len(pw)
    cum = np.concatenate(([0.0], np.cumsum(pw)))
    per_dur: dict = {}
    for label, w in durations.items():
        if n < w:
            continue
        sums = cum[w:] - cum[:-w]
        peak = float(sums.max() / w)
        if peak <= 0:
            continue
        per_dur[label] = round(peak, 1)
    return (str(act_id), {"act_id": str(act_id), "durations": per_dur})


def compute_power_records(
    streams_dir: str,
    activities_df: "pd.DataFrame | None" = None,
    sport_filter: str = "velo",
    cache_path: str | None = None,
    max_workers: int = 8,
) -> dict:
    """
    Records de puissance par durée (vélo) via fenêtre glissante sur les streams.

    Cache par activité dans `power_pr_cache_{sport}.json`. Retourne
    `{ "1min": {power_w, date, activity_id}, ... }`.
    """
    from concurrent.futures import ThreadPoolExecutor
    from sport_mapping import get_sport

    if cache_path is None:
        parent = os.path.dirname(os.path.abspath(streams_dir.rstrip(os.sep) or streams_dir))
        cache_path = os.path.join(parent, f"power_pr_cache_{sport_filter}.json")

    date_map: dict = {}
    sport_ids: set = set()
    if activities_df is not None and not activities_df.empty:
        for _, row in activities_df.iterrows():
            act_id = str(int(row["ID"]))
            date_map[act_id] = pd.to_datetime(row["Date"]).isoformat()
        sport_mask = activities_df["Type"].apply(lambda t: get_sport(str(t)) == sport_filter)
        sport_ids = set(activities_df.loc[sport_mask, "ID"].astype(int).astype(str))

    cache: dict = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            cache = {}

    if not storage.isdir(streams_dir):
        return {}

    stream_files: list = []
    for fname in storage.listdir(streams_dir):
        if not fname.endswith(".csv"):
            continue
        act_id = fname.replace(".csv", "")
        if sport_ids and act_id not in sport_ids:
            continue
        stream_files.append((os.path.join(streams_dir, fname), act_id))

    current_keys = {act_id for (_, act_id) in stream_files}
    stale = [k for k in list(cache.keys()) if k not in current_keys]
    for k in stale:
        cache.pop(k, None)

    new_files = [(p, aid, _PR_POWER_DURATIONS) for (p, aid) in stream_files if aid not in cache]

    if new_files:
        print(f"  [PR power {sport_filter}] {len(new_files)} streams à analyser "
              f"(cache: {len(cache)}, stale purgés: {len(stale)})")
        workers = max(1, min(max_workers, len(new_files)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_power_compute_one_file, new_files):
                if res is None:
                    continue
                key, entry = res
                cache[key] = entry
    else:
        print(f"  [PR power {sport_filter}] cache à jour ({len(cache)} entrées)")

    if new_files or stale:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except OSError:
            pass

    records: dict = {}
    for entry in cache.values():
        act_id = entry.get("act_id")
        for label, watts in (entry.get("durations") or {}).items():
            if watts is None or label not in _PR_POWER_DURATIONS:
                continue
            current = records.get(label)
            if current is None or watts > current["power_w"]:
                records[label] = {
                    "power_w": round(float(watts), 1),
                    "date": date_map.get(str(act_id), ""),
                    "activity_id": act_id,
                }
    return records


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
        GAP_speed    = speed × facteur  # facteur = coût énergétique relatif
                                        # (montée → facteur > 1 → équivalent plat plus rapide)

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
            gap_speeds[i] = speeds[i] * facteur

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

def compute_acwr_rolling(daily_load, at) -> float | None:
    """
    ACWR "rolling" (somme aiguë / moyenne chronique), conforme à la définition
    classique Hulin et al. 2016 — utilisée par la surface /api/v1/engine/state.

    Distinct du compute_acwr() EWMA ci-dessus, qui reste utilisé partout
    ailleurs dans la pipeline analyse.

    Paramètres
    ----------
    daily_load : dict[date | str | pd.Timestamp, float]
        Charge quotidienne (TRIMP, km, ou autre proxy). Jours manquants = 0.
    at : date | str | pd.Timestamp
        Jour de référence (inclus dans la fenêtre).

    Règles
    ------
    - Aiguë      : somme glissante 7j (J inclus).
    - Chronique  : moyenne glissante 28j (J inclus).
    - Ratio      : aiguë / chronique.
    - None si moins de 7 jours d'historique avant `at` (J inclus).
    - None si chronique nulle (division par zéro).
    """
    from datetime import date as _date

    if not daily_load:
        return None

    def _to_date(x):
        if isinstance(x, _date):
            return x
        return pd.Timestamp(x).date()

    at_d = _to_date(at)
    loads = {_to_date(k): float(v) for k, v in daily_load.items()}

    # Historique disponible avant ou à `at`
    earliest = min(loads.keys())
    history_days = (at_d - earliest).days + 1
    if history_days < 7:
        return None

    # Fenêtres (J inclus)
    acute_start = at_d - timedelta(days=6)
    chronic_start = at_d - timedelta(days=27)

    acute_sum = sum(v for d, v in loads.items() if acute_start <= d <= at_d)
    chronic_vals = [loads.get(chronic_start + timedelta(days=i), 0.0) for i in range(28)]
    chronic_mean = sum(chronic_vals) / 28.0

    if chronic_mean == 0:
        return None
    return round(acute_sum / chronic_mean, 3)


def acwr_label(acwr: float) -> str:
    """Étiquette textuelle de l'ACWR."""
    if acwr < 0.8:
        return "sous-charge"
    if acwr <= 1.3:
        return "zone optimale"
    if acwr <= 1.5:
        return "charge élevée"
    return "surcharge — risque blessure"
