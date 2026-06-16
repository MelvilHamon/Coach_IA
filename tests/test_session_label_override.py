"""
tests/test_session_label_override.py — Correction manuelle du type de séance.

Vérifie que PUT /api/activities/{id}/session_type enregistre un override qui
prime ensuite sur la classification automatique dans GET /api/activities.
"""

from api.auth import create_session


def _cookie_client(client, user):
    token = create_session(user["id"])
    client.cookies.set("ca_session", token)
    return client


def test_put_override_then_reflected_in_list(client, user, enriched_csv):
    _cookie_client(client, user)
    activity_id = int(enriched_csv.iloc[0]["ID"])  # session_type initial = endurance fondamentale

    # Override vers un type valide.
    r = client.put(f"/api/activities/{activity_id}/session_type",
                   json={"session_type": "fractionné moyen"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["session_type"] == "fractionné moyen"
    assert body["detected_type"] == "endurance fondamentale"

    # GET liste : le type corrigé prime.
    r = client.get("/api/activities", params={"limit": 1000})
    acts = {a["id"]: a for a in r.json()["activities"]}
    assert acts[activity_id]["session_type"] == "fractionné moyen"

    # Le filtre par type tient compte de l'override.
    r = client.get("/api/activities", params={"type": "fractionné moyen", "limit": 1000})
    assert activity_id in {a["id"] for a in r.json()["activities"]}

    client.cookies.clear()


def test_put_invalid_type_rejected(client, user, enriched_csv):
    _cookie_client(client, user)
    activity_id = int(enriched_csv.iloc[0]["ID"])
    r = client.put(f"/api/activities/{activity_id}/session_type",
                   json={"session_type": "n'importe quoi"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "invalid_session_type"
    client.cookies.clear()


def test_put_updates_existing_override(client, user, enriched_csv):
    _cookie_client(client, user)
    activity_id = int(enriched_csv.iloc[0]["ID"])
    client.put(f"/api/activities/{activity_id}/session_type",
               json={"session_type": "fractionné court"})
    client.put(f"/api/activities/{activity_id}/session_type",
               json={"session_type": "tempo / seuil"})
    r = client.get("/api/activities", params={"limit": 1000})
    acts = {a["id"]: a for a in r.json()["activities"]}
    assert acts[activity_id]["session_type"] == "tempo / seuil"
    client.cookies.clear()
