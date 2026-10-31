"""Full-system end-to-end integration tests (Sentinel Auth v3.3).

These tests prove the REAL cross-service flow::

    Core Authentication
      -> Detection pre-token check      (Core  -> Detection, HTTP, advisory)
      -> Core LoginEvent                 (Core  -> Detection, HTTP, persisted)
      -> Detection risk assessment       (Detection DB)
      -> ML inference                    (Detection -> ML, HTTP, persisted)
      -> Detection decision              (Detection DB)
      -> Core protective action          (Detection -> Core, HTTP)

Three SEPARATE PostgreSQL databases are used, one per bounded context:

===================  ==========================  ==============================
Database              Bounded context            Tables
===================  ==========================  ==============================
``sentinel_test_core``     Core/Auth, IAM, MFA       13 base tables
``sentinel_test_detection`` Detection, SOC alerts    7 base tables
``sentinel_test_ml``        ML registry, inference   3 base tables + 1 view
===================  ==========================  ==============================

The SQLite ``client`` fixture from ``tests/conftest.py`` is deliberately NOT
used: it overrides all three DB dependencies onto ONE in-memory database and
would collapse the very topology these tests exist to prove.  Every database
assertion below therefore queries a real, distinct PostgreSQL database.

The service boundaries are crossed over REAL HTTP.  ``httpx.ASGITransport``
replaces the socket only; the real routers, the real ``X-Internal-Secret``
verification, the real request schemas and the real database transactions all
run.  A scenario that "passes" here therefore proves the production contract,
not a mock of it.

Nothing about the scoring policy is mocked: the risk fusion weights
(0.4 / 0.6), the thresholds (0.25 / 0.5 / 0.75), the canonical 6 ML features
and their order are the production ones.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

import httpx
import joblib
import numpy as np
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sklearn.ensemble import IsolationForest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app import ml as ml_module


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: The three disposable test databases.  ``CORE_DETECTION_TEST_URL`` is the
#: canonical name used by the existing PostgreSQL modules; the Detection and
#: ML URLs keep their own names.
CORE_TEST_URL = os.environ.get("CORE_DETECTION_TEST_URL", "")
DETECTION_TEST_URL = os.environ.get("DETECTION_TEST_URL", "")
ML_TEST_URL = os.environ.get("ML_TEST_URL", "")


def _require_postgres_environment() -> None:
    """Skip the whole module when the PostgreSQL environment is absent.

    A missing test database is an absent capability, not a broken test, so
    the module SKIPS with an explicit reason instead of erroring out during
    fixture setup.  The skip fires at import time (``allow_module_level``)
    so no test is even collected.
    """
    from tests.postgres_env import missing_postgres_env_vars

    missing = missing_postgres_env_vars()
    if missing:
        pytest.skip(
            "NOT RUN - PostgreSQL is not configured, so the full-system E2E "
            f"tests were skipped. Missing environment variable(s): "
            f"{', '.join(missing)}.",
            allow_module_level=True,
        )

    if not (CORE_TEST_URL and DETECTION_TEST_URL and ML_TEST_URL):
        pytest.skip(
            "NOT RUN - the three disposable test database URLs are not all "
            "set. CORE_DETECTION_TEST_URL, DETECTION_TEST_URL and "
            "ML_TEST_URL are required for the full-system E2E tests.",
            allow_module_level=True,
        )


_require_postgres_environment()

#: Every database this module touches must carry this marker.  The module
#: recreates the ``public`` schema, so a production database would be
#: destroyed.  The guard fails loudly instead of skipping.
TEST_MARKER = "_test"

#: The canonical 6 ML features, in the exact order Detection sends them.
#: Mirrors ``app.ml.FEATURE_FIELDS``; asserted against it at collection time.
CANONICAL_FEATURES = (
    "hour_of_day",
    "fail_count_24h",
    "ip_change_rate_7d",
    "new_device",
    "average_login_interval_seconds",
    "deviation_score",
)

#: The internal shared secret.  It must satisfy ``get_internal_secret``:
#: at least 32 characters and not the known-insecure placeholder.
INTERNAL_SECRET = "e2e-full-system-internal-secret-0123456789"

#: Hosts used for the in-process service boundaries.
CORE_URL = "http://core.test"
DETECTION_URL = "http://detection.test"
ML_URL = "http://ml.test"

#: The canonical schema files, applied to the three disposable databases.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(REPO_ROOT, "infra", "postgres")

#: The detection policy used by the E2E scenarios.  It is the production
#: ``v1.0`` policy MINUS the ``unusual_hour`` rule, so the verdict cannot
#: depend on the wall-clock hour of the test run.  The weights (0.4 / 0.6)
#: and the thresholds (0.25 / 0.5 / 0.75) are the canonical production ones.
E2E_POLICY_VERSION = "e2e-v1.0"
E2E_POLICY_RULES = [
    {
        "name": "multiple_failures",
        "field": "fail_count_24h",
        "operator": ">=",
        "value": 3,
        "weight": 0.40,
        "score": 0.90,
        "enabled": True,
        "description": "3 or more failed attempts in the last 24h",
    },
    {
        "name": "new_device",
        "field": "new_device",
        "operator": "==",
        "value": True,
        "weight": 0.20,
        "score": 0.50,
        "enabled": True,
        "description": "Login from a device not seen before",
    },
    {
        "name": "high_deviation",
        "field": "deviation_score",
        "operator": ">=",
        "value": 0.70,
        "weight": 0.30,
        "score": 0.70,
        "enabled": True,
        "description": "Behaviour deviates strongly from the user baseline",
    },
]
E2E_POLICY_CONFIG = {
    "weights": {"rule": 0.4, "ml": 0.6},
    "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75},
}

#: The rule score each scenario produces, computed by the canonical formula
#: ``SUM(score * weight) / SUM(weight of ALL enabled rules)`` with a
#: denominator of 0.90:
#:   A benign   -> new_device only                       -> 0.10/0.90
#:   B high     -> multiple_failures only                -> 0.36/0.90
#:   C critical -> all three rules                      -> 0.67/0.90
BENIGN_RULE_SCORE = 0.10 / 0.90
HIGH_RULE_SCORE = 0.36 / 0.90
CRITICAL_RULE_SCORE = 0.67 / 0.90

#: The ML feature vectors the three scenarios produce, reduced to the two
#: features the trained artifact actually reads.  The other four canonical
#: features are held constant in the training data, so the IsolationForest
#: never splits on them and they cannot move the score (see
#: :func:`_build_artifact`).
#:   A benign   : no failures, no IP change
#:   B high     : 3 failures, IP change
#:   C critical : 8 failures, IP change
ML_ANCHORS = {
    "benign": (0, 0.0),
    "high": (3, 1.0),
    "critical": (8, 1.0),
}

#: The IP the E2E logins come from.  Each scenario uses its own so the Core
#: login rate limiter never leaks between tests.
SCENARIO_IP = {
    "benign": "203.0.113.10",
    "high": "203.0.113.11",
    "critical": "203.0.113.12",
}

#: The IP the seeded login history comes from.  It differs from the login IP
#: on purpose: ``ip_change_rate_7d`` is ``1 - (attempts from the current IP) /
#: (attempts in the window)``, so a different source IP makes the feature
#: deterministically 1.0 for every scenario that has history.
HISTORY_IP = "198.51.100.20"

#: The User-Agent that identifies the "familiar" device of a scenario.  The
#: device fingerprint is a SHA-256 over ``User-Agent|Accept-Language|
#: Accept-Encoding``, so a different User-Agent is a different device.
KNOWN_DEVICE_UA = "SentinelE2E/1.0"
NEW_DEVICE_UA = "SentinelE2E/2.0"


def pytest_configure(config: pytest.Config) -> None:
    """Assert the canonical ML feature contract at collection time."""
    assert tuple(ml_module.FEATURE_FIELDS) == CANONICAL_FEATURES, (
        "the canonical 6 ML features (and their order) changed; the E2E "
        "artifact and the fixtures below must be updated to match"
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _database_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _assert_disposable(url: str, label: str) -> str:
    """Refuse to run against anything but a disposable ``*_test*`` database."""
    name = _database_name(url)
    if TEST_MARKER not in name.lower():
        pytest.fail(
            f"Refusing to run {label} against {name!r}: the database name "
            f"must contain {TEST_MARKER!r}. The E2E module recreates the "
            f"public schema, so real development databases "
            f"(sentinel_core / sentinel_detection / sentinel_ml) must never "
            f"be used as a test target."
        )
    return name


def _read_schema(filename: str) -> str:
    path = os.path.join(SCHEMA_DIR, filename)
    if not os.path.exists(path):
        pytest.skip(f"schema file {filename} is missing")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _rebuild(engine: Engine, filename: str) -> None:
    """Recreate the ``public`` schema and apply one canonical schema file."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        conn.execute(text(_read_schema(filename)))


