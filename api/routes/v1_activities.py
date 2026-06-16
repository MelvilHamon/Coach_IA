"""
api/routes/v1_activities.py — Liste frugale des activités (pour app mobile).

Pas de GPS, pas de zones, pas de cadence — uniquement les champs requis par
le contrat /api/v1.
"""

from datetime import date as DateT

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import load_activities
from api.dependencies import require_api_key
from api.v1_schemas import ActivitiesResponse, ActivityItem

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "analyse"))
from sport_mapping import get_sport  # noqa: E402

router = APIRouter(prefix="/api/v1/activities", tags=["v1-activities"])

# Strava sport_type → v1 type. Tout ce qui n'est pas explicitement run/ride/swim
# tombe sur "other" (Hike, Workout, etc.).
_RIDE = {"Ride", "VirtualRide", "EBikeRide", "Gravel", "GravelRide", "MountainBikeRide"}
_RUN = {"Run", "TrailRun", "VirtualRun"}
_SWIM = {"Swim"}


def _map_type(strava_type: str) -> str:
    if strava_type in _RUN:
        return "run"
    if strava_type in _RIDE:
        return "ride"
    if strava_type in _SWIM:
        return "swim"
    return "other"


def _nan_to_none(v):
    if v is None:
        return None
    if isinstance(v, float) and (pd.isna(v)):
        return None
    return v


@router.get("", response_model=ActivitiesResponse, summary="Liste paginée des activités")
def list_v1(
    from_: DateT | None = Query(None, alias="from"),
    to: DateT | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_api_key),
):
    if from_ and to and from_ > to:
        raise HTTPException(400, detail={
            "error": "invalid_date_range",
            "message": "from doit être <= to.",
        })

    df = load_activities(user["id"])
    if df.empty:
        return ActivitiesResponse(activities=[])

    d = df.copy()
    d["_date"] = pd.to_datetime(d["Date"], utc=True).dt.date

    if from_:
        d = d[d["_date"] >= from_]
    if to:
        d = d[d["_date"] <= to]

    d = d.sort_values("Date", ascending=False).head(limit)

    items: list[ActivityItem] = []
    for _, row in d.iterrows():
        strava_type = str(row.get("Type", ""))
        dur_min = float(row.get("Temps (min)") or 0)
        dist_km = float(row.get("Distance (km)") or 0)
        items.append(ActivityItem(
            id=f"act_{int(row['ID'])}",
            date=row["_date"],
            type=_map_type(strava_type),
            duration_s=int(round(dur_min * 60)),
            distance_m=int(round(dist_km * 1000)),
            trimp=_nan_to_none(row.get("trimp")),
            hr_tss=_nan_to_none(row.get("hrtss")),
            elevation_gain_m=_nan_to_none(row.get("Dénivelé (m)")),
        ))
    return ActivitiesResponse(activities=items)
