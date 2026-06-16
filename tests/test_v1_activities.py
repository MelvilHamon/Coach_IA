"""Tests /api/v1/activities."""


def test_list_returns_shape(client, auth_headers, enriched_csv):
    r = client.get("/api/v1/activities?limit=5", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["activities"]) == 5
    item = body["activities"][0]
    assert item["id"].startswith("act_")
    assert item["type"] == "run"
    assert item["duration_s"] == 3000  # 50 min × 60
    assert item["distance_m"] == 10000
    assert item["trimp"] == 50.0


def test_list_filtered_by_date(client, auth_headers, enriched_csv):
    r = client.get(
        "/api/v1/activities?from=2026-05-01&to=2026-05-03&limit=200",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert len(r.json()["activities"]) == 3


def test_list_invalid_range(client, auth_headers, enriched_csv):
    r = client.get(
        "/api/v1/activities?from=2026-06-01&to=2026-05-01",
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_date_range"


def test_limit_cap(client, auth_headers, enriched_csv):
    r = client.get("/api/v1/activities?limit=999", headers=auth_headers)
    # FastAPI validation: limit > 200 → 422 mappé en invalid_params.
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_params"