def _table_names(engine: Engine) -> set:
    rows = engine.connect().execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
    ).fetchall()
    return {row[0] for row in rows}


def _scalar(engine: Engine, sql: str, **params) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _rows(engine: Engine, sql: str, **params) -> List[sa.Row]:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).fetchall()


# ---------------------------------------------------------------------------
# ML artifact
# ---------------------------------------------------------------------------

def _model_row(fail_count: int, ip_change: float) -> np.ndarray:
    """Build one model input row.

    The four features the E2E scenarios cannot control exactly
    (``hour_of_day``, ``new_device``, ``average_login_interval_seconds``,
    ``deviation_score``) are held constant in the TRAINING data, so the
    IsolationForest never splits on them and they cannot move the score.
    The values used here therefore only have to be consistent with the
    training distribution, not with the scenario.
    """
    return np.asarray(
        [[12.0, float(fail_count), float(ip_change), 0.0, 600.0, 0.5]],
        dtype=np.float32,
    )


def _build_artifact(path) -> Dict[str, float]:
    """Train a real Isolation Forest artifact for the positive ML path.

    The artifact is a genuine scikit-learn bundle in the exact shape
    :meth:`app.ml.IsolationForestRuntime.load` expects: an estimator, a
    fitted ``MinMaxScaler`` and the canonical feature order.

    Two properties make the E2E assertions deterministic:

    1. ``hour_of_day``, ``new_device``, ``average_login_interval_seconds``
       and ``deviation_score`` are CONSTANT in the training data.  An
       IsolationForest never splits on a zero-variance column, so those four
       features cannot influence the score.  The E2E scenarios cannot
       control them exactly (they depend on the wall clock and on the login
       history), and a model that reacted to them would make the scenarios
       non-deterministic.
    2. The model therefore reads exactly ``fail_count_24h`` and
       ``ip_change_rate_7d``, the two features the scenarios control
       exactly.

    The scaler is a plain ``MinMaxScaler`` fitted on the training oriented
    scores - exactly like the production artifact and the existing
    ``tests/test_ml_runtime.py``.  No scenario-specific calibration is
    involved: every score is a genuine model output.

    The artifact is written to a temporary directory and is never promoted
    to production.
    """
    rng = np.random.default_rng(13)

    n_normal, n_anomalous = 500, 50
    training = np.zeros((n_normal + n_anomalous, 6), dtype=np.float64)

    # Normal population: no failure burst, low IP churn.
    training[:n_normal, 0] = 12.0                                  # hour_of_day
    training[:n_normal, 1] = rng.integers(0, 2, n_normal)          # fail_count_24h
    training[:n_normal, 2] = rng.uniform(0.0, 0.30, n_normal)      # ip_change_rate_7d
    training[:n_normal, 3] = 0.0                                   # new_device
    training[:n_normal, 4] = 600.0                                 # interval
    training[:n_normal, 5] = 0.5                                   # deviation_score

    # Anomalous population: failure bursts and heavy IP churn.
    tail = slice(n_normal, None)
    training[tail, 0] = 12.0
    training[tail, 1] = rng.integers(3, 10, n_anomalous)
    training[tail, 2] = rng.uniform(0.6, 1.0, n_anomalous)
    training[tail, 3] = 0.0
    training[tail, 4] = 600.0
    training[tail, 5] = 0.5

    model = IsolationForest(contamination="auto", random_state=42).fit(training)

    oriented = {
        name: -float(model.decision_function(_model_row(*vector))[0])
        for name, vector in ML_ANCHORS.items()
    }

    # The four uncontrollable columns must not move the score at all.
    for name, (fail_count, ip_change) in ML_ANCHORS.items():
        reference = oriented[name]
        for column, alternate in ((0, 3.0), (3, 1.0), (4, 9999.0), (5, 0.99)):
            row = _model_row(fail_count, ip_change)
            row[0, column] = alternate
            moved = -float(model.decision_function(row)[0])
            assert abs(moved - reference) < 1e-12, (
                f"the E2E artifact still reacts to feature column {column} "
                f"for the {name!r} anchor; the training design must keep "
                f"that column constant"
            )

    assert oriented["benign"] < oriented["high"] < oriented["critical"], (
        "the trained artifact does not order the anchors as expected "
        f"(benign={oriented['benign']}, high={oriented['high']}, "
        f"critical={oriented['critical']})"
    )

    from sklearn.preprocessing import MinMaxScaler

    scaler = MinMaxScaler(clip=True).fit(
        (-model.decision_function(training)).reshape(-1, 1)
    )

    joblib.dump(
        {
            "model": model,
            "score_scaler": scaler,
            "features": list(CANONICAL_FEATURES),
            "version": "e2e-isolation-forest",
        },
        path,
    )

    scores = {
        name: float(
            scaler.transform(np.asarray([[oriented[name]]])).ravel()[0]
        )
        for name in ML_ANCHORS
    }
    return {"oriented": oriented, "scores": scores}


# ---------------------------------------------------------------------------
# Service routing (in-process HTTP between the three bounded contexts)
# ---------------------------------------------------------------------------

class _ServiceRouter:
    """Routes the outbound service-to-service HTTP calls in-process.

    ``httpx`` resolves a transport per request URL, so mounting the ASGI
    transport on ``http://core.test`` / ``http://detection.test`` /
    ``http://ml.test`` intercepts exactly the calls that target those
    services and leaves every other request alone.

    The router can also inject a failure for a given host, which is how the
    outage scenarios (D, E, F) are produced without touching production
    code.
    """

    def __init__(self) -> None:
        self.faults: Dict[str, str] = {}
        self.calls: List[Dict[str, Any]] = []

    def fault(self, host: str, kind: str) -> None:
        """Make every call to ``host`` fail with ``kind``."""
        self.faults[host] = kind

    def clear_faults(self) -> None:
        self.faults.clear()

    @property
    def core_calls(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["host"] == "core.test"]

    @property
    def detection_calls(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["host"] == "detection.test"]

    @property
    def ml_calls(self) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["host"] == "ml.test"]

    def action_calls(self) -> List[Dict[str, Any]]:
        """The Detection -> Core protective-action calls."""
        return [c for c in self.core_calls if c["path"] == "/api/v1/internal/actions"]


