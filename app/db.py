"""Database module: engines and sessions for the three logical PostgreSQL databases.

Sentinel Auth v3.3 runs as ONE FastAPI process but owns THREE logical
databases on a single PostgreSQL server:

======================  ==============================  ===================
Database                Bounded context                 Module prefix
======================  ==============================  ===================
``sentinel_core``       Core/Auth, IAM, devices, MFA   ``core``
``sentinel_detection``  Detection, policies, SOC alerts ``detection``
``sentinel_ml``         ML registry, inference logs    ``ml``
======================  ==============================  ===================

Each bounded context has its own engine, connection pool and session
factory, so a Detection query can never accidentally run against the Core
schema.  The dependency injection points are:

* :func:`get_core_db`      - ``Depends(get_core_db)``
* :func:`get_detection_db` - ``Depends(get_detection_db)``
* :func:`get_ml_db`        - ``Depends(get_ml_db)``

Canonical schemas live in ``infra/postgres/schema-*-v3.3.sql`` and are
applied by ``infra/postgres/init/00-init-databases.sh``.  The application
never creates tables at runtime: :func:`init_db` is retained for local/unit
test use only and is explicitly deprecated for production bootstrap.

Environment
-----------
``CORE_DATABASE_URL``, ``DETECTION_DATABASE_URL`` and ``ML_DATABASE_URL``
    are the canonical settings and are REQUIRED for their own context.
    ``DATABASE_URL`` is a legacy single-database variable kept for
    backward compatibility.  It is used as a fallback for the **Core**
    context only (Core-monolith compatibility).  Detection and ML refuse
    to fall back to it, because reusing one database for all three
    contexts would put the Detection and ML tables in the Core schema and
    silently break the three-database topology.  A deployment that
    genuinely still runs the single-database layout can opt back in with
    ``ALLOW_LEGACY_SINGLE_DB=1``, which re-enables the fallback for every
    context and logs a loud warning.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger(__name__)


class DatabaseConfigurationError(RuntimeError):
    """Raised when a bounded context cannot resolve its database URL.

    This is a configuration error, not a transient failure: the deployment
    is missing a required URL.  It is raised eagerly (at URL resolution)
    rather than failing later with a confusing "relation does not exist"
    from the wrong database.
    """


def _legacy_single_db_allowed() -> bool:
    """Return True when the legacy single-database fallback is explicitly enabled.

    The opt-in must be deliberate: ``ALLOW_LEGACY_SINGLE_DB=1``.
    """
    return os.getenv(LEGACY_SINGLE_DB_FLAG, "").strip() == "1"


#: Single declarative registry for the whole monolith.
#:
#: Splitting it into ``CoreBase``/``DetectionBase``/``MLBase`` is NOT done
#: here: the ownership boundary is enforced by the session dependency, not
#: by the mapper registry.  Keeping one ``Base`` avoids a large, risky
#: refactor while the three databases run for real.
Base = declarative_base()

#: Default URLs.  They mirror ``docker-compose.yml`` / ``.env.example`` and
#: are only used when the corresponding environment variable is absent.
DEFAULT_CORE_DATABASE_URL = "postgresql://sentinel:sentinel@localhost:5432/sentinel_core"
DEFAULT_DETECTION_DATABASE_URL = "postgresql://sentinel:sentinel@localhost:5432/sentinel_detection"
DEFAULT_ML_DATABASE_URL = "postgresql://sentinel:sentinel@localhost:5432/sentinel_ml"

#: Legacy single-database variable, used only as a documented fallback.
LEGACY_DATABASE_URL_ENV = "DATABASE_URL"

#: Opt-in flag that re-enables the legacy single-database fallback for the
#: Detection and ML contexts.  It exists so an old single-database
#: deployment can keep working, but it must be set EXPLICITLY: silently
#: collapsing three bounded contexts onto one database is exactly the
#: failure mode this architecture is built to prevent.
LEGACY_SINGLE_DB_FLAG = "ALLOW_LEGACY_SINGLE_DB"

#: Bounded-context keys.
CORE = "core"
DETECTION = "detection"
ML = "ml"

#: Per-context environment variable names (canonical).
CONTEXT_ENV_VARS: Dict[str, str] = {
    CORE: "CORE_DATABASE_URL",
    DETECTION: "DETECTION_DATABASE_URL",
    ML: "ML_DATABASE_URL",
}

#: Per-context default URLs.
CONTEXT_DEFAULT_URLS: Dict[str, str] = {
    CORE: DEFAULT_CORE_DATABASE_URL,
    DETECTION: DEFAULT_DETECTION_DATABASE_URL,
    ML: DEFAULT_ML_DATABASE_URL,
}

#: Cache of engines, keyed by context.  Each context gets its OWN engine so
#: the connection pools stay separate.
_engines: Dict[str, Engine] = {}

#: Cache of session factories, keyed by context.
_sessionmakers: Dict[str, sessionmaker] = {}


def resolve_database_url(context: str) -> str:
    """Return the database URL for a bounded context.

    Resolution order:

    1. ``CORE_DATABASE_URL`` / ``DETECTION_DATABASE_URL`` / ``ML_DATABASE_URL``
    2. for the **Core** context only: the legacy ``DATABASE_URL``
    3. the per-context built-in default

    The legacy ``DATABASE_URL`` names a SINGLE database.  Letting the
    Detection and ML contexts fall back to it would collapse all three
    bounded contexts onto one database - exactly the topology this
    architecture exists to prevent - and it would do so silently, with the
    Detection engine writing into the Core schema.

    Therefore the legacy fallback is available to the Core context only
    (Core-monolith compatibility).  Detection and ML **require** their own
    URL.  A deployment that genuinely still runs the single-database layout
    can opt back in explicitly with ``ALLOW_LEGACY_SINGLE_DB=1``, which
    re-enables the fallback for every context and logs a loud warning.

    Raises:
        DatabaseConfigurationError: when a non-Core context has no URL of
            its own and the legacy fallback is not explicitly enabled.
    """
    env_var = CONTEXT_ENV_VARS[context]
    url = os.getenv(env_var)
    if url:
        return url

    legacy = os.getenv(LEGACY_DATABASE_URL_ENV)
    if legacy:
        if context == CORE or _legacy_single_db_allowed():
            logger.warning(
                "%s is not set; falling back to the legacy %s for the %s "
                "database. Set %s explicitly so %s traffic cannot land in "
                "the Core schema.",
                env_var,
                LEGACY_DATABASE_URL_ENV,
                context,
                env_var,
                context,
            )
            return legacy

        raise DatabaseConfigurationError(
            f"{env_var} is not set, so the {context} database cannot be "
            f"resolved. The legacy {LEGACY_DATABASE_URL_ENV} names a single "
            f"database and must not be reused for the {context} context: "
            f"that would put {context} tables in the Core schema and break "
            f"the three-database topology. Set {env_var} to the {context} "
            f"database URL. If you intentionally still run the legacy "
            f"single-database layout, set "
            f"{LEGACY_SINGLE_DB_FLAG}=1 to opt in explicitly."
        )

    return CONTEXT_DEFAULT_URLS[context]


def get_engine(database_url: str, context: Optional[str] = None) -> Engine:
    """Create or return the engine for ``database_url``.

    ``context`` is the bounded-context key.  When given, the engine is cached
    per context, so a second call with a *different* URL for the same context
    replaces the cached engine instead of silently returning the first one.
    """
    if context is None:
        # Legacy, context-free behaviour: a single engine per URL.
        for engine in _engines.values():
            if engine.url.render_as_string(hide_password=False) == database_url:
                return engine
        engine = create_engine(database_url, pool_pre_ping=True)
        _engines["__legacy__"] = engine
        return engine

    engine = _engines.get(context)
    if engine is None or engine.url.render_as_string(hide_password=False) != database_url:
        if engine is not None:
            # The configured URL changed; dispose the stale pool.
            engine.dispose()
        engine = create_engine(database_url, pool_pre_ping=True)
        _engines[context] = engine
    return engine


def get_session_maker(engine: Engine, context: Optional[str] = None) -> sessionmaker:
    """Create or return the session factory bound to ``engine``."""
    if context is None:
        existing = _sessionmakers.get("__legacy__")
        if existing is not None and existing.kw.get("bind") is engine:
            return existing
        maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        _sessionmakers["__legacy__"] = maker
        return maker

    maker = _sessionmakers.get(context)
    if maker is None or maker.kw.get("bind") is not engine:
        maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        _sessionmakers[context] = maker
    return maker


def get_context_session(context: str) -> Session:
    """Return a new session bound to the given bounded context's database."""
    url = resolve_database_url(context)
    engine = get_engine(url, context=context)
    maker = get_session_maker(engine, context=context)
    return maker()


