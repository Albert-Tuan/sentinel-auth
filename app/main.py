"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.client_ip import validate_proxy_trust_config
from app.auth import router as auth_router
from app.iam import router as iam_router
from app.detection import router as detection_router, policy_router
from app.internal_actions import router as internal_actions_router
from app.ml import router as ml_router
from app.alerts import router as alerts_router
from app.devices import router as devices_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events.

    The application never creates tables here.  The three logical databases
    are bootstrapped by ``infra/postgres/init/00-init-databases.sh`` from the
    canonical ``infra/postgres/schema-*-v3.3.sql`` files; calling
    ``Base.metadata.create_all`` here would create every Core + Detection +
    ML table inside ONE database and destroy the three-database topology.
    """
    # Reject FORWARDED_ALLOW_IPS="*" before accepting any connections.
    validate_proxy_trust_config()

    # Warm one engine/session-factory per bounded context so the first
    # request of each context does not pay the connection setup cost.
    for context in (db.CORE, db.DETECTION, db.ML):
        url = db.resolve_database_url(context)
        engine = db.get_engine(url, context=context)
        db.get_session_maker(engine, context=context)
        logger.info(
            "database context %s -> %s",
            context,
            engine.url.render_as_string(hide_password=True),
        )

    yield

    db.dispose_engines()


app = FastAPI(
    title="Sentinel Auth",
    version="3.3.0",
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
app.include_router(iam_router)
app.include_router(detection_router)
app.include_router(policy_router)
app.include_router(internal_actions_router)
app.include_router(ml_router)
app.include_router(alerts_router)
app.include_router(devices_router)


@app.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    """Readiness probe."""
    return {"status": "ready"}
