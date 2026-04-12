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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.config import ALLOWED_ORIGINS, IS_PROD, LOG_LEVEL, APP_ENV
from api.routes import activities, charts, gps, reviews, config, records, sync, auth_routes, planning, gear, feedback, workouts, blocks
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


# ── Migration R2 (temporaire — supprimer après migration) ───────────────────

@app.get("/api/migrate-r2")
def migrate_r2(delete_local: bool = False):
    """Endpoint temporaire pour migrer les fichiers vers R2."""
    from api.storage import USE_R2, _USERS_DIR, _R2_MANAGED, _R2_BUCKET
    import os, json

    if not USE_R2:
        return {"error": "R2 non configuré (variables R2_* manquantes)"}

    # Collect files
    pairs = []
    users_dir = _USERS_DIR
    if os.path.isdir(users_dir):
        for user_id in sorted(os.listdir(users_dir)):
            user_base = os.path.join(users_dir, user_id)
            if not os.path.isdir(user_base):
                continue
            for managed_subdir in _R2_MANAGED:
                subdir_path = os.path.join(user_base, managed_subdir)
                if not os.path.isdir(subdir_path):
                    continue
                for fname in os.listdir(subdir_path):
                    fpath = os.path.join(subdir_path, fname)
                    if os.path.isfile(fpath):
                        rel = os.path.relpath(fpath, users_dir).replace("\\", "/")
                        pairs.append((fpath, rel))

    if not pairs:
        return {"status": "nothing to migrate", "files": 0}

    total_mb = sum(os.path.getsize(p) for p, _ in pairs) / 1024 / 1024

    from api.storage import _s3
    s3 = _s3()
    uploaded = 0
    errors = []

    for fpath, key in pairs:
        try:
            ct = "application/json" if key.endswith(".json") else "text/csv"
            with open(fpath, "rb") as f:
                s3.put_object(Bucket=_R2_BUCKET, Key=key, Body=f.read(), ContentType=ct)
            uploaded += 1
            if delete_local:
                os.remove(fpath)
        except Exception as e:
            errors.append(f"{key}: {e}")

    return {
        "status": "done",
        "bucket": _R2_BUCKET,
        "files_uploaded": uploaded,
        "total_mb": round(total_mb, 1),
        "errors": errors[:10],
        "local_deleted": delete_local,
    }

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