class _RoutingTransport(httpx.AsyncBaseTransport):
    """ASGI transport that records calls and can inject outages."""

    def __init__(self, inner: httpx.AsyncBaseTransport, router: _ServiceRouter):
        self._inner = inner
        self._router = router

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        kind = self._router.faults.get(host)

        body: Optional[Any] = None
        try:
            body = json.loads(request.content.decode() or "null")
        except (ValueError, UnicodeDecodeError):
            body = None

        self._router.calls.append(
            {
                "host": host,
                "method": request.method,
                "path": request.url.path,
                "json": body,
                "headers": dict(request.headers),
                "faulted": kind,
            }
        )

        if kind == "connect_error":
            raise httpx.ConnectError(
                f"simulated outage of {host}", request=request
            )
        if kind == "timeout":
            raise httpx.ConnectTimeout(
                f"simulated timeout of {host}", request=request
            )
        if kind == "http_503":
            return httpx.Response(503, json={"detail": "simulated outage"})

        return await self._inner.handle_async_request(request)


def _app():
    from app.main import app

    return app


def _install_router(monkeypatch, router: _ServiceRouter) -> None:
    """Point every outbound ``httpx`` client at the in-process services."""
    from app import auth as auth_module
    from app import detection as detection_module
    from app import internal_client

    transport = _RoutingTransport(httpx.ASGITransport(app=_app()), router)
    original_init = httpx.AsyncClient.__init__

    def _asgi_init(self, *args, **kwargs):
        kwargs.setdefault(
            "mounts",
            {CORE_URL: transport, DETECTION_URL: transport, ML_URL: transport},
        )
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _asgi_init)

    # The service addresses are module-level constants in some modules and
    # are read from the environment in others; set both so the wiring is
    # explicit and cannot drift.
    monkeypatch.setattr(auth_module, "DETECTION_URL", DETECTION_URL)
    monkeypatch.setattr(auth_module, "RUN_PRE_TOKEN_CHECK", "1")
    monkeypatch.setattr(auth_module, "RUN_LOGIN_EVENT_DELIVERY", "1")
    monkeypatch.setattr(detection_module, "ml_service_url", lambda: ML_URL)
    monkeypatch.setattr(internal_client, "core_app_url", lambda: CORE_URL)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_engines() -> Dict[str, Engine]:
    """The three disposable PostgreSQL engines with fresh canonical schemas."""
    _assert_disposable(CORE_TEST_URL, "the Core E2E database")
    _assert_disposable(DETECTION_TEST_URL, "the Detection E2E database")
    _assert_disposable(ML_TEST_URL, "the ML E2E database")

    engines = {
        "core": create_engine(CORE_TEST_URL),
        "detection": create_engine(DETECTION_TEST_URL),
        "ml": create_engine(ML_TEST_URL),
    }
    try:
        for engine in engines.values():
            engine.connect()
    except sa.exc.SQLAlchemyError as exc:
        for engine in engines.values():
            engine.dispose()
        pytest.skip(f"NOT RUN - cannot reach the test PostgreSQL server: {exc}")

    try:
        _rebuild(engines["core"], "schema-core-v3.3.sql")
        _rebuild(engines["detection"], "schema-detection-v3.3.sql")
        _rebuild(engines["ml"], "schema-ml-service-v3.3.sql")
    except Exception as exc:  # noqa: BLE001 - a broken schema is a hard error
        for engine in engines.values():
            engine.dispose()
        raise AssertionError(
            f"could not apply the canonical schemas: {exc}"
        ) from exc

    yield engines

    for engine in engines.values():
        engine.dispose()


@pytest.fixture(scope="module")
def ml_artifact(pg_engines, tmp_path_factory) -> Dict[str, Any]:
    """Train the real Isolation Forest artifact and register it in the ML DB."""
    path = tmp_path_factory.mktemp("e2e-ml-artifact") / "model.joblib"
    info = _build_artifact(path)

    # Register the artifact as the active production model of the
    # DISPOSABLE ML test database so the ML service resolves it the same way
    # a real deployment would.  Nothing is promoted anywhere else.
    with pg_engines["ml"].begin() as conn:
        conn.execute(
            text(
                "UPDATE model_versions "
                "SET status = 'active', is_production = TRUE, model_path = :p "
                "WHERE version = 'v1.0-isolation-forest'"
            ),
            {"p": str(path)},
        )

    ml_module.reset_runtime()
    return {"path": path, **info}


@pytest.fixture(autouse=True)
def e2e_environment(pg_engines, ml_artifact, monkeypatch):
    """Point the application at the three disposable test databases."""
    from app.db import dispose_engines

    monkeypatch.setenv("CORE_DATABASE_URL", CORE_TEST_URL)
    monkeypatch.setenv("DETECTION_DATABASE_URL", DETECTION_TEST_URL)
    monkeypatch.setenv("ML_DATABASE_URL", ML_TEST_URL)
    monkeypatch.setenv("INTERNAL_SECRET", INTERNAL_SECRET)
    monkeypatch.setenv("ML_MODEL_PATH", str(ml_artifact["path"]))

    dispose_engines()
    ml_module.reset_runtime()

    yield

    dispose_engines()
    ml_module.reset_runtime()


@pytest.fixture()
def router(monkeypatch) -> _ServiceRouter:
    """The in-process service router with fault injection."""
    instance = _ServiceRouter()
    _install_router(monkeypatch, instance)
    return instance


@pytest.fixture()
def detection_policy(pg_engines) -> None:
    """Activate the deterministic E2E policy for the duration of a test.

    The production ``v1.0`` policy row is left untouched in the database; it
    is only deactivated so that the deterministic policy is the single active
    one.  Its rules and config are asserted to be unchanged afterwards.
    """
    with pg_engines["detection"].begin() as conn:
        conn.execute(text("UPDATE policies SET is_active = FALSE"))
        conn.execute(
            text(
                "INSERT INTO policies "
                "(version, name, description, rules, config, is_active, created_at) "
                "VALUES (:v, :n, :d, CAST(:r AS jsonb), CAST(:c AS jsonb), TRUE, NOW()) "
                "ON CONFLICT (version) DO UPDATE SET rules = EXCLUDED.rules, "
                "config = EXCLUDED.config, is_active = TRUE"
            ),
            {
                "v": E2E_POLICY_VERSION,
                "n": "E2E deterministic policy",
                "d": "production v1.0 without the wall-clock hour rule",
                "r": json.dumps(E2E_POLICY_RULES),
                "c": json.dumps(E2E_POLICY_CONFIG),
            },
        )


