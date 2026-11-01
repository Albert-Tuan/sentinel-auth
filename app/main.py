"""FastAPI application entry point."""
import importlib
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
from app.login_history import router as login_history_router
from app.manager import router as manager_router

logger = logging.getLogger(__name__)


def _include_optional_router(module_name: str) -> bool:
    """Mount a router whose module may not exist yet.

    The three Manager-analytics routers have three different owners:
    ``app/manager.py`` (Khang), ``app/core_analytics.py`` (Sony) and
    ``app/detection_analytics.py`` (Tuấn Anh).  Only the first exists on
    this branch; the other two are separate deliverables that land
    independently.

    The lead approved mounting all three routers in this file once the
    corresponding modules exist.  A guarded mount honours that approval
    without requiring a second edit to this shared entrypoint when the
    provider modules arrive - and without breaking the application while
    they are still missing.

    Returns True when the router was mounted.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        logger.info(
            "router %s is not available yet - its module has not landed",
            module_name,
        )
        return False
    router = getattr(module, "router", None)
    if router is None:
        logger.warning("module %s declares no 'router' - skipped", module_name)
        return False
    app.include_router(router)
    logger.info("mounted router from %s", module_name)
    return True


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
app.include_router(login_history_router)
app.include_router(manager_router)

# The two internal analytics providers are owned by the Core and Detection
# contexts and land as separate deliverables.  They are mounted when their
# module appears (design document section 7).
_include_optional_router("app.core_analytics")
_include_optional_router("app.detection_analytics")


@app.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    """Readiness probe."""
    return {"status": "ready"}
