"""
api/routes/auth_routes.py — Authentication: OTP login + Strava OAuth linking.
"""

import os
import secrets

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.auth import (
    send_otp, verify_otp,
    create_session, delete_session,
    update_display_name,
    save_garmin_credentials,
    has_garmin_credentials, has_strava_connected,
    get_strava_tokens, save_strava_tokens, disconnect_strava,
    save_user_profile, get_user_profile,
    create_oauth_state, verify_oauth_state,
)
from api.config import COOKIE_SECURE, COOKIE_SAMESITE, COOKIE_DOMAIN, SESSION_MAX_AGE_DAYS
from api.strava_oauth import get_authorize_url, exchange_code
from api.dependencies import get_current_user, SESSION_COOKIE

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Models ────────────────────────────────────────────────────────────────────

class SendOtpBody(BaseModel):
    email: str

class VerifyOtpBody(BaseModel):
    email: str
    code: str
    display_name: str = ""

class GarminCredsBody(BaseModel):
    email: str
    password: str

class UserProfileBody(BaseModel):
    gender: str = "male"
    hr_max: int | None = None
    hr_rest: int | None = None
    hr_threshold: int | None = None
    hr_z1_max: int | None = None
    hr_z2_max: int | None = None
    hr_z3_max: int | None = None
    hr_z4_max: int | None = None
    hr_z5_max: int | None = None
    weight_kg: float | None = None


# ── Public endpoints (no auth required) ───────────────────────────────────────

@router.post("/send-otp")
def handle_send_otp(body: SendOtpBody):
    """Send a 6-digit OTP to the given email. Creates account on first verify."""
    try:
        result = send_otp(body.email)
        return result
    except ValueError as e:
        return {"error": str(e)}


@router.post("/verify-otp")
def handle_verify_otp(body: VerifyOtpBody, response: Response):
    """Verify the OTP code. Auto-creates user if new. Returns session cookie."""
    user = verify_otp(body.email, body.code)
    if not user:
        return {"error": "Code invalide ou expiré."}
    if body.display_name and body.display_name.strip() != user["display_name"]:
        update_display_name(user["id"], body.display_name)
        user["display_name"] = body.display_name.strip()
    token = create_session(user["id"])
    response.set_cookie(
        SESSION_COOKIE, token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=SESSION_MAX_AGE_DAYS * 86400,
        domain=COOKIE_DOMAIN,
        path="/",
    )
    return {"ok": True, "user": user}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


# ── Strava OAuth ─────────────────────────────────────────────────────────────

@router.get("/strava/login")
def strava_login(request: Request, user: dict = Depends(get_current_user)):
    """
    Redirige vers Strava pour autoriser l'accès.
    L'utilisateur doit être connecté (session cookie).
    Inclut un state token pour protection CSRF.
    """
    import logging
    logger = logging.getLogger("coachagent.auth")

    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/auth/strava/callback"
    state = create_oauth_state(user["id"])
    try:
        url = get_authorize_url(redirect_uri=redirect_uri, state=state)
    except ValueError as e:
        logger.error("Strava config error: %s", e)
        return RedirectResponse(url="/#settings?error=strava_not_configured", status_code=302)
    logger.info("Redirecting user %s to Strava OAuth", user["id"])
    return RedirectResponse(url=url, status_code=302)


@router.get("/strava/callback")
def strava_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    """
    Callback Strava OAuth. Vérifie le state, échange le code contre des tokens.
    Redirige vers le frontend (settings).
    """
    import logging
    logger = logging.getLogger("coachagent.auth")

    # Verify CSRF state token (primary auth method for callback)
    state_user_id = verify_oauth_state(state)
    if not state_user_id:
        # Fallback: try session cookie (for backward compat during transition)
        from api.auth import get_user_by_session
        session_token = request.cookies.get(SESSION_COOKIE)
        user = get_user_by_session(session_token) if session_token else None
        if not user:
            logger.warning("Strava callback: invalid state and no session")
            return RedirectResponse(url="/#settings?error=not_authenticated", status_code=302)
        user_id = user["id"]
    else:
        user_id = state_user_id

    if error or not code:
        logger.info("Strava denied or no code: error=%s", error)
        return RedirectResponse(url="/#settings?error=strava_denied", status_code=302)

    try:
        tokens = exchange_code(code)
        logger.info("Strava token exchange OK for user %s, athlete_id=%s",
                     user_id, tokens["athlete_id"])
        save_strava_tokens(
            user_id=user_id,
            athlete_id=tokens["athlete_id"],
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_at=tokens["expires_at"],
        )
        return RedirectResponse(url="/#settings?strava=connected", status_code=302)
    except Exception as e:
        logger.error("Strava callback error for user %s: %s", user_id, e)
        return RedirectResponse(url="/#settings?error=strava_exchange_failed", status_code=302)