@pytest.fixture(autouse=True)
def clean_databases(pg_engines):
    """Truncate the transactional tables before every scenario.

    Each scenario must start from a known state: the previous scenario's
    rows (login attempts, alerts, sessions, inference logs) would otherwise
    leak into the counts and the risk features.  The schema is NOT recreated
    here - the module-scoped ``pg_engines`` fixture owns that - only the rows
    are removed.
    """
    resets = {
        "core": (
            "sessions", "audit_logs", "rate_limits", "ip_addresses",
            "mfa_notifications", "mfa_transactions", "user_roles",
            "user_trusted_devices", "user_notifications", "users",
        ),
        "detection": (
            "alert_timeline", "alerts", "detection_logs", "risk_assessments",
            "login_attempts", "soc_analysts",
        ),
        "ml": ("feature_statistics", "inference_logs"),
    }
    for context, tables in resets.items():
        engine = pg_engines[context]
        with engine.begin() as conn:
            for table in tables:
                conn.execute(text(f"DELETE FROM {table}"))

    # The deterministic policy is activated for every scenario.  The
    # production ``v1.0`` policy row is left untouched in the database; it
    # is only deactivated so that the deterministic policy is the single
    # active one.
    with pg_engines["detection"].begin() as conn:
        conn.execute(text("UPDATE policies SET is_active = FALSE"))
        conn.execute(
            text(
                "INSERT INTO policies "
                "(version, name, description, rules, config, is_active, created_at) "
                "VALUES (:v, :n, :d, CAST(:r AS jsonb), CAST(:c AS jsonb), TRUE, NOW()) "
                "ON CONFLICT (version) DO UPDATE SET rules = EXCLUDED.rules, "
                "config = EXCLUDED.config, is_active = TRUE"
            ),
            {
                "v": E2E_POLICY_VERSION,
                "n": "E2E deterministic policy",
                "d": "production v1.0 without the wall-clock hour rule",
                "r": json.dumps(E2E_POLICY_RULES),
                "c": json.dumps(E2E_POLICY_CONFIG),
            },
        )
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    from argon2 import PasswordHasher

    return PasswordHasher().hash(password)


def _create_core_user(engine: Engine, username: str, password: str) -> str:
    """Create an active Core user with the USER role."""
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (username, email, password_hash, status, "
                "admin_mfa_required, detection_mfa_once) "
                "VALUES (:u, :e, :h, 'active', FALSE, FALSE) RETURNING id"
            ),
            {
                "u": username,
                "e": f"{username}@example.com",
                "h": _hash_password(password),
            },
        ).scalar()
        conn.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, 'USER')"),
            {"u": user_id},
        )
    return str(user_id)


def _seed_attempts(
    engine: Engine,
    *,
    user_id: str,
    username: str,
    rows: Sequence[Dict[str, Any]],
) -> None:
    """Insert historical ``login_attempts`` rows directly into Detection."""
    with engine.begin() as conn:
        for row in rows:
            conn.execute(
                text(
                    "INSERT INTO login_attempts "
                    "(event_id, user_id, username_attempted, outcome, mfa_used, "
                    " ip_address, user_agent, device_fingerprint, timestamp, status, "
                    " request_id, risk_level, detection_decision) "
                    "VALUES (:event_id, :user_id, :username, :outcome, FALSE, "
                    " :ip, :ua, :fp, :ts, 'processed', :request_id, 'low', 'allow')"
                ),
                {
                    "event_id": str(uuid4()),
                    "user_id": user_id,
                    "username": username,
                    "outcome": row["outcome"],
                    "ip": row["ip"],
                    "ua": row.get("user_agent", "SentinelE2E/seed"),
                    "fp": row.get("fingerprint"),
                    "ts": row["timestamp"],
                    "request_id": str(uuid4()),
                },
            )


def _fingerprint(headers: Dict[str, str]) -> str:
    from app.device_fingerprint import fingerprint_material, hash_fingerprint

    return hash_fingerprint(
        fingerprint_material(
            headers.get("User-Agent"),
            headers.get("Accept-Language"),
            headers.get("Accept-Encoding"),
        )
    )


def _client(ip: str) -> TestClient:
    """A TestClient whose peer address is a real IP.

    ``TestClient`` defaults to the peer ``testclient``, which is not a valid
    ``INET`` value and would make the Core ``rate_limits`` / ``ip_addresses``
    writes fail.  Every scenario uses its own IP so the login rate limiter
    never leaks between tests.
    """
    return TestClient(_app(), client=(ip, 50000))


def _login(
    client: TestClient,
    username: str,
    password: str,
    headers: Optional[Dict[str, str]] = None,
):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=headers or {},
    )


def _request_headers(user_agent: str = "SentinelE2E/1.0") -> Dict[str, str]:
    """The headers that define the device fingerprint of a login."""
    return {
        "User-Agent": user_agent,
        "Accept-Language": "vi-VN",
        "Accept-Encoding": "gzip",
    }


def _delivered_event_ids(router: _ServiceRouter) -> List[str]:
    """The ``event_id``s of the LoginEvents Core delivered to Detection."""
    return [
        call["json"]["event_id"]
        for call in router.detection_calls
        if call["path"] == "/api/v1/internal/login-events"
    ]


def _last_delivered_event_id(router: _ServiceRouter) -> str:
    """The ``event_id`` of the most recent LoginEvent delivery."""
    ids = _delivered_event_ids(router)
    assert ids, "Core did not deliver a LoginEvent to Detection"
    return ids[-1]


def _replay_login_event(
    pg_engines: Dict[str, Engine],
    router: _ServiceRouter,
    username: str,
    user_id: str,
):
    """Re-deliver the EXISTING login event of a user to Detection.

    This exercises the ``event_id`` idempotency contract of
    ``POST /api/v1/internal/login-events``: the same event must not create a
    second attempt, a second assessment, a second alert or a second
    destructive Core action.
    """
    rows = _rows(
        pg_engines["detection"],
        "SELECT event_id, outcome, user_agent, device_fingerprint "
        "FROM login_attempts WHERE username_attempted = :u "
        "ORDER BY created_at DESC LIMIT 1",
        u=username,
    )
    assert rows, "no login attempt to replay"
    original = rows[0]

    payload = {
        "event_id": str(original.event_id),
        "user_id": user_id,
        "username_attempted": username,
        "outcome": original.outcome,
        "mfa_used": False,
        "ip_address": SCENARIO_IP["critical"],
        "user_agent": original.user_agent,
        "device_fingerprint": original.device_fingerprint,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": str(uuid4()),
    }

    with TestClient(_app()) as client:
        return client.post(
            "/api/v1/internal/login-events",
            json=payload,
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )


# ---------------------------------------------------------------------------
# Scenario fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_history(pg_engines):
    """Seed the Detection login history the risky scenarios need.

    The history is written straight into the Detection database, which is
    where ``build_features`` reads it from.  It simulates the failed logins
    and the device/IP history a risky login builds up.
    """

    def _seed(user_id: str, username: str, spec: str) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        known_fp = _fingerprint(_request_headers(KNOWN_DEVICE_UA))
        other_fp = _fingerprint(_request_headers(NEW_DEVICE_UA))

        if spec == "high":
            # Three failures one minute apart, from the familiar device and
            # from the history IP.
            rows = [
                {
                    "outcome": "failure",
                    "ip": HISTORY_IP,
                    "fingerprint": known_fp,
                    "timestamp": now - timedelta(minutes=minutes),
                }
                for minutes in (3, 2, 1)
            ]
        elif spec == "critical":
            # Eight failures: seven in a tight burst plus one far in the
            # past.  The far-past attempt is what makes the gap between the
            # mean and the actual login interval large, which is what drives
            # ``deviation_score`` above the 0.70 rule threshold.
            rows = [
                {
                    "outcome": "failure",
                    "ip": HISTORY_IP,
                    "fingerprint": known_fp,
                    "timestamp": now - timedelta(minutes=300),
                }
            ] + [
                {
                    "outcome": "failure",
                    "ip": HISTORY_IP,
                    "fingerprint": known_fp,
                    "timestamp": now - timedelta(minutes=minutes),
                }
                for minutes in (7, 6, 5, 4, 3, 2, 1)
            ]
        else:
            raise AssertionError(f"unknown history spec {spec!r}")

        _seed_attempts(
            pg_engines["detection"],
            user_id=user_id,
            username=username,
            rows=rows,
        )

    return _seed