def get_core_db() -> Iterator[Session]:
    """Dependency yielding a session bound to ``sentinel_core``."""
    db = get_context_session(CORE)
    try:
        yield db
    finally:
        db.close()


def get_detection_db() -> Iterator[Session]:
    """Dependency yielding a session bound to ``sentinel_detection``."""
    db = get_context_session(DETECTION)
    try:
        yield db
    finally:
        db.close()


def get_ml_db() -> Iterator[Session]:
    """Dependency yielding a session bound to ``sentinel_ml``."""
    db = get_context_session(ML)
    try:
        yield db
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """Legacy single-database dependency.

    Retained for backward compatibility and for code paths that are genuinely
    database-agnostic.  It routes to the CORE database, which is the only
    database the monolith historically used.  New code must use
    :func:`get_core_db`, :func:`get_detection_db` or :func:`get_ml_db`
    according to the bounded context that owns the data.
    """
    yield from get_core_db()


def dispose_engines() -> None:
    """Dispose every cached engine.  Used by tests that change configuration."""
    for engine in list(_engines.values()):
        engine.dispose()
    _engines.clear()
    _sessionmakers.clear()


def init_db(context: str = CORE) -> None:
    """Create the tables of ONE bounded context in its own database.

    .. deprecated::
        Production bootstrap is owned by
        ``infra/postgres/init/00-init-databases.sh`` which applies the
        canonical ``infra/postgres/schema-*-v3.3.sql`` files.  Calling this
        function against a database that already holds another context's
        schema would break the three-database topology, so it refuses to
        create *all* registered tables and only creates the ones belonging to
        the requested context.

    This helper exists for local experiments and unit tests only.
    """
    from app import models  # noqa: F401  (ensure models are registered)

    context_tables = tables_for_context(context)
    url = resolve_database_url(context)
    engine = get_engine(url, context=context)
    metadata = Base.metadata
    wanted = [metadata.tables[name] for name in context_tables if name in metadata.tables]
    metadata.create_all(bind=engine, tables=wanted, checkfirst=True)


#: Mapping of bounded context -> owned table names.  Derived from the
#: canonical schema files in ``infra/postgres/``.
CONTEXT_TABLES: Dict[str, tuple] = {
    CORE: (
        "roles",
        "users",
        "user_roles",
        "ip_addresses",
        "sessions",
        "mfa_transactions",
        "mfa_notifications",
        "audit_logs",
        "user_trusted_devices",
        "system_settings",
        "outbox_events",
        "user_notifications",
        "rate_limits",
    ),
    DETECTION: (
        "policies",
        "login_attempts",
        "risk_assessments",
        "detection_logs",
        "soc_analysts",
        "alerts",
        "alert_timeline",
    ),
    ML: (
        "model_versions",
        "inference_logs",
        "feature_statistics",
    ),
}


def tables_for_context(context: str) -> tuple:
    """Return the table names owned by a bounded context."""
    try:
        return CONTEXT_TABLES[context]
    except KeyError:
        raise KeyError(f"unknown bounded context {context!r}") from None
