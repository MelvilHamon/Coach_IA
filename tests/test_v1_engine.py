"""Tests /api/v1/engine/state et /api/v1/engine/timeseries."""

from datetime import date


def test_state_happy_path(client, auth_headers, enriched_csv):
    r = client.get("/api/v1/engine/state?date=2026-06-01", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-06-01"
    assert "fitness" in body and "fatigue" in body and "form" in body
    assert body["form"] == round(body["fitness"] - body["fatigue"], 1)
    assert body["readiness_hint"] in {"low", "neutral", "high"}
    assert "load_7d" in body and "load_28d" in body
    # 7j × 50 TRIMP = 350
    assert body["load_7d"] == 350.0


def test_state_no_data_returns_404(client, auth_headers, user):
    # user existe mais pas de CSV.
    r = client.get("/api/v1/engine/state", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["error"] == "no_data"


def test_timeseries_happy_path(client, auth_headers, enriched_csv):
    r = client.get(
        "/api/v1/engine/timeseries?from=2026-05-15&to=2026-05-20&metrics=fitness,form,load",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from"] == "2026-05-15"
    assert body["to"] == "2026-05-20"
    assert set(body["series"].keys()) == {"fitness", "form", "load"}
    assert len(body["series"]["fitness"]) == 6  # 6 jours inclus


def test_timeseries_invalid_range(client, auth_headers, enriched_csv):
    r = client.get(
        "/api/v1/engine/timeseries?from=2026-06-10&to=2026-05-01&metrics=fitness",
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_date_range"


def test_timeseries_invalid_metric(client, auth_headers, enriched_csv):
    r = client.get(
        "/api/v1/engine/timeseries?from=2026-05-01&to=2026-05-05&metrics=foo",
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_params"