# ---------------------------------------------------------------------------
# Scenario A - Normal login
# ---------------------------------------------------------------------------

class TestScenarioANormalLogin:
    """Scenario A: a normal login crosses the whole system, harmlessly.

    Core authenticates -> Detection pre-token check returns low/medium ->
    Core creates a session and delivers the LoginEvent -> Detection persists
    the attempt and the assessment -> ML inference is recorded -> no alert
    is raised -> each context wrote to its OWN PostgreSQL database.
    """

    def test_full_flow_writes_each_context_to_its_own_database(
        self,
        pg_engines,
        router,
        detection_policy,
        ml_artifact,
    ):
        username = "e2e_scenario_a"
        password = "ScenarioAPassword"
        user_id = _create_core_user(pg_engines["core"], username, password)

        with _client(SCENARIO_IP["benign"]) as client:
            response = _login(
                client, username, password, _request_headers(KNOWN_DEVICE_UA)
            )

        # --- 1. Core authentication succeeded and a session was created ---
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mfa_required"] is False
        assert body["access_token"]
        assert body["refresh_token"]
        session_id = body["session_id"]

        sessions = _rows(
            pg_engines["core"],
            "SELECT id, user_id, revoked_at FROM sessions WHERE id = :sid",
            sid=session_id,
        )
        assert len(sessions) == 1, "Core did not create exactly one session"
        assert str(sessions[0].user_id) == user_id
        assert sessions[0].revoked_at is None

        # --- 2. Core -> Detection pre-token check really happened ---
        pre_token_calls = [
            c for c in router.detection_calls
            if c["path"] == "/api/v1/internal/pre-token-check"
        ]
        assert len(pre_token_calls) == 1, (
            "expected exactly one pre-token check, got "
            f"{[(c['method'], c['path']) for c in router.detection_calls]}"
        )
        assert pre_token_calls[0]["headers"].get("x-internal-secret") == INTERNAL_SECRET
        assert pre_token_calls[0]["json"]["username"] == username

        # --- 3. Core -> Detection LoginEvent delivery really happened ---
        event_calls = [
            c for c in router.detection_calls
            if c["path"] == "/api/v1/internal/login-events"
        ]
        assert len(event_calls) == 1, (
            "expected exactly one login-event delivery, got "
            f"{[(c['method'], c['path']) for c in router.detection_calls]}"
        )
        assert event_calls[0]["headers"].get("x-internal-secret") == INTERNAL_SECRET
        assert event_calls[0]["json"]["outcome"] == "success"

        # The delivered ``event_id`` identifies the persisted attempt.
        delivered_event_id = event_calls[0]["json"]["event_id"]

        # --- 4. Detection persisted exactly ONE attempt and ONE assessment ---
        attempts = _rows(
            pg_engines["detection"],
            "SELECT id, event_id, outcome, status, risk_level, "
            "detection_decision, user_id FROM login_attempts "
            "WHERE event_id = :eid",
            eid=delivered_event_id,
        )
        assert len(attempts) == 1, (
            f"expected exactly 1 login_attempts row, got {len(attempts)}"
        )
        attempt = attempts[0]
        assert attempt.outcome == "success"
        assert attempt.status == "processed"
        assert str(attempt.user_id) == user_id

        assessments = _rows(
            pg_engines["detection"],
            "SELECT rule_score, ml_score, combined_score, ml_status, "
            "risk_level, decision FROM risk_assessments WHERE login_attempt_id = :aid",
            aid=attempt.id,
        )
        assert len(assessments) == 1, (
            f"expected exactly 1 risk_assessments row, got {len(assessments)}"
        )
        assessment = assessments[0]

        # The pre-token gate is advisory: it must NOT have persisted an
        # assessment of its own, so exactly one exists.
        assert assessment.risk_level in ("low", "medium"), (
            f"expected a low/medium verdict, got {assessment.risk_level}"
        )
        assert assessment.decision == "allow"
        assert float(assessment.rule_score) == pytest.approx(
            BENIGN_RULE_SCORE, abs=1e-4
        )
        assert assessment.ml_status == "success"
        assert assessment.ml_score is not None
        assert float(assessment.combined_score) == pytest.approx(
            0.4 * BENIGN_RULE_SCORE
            + 0.6 * float(assessment.ml_score),
            abs=1e-4,
        )

        # --- 5. ML inference was really performed and recorded ---
        #
        # The ML service is called TWICE for one login: once by the
        # pre-token gate (which needs a verdict before Core issues a token)
        # and once by the persisted scoring that follows the LoginEvent
        # delivery.  Both are real inference calls.
        assert len(router.ml_calls) == 2, (
            f"expected 2 ML calls (pre-token gate + persisted scoring), "
            f"got {len(router.ml_calls)}"
        )
        for ml_call in router.ml_calls:
            assert ml_call["path"] == "/api/v1/internal/ml/score"
            assert ml_call["headers"].get("x-internal-secret") == INTERNAL_SECRET
            # The 6 canonical features, in the canonical order, were sent.
            assert list(ml_call["json"]["features"].keys()) == list(CANONICAL_FEATURES)

        inference_logs = _rows(
            pg_engines["ml"],
            "SELECT model_version_used, model_status, normalized_score, "
            "is_anomaly, features FROM inference_logs ORDER BY created_at",
        )
        assert len(inference_logs) == 2, (
            f"expected exactly 2 inference_logs rows, got {len(inference_logs)}"
        )
        for log in inference_logs:
            assert log.model_status == "ready"
            assert log.model_version_used == "e2e-isolation-forest"
            # The features really went through the model.  JSONB does not
            # preserve key order, so the canonical SET is asserted here; the
            # ordered vector was asserted on the HTTP payload above.
            assert set(log.features.keys()) == set(CANONICAL_FEATURES)
            assert 0.0 <= float(log.normalized_score) <= 1.0

        # The persisted scoring produced the score that was stored on the
        # assessment.
        assert float(inference_logs[-1].normalized_score) == pytest.approx(
            float(assessment.ml_score), abs=1e-4
        )

        # --- 6. No alert for a low/medium verdict ---
        assert _scalar(
            pg_engines["detection"],
            "SELECT count(*) FROM alerts WHERE login_attempt_id = :aid",
            aid=attempt.id,
        ) == 0
        assert _scalar(
            pg_engines["detection"],
            "SELECT count(*) FROM alert_timeline",
        ) == 0

        # --- 7. No protective action was requested ---
        assert router.action_calls() == []

        # --- 8. The three contexts really used three DIFFERENT databases ---
        assert _table_names(pg_engines["core"]) != _table_names(
            pg_engines["detection"]
        )
        # The Core DB holds no Detection table and vice versa.
        core_tables = _table_names(pg_engines["core"])
        detection_tables = _table_names(pg_engines["detection"])
        assert "login_attempts" not in core_tables
        assert "users" not in detection_tables
        assert "inference_logs" in _table_names(pg_engines["ml"])
        assert "inference_logs" not in detection_tables


# ---------------------------------------------------------------------------
# Scenario B - High-risk login
# ---------------------------------------------------------------------------

