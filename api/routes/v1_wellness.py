"""
api/routes/v1_wellness.py — Endpoints d'écriture pour l'app mobile.

POST /api/v1/wellness/daily   : upsert (user_id, date) dans wellness_daily.
POST /api/v1/feedback/session : insert dans session_feedback.

Note : un store JSON existait déjà pour le feedback (api/routes/feedback.py)
mais avec une shape différente (sensations/difficulty). On ne le touche pas
et on stocke les feedbacks v1 dans une nouvelle table dédiée pour ne pas
mélanger les deux formats.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from api.database import get_db, IS_SQLITE
from api.dependencies import require_api_key
from api.v1_schemas import (
    SessionFeedbackBody, SessionFeedbackResponse,
    WellnessDailyBody, WellnessDailyResponse,
)

router = APIRouter(prefix="/api/v1", tags=["v1-wellness"])


@router.post(
    "/wellness/daily",
    response_model=WellnessDailyResponse,
    summary="Upsert du wellness quotidien",
)
def post_wellness(body: WellnessDailyBody, user: dict = Depends(require_api_key)):
    now = datetime.now(timezone.utc).isoformat()
    params = {
        "uid": user["id"],
        "date": body.date.isoformat(),
        "form": body.form_vs_normal,
        "mot": body.motivation,
        "fat": body.fatigue,
        "nig": body.active_niggles,
        "now": now,
    }
    # ON CONFLICT identique SQLite/PostgreSQL (la PK (user_id, date) cible le conflit).
    sql = """
        INSERT INTO wellness_daily
            (user_id, date, form_vs_normal, motivation, fatigue, active_niggles,
             created_at, updated_at)
        VALUES (:uid, :date, :form, :mot, :fat, :nig, :now, :now)
        ON CONFLICT(user_id, date) DO UPDATE SET
            form_vs_normal = :form,
            motivation     = :mot,
            fatigue        = :fat,
            active_niggles = :nig,
            updated_at     = :now
    """
    with get_db() as db:
        db.execute(text(sql), params)
    return WellnessDailyResponse(ok=True, date=body.date)


@router.post(
    "/feedback/session",
    response_model=SessionFeedbackResponse,
    summary="Feedback subjectif post-séance (RPE + affect)",
)
def post_feedback(body: SessionFeedbackBody, user: dict = Depends(require_api_key)):
    now = datetime.now(timezone.utc).isoformat()
    params = {
        "uid": user["id"],
        "act": body.activity_id,
        "rpe": body.rpe,
        "affect": body.affect,
        "rep": body.reported_at.isoformat(),
        "now": now,
    }
    with get_db() as db:
        if IS_SQLITE:
            result = db.execute(text("""
                INSERT INTO session_feedback
                    (user_id, activity_id, rpe, affect, reported_at, created_at)
                VALUES (:uid, :act, :rpe, :affect, :rep, :now)
            """), params)
            new_id = result.lastrowid
        else:
            row = db.execute(text("""
                INSERT INTO session_feedback
                    (user_id, activity_id, rpe, affect, reported_at, created_at)
                VALUES (:uid, :act, :rpe, :affect, :rep, :now)
                RETURNING id
            """), params).fetchone()
            new_id = row[0]
    if new_id is None:
        raise HTTPException(500, detail={"error": "internal_error", "message": "Insert failed."})
    return SessionFeedbackResponse(ok=True, id=int(new_id))