@router.post("/strava/disconnect")
def strava_disconnect(user: dict = Depends(get_current_user)):
    """Déconnecte le compte Strava de l'utilisateur."""
    disconnect_strava(user["id"])
    return {"ok": True}


# ── Protected endpoints ───────────────────────────────────────────────────────

@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    import json as _json
    profile = get_user_profile(user["id"])
    strava_tokens = get_strava_tokens(user["id"])

    # Profil FC/vitesse auto-détecté depuis les streams (informatif pour l'UI).
    # Permet d'afficher côté Settings la valeur estimée à côté de la valeur
    # utilisateur pour que l'athlète puisse comparer.
    hr_auto = None
    speed_auto = None
    hr_source = None
    try:
        from api.user_data import get_user_paths
        _paths = get_user_paths(user["id"])
        if os.path.exists(_paths.config_json):
            with open(_paths.config_json, encoding="utf-8") as f:
                _cfg = _json.load(f)
            hr_auto = _cfg.get("athlete_hr_profile")
            speed_auto = _cfg.get("athlete_speed_profile")
            hr_source = (_cfg.get("athlete") or {}).get("hr_max_source")
    except Exception:
        pass

    return {
        "user": user,
        "has_garmin": has_garmin_credentials(user["id"]),
        "has_strava": has_strava_connected(user["id"]),
        "strava_athlete_id": strava_tokens["athlete_id"] if strava_tokens else None,
        "profile": profile,
        "hr_profile_auto": hr_auto,
        "speed_profile_auto": speed_auto,
        "hr_max_source": hr_source,
    }


