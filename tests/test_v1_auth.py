"""Tests auth Bearer (401 sur missing / invalid)."""


def test_no_header_returns_401(client):
    r = client.get("/api/v1/engine/state")
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "unauthorized"
    assert "message" in body


def test_invalid_key_returns_401(client):
    r = client.get(
        "/api/v1/engine/state",
        headers={"Authorization": "Bearer ca_v1_pas_une_vraie_cle"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_api_key"


def test_wrong_scheme_returns_401(client):
    r = client.get(
        "/api/v1/engine/state",
        headers={"Authorization": "Basic foobar"},
    )
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"
