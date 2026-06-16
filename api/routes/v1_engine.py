"""
api/routes/v1_engine.py — État Banister + timeseries (lecture).

Lecture pure du CSV enrichi déjà produit par run_analysis. Aucune
recomputation du moteur Banister ici.
"""

from datetime import date as DateT, timedelta

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import load_activities
from api.dependencies import require_api_key
from api.v1_schemas import EngineState, TimeseriesPoint, TimeseriesResponse
from analyse.metrics import compute_acwr_rolling

router = APIRouter(prefix="/api/v1/engine", tags=["v1-engine"])

_ALLOWED_METRICS = {"fitness", "fatigue", "form", "load", "acwr"}


def _daily_trimp(df: pd.DataFrame) -> pd.Series:
    """Série quotidienne TRIMP indexée par date, jours manquants à 0."""
    if df.empty or "trimp" not in df.columns:
        return pd.Series(dtype=float)
    d = df.copy()
    d["_date"] = pd.to_datetime(d["Date"], utc=True).dt.date
    d["_trimp"] = d["trimp"].fillna(0)
    s = d.groupby("_date")["_trimp"].sum()
    if s.empty:
        return s
    full = pd.date_range(s.index.min(), s.index.max(), freq="D").date
    return s.reindex(full, fill_value=0.0)


def _daily_last(df: pd.DataFrame, col: str) -> pd.Series:
    """Dernière valeur de `col` par jour, forward-filled."""
    if df.empty or col not in df.columns:
        return pd.Series(dtype=float)
    d = df.copy()
    d["_date"] = pd.to_datetime(d["Date"], utc=True).dt.date
    d = d.sort_values("Date")
    s = d.groupby("_date")[col].last().dropna()
    if s.empty:
        return s
    full = pd.date_range(s.index.min(), s.index.max(), freq="D").date
    return s.reindex(full).ffill()


def _readiness(form: float, acwr: float | None) -> str:
    if form < -10:
        return "low"
    if form > 15 and acwr is not None and 0.8 <= acwr <= 1.3:
        return "high"
    return "neutral"


@router.get(
    "/state",
    response_model=EngineState,
    summary="État Banister + ACWR pour un jour donné",
)
def get_state(
    date: DateT | None = Query(None, description="Jour cible (défaut = aujourd'hui)."),
    user: dict = Depends(require_api_key),
):
    df = load_activities(user["id"])
    if df.empty:
        raise HTTPException(404, detail={"error": "no_data", "message": "Aucune activité."})

    at = date or pd.Timestamp.utcnow().date()

    daily = _daily_trimp(df)
    ctl_s = _daily_last(df, "ctl")
    atl_s = _daily_last(df, "atl")

    if ctl_s.empty or at < ctl_s.index.min():
        raise HTTPException(404, detail={
            "error": "no_data",
            "message": f"Pas de données Banister pour {at.isoformat()}.",
        })

    # Forward-fill jusqu'à `at` (au cas où `at` est dans le futur ou un jour de repos)
    ctl_at = float(ctl_s.loc[ctl_s.index <= at].iloc[-1])
    atl_at = float(atl_s.loc[atl_s.index <= at].iloc[-1])
    form = round(ctl_at - atl_at, 1)

    load_7d = float(daily.loc[(daily.index >= at - timedelta(days=6)) & (daily.index <= at)].sum())
    load_28d = float(daily.loc[(daily.index >= at - timedelta(days=27)) & (daily.index <= at)].sum())

    acwr = compute_acwr_rolling({d: float(v) for d, v in daily.items()}, at)

    # Trend form 7j : form(at) - form(at-7) si dispo, sinon 0
    at_prev = at - timedelta(days=7)
    if at_prev >= ctl_s.index.min():
        ctl_prev = float(ctl_s.loc[ctl_s.index <= at_prev].iloc[-1])
        atl_prev = float(atl_s.loc[atl_s.index <= at_prev].iloc[-1])
        trend = round(form - (ctl_prev - atl_prev), 1)
    else:
        trend = 0.0

    return EngineState(
        date=at,
        fitness=round(ctl_at, 1),
        fatigue=round(atl_at, 1),
        form=form,
        acwr=acwr,
        load_7d=round(load_7d, 1),
        load_28d=round(load_28d, 1),
        trend_form_7d=trend,
        readiness_hint=_readiness(form, acwr),
    )


@router.get(
    "/timeseries",
    response_model=TimeseriesResponse,
    response_model_by_alias=True,
    summary="Séries quotidiennes Banister / charge / ACWR",
)
def get_timeseries(
    from_: DateT = Query(..., alias="from"),
    to: DateT = Query(...),
    metrics: str = Query("fitness,fatigue,form", description="CSV parmi fitness,fatigue,form,load,acwr"),
    user: dict = Depends(require_api_key),
):
    if from_ > to:
        raise HTTPException(400, detail={
            "error": "invalid_date_range",
            "message": "from doit être <= to.",
        })

    requested = [m.strip() for m in metrics.split(",") if m.strip()]
    invalid = [m for m in requested if m not in _ALLOWED_METRICS]
    if invalid:
        raise HTTPException(400, detail={
            "error": "invalid_params",
            "message": f"metrics inconnues : {invalid}. Valides : {sorted(_ALLOWED_METRICS)}.",
        })

    df = load_activities(user["id"])
    if df.empty:
        return TimeseriesResponse(**{"from": from_, "to": to, "series": {m: [] for m in requested}})

    daily_trimp = _daily_trimp(df)
    ctl_s = _daily_last(df, "ctl")
    atl_s = _daily_last(df, "atl")

    # ACWR par jour (rolling) sur la fenêtre demandée.
    loads_map = {d: float(v) for d, v in daily_trimp.items()}

    series: dict[str, list[TimeseriesPoint]] = {}
    cur = from_
    days: list[DateT] = []
    while cur <= to:
        days.append(cur)
        cur += timedelta(days=1)

    def _ffill_at(s: pd.Series, d: DateT) -> float | None:
        if s.empty:
            return None
        sub = s.loc[s.index <= d]
        if sub.empty:
            return None
        v = sub.iloc[-1]
        return None if pd.isna(v) else round(float(v), 2)

    for m in requested:
        pts = []
        for d in days:
            if m == "fitness":
                v = _ffill_at(ctl_s, d)
            elif m == "fatigue":
                v = _ffill_at(atl_s, d)
            elif m == "form":
                ctl = _ffill_at(ctl_s, d)
                atl = _ffill_at(atl_s, d)
                v = round(ctl - atl, 2) if ctl is not None and atl is not None else None
            elif m == "load":
                v = float(daily_trimp.get(d, 0.0))
            else:  # acwr
                v = compute_acwr_rolling(loads_map, d)
            pts.append(TimeseriesPoint(date=d, value=v))
        series[m] = pts

    return TimeseriesResponse(**{"from": from_, "to": to, "series": series})