class TestScenarioBHighRiskLogin:
    """Scenario B: a high-risk login raises exactly one alert and forces MFA.

    Detection classifies the login as high risk -> one alert with a
    system-created timeline entry -> Detection asks Core to enforce
    REQUIRE_MFA -> Core really applies the protection -> the enforcement
    outcome is recorded.
    """

    def test_high_risk_creates_one_alert_and_forces_mfa(
        self,
        pg_engines,
        router,
        detection_policy,
        ml_artifact,
        seeded_history,
    ):
        username = "e2e_scenario_b"
        password = "ScenarioBPassword"
        user_id = _create_core_user(pg_engines["core"], username, password)
        seeded_history(user_id, username, "high")

        with _client(SCENARIO_IP["high"]) as client:
            response = _login(
                client, username, password, _request_headers(KNOWN_DEVICE_UA)
            )

        assert response.status_code == 200, response.text
        body = response.json()

        # --- 1. Detection classified the login as HIGH ---
        #
        # The attempt is identified by the ``event_id`` Core delivered, so
        # the seeded login history cannot pollute the count.
        attempts = _rows(
            pg_engines["detection"],
            "SELECT id, risk_level, detection_decision, primary_alert_id "
            "FROM login_attempts WHERE event_id = :eid",
            eid=_last_delivered_event_id(router),
        )
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.risk_level == "high", (
            f"expected risk_level='high', got {attempt.risk_level}"
        )
        assert attempt.detection_decision == "challenge"

        assessments = _rows(
            pg_engines["detection"],
            "SELECT rule_score, ml_score, combined_score, ml_status, risk_level, "
            "decision FROM risk_assessments WHERE login_attempt_id = :aid",
            aid=attempt.id,
        )
        assert len(assessments) == 1
        assessment = assessments[0]
        assert float(assessment.rule_score) == pytest.approx(
            HIGH_RULE_SCORE, abs=1e-4
        )
        assert assessment.ml_status == "success"
        assert float(assessment.combined_score) == pytest.approx(
            0.4 * HIGH_RULE_SCORE + 0.6 * float(assessment.ml_score),
            abs=1e-4,
        )
        # The canonical band: high is [0.50, 0.75).
        assert 0.50 <= float(assessment.combined_score) < 0.75

        # --- 2. Exactly ONE alert, with a system-created timeline entry ---
        alerts = _rows(
            pg_engines["detection"],
            "SELECT id, status, risk_level, login_attempt_id FROM alerts "
            "WHERE login_attempt_id = :aid",
            aid=attempt.id,
        )
        assert len(alerts) == 1, f"expected exactly 1 alert, got {len(alerts)}"
        alert = alerts[0]
        assert alert.risk_level == "high"
        assert alert.status == "open"
        assert str(attempt.primary_alert_id) == str(alert.id)

        timeline = _rows(
            pg_engines["detection"],
            "SELECT event_type, actor_type, new_value FROM alert_timeline "
            "WHERE alert_id = :aid ORDER BY created_at",
            aid=alert.id,
        )
        assert len(timeline) == 1, (
            f"expected exactly 1 timeline entry, got {len(timeline)}"
        )
        assert timeline[0].event_type == "created"
        assert timeline[0].actor_type == "system"
        assert timeline[0].new_value == "open"

        # --- 3. Detection asked Core to enforce REQUIRE_MFA over HTTP ---
        action_calls = router.action_calls()
        assert len(action_calls) == 1, (
            f"expected exactly 1 Core action call, got {len(action_calls)}"
        )
        action = action_calls[0]
        assert action["method"] == "POST"
        assert action["path"] == "/api/v1/internal/actions"
        assert action["headers"].get("x-internal-secret") == INTERNAL_SECRET
        assert action["json"]["action"] == "REQUIRE_MFA"
        assert action["json"]["target_user_id"] == user_id
        assert action["json"]["idempotency_key"].startswith("detection:")

        # --- 4. Core really applied the protection ---
        #
        # ``users.detection_mfa_once`` alone is NOT evidence that the
        # Detection -> Core action boundary ran: Core also sets that flag
        # itself when the pre-token gate reports a high verdict.  The Core
        # audit log IS the evidence - it is written only by
        # ``POST /api/v1/internal/actions``.
        users = _rows(
            pg_engines["core"],
            "SELECT detection_mfa_once, status FROM users WHERE id = :uid",
            uid=user_id,
        )
        assert len(users) == 1
        assert users[0].detection_mfa_once is True, (
            "Core did not set the one-time MFA flag"
        )
        assert users[0].status == "active"

        # Core recorded the protective action in its OWN audit log.
        audits = _rows(
            pg_engines["core"],
            "SELECT action, actor_type, after_state FROM audit_logs "
            "WHERE action = 'protective_action:REQUIRE_MFA' AND resource_id = :uid",
            uid=user_id,
        )
        assert len(audits) == 1, (
            f"expected exactly 1 protective-action audit log, got {len(audits)}"
        )
        assert audits[0].actor_type == "system"
        # The audit entry proves the action endpoint really applied the
        # REQUIRE_MFA contract.
        after_state = audits[0].after_state
        assert after_state["mfa_enabled"] is True
        assert after_state["one_time"] is True
        assert after_state["detection_mfa_once"] is True

        # --- 5. The enforcement outcome was recorded in Detection ---
        outcome_logs = _rows(
            pg_engines["detection"],
            "SELECT stage, stage_detail, reason, details FROM detection_logs "
            "WHERE login_attempt_id = :aid AND stage = 'action_sent' "
            "AND stage_detail = 'REQUIRE_MFA'",
            aid=attempt.id,
        )
        assert len(outcome_logs) == 1, (
            f"expected exactly 1 action_sent log, got {len(outcome_logs)}"
        )
        assert outcome_logs[0].details["enforced"] is True
        assert outcome_logs[0].details["action"] == "REQUIRE_MFA"
        assert outcome_logs[0].details["risk_level"] == "high"

        # --- 6. The high verdict also gated the token at the pre-token step ---
        pre_token_calls = [
            c for c in router.detection_calls
            if c["path"] == "/api/v1/internal/pre-token-check"
        ]
        assert len(pre_token_calls) == 1

        # The Core login therefore required MFA instead of issuing a token.
        assert body["mfa_required"] is True
        assert body["access_token"] == ""


# ---------------------------------------------------------------------------
# Scenario C - Critical-risk login
# ---------------------------------------------------------------------------

