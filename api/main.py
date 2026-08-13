"""
api/main.py — Point d'entrée FastAPI.

Usage :
    # Dev
    uvicorn api.main:app --reload --port 8000

    # Production
    APP_ENV=production ALLOWED_ORIGINS=https://yourdomain.com uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import HTTPException as FastAPIHTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.config import ALLOWED_ORIGINS, IS_PROD, LOG_LEVEL, APP_ENV
from api.routes import activities, charts, gps, reviews, config, records, sync, auth_routes, planning, gear, feedback, workouts, blocks, stadiums
from api.routes import v1_engine, v1_activities, v1_wellness, v1_keys
from api.auth import init_db
from api.migrate import auto_migrate_if_needed

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("coachagent")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND = os.path.join(_ROOT, "frontend")
_CONFIG = os.path.join(_ROOT, "config.json")


# ── Lifecycle ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("APP_ENV=%s, CORS origins=%s", APP_ENV, ALLOWED_ORIGINS)

    if IS_PROD and (not ALLOWED_ORIGINS or ALLOWED_ORIGINS == ["*"]):
        logger.warning("ALLOWED_ORIGINS not set in production! Set it to your domain.")

    # Le référentiel des stades est embarqué dans l'image (Dockerfile). S'il
    # manque, l'onglet "Mes stades" reste vide sans autre signe extérieur.
    if not stadiums.reference_available():
        logger.warning(
            "Référentiel des stades absent — l'onglet \"Mes stades\" restera vide. "
            "Vérifier le COPY data/stades_athle.json du Dockerfile et l'exception .dockerignore."
        )

    # Init user database
    init_db()
    logger.info("Base utilisateurs initialisée")

    # Auto-migrate single-user data if needed
    migrated = auto_migrate_if_needed()
    if migrated:
        logger.info("Migration single-user → multi-user (user=%s)", migrated)

    # Startup : auto-sync si données périmées
    cfg = {}
    if os.path.exists(_CONFIG):
        with open(_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    launched = sync.maybe_auto_sync(cfg)
    if launched:
        logger.info("Auto-sync lancé en background")
    yield

    # Graceful shutdown: wait for running sync threads
    from api.routes.sync import wait_for_sync_threads
    wait_for_sync_threads(timeout=30)


app = FastAPI(title="CoachAgent API", version="1.0.0", lifespan=lifespan)

# ── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "env": APP_ENV}



# ── Routes API ───────────────────────────────────────────────────────────────

app.include_router(auth_routes.router)
app.include_router(activities.router)
app.include_router(charts.router)
app.include_router(gps.router)
app.include_router(reviews.router)
app.include_router(config.router)
app.include_router(records.router)
app.include_router(sync.router)
app.include_router(planning.router)
app.include_router(gear.router)
app.include_router(feedback.router)
app.include_router(workouts.router)
app.include_router(blocks.router)
app.include_router(stadiums.router)

# ── /api/v1 (surface stable pour client externe) ─────────────────────────────

app.include_router(v1_keys.router)
app.include_router(v1_engine.router)
app.include_router(v1_activities.router)
app.include_router(v1_wellness.router)


# Format d'erreur uniforme pour les routes /api/v1 :
# {"error": "<code>", "message": "<texte>"}. Les routes hors v1 conservent
# leur comportement actuel (detail brut) pour ne pas casser le frontend.
@app.exception_handler(FastAPIHTTPException)
async def _v1_http_exception_handler(request: Request, exc: FastAPIHTTPException):
    if request.url.path.startswith("/api/v1") or request.url.path.startswith("/api/auth/api-keys"):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": _default_code_for(exc.status_code),
                "message": str(detail) if detail else "Erreur.",
            },
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def _v1_validation_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/v1") or request.url.path.startswith("/api/auth/api-keys"):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "Paramètres invalides.")
        return JSONResponse(status_code=422, content={
            "error": "invalid_params",
            "message": f"{loc}: {msg}" if loc else msg,
        })
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def _default_code_for(status: int) -> str:
    return {
        400: "invalid_params",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "invalid_params",
    }.get(status, "internal_error")

# ── Cache headers ────────────────────────────────────────────────────────────

@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/"):
        return response
    if IS_PROD:
        # En prod : cache navigateur avec ETag (géré par nginx idéalement)
        if path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "public, max-age=3600"
        elif path.endswith(".html") or path == "/":
            response.headers["Cache-Control"] = "no-cache"
    else:
        # En dev : pas de cache
        if path.endswith((".js", ".css", ".html")) or path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
    return response

# ── Servir le frontend ───────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
