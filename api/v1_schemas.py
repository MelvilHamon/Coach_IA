"""
api/v1_schemas.py — Modèles Pydantic pour la surface /api/v1.

Contract figé partagé avec l'app mobile externe via /docs.
"""

from datetime import date as DateT, datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Erreur uniforme ─────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str = Field(..., description="Code machine de l'erreur.", examples=["invalid_date_range"])
    message: str = Field(..., description="Message lisible.", examples=["from doit être <= to"])


# ── Engine ───────────────────────────────────────────────────────────────────

ReadinessHint = Literal["low", "neutral", "high"]


class EngineState(BaseModel):
    date: DateT = Field(..., examples=["2026-06-03"])
    fitness: float = Field(..., description="CTL (Banister EWMA 42j).", examples=[78.2])
    fatigue: float = Field(..., description="ATL (Banister EWMA 7j).", examples=[45.1])
    form: float = Field(..., description="fitness - fatigue (TSB).", examples=[33.1])
    acwr: float | None = Field(
        None,
        description="Acute (7j sum) / Chronic (28j mean) du TRIMP. null si <7j d'historique.",
        examples=[1.12],
    )
    load_7d: float = Field(..., description="Somme TRIMP 7 derniers jours.", examples=[420.0])
    load_28d: float = Field(..., description="Somme TRIMP 28 derniers jours.", examples=[1380.0])
    trend_form_7d: float = Field(..., description="form(at) - form(at-7).", examples=[-2.3])
    readiness_hint: ReadinessHint = Field(
        ...,
        description=(
            "Indicateur synthétique : "
            "'low' si form<-10 ; "
            "'high' si form>15 ET acwr ∈ [0.8,1.3] ; "
            "'neutral' sinon."
        ),
        examples=["neutral"],
    )


class TimeseriesPoint(BaseModel):
    date: DateT = Field(..., examples=["2026-06-02"])
    value: float | None = Field(None, examples=[78.4])


class TimeseriesResponse(BaseModel):
    from_: DateT = Field(..., alias="from", examples=["2026-05-04"])
    to: DateT = Field(..., examples=["2026-06-03"])
    series: dict[str, list[TimeseriesPoint]] = Field(
        ...,
        description="Clés possibles : fitness, fatigue, form, load, acwr.",
    )

    model_config = {"populate_by_name": True}


# ── Activities ───────────────────────────────────────────────────────────────

ActivityType = Literal["run", "ride", "swim", "other"]


class ActivityItem(BaseModel):
    id: str = Field(..., examples=["act_12345"])
    date: DateT = Field(..., examples=["2026-06-02"])
    type: ActivityType = Field(..., examples=["run"])
    duration_s: int = Field(..., examples=[4320])
    distance_m: int = Field(..., examples=[14200])
    trimp: float | None = Field(None, examples=[142.0])
    hr_tss: float | None = Field(None, examples=[88.0])
    elevation_gain_m: float | None = Field(None, examples=[230.0])


class ActivitiesResponse(BaseModel):
    activities: list[ActivityItem]


# ── Wellness ─────────────────────────────────────────────────────────────────

class WellnessDailyBody(BaseModel):
    date: DateT = Field(..., examples=["2026-06-03"])
    form_vs_normal: int = Field(..., ge=-2, le=2, examples=[1])
    motivation: int = Field(..., ge=1, le=5, examples=[4])
    fatigue: int = Field(..., ge=1, le=5, examples=[3])
    active_niggles: int = Field(..., ge=0, examples=[1])


class WellnessDailyResponse(BaseModel):
    ok: bool = True
    date: DateT


# ── Session feedback ─────────────────────────────────────────────────────────

Affect = Literal["weak", "neutral", "strong"]


class SessionFeedbackBody(BaseModel):
    activity_id: str = Field(..., examples=["act_12345"])
    rpe: int = Field(..., ge=1, le=10, examples=[7])
    affect: Affect = Field(..., examples=["strong"])
    reported_at: datetime = Field(..., examples=["2026-06-02T18:30:00Z"])


class SessionFeedbackResponse(BaseModel):
    ok: bool = True
    id: int


# ── API keys (cookie-protected) ──────────────────────────────────────────────

class ApiKeyMintBody(BaseModel):
    label: str = Field("", max_length=100, description="Libellé libre (ex. 'mobile-iphone').")


class ApiKeyMintResponse(BaseModel):
    id: str
    key: str = Field(..., description="Clé en clair — affichée UNE SEULE FOIS.")
    prefix: str
    label: str
    created_at: datetime


class ApiKeyListItem(BaseModel):
    id: str
    label: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyListItem]
