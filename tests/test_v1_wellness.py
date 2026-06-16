"""Tests endpoints écriture (wellness + feedback)."""

from sqlalchemy import text

from api.database import get_db


def test_wellness_daily_upsert(client, auth_headers, user):
    payload = {
        "date": "2026-06-03",
        "form_vs_normal": 1,
        "motivation": 4,
        "fatigue": 3,
        "active_niggles": 1,
    }
    r = client.post("/api/v1/wellness/daily", headers=auth_headers, json=payload)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "date": "2026-06-03"}

    # Upsert idempotent : 2e POST avec valeurs modifiées met à jour, pas en double.
    payload["motivation"] = 5
    r2 = client.post("/api/v1/wellness/daily", headers=auth_headers, json=payload)
    assert r2.status_code == 200

    with get_db() as db:
        rows = db.execute(text("""
            SELECT motivation FROM wellness_daily
            WHERE user_id = :uid AND date = :date
        """), {"uid": user["id"], "date": "2026-06-03"}).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 5


def test_wellness_invalid_range(client, auth_headers, user):
    payload = {
        "date": "2026-06-03",
        "form_vs_normal": 99,  # hors -2..+2
        "motivation": 4,
        "fatigue": 3,
        "active_niggles": 1,
    }
    r = client.post("/api/v1/wellness/daily", headers=auth_headers, json=payload)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_params"


def test_feedback_session_insert(client, auth_headers, user):
    payload = {
        "activity_id": "act_12345",
        "rpe": 7,
        "affect": "strong",
        "reported_at": "2026-06-02T18:30:00Z",
    }
    r = client.post("/api/v1/feedback/session", headers=auth_headers, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["id"], int)

    with get_db() as db:
        row = db.execute(text("""
            SELECT activity_id, rpe, affect FROM session_feedback
            WHERE user_id = :uid
        """), {"uid": user["id"]}).fetchone()
    assert row[0] == "act_12345"
    assert row[1] == 7
    assert row[2] == "strong"


def test_feedback_invalid_affect(client, auth_headers, user):
    payload = {
        "activity_id": "act_1",
        "rpe": 5,
        "affect": "lolnope",
        "reported_at": "2026-06-02T18:30:00Z",
    }
    r = client.post("/api/v1/feedback/session", headers=auth_headers, json=payload)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_params"
