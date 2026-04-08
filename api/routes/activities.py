"""
api/routes/activities.py — Endpoints activités.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from api.deps import load_activities, get_stream, nan_safe
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/activities", tags=["activities"])


@router.get("")
def list_activities(
    user: dict = Depends(get_current_user),
    type: Optional[str] = Query(None, description="Filtrer par session_type"),
    sport: Optional[str] = Query(None, description="Filtrer par sport : run, velo, autre"),
    period: Optional[str] = Query(None, description="30j, 90j, ou all"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Liste paginée des activités enrichies."""
    df = load_activities(user["id"])
    if df.empty:
        return {"activities": [], "total": 0}

    if sport and sport != "all" and "sport" in df.columns:
        df = df[df["sport"] == sport]

    if type and type != "Tous":
        df = df[df["session_type"] == type]

    if period == "30j":
        cutoff = df["Date"].max() - __import__("pandas").Timedelta(days=30)
        df = df[df["Date"] >= cutoff]
    elif period == "90j":
        cutoff = df["Date"].max() - __import__("pandas").Timedelta(days=90)
        df = df[df["Date"] >= cutoff]

    total = len(df)
    page = df.iloc[offset : offset + limit]

    activities = []
    for _, row in page.iterrows():
        activities.append(nan_safe({
            "id":                   int(row["ID"]),
            "nom":                  row.get("Nom", ""),
            "date":                 row["Date"].isoformat(),
            "distance_km":          row.get("Distance (km)"),
            "temps_min":            row.get("Temps (min)"),
            "allure_min_km":        row.get("Allure (min/km)"),
            "pace_display":         row.get("pace_display"),
            "denivele_m":           row.get("Dénivelé (m)"),
            "fc_bpm":               row.get("Fréquence cardiaque (bpm)"),
            "type_strava":          row.get("Type", ""),
            "sport":                row.get("sport", ""),
            "session_type":         row.get("session_type", ""),
            "trimp":                row.get("trimp"),
            "hrtss":                row.get("hrtss"),
            "acwr_km":              row.get("acwr_km"),
            "weekly_km":            row.get("weekly_km"),
            "injury_risk_score":    row.get("injury_risk_score"),
            "injury_risk_label":    row.get("injury_risk_label", ""),
            "efficiency_factor":    row.get("efficiency_factor"),
            "vo2max_estimate":      row.get("vo2max_estimate"),
            "tsb":                  row.get("tsb"),
            "monotony":             row.get("monotony"),
            "strain":               row.get("strain"),
            "z1_min":               row.get("z1_min"),
            "z2_min":               row.get("z2_min"),
            "z3_min":               row.get("z3_min"),
            "z4_min":               row.get("z4_min"),
            "z5_min":               row.get("z5_min"),
            "flags": {
                "acwr":        row.get("flag_acwr"),
                "monotony":    row.get("flag_monotony"),
                "load_spike":  row.get("flag_load_spike"),
                "consecutive": row.get("flag_consecutive"),
            },
        }))

    return {"activities": activities, "total": total}


@router.get("/types")
def list_types(user: dict = Depends(get_current_user)):
    """Types de séances disponibles."""
    df = load_activities(user["id"])
    if df.empty:
        return {"types": []}
    types = sorted(df["session_type"].dropna().unique().tolist())
    return {"types": types}


@router.get("/{activity_id}")
def get_activity(activity_id: int, user: dict = Depends(get_current_user)):
    """Détail complet d'une activité."""
    df = load_activities(user["id"])
    if df.empty:
        return {"error": "no_data"}

    mask = df["ID"].astype(int) == activity_id
    if not mask.any():
        return {"error": "not_found"}

    row = df[mask].iloc[0]

    detail = nan_safe({col: row[col] for col in df.columns})
    detail["id"] = activity_id
    detail["pace_display"] = row.get("pace_display")

    # Zones FC — exclure les NaN (activités sans FC)
    zones = {}
    for z in ("z1", "z2", "z3", "z4", "z5"):
        pct = row.get(f"{z}_pct")
        mins = row.get(f"{z}_min")
        if pct is not None and not __import__("pandas").isna(pct):
            zones[z] = nan_safe({"pct": pct, "min": mins})
    detail["zones"] = zones

    # Flags
    detail["flags"] = nan_safe({
        "acwr":         row.get("flag_acwr"),
        "monotony":     row.get("flag_monotony"),
        "load_spike":   row.get("flag_load_spike"),
        "consecutive":  row.get("flag_consecutive"),
    })

    return detail


@router.get("/{activity_id}/stream")
def get_activity_stream(activity_id: int, user: dict = Depends(get_current_user)):
    """Stream Strava (time, speed, HR, altitude) pour une activité."""
    stream_df = get_stream(activity_id, user["id"])
    if stream_df is None:
        return {"error": "no_stream", "points": []}

    points = []
    for _, row in stream_df.iterrows():
        points.append(nan_safe({
            "time_s":      row.get("time_s"),
            "speed_kmh":   row.get("speed_kmh"),
            "bpm":         row.get("bpm"),
            "altitude_m":  row.get("altitude_m"),
        }))

    return {"activity_id": activity_id, "points": points}
