"""
api/main.py — Point d'entrée FastAPI.

Usage :
    uvicorn api.main:app --reload --port 8000
"""

import json
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import activities, charts, gps, reviews, config, records, sync

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND = os.path.join(_ROOT, "frontend")
_CONFIG = os.path.join(_ROOT, "config.json")


# ── Lifecycle ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup : auto-sync si données périmées
    cfg = {}
    if os.path.exists(_CONFIG):
        with open(_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    launched = sync.maybe_auto_sync(cfg)
    if launched:
        print("[startup] Auto-sync lancé en background")
    yield


app = FastAPI(title="CoachAgent API", version="1.0.0", lifespan=lifespan)

# CORS pour dev (frontend servi séparément si besoin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes API
app.include_router(activities.router)
app.include_router(charts.router)
app.include_router(gps.router)
app.include_router(reviews.router)
app.include_router(config.router)
app.include_router(records.router)
app.include_router(sync.router)

# Désactiver le cache navigateur en dev (force le rechargement des JS/CSS)
@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".js", ".css", ".html")) or path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response

# Servir le frontend
app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