def _write_recompute_status(user_id: str, status: str, error: str = None):
    """Écrit l'état du recalcul dans sync_state.json (running / done / error)."""
    import json
    try:
        from api.user_data import get_user_paths
        paths = get_user_paths(user_id)
        state_path = os.path.join(paths.base, "sync_state.json")
        state = {}
        if os.path.exists(state_path):
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        state["profile_recompute_status"] = status
        state["profile_recompute_updated_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        if error:
            state["profile_recompute_error"] = error
        elif "profile_recompute_error" in state:
            del state["profile_recompute_error"]
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # non-critique : on ne bloque pas le recalcul pour ça


def _reanalyze_after_profile_change(user_id: str):
    """Sync le profil DB → config.json puis relance l'analyse (force=True)."""
    import json
    import logging
    from contextlib import redirect_stdout
    import io

    logger = logging.getLogger("coachagent.sync")
    _write_recompute_status(user_id, "running")

    try:
        from api.user_data import get_user_paths
        from api.auth import get_user_profile as _get_profile

        paths = get_user_paths(user_id)
        data_dir = paths.base

        # 1. Sync profil → config.json
        config = {}
        if os.path.exists(paths.config_json):
            with open(paths.config_json, encoding="utf-8") as f:
                config = json.load(f)

        athlete = config.get("athlete", {})
        profile = _get_profile(user_id) or {}

        # Cascade de priorité hr_max/hr_rest :
        # 1. Utilisateur a renseigné la valeur dans l'UI → source="user" (authoritative)
        # 2. Sinon on laisse run_analysis la remplacer par l'estimée des streams.
        # On ne REMET PAS la source à "estimated" ici si la valeur vient d'être
        # enlevée par l'utilisateur (champ vidé) : run_analysis recalcul fera ça.
        if profile.get("hr_max"):
            athlete["hr_max"] = profile["hr_max"]
            athlete["hr_max_source"] = "user"
        else:
            # L'utilisateur n'a pas (ou plus) de valeur → on déclenche la
            # retombée sur l'estimée au prochain run_analysis en retirant la
            # marque "user".
            if athlete.get("hr_max_source") == "user":
                athlete["hr_max_source"] = "default"
        if profile.get("hr_rest"):
            athlete["hr_rest"] = profile["hr_rest"]
            athlete["hr_rest_source"] = "user"
        else:
            if athlete.get("hr_rest_source") == "user":
                athlete["hr_rest_source"] = "default"
        if profile.get("hr_threshold"):
            athlete["hr_threshold"] = profile["hr_threshold"]
        if profile.get("gender"):
            athlete["sex"] = profile["gender"]
        if profile.get("weight_kg"):
            athlete["weight_kg"] = profile["weight_kg"]

        custom_zones = []
        for i in range(1, 6):
            val = profile.get(f"hr_z{i}_max")
            if val:
                custom_zones.append(val)
        if len(custom_zones) == 5:
            athlete["hr_zones_custom"] = custom_zones

        config["athlete"] = athlete
        os.makedirs(os.path.dirname(paths.config_json), exist_ok=True)
        with open(paths.config_json, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # 2. Relancer l'analyse avec force=True
        import sys
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for sub in ("analyse", "appelAPIs"):
            p = os.path.join(_root, sub)
            if p not in sys.path:
                sys.path.insert(0, p)
        from run_analysis import run_analysis

        buf = io.StringIO()
        with redirect_stdout(buf):
            run_analysis(data_dir=data_dir, config_path=paths.config_json, force=True)

        # 3. Invalider le cache
        from api.deps import invalidate_cache
        invalidate_cache(["activities", "metrics"], user_id=user_id)

        logger.info("[profile:%s] Re-analysis completed after profile update", user_id)
        _write_recompute_status(user_id, "done")

    except Exception as e:
        logger.error("[profile:%s] Re-analysis failed: %s", user_id, e, exc_info=True)
        _write_recompute_status(user_id, "error", error=str(e))


@router.get("/profile")
def read_profile(user: dict = Depends(get_current_user)):
    profile = get_user_profile(user["id"])
    return {"profile": profile}


@router.post("/profile")
def set_profile(body: UserProfileBody, user: dict = Depends(get_current_user)):
    save_user_profile(user["id"], body.model_dump())

    # Mettre à jour config.json et relancer l'analyse en background.
    # L'état (running / done / error) est écrit dans sync_state.json et
    # consultable via GET /api/auth/profile/recompute-status.
    _write_recompute_status(user["id"], "running")

    import threading
    threading.Thread(
        target=_reanalyze_after_profile_change,
        args=(user["id"],),
        daemon=True,
    ).start()

    return {"ok": True, "recompute_status": "running"}


@router.post("/profile/recompute")
def trigger_recompute(user: dict = Depends(get_current_user)):
    """Déclenche manuellement un recalcul forcé des métriques de l'utilisateur.
    Utile pour appliquer les nouvelles règles de classification sans avoir
    à modifier son profil physiologique."""
    _write_recompute_status(user["id"], "running")

    import threading
    threading.Thread(
        target=_reanalyze_after_profile_change,
        args=(user["id"],),
        daemon=True,
    ).start()
    return {"ok": True, "recompute_status": "running"}


@router.get("/profile/recompute-status")
def profile_recompute_status(user: dict = Depends(get_current_user)):
    """Retourne l'état du recalcul des métriques déclenché par save_profile."""
    import json as _json
    try:
        from api.user_data import get_user_paths
        paths = get_user_paths(user["id"])
        state_path = os.path.join(paths.base, "sync_state.json")
        if not os.path.exists(state_path):
            return {"status": "idle"}
        with open(state_path, encoding="utf-8") as f:
            state = _json.load(f)
        return {
            "status":     state.get("profile_recompute_status", "idle"),
            "updated_at": state.get("profile_recompute_updated_at"),
            "error":      state.get("profile_recompute_error"),
        }
    except Exception as e:
        return {"status": "idle", "error": str(e)}


@router.post("/garmin-credentials")
def set_garmin(body: GarminCredsBody, user: dict = Depends(get_current_user)):
    save_garmin_credentials(user["id"], body.email, body.password)
    return {"ok": True}
