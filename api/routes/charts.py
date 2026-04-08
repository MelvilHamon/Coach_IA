"""
api/routes/charts.py — Endpoints données pour graphiques.

Retourne des données structurées, pas des figures Plotly.
Le frontend construit les graphiques.

Tous les endpoints acceptent un paramètre optionnel `sport` (run, velo, all).
"""

import pandas as pd
from fastapi import APIRouter, Depends, Query
from typing import Optional

from api.deps import load_activities, nan_safe
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/charts", tags=["charts"])


def _filter_sport(df: pd.DataFrame, sport: str | None) -> pd.DataFrame:
    """Filtre le DataFrame par sport si la colonne existe et sport est spécifié."""
    if sport and sport != "all" and "sport" in df.columns:
        return df[df["sport"] == sport]
    return df


@router.get("/volume")
def chart_volume(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """Volume hebdomadaire (16 dernières semaines) + ACWR par semaine."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"weeks": []}

    df_asc = df.sort_values("Date")
    df_w = df_asc[df_asc["weekly_km"].notna()].copy()
    if df_w.empty:
        return {"weeks": []}

    df_w["week"] = (
        df_w["Date"].dt.tz_convert(None).dt.to_period("W")
        .apply(lambda p: p.start_time)
    )
    agg = (
        df_w.groupby("week")
        .agg(
            total_km=("Distance (km)", "sum"),
            acwr=("acwr_km", "last"),
            n_sessions=("ID", "count"),
            total_denivele=("Dénivelé (m)", "sum"),
        )
        .reset_index()
        .tail(16)
    )

    weeks = []
    for _, row in agg.iterrows():
        weeks.append(nan_safe({
            "week":            row["week"].isoformat(),
            "total_km":        row["total_km"],
            "acwr":            row["acwr"],
            "n_sessions":      int(row["n_sessions"]),
            "total_denivele":  row["total_denivele"],
        }))

    return {"weeks": weeks}


@router.get("/acwr")
def chart_acwr(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """ACWR sur 90 jours."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"points": []}

    df_a = df[df["acwr_km"].notna()].sort_values("Date")
    if df_a.empty:
        return {"points": []}

    cutoff = df_a["Date"].max() - pd.Timedelta(days=90)
    df_90 = df_a[df_a["Date"] >= cutoff]

    points = []
    for _, row in df_90.iterrows():
        points.append(nan_safe({
            "date":                 row["Date"].isoformat(),
            "acwr":                 row["acwr_km"],
            "injury_risk_score":    row.get("injury_risk_score"),
            "injury_risk_label":    row.get("injury_risk_label", ""),
        }))

    return {"points": points}


@router.get("/pace")
def chart_pace(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """Allure par type de séance."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"series": []}

    # Déterminer les types de séances pertinents selon le sport
    detected_sport = sport or "run"
    if detected_sport == "velo":
        target_types = [
            "endurance vélo", "sortie longue vélo", "tempo vélo",
            "récupération vélo", "intervalles vélo",
        ]
    else:
        target_types = [
            "endurance fondamentale", "fractionné court", "fractionné moyen",
            "fractionné long", "mixte", "tempo / seuil", "sortie longue",
        ]

    df_p = df[
        df["session_type"].isin(target_types) & df["Allure (min/km)"].notna()
    ].sort_values("Date")

    if df_p.empty:
        return {"series": []}

    series = []
    for stype in target_types:
        sub = df_p[df_p["session_type"] == stype]
        if sub.empty:
            continue
        points = []
        for _, row in sub.iterrows():
            points.append(nan_safe({
                "date":  row["Date"].isoformat(),
                "pace":  row["Allure (min/km)"],
            }))
        series.append({"type": stype, "points": points})

    return {"series": series}


@router.get("/speed")
def chart_speed(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """Vitesse moyenne par type de séance (utile pour le vélo)."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"series": []}

    # Calculer la vitesse si pas déjà présente
    df = df.copy()
    df["speed_kmh"] = df.apply(
        lambda r: r["Distance (km)"] / (r["Temps (min)"] / 60)
        if r.get("Temps (min)") and r["Temps (min)"] > 0 and r.get("Distance (km)") and r["Distance (km)"] > 0
        else None,
        axis=1,
    )

    detected_sport = sport or "run"
    if detected_sport == "velo":
        target_types = [
            "endurance vélo", "sortie longue vélo", "tempo vélo",
            "récupération vélo", "intervalles vélo",
        ]
    else:
        target_types = [
            "endurance fondamentale", "fractionné court", "fractionné moyen",
            "fractionné long", "mixte", "tempo / seuil", "sortie longue",
        ]

    df_s = df[
        df["session_type"].isin(target_types) & df["speed_kmh"].notna()
    ].sort_values("Date")

    if df_s.empty:
        return {"series": []}

    series = []
    for stype in target_types:
        sub = df_s[df_s["session_type"] == stype]
        if sub.empty:
            continue
        points = []
        for _, row in sub.iterrows():
            points.append(nan_safe({
                "date":  row["Date"].isoformat(),
                "speed": round(row["speed_kmh"], 1),
            }))
        series.append({"type": stype, "points": points})

    return {"series": series}


@router.get("/ef")
def chart_ef(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """Efficiency Factor avec moyenne glissante."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"points": []}

    df_e = df[df["efficiency_factor"].notna()].sort_values("Date").copy()
    if df_e.empty:
        return {"points": []}

    df_e["ef_roll"] = df_e["efficiency_factor"].rolling(10, min_periods=3).mean()

    points = []
    for _, row in df_e.iterrows():
        points.append(nan_safe({
            "date":     row["Date"].isoformat(),
            "ef":       row["efficiency_factor"],
            "ef_roll":  row.get("ef_roll"),
        }))

    return {"points": points}


@router.get("/vo2")
def chart_vo2(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """VO2max estimé avec tendance."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"points": []}

    df_v = df[df["vo2max_estimate"].notna()].sort_values("Date").copy()
    if df_v.empty:
        return {"points": []}

    df_v["vo2_roll"] = df_v["vo2max_estimate"].rolling(8, min_periods=3).mean()

    points = []
    for _, row in df_v.iterrows():
        points.append(nan_safe({
            "date":      row["Date"].isoformat(),
            "vo2":       row["vo2max_estimate"],
            "vo2_roll":  row.get("vo2_roll"),
        }))

    return {"points": points}


@router.get("/distribution")
def chart_distribution(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """Répartition des types de séances."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"types": []}

    counts = df["session_type"].value_counts()
    total = counts.sum()

    types = []
    for stype, n in counts.items():
        types.append({
            "type":  str(stype),
            "count": int(n),
            "pct":   round(n / total * 100, 1) if total else 0,
        })

    return {"types": types, "total": int(total)}


@router.get("/fitness")
def chart_fitness(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """CTL / ATL / TSB (Banister EWMA) sur 90 jours."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"points": []}

    needed = {"ctl", "atl", "tsb"}
    if not needed.issubset(df.columns):
        return {"points": []}

    df_f = df[df["ctl"].notna()].sort_values("Date")
    if df_f.empty:
        return {"points": []}

    cutoff = df_f["Date"].max() - pd.Timedelta(days=90)
    df_90 = df_f[df_f["Date"] >= cutoff]

    points = []
    for _, row in df_90.iterrows():
        points.append(nan_safe({
            "date": row["Date"].isoformat(),
            "ctl":  row["ctl"],
            "atl":  row["atl"],
            "tsb":  row["tsb"],
        }))

    return {"points": points}


@router.get("/monotony")
def chart_monotony(
    user: dict = Depends(get_current_user),
    sport: Optional[str] = Query(None),
):
    """Monotony & Strain (Foster 1998) sur 90 jours."""
    df = load_activities(user["id"])
    df = _filter_sport(df, sport)
    if df.empty:
        return {"points": []}

    needed = {"monotony", "strain"}
    if not needed.issubset(df.columns):
        return {"points": []}

    df_m = df[df["monotony"].notna()].sort_values("Date")
    if df_m.empty:
        return {"points": []}

    cutoff = df_m["Date"].max() - pd.Timedelta(days=90)
    df_90 = df_m[df_m["Date"] >= cutoff]

    points = []
    for _, row in df_90.iterrows():
        points.append(nan_safe({
            "date":      row["Date"].isoformat(),
            "monotony":  row["monotony"],
            "strain":    row["strain"],
        }))

    return {"points": points}
