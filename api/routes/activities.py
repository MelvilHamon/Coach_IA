"""
api/routes/activities.py — Endpoints activités.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from api.database import get_db
from api.deps import load_activities, get_stream, nan_safe
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/activities", tags=["activities"])

# Types de séance valides pour une correction manuelle (vocabulaire de
# session_classifier, course + vélo).
VALID_SESSION_TYPES = frozenset({
    "fractionné court", "fractionné moyen", "fractionné long", "mixte",
    "fractionné sprint", "fractionné pyramide symétrique",
    "fractionné pyramide ascendante", "fractionné pyramide descendante",
    "tempo / seuil", "endurance fondamentale", "sortie longue", "trail",
    "récupération active", "randonnée", "autre",
    "intervalles vélo", "récupération vélo", "sortie longue vélo",
    "tempo vélo", "endurance vélo",
})


class SessionTypeOverride(BaseModel):
    session_type: str


def _load_validated_labels(user_id: str) -> dict[str, str]:
    """Retourne {activity_id(str): validated_type} pour cet utilisateur."""
    with get_db() as db:
        rows = db.execute(text(
            "SELECT activity_id, validated_type FROM session_labels WHERE user_id = :uid"
        ), {"uid": user_id}).fetchall()
    return {str(r[0]): r[1] for r in rows}


def _apply_overrides(df, user_id: str):
    """Applique les corrections utilisateur sur la colonne session_type."""
    labels = _load_validated_labels(user_id)
    if not labels or df.empty or "session_type" not in df.columns:
        return df
    df = df.copy()
    ids = df["ID"].astype(str)
    df.loc[:, "session_type"] = [
        labels.get(aid, st) for aid, st in zip(ids, df["session_type"])
    ]
    return df


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

    # Les corrections manuelles priment sur la classification auto (avant filtre).
    df = _apply_overrides(df, user["id"])

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

    df = _apply_overrides(df, user["id"])

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


@router.put("/{activity_id}/session_type")
def set_session_type(
    activity_id: int,
    body: SessionTypeOverride,
    user: dict = Depends(get_current_user),
):
    """Corrige manuellement le type de séance (override de la détection auto).

    Stocke le label validé dans session_labels (upsert) ; il prime ensuite sur
    la classification automatique et alimente le jeu de référence.
    """
    new_type = body.session_type.strip()
    if new_type not in VALID_SESSION_TYPES:
        raise HTTPException(422, detail={
            "error": "invalid_session_type",
            "message": f"Type inconnu : {new_type!r}",
            "valid": sorted(VALID_SESSION_TYPES),
        })

    # Type détecté courant (pour traçabilité detected vs validated).
    detected = None
    df = load_activities(user["id"])
    if not df.empty:
        m = df["ID"].astype(int) == activity_id
        if not m.any():
            raise HTTPException(404, detail={"error": "not_found"})
        detected = df[m].iloc[0].get("session_type")

    now = datetime.now(timezone.utc).isoformat()
    params = {
        "uid": user["id"], "act": str(activity_id),
        "det": detected, "val": new_type, "now": now,
    }
    # ON CONFLICT identique SQLite/PostgreSQL (PK (user_id, activity_id)).
    with get_db() as db:
        db.execute(text("""
            INSERT INTO session_labels
                (user_id, activity_id, detected_type, validated_type, created_at, updated_at)
            VALUES (:uid, :act, :det, :val, :now, :now)
            ON CONFLICT(user_id, activity_id) DO UPDATE SET
                validated_type = :val,
                updated_at     = :now
        """), params)

    return {"ok": True, "activity_id": activity_id,
            "session_type": new_type, "detected_type": detected}


@router.get("/{activity_id}/stream")
def get_activity_stream(activity_id: int, user: dict = Depends(get_current_user)):
    """Stream Strava (time, speed, HR, altitude) pour une activité."""
    stream_df = get_stream(activity_id, user["id"])
    if stream_df is None:
        return {"error": "no_stream", "points": []}

    points = []
    for _, row in stream_df.iterrows():
        pt = nan_safe({
            "time_s":      row.get("time_s"),
            "speed_kmh":   row.get("speed_kmh"),
            "bpm":         row.get("bpm"),
            "altitude_m":  row.get("altitude_m"),
        })
        if "power_w" in stream_df.columns:
            pt["power_w"] = nan_safe(row.get("power_w"))
        points.append(pt)

    return {"activity_id": activity_id, "points": points}
