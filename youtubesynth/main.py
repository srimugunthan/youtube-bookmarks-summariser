"""FastAPI application with lifespan DB connection."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from youtubesynth.api.routes import router
from youtubesynth.config import settings
from youtubesynth.services.db import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.db_path)
    await db.connect()
    app.state.db = db
    yield
    await db.close()


app = FastAPI(title="YouTubeSynth", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# Serve built React frontend in production (only if static dir exists)
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
