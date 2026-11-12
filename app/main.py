"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status

from app import db
from app.client_ip import validate_proxy_trust_config
from app.cors_config import install_cors_middleware, resolve_cors_origins
from app.internal_auth import (
    InternalAuthConfigurationError,
    get_internal_secret,
)
from app.readiness import readiness_payload_async
from app.auth import router as auth_router
from app.iam import router as iam_router
from app.detection import router as detection_router, policy_router
from app.internal_actions import router as internal_actions_router
from app.ml import router as ml_router
from app.alerts import router as alerts_router
from app.devices import router as devices_router
from app.login_history import router as login_history_router
from app.manager import router as manager_router
from app.core_analytics import router as core_analytics_router
from app.detection_analytics import router as detection_analytics_router

logger = logging.getLogger(__name__)


class InternalSecretConfigurationError(RuntimeError):
    """Raised at startup when ``INTERNAL_SECRET`` is not securely configured.

    The service-to-service boundary is the only authentication the internal
    endpoints have.  A deployment without a usable secret would answer 503
    on every internal route and fail OPEN on every outbound service call -
    the pre-token risk check would silently stop gating logins.  Failing at
    startup is the honest outcome: the operator has to fix the
    configuration instead of running with a disabled boundary.
    """


def _validate_internal_secret_configuration() -> None:
    """Verify that a usable ``INTERNAL_SECRET`` is configured.

    The secret value is never logged and never included in the error
    message - only the reason it was rejected is.
    """
    try:
        get_internal_secret()
    except InternalAuthConfigurationError as exc:
        raise InternalSecretConfigurationError(
            f"the internal service secret is not usable: {exc}. "
            "Generate one with: python3 -c 'import secrets; "
            "print(secrets.token_urlsafe(32))'"
        ) from None
    logger.info("the internal service secret is configured")


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

    # Reject an unconfigured internal secret before accepting any
    # connections.  Without it every internal endpoint answers 503 and
    # every OUTBOUND service call (the login-event delivery, the pre-token
    # risk check) degrades to a fail-open path, so a deployment that lost
    # its secret would silently run with its service boundary disabled.
    # The secret itself is never logged.
    _validate_internal_secret_configuration()

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

# =============================================================================
# CORS
# =============================================================================
# The allow-list is read from ``CORS_ALLOWED_ORIGINS`` and defaults to the
# origins the local deployment itself is served at.  A wildcard origin is
# refused outright: combined with credentialed requests it lets any website
# read authenticated responses.  See ``app/cors_config.py``.
_allowed_origins = resolve_cors_origins()
install_cors_middleware(app, _allowed_origins)
logger.info(
    "CORS allowed origins: %s",
    ", ".join(_allowed_origins) if _allowed_origins else "<none: same-origin only>",
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
# contexts (design document section 7).  They are mounted **explicitly**:
# a missing provider module must fail the application startup rather than
# silently disappear from the route table, because a Manager facade that
# cannot reach a provider reports a false "degraded" state instead of a
# missing dependency.
app.include_router(core_analytics_router)
app.include_router(detection_analytics_router)


@app.get("/health")
async def health() -> dict:
    """Liveness probe.

    It answers "is this process alive?" and deliberately consults NO
    dependency: a database that is down must not make an orchestrator
    restart a perfectly healthy process.
    """
    return {"status": "ok"}


@app.get("/ready")
async def ready(response: Response) -> dict:
    """Readiness probe.

    It answers "can this process serve traffic right now?" by probing the
    minimum dependencies the monolith needs: the Core, Detection and ML
    databases.  The probe is strictly read-only (``SELECT 1`` per context)
    and never loads the ML artifact or runs an inference.

    A missing database answers ``503`` - the service cannot serve the
    requests that need that context.  A missing ML *artifact* is a
    different failure: the Detection Engine falls back to a rule-only
    score, so the service stays ready and reports itself as degraded.

    The probe runs in a worker thread, so the database wait never holds the
    event loop.  See ``app/readiness.py`` for the full contract.
    """
    payload = await readiness_payload_async()
    if payload.get("status") != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