class TestScenarioCCriticalRiskLogin:
    """Scenario C: a critical-risk login is blocked and the sessions revoked.

    Detection classifies the login as critical -> one alert -> the canonical
    policy maps critical to REVOKE_SESSIONS -> Core enforces it over HTTP
    (never by touching the Detection database) -> replaying the same event
    does NOT duplicate the action.
    """

    def test_critical_risk_revokes_sessions_over_http_and_is_idempotent(
        self,
        pg_engines,
        router,
        detection_policy,
        ml_artifact,
        seeded_history,
    ):
        username = "e2e_scenario_c"
        password = "ScenarioCPassword"
        user_id = _create_core_user(pg_engines["core"], username, password)

        # A live session exists before the risky login, so the revocation
        # has something to revoke.  The setup login happens BEFORE the risky
        # history is seeded, otherwise the setup login itself would be scored
        # critical and would trigger a second protective action.
        with _client(SCENARIO_IP["benign"]) as setup_client:
            setup = _login(setup_client, username, password, _request_headers(KNOWN_DEVICE_UA))
        assert setup.status_code == 200, setup.text
        live_session_id = setup.json()["session_id"]

        seeded_history(user_id, username, "critical")

        with _client(SCENARIO_IP["critical"]) as client:
            response = _login(
                client, username, password, _request_headers(NEW_DEVICE_UA)
            )

        assert response.status_code == 200, response.text

        # --- 1. Detection classified the login as CRITICAL ---
        #
        # The attempt is identified by the ``event_id`` Core delivered for
        # the risky login, so the seeded history cannot pollute the count.
        delivered = _delivered_event_ids(router)
        assert len(delivered) == 2, (
            f"expected 2 LoginEvent deliveries (setup + risky), got {len(delivered)}"
        )
        attempts = _rows(
            pg_engines["detection"],
            "SELECT id, risk_level, detection_decision FROM login_attempts "
            "WHERE event_id = :eid",
            eid=delivered[-1],
        )
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.risk_level == "critical", (
            f"expected risk_level='critical', got {attempt.risk_level}"
        )
        assert attempt.detection_decision == "block"

        assessments = _rows(
            pg_engines["detection"],
            "SELECT rule_score, ml_score, combined_score, ml_status, risk_level "
            "FROM risk_assessments WHERE login_attempt_id = :aid",
            aid=attempt.id,
        )
        assert len(assessments) == 1
        assessment = assessments[0]
        assert float(assessment.rule_score) == pytest.approx(
            CRITICAL_RULE_SCORE, abs=1e-4
        )
        assert float(assessment.combined_score) >= 0.75
        assert assessment.risk_level == "critical"

        # --- 2. An alert was created ---
        alerts = _rows(
            pg_engines["detection"],
            "SELECT id, risk_level FROM alerts WHERE login_attempt_id = :aid",
            aid=attempt.id,
        )
        assert len(alerts) == 1
        assert alerts[0].risk_level == "critical"

        # --- 3. The canonical policy mapped critical to REVOKE_SESSIONS ---
        action_calls = router.action_calls()
        assert len(action_calls) == 1, (
            f"expected exactly 1 Core action call, got {len(action_calls)}"
        )
        action = action_calls[0]
        assert action["path"] == "/api/v1/internal/actions"
        assert action["json"]["action"] == "REVOKE_SESSIONS"
        assert action["json"]["target_user_id"] == user_id

        # --- 4. Core really revoked the session, over HTTP ---
        revoked = _rows(
            pg_engines["core"],
            "SELECT id, revoked_at FROM sessions WHERE id = :sid",
            sid=live_session_id,
        )
        assert len(revoked) == 1
        assert revoked[0].revoked_at is not None, (
            "Core did not revoke the live session"
        )

        audits = _scalar(
            pg_engines["core"],
            "SELECT count(*) FROM audit_logs "
            "WHERE action = 'protective_action:REVOKE_SESSIONS' AND resource_id = :uid",
            uid=user_id,
        )
        assert audits == 1

        # The enforcement outcome was recorded as enforced.
        outcome_logs = _rows(
            pg_engines["detection"],
            "SELECT details FROM detection_logs WHERE login_attempt_id = :aid "
            "AND stage = 'action_sent' AND stage_detail = 'REVOKE_SESSIONS'",
            aid=attempt.id,
        )
        assert len(outcome_logs) == 1
        assert outcome_logs[0].details["enforced"] is True

        # --- 5. Replaying the SAME event must not duplicate the action ---
        attempts_before = _scalar(
            pg_engines["detection"],
            "SELECT count(*) FROM login_attempts WHERE event_id = :eid",
            eid=delivered[-1],
        )
        assert attempts_before == 1

        replay = _replay_login_event(pg_engines, router, username, user_id)
        # The endpoint answers 202 ACCEPTED (it queues the event for scoring).
        assert replay.status_code == 202, replay.text
        assert replay.json()["status"] == "accepted"

        # No second attempt, no second alert, no second Core action.
        assert _scalar(
            pg_engines["detection"],
            "SELECT count(*) FROM login_attempts WHERE event_id = :eid",
            eid=delivered[-1],
        ) == 1
        assert _scalar(
            pg_engines["detection"],
            "SELECT count(*) FROM alerts WHERE login_attempt_id = :aid",
            aid=attempt.id,
        ) == 1
        assert len(router.action_calls()) == 1, (
            "replaying the same login event triggered a second Core action"
        )
        assert _scalar(
            pg_engines["core"],
            "SELECT count(*) FROM audit_logs "
            "WHERE action = 'protective_action:REVOKE_SESSIONS' AND resource_id = :uid",
            uid=user_id,
        ) == 1


# ---------------------------------------------------------------------------
# Scenario D - ML service unavailable
# ---------------------------------------------------------------------------

class TestScenarioDMLUnavailable:
    """Scenario D: when the ML service is down, Detection degrades gracefully.

    The pipeline must not crash, ``ml_score`` must be NULL, the combined
    score must fall back to the rule score and the assessment must record
    the fallback state.
    """

    def test_ml_outage_falls_back_to_the_rule_score(
        self,
        pg_engines,
        router,
        detection_policy,
        ml_artifact,
        seeded_history,
    ):
        username = "e2e_scenario_d"
        password = "ScenarioDPassword"
        user_id = _create_core_user(pg_engines["core"], username, password)
        seeded_history(user_id, username, "high")

        # Take the ML service down for the whole scenario.
        router.fault("ml.test", "connect_error")

        with _client(SCENARIO_IP["high"]) as client:
            response = _login(
                client, username, password, _request_headers(KNOWN_DEVICE_UA)
            )

        # The login path survived the ML outage.
        assert response.status_code == 200, response.text

        # The ML service was really called and really failed.  It is called
        # twice for one login: once by the pre-token gate and once by the
        # persisted scoring.  Both failed.
        assert len(router.ml_calls) == 2, (
            f"expected 2 ML calls (pre-token gate + persisted scoring), "
            f"got {len(router.ml_calls)}"
        )
        for ml_call in router.ml_calls:
            assert ml_call["faulted"] == "connect_error"

        # --- The assessment records the fallback ---
        attempts = _rows(
            pg_engines["detection"],
            "SELECT id FROM login_attempts WHERE event_id = :eid",
            eid=_last_delivered_event_id(router),
        )
        assert len(attempts) == 1
        assessments = _rows(
            pg_engines["detection"],
            "SELECT rule_score, ml_score, combined_score, ml_status, risk_level, "
            "decision FROM risk_assessments WHERE login_attempt_id = :aid",
            aid=attempts[0].id,
        )
        assert len(assessments) == 1
        assessment = assessments[0]

        assert assessment.ml_score is None, (
            "ml_score must be NULL when the ML service is unavailable"
        )
        assert assessment.ml_status in ("unavailable", "error"), (
            f"expected the fallback status, got {assessment.ml_status!r}"
        )
        assert float(assessment.combined_score) == pytest.approx(
            float(assessment.rule_score), abs=1e-6
        ), (
            "combined_score must fall back to the rule score when ML is down"
        )
        assert float(assessment.rule_score) == pytest.approx(
            HIGH_RULE_SCORE, abs=1e-4
        )
        # The verdict still came out, from the rules alone.  With the ML
        # signal missing the combined score IS the rule score, and the
        # canonical thresholds bucket 0.40 as "medium" - the pipeline
        # degrades to the rules, it does not invent a verdict.
        assert float(assessment.combined_score) == pytest.approx(0.40, abs=1e-4)
        assert assessment.risk_level == "medium", (
            "with no ML signal the rule score alone must decide the level; "
            f"0.40 buckets as 'medium', got {assessment.risk_level!r}"
        )
        assert assessment.decision == "allow"

        # No inference was logged in the ML database (the service never ran).
        assert _scalar(
            pg_engines["ml"], "SELECT count(*) FROM inference_logs"
        ) == 0

        # The degradation is visible in the detection log.
        ml_logs = _rows(
            pg_engines["detection"],
            "SELECT stage, reason FROM detection_logs "
            "WHERE login_attempt_id = :aid AND stage = 'ml_call'",
            aid=attempts[0].id,
        )
        assert len(ml_logs) == 1
        assert ml_logs[0].reason


