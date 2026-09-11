"""FastAPI application entry point."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.auth import router as auth_router
from app.detection import router as detection_router
from app.ml import router as ml_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    database_url = os.getenv("DATABASE_URL", "postgresql://sentinel:sentinel@postgres:5432/sentinel")
    engine = db.get_engine(database_url)
    db.get_session_maker(engine)
    yield


app = FastAPI(
    title="Sentinel Auth",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(detection_router)
app.include_router(ml_router)


@app.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    """Readiness probe."""
    return {"status": "ready"}