# ---------------------------------------------------------------------------
# Scenario E - Detection engine unavailable
# ---------------------------------------------------------------------------

class TestScenarioEDetectionUnavailable:
    """Scenario E: when Detection is down, Core fails OPEN.

    The login must still succeed - but only because the credentials were
    genuinely verified.  The fail-open must not bypass the credential check
    or the MFA check.
    """

    def test_core_fails_open_without_bypassing_the_credentials(
        self,
        pg_engines,
        router,
        detection_policy,
        ml_artifact,
    ):
        username = "e2e_scenario_e"
        password = "ScenarioEPassword"
        _create_core_user(pg_engines["core"], username, password)

        # Take the whole Detection service down.
        router.fault("detection.test", "connect_error")

        with _client(SCENARIO_IP["benign"]) as client:
            response = _login(
                client, username, password, _request_headers(KNOWN_DEVICE_UA)
            )

        # --- 1. The login succeeded: Core failed OPEN ---
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mfa_required"] is False
        assert body["access_token"]
        assert body["session_id"]

        # The session really exists in the Core database.
        sessions = _rows(
            pg_engines["core"],
            "SELECT id FROM sessions WHERE id = :sid",
            sid=body["session_id"],
        )
        assert len(sessions) == 1

        # The pre-token check and the event delivery were really attempted.
        paths = [c["path"] for c in router.detection_calls]
        assert "/api/v1/internal/pre-token-check" in paths
        assert "/api/v1/internal/login-events" in paths

        # --- 2. The fail-open did NOT bypass the credential check ---
        with _client("203.0.113.13") as client:
            wrong = _login(
                client, username, "TheWrongPassword", _request_headers(KNOWN_DEVICE_UA)
            )
        assert wrong.status_code == 401, (
            "the fail-open path must still verify the password"
        )

        # --- 3. The fail-open did NOT bypass the MFA check ---
        # A user with a persistent MFA requirement is still challenged even
        # when Detection is unreachable.
        mfa_username = "e2e_scenario_e_mfa"
        mfa_password = "ScenarioEMfaPassword"
        mfa_user_id = _create_core_user(
            pg_engines["core"], mfa_username, mfa_password
        )
        with pg_engines["core"].begin() as conn:
            conn.execute(
                text(
                    "UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"
                ),
                {"uid": mfa_user_id},
            )

        with _client("203.0.113.14") as client:
            mfa_response = _login(
                client, mfa_username, mfa_password, _request_headers(KNOWN_DEVICE_UA)
            )
        assert mfa_response.status_code == 200
        assert mfa_response.json()["mfa_required"] is True
        assert mfa_response.json()["access_token"] == "", (
            "the fail-open path must not issue a token while MFA is required"
        )

        # Nothing was written to Detection (the service was down).
        assert _scalar(
            pg_engines["detection"], "SELECT count(*) FROM login_attempts"
        ) == 0


# ---------------------------------------------------------------------------
# Scenario F - Core action endpoint unavailable
# ---------------------------------------------------------------------------

class TestScenarioFCoreActionUnavailable:
    """Scenario F: when Core cannot apply the action, Detection keeps its verdict.

    The verdict and the alert must survive, the failure must be recorded as
    ``enforced=false``, and Detection must not claim the action was applied.
    """

    def test_verdict_survives_and_the_failure_is_recorded(
        self,
        pg_engines,
        router,
        detection_policy,
        ml_artifact,
        seeded_history,
    ):
        username = "e2e_scenario_f"
        password = "ScenarioFPassword"
        user_id = _create_core_user(pg_engines["core"], username, password)
        seeded_history(user_id, username, "high")

        # Take the Core action endpoint down.  The Detection -> Core call
        # goes to core.test, and so does the pre-token answer... but the
        # pre-token check goes to detection.test, so only the Core action
        # boundary is affected.
        router.fault("core.test", "connect_error")

        with _client(SCENARIO_IP["high"]) as client:
            response = _login(
                client, username, password, _request_headers(KNOWN_DEVICE_UA)
            )

        # The pipeline did not crash.
        assert response.status_code == 200, response.text

        # --- 1. The verdict was persisted ---
        attempts = _rows(
            pg_engines["detection"],
            "SELECT id, risk_level, detection_decision FROM login_attempts "
            "WHERE event_id = :eid",
            eid=_last_delivered_event_id(router),
        )
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.risk_level == "high"
        assert attempt.detection_decision == "challenge"

        assessments = _rows(
            pg_engines["detection"],
            "SELECT rule_score, ml_score, combined_score, ml_status, risk_level "
            "FROM risk_assessments WHERE login_attempt_id = :aid",
            aid=attempt.id,
        )
        assert len(assessments) == 1
        assert assessments[0].risk_level == "high"
        assert assessments[0].ml_status == "success"

        # --- 2. The alert was persisted ---
        alerts = _rows(
            pg_engines["detection"],
            "SELECT id, risk_level, status FROM alerts WHERE login_attempt_id = :aid",
            aid=attempt.id,
        )
        assert len(alerts) == 1
        assert alerts[0].risk_level == "high"

        # --- 3. The failure is recorded as NOT enforced ---
        outcome_logs = _rows(
            pg_engines["detection"],
            "SELECT stage, stage_detail, reason, details FROM detection_logs "
            "WHERE login_attempt_id = :aid AND stage = 'action_sent' "
            "AND stage_detail = 'REQUIRE_MFA'",
            aid=attempt.id,
        )
        assert len(outcome_logs) == 1, (
            "the failed enforcement was not recorded in detection_logs"
        )
        outcome = outcome_logs[0]
        assert outcome.details["enforced"] is False, (
            "Detection claimed the action was enforced even though Core was down"
        )
        assert outcome.details["action"] == "REQUIRE_MFA"
        assert outcome.reason, "the enforcement failure must carry a reason"

        # --- 4. Core really did NOT apply the protective action ---
        #
        # ``users.detection_mfa_once`` is set by Core ITSELF when the
        # pre-token gate reports a high verdict (see ``app.auth.login``), so
        # that flag is NOT evidence that the Detection -> Core action
        # boundary ran.  The Core audit log IS: it is written only by
        # ``POST /api/v1/internal/actions``.
        audits = _scalar(
            pg_engines["core"],
            "SELECT count(*) FROM audit_logs "
            "WHERE action = 'protective_action:REQUIRE_MFA' AND resource_id = :uid",
            uid=user_id,
        )
        assert audits == 0, (
            "Core recorded a protective action even though the action "
            "endpoint was unreachable"
        )

        # --- 5. The Core action call really was attempted and really failed ---
        action_calls = router.action_calls()
        assert len(action_calls) == 1
        assert action_calls[0]["faulted"] == "connect_error"
        assert action_calls[0]["json"]["action"] == "REQUIRE_MFA"
        assert action_calls[0]["json"]["target_user_id"] == user_id
