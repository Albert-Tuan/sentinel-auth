"""Live-provider integration tests for the Security Manager facade (M10).

What is proved
--------------
``tests/test_manager_analytics.py`` exercises the facade against **contract
stubs**: the payloads of design sections 4.1 / 4.2.  That proves the
reshaping, the KPI math and the degradation logic, but it cannot prove that
the two upstream providers - ``app/core_analytics.py`` (Core context) and
``app/detection_analytics.py`` (Detection context) - actually agree with the
facade.

This module closes that gap.  Nothing is stubbed:

* the application runs against **three real PostgreSQL databases** -
  ``sentinel_core_test`` (Core), ``sentinel_detection_test`` (Detection) and
  ``sentinel_ml_test`` (ML), each rebuilt from the canonical
  ``infra/postgres/schema-*-v3.3.sql`` files;
* the Manager facade reaches Core and Detection over **real HTTP**: an
  ``httpx.ASGITransport`` replaces the socket only, so the real routers, the
  real ``X-Internal-Secret`` verification, the real request parsing and the
  real SQL against the real databases all run;
* the ML source is read **directly** from ``sentinel_ml``, exactly as
  production does;
* the RBAC check uses **real opaque bearer tokens**: the SHA-256 hash of the
  token is stored in ``sessions.access_token_hash`` and the role is resolved
  from ``user_roles`` x ``roles`` in real time.

Every assertion therefore compares the facade's answer against the database
state it is supposed to summarise, computed from the fixture - not against a
second copy of the implementation.

The deterministic fixture
--------------------------
The reporting window is fixed and absolute::

    [2026-10-01T00:00:00Z, 2026-10-02T00:00:00Z)

so every number below is reproducible and independent of the wall clock.  The
fixture deliberately contains the boundary cases the design calls out:

* a session created exactly at ``from`` (included) and one created exactly at
  ``to`` (excluded);
* an alert acknowledged **after** ``to`` - it must contribute to neither the
  acknowledgement count nor MTTA;
* an alert whose current status is ``acknowledged`` **and** another that was
  acknowledged and later resolved - so the event-based
  ``acknowledged_count`` and the current-status ``by_status.acknowledged``
  are different numbers on the same fixture;
* a critical alert created exactly at ``to`` - it is outside every
  window-scoped aggregate but still inside the current-backlog
  ``critical_incidents`` list;
* an ML inference whose ``model_version_id`` is NULL, so the version
  attribution falls back to ``model_version_used``.

Configuration::

    CORE_DETECTION_TEST_URL   disposable Core database
    DETECTION_TEST_URL        disposable Detection database
    ML_TEST_URL               disposable ML database

When any of them is absent the module SKIPS with an explicit reason - it
never fabricates a pass.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import joblib
import numpy as np
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CORE_TEST_URL = os.environ.get("CORE_DETECTION_TEST_URL", "")
DETECTION_TEST_URL = os.environ.get("DETECTION_TEST_URL", "")
ML_TEST_URL = os.environ.get("ML_TEST_URL", "")

#: Every database this module touches must carry this marker.  The module
#: recreates the ``public`` schema, so a production database would be
#: destroyed.  The guard fails loudly instead of skipping.
TEST_MARKER = "_test"

#: The internal shared secret.  It must satisfy ``get_internal_secret``:
#: at least 32 characters and not the known-insecure placeholder.
INTERNAL_SECRET = "m10-live-manager-internal-secret-0123456789"

#: The hosts the outbound service-to-service calls target.  They are the
#: in-process stand-ins for the Core and Detection services.
CORE_URL = "http://core.test"
DETECTION_URL = "http://detection.test"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(REPO_ROOT, "infra", "postgres")

#: The fixed reporting window: half-open ``[from, to)``.
WINDOW_FROM = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
WINDOW_TO = datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)

#: A window with no data at all - used for the empty-population checks.
EMPTY_FROM = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
EMPTY_TO = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)

#: The five public Manager endpoints.
MANAGER_ENDPOINTS = (
    "/api/v1/manager/dashboard",
    "/api/v1/manager/trends",
    "/api/v1/manager/alerts",
    "/api/v1/manager/soc-kpi",
    "/api/v1/manager/ml-stats",
)

#: The version of the live ML artifact and of its registry row.
LIVE_MODEL_VERSION = "m10-live-isolation-forest"


def _require_postgres_environment() -> None:
    """Skip the whole module when the three test databases are absent."""
    if not (CORE_TEST_URL and DETECTION_TEST_URL and ML_TEST_URL):
        pytest.skip(
            "NOT RUN - the three disposable test database URLs are not all "
            "set. CORE_DETECTION_TEST_URL, DETECTION_TEST_URL and "
            "ML_TEST_URL are required for the live Manager integration tests.",
            allow_module_level=True,
        )


_require_postgres_environment()


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
            f"must contain {TEST_MARKER!r}. This module recreates the "
            f"public schema, so a real development database "
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


def _rows(engine: Engine, sql: str, **params: Any) -> List[sa.Row]:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).fetchall()


def _scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _hash_token(token: str) -> str:
    """The SHA-256 hash the Core session table stores for an opaque token."""
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# ML artifact
# ---------------------------------------------------------------------------

def _build_artifact(path) -> str:
    """Train a real Isolation Forest bundle for the ML runtime.

    The bundle has exactly the shape ``app.ml.IsolationForestRuntime.load``
    expects: an estimator, a fitted ``MinMaxScaler``, the canonical feature
    order and a version string.  It is a genuine scikit-learn artifact - the
    Manager reports ``model_status: "ready"`` only when this file really
    loads.
    """
    from app import ml as ml_module

    rng = np.random.default_rng(7)
    training = rng.uniform(size=(200, 6))
    training[:, 0] *= 23
    training[:, 1] *= 8
    training[:, 4] *= 10_000

    model = IsolationForest(contamination="auto", random_state=42).fit(training)
    oriented = -model.decision_function(training)
    scaler = MinMaxScaler(clip=True).fit(oriented.reshape(-1, 1))

    joblib.dump(
        {
            "model": model,
            "score_scaler": scaler,
            "features": list(ml_module.FEATURE_FIELDS),
            "version": LIVE_MODEL_VERSION,
        },
        path,
    )
    return LIVE_MODEL_VERSION


# ---------------------------------------------------------------------------
# The in-process service boundary (outbound HTTP)
# ---------------------------------------------------------------------------

class _ServiceRouter:
    """Records the outbound service-to-service calls and injects outages.

    The facade's Core / Detection calls must cross a **real HTTP boundary**.
    ``httpx.ASGITransport`` replaces the socket only; the real router, the
    real secret verification and the real SQL run.  The router records every
    call so a test can prove the facade really used the boundary (and not a
    direct function call), and it can fail a host to exercise the
    degradation contract of design section 6.1.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.faults: Dict[str, str] = {}

    def fault(self, host: str, kind: str) -> None:
        """Make every call to ``host`` fail with ``kind``."""
        self.faults[host] = kind

    def clear_faults(self) -> None:
        self.faults.clear()

    def paths_for(self, host: str) -> List[str]:
        return [c["path"] for c in self.calls if c["host"] == host]

    def calls_for(self, host: str) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["host"] == host]


class _FaultTransport(httpx.AsyncBaseTransport):
    """Injects a transport-level or HTTP-level failure."""

    def __init__(self, kind: str):
        self.kind = kind

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.kind == "connect_error":
            raise httpx.ConnectError(
                "simulated outage", request=request
            )
        if self.kind == "timeout":
            raise httpx.ReadTimeout("simulated timeout", request=request)
        if self.kind == "http_500":
            return httpx.Response(500, json={"detail": "simulated upstream failure"})
        if self.kind == "invalid_json":
            return httpx.Response(200, content=b"<html>not json at all</html>")
        raise AssertionError(f"unknown fault kind {self.kind!r}")


class _RecordingTransport(httpx.AsyncBaseTransport):
    """ASGI transport that records the request and can inject an outage.

    The request is recorded **before** the fault is applied, so a test can
    prove the facade really attempted the call.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, router: _ServiceRouter,
                 host: str):
        self._inner = inner
        self._router = router
        self._host = host

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._router.calls.append(
            {
                "host": self._host,
                "method": request.method,
                "path": request.url.path,
                "url": str(request.url),
                "headers": dict(request.headers),
            }
        )
        kind = self._router.faults.get(self._host)
        if kind:
            return await _FaultTransport(kind).handle_async_request(request)
        return await self._inner.handle_async_request(request)


def _install_router(monkeypatch, router: _ServiceRouter) -> None:
    """Point every outbound ``httpx`` client at the in-process services."""
    from app.main import app as fastapi_app

    inner = httpx.ASGITransport(app=fastapi_app)
    core_transport = _RecordingTransport(inner, router, "core.test")
    detection_transport = _RecordingTransport(inner, router, "detection.test")

    original_init = httpx.AsyncClient.__init__

    def _asgi_init(self, *args, **kwargs):
        kwargs.setdefault(
            "mounts",
            {CORE_URL: core_transport, DETECTION_URL: detection_transport},
        )
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _asgi_init)


# ---------------------------------------------------------------------------
# The deterministic fixture
# ---------------------------------------------------------------------------

#: The bearer tokens of the fixture users.  Their SHA-256 hashes are stored
#: in ``sessions.access_token_hash``; the RBAC layer resolves them for real.
TOKENS = {
    "manager": "live-manager-token",
    "analyst": "live-analyst-token",
    "admin": "live-admin-token",
    "plain": "live-plain-token",
    "suspended": "live-suspended-token",
    "expired": "live-expired-token",
}

#: A session that never expires - the "active" sessions of the fixture.
FOREVER = datetime(2099, 1, 1, tzinfo=UTC)
#: A session that expired long ago.
PAST = datetime(2020, 1, 1, tzinfo=UTC)


def _seed_core(engine: Engine) -> Dict[str, Any]:
    """Seed the Core database with the deterministic fixture.

    The users cover every RBAC case (manager / analyst / admin / plain /
    suspended / expired session).  The sessions cover the window boundaries:
    one created exactly at ``from`` (included), one exactly at ``to``
    (excluded), one revoked inside the window, and the bearer-token sessions.
    """
    ids: Dict[str, Any] = {}

    with engine.begin() as conn:
        for table in (
            "audit_logs", "mfa_transactions", "sessions",
            "user_roles", "users",
        ):
            conn.execute(text(f"DELETE FROM {table}"))

        # --- users ---------------------------------------------------------
        users = [
            # key, username, status, mfa_required, forced_mfa, failed, created
            ("manager", "live_mgr", "active", False, False, 0,
             datetime(2026, 10, 1, 0, 10, tzinfo=UTC)),
            ("analyst", "live_analyst", "active", False, False, 0,
             datetime(2026, 10, 1, 0, 20, tzinfo=UTC)),
            ("admin", "live_admin", "active", False, False, 0,
             datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
            ("plain", "live_plain", "active", False, False, 0,
             datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
            ("suspended", "live_suspended", "suspended", False, False, 0,
             datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
            ("locked", "live_locked", "locked", False, False, 0,
             datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
            ("mfa", "live_mfa", "active", True, False, 0,
             datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
            ("forced", "live_forced", "active", False, True, 0,
             datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
            ("failed", "live_failed", "active", False, False, 3,
             datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
        ]
        for key, username, status, mfa, forced, failed, created in users:
            user_id = str(uuid4())
            ids[key] = user_id
            conn.execute(
                text(
                    "INSERT INTO users (id, username, password_hash, email, "
                    "status, admin_mfa_required, detection_mfa_once, "
                    "failed_login_count, created_at) "
                    "VALUES (:id, :u, 'argon2-hash', :e, :s, :m, :f, :fc, :c)"
                ),
                {
                    "id": user_id, "u": username, "e": f"{username}@example.com",
                    "s": status, "m": mfa, "f": forced, "fc": failed, "c": created,
                },
            )

        # --- roles ---------------------------------------------------------
        role_map = {
            "manager": ["USER", "SECURITY_MANAGER"],
            "analyst": ["USER", "SOC_ANALYST"],
            "admin": ["USER", "SECURITY_ADMIN"],
            "plain": ["USER"],
            "suspended": ["USER"],
            "locked": ["USER"],
            "mfa": ["USER"],
            "forced": ["USER"],
            "failed": ["USER"],
        }
        for key, roles in role_map.items():
            for role in roles:
                conn.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id) "
                        "VALUES (:u, :r)"
                    ),
                    {"u": ids[key], "r": role},
                )

        # --- sessions ------------------------------------------------------
        #
        # s1/s2/s3/s4 are created inside the window; s5 exactly at ``to``
        # (excluded) and s6 just before ``from`` (excluded).  s7 is revoked
        # inside the window.  s8..s11 are the bearer-token sessions and s12
        # is an expired session.
        sessions = [
            # key, user, created_at, expires_at, revoked_at
            ("s1", "plain", datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC), FOREVER, None),
            ("s2", "plain", datetime(2026, 10, 1, 0, 30, tzinfo=UTC), FOREVER, None),
            ("s3", "manager", datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC), FOREVER, None),
            ("s4", "plain", datetime(2026, 10, 1, 23, 59, 59, tzinfo=UTC), FOREVER, None),
            ("s5", "plain", datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC), FOREVER, None),
            ("s6", "analyst", datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC), FOREVER, None),
            ("s7", "analyst", datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC), FOREVER,
             datetime(2026, 10, 1, 5, 0, 0, tzinfo=UTC)),
            ("s8", "analyst", datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC), FOREVER, None),
            ("s9", "admin", datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC), FOREVER, None),
            ("s10", "plain", datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC), FOREVER, None),
            ("s11", "suspended", datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC), FOREVER, None),
            ("s12", "plain", datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC), PAST, None),
        ]
        session_ids: Dict[str, str] = {}
        for key, user, created, expires, revoked in sessions:
            session_id = str(uuid4())
            session_ids[key] = session_id
            conn.execute(
                text(
                    "INSERT INTO sessions (id, user_id, access_token_hash, "
                    "expires_at, revoked_at, created_at) "
                    "VALUES (:id, :u, :h, :e, :r, :c)"
                ),
                {
                    "id": session_id, "u": ids[user],
                    "h": _hash_token(f"unrelated-{key}"),
                    "e": expires, "r": revoked, "c": created,
                },
            )

        # The bearer-token sessions carry the real token hashes.
        token_sessions = {
            "manager": ("s3", "manager"),
            "analyst": ("s8", "analyst"),
            "admin": ("s9", "admin"),
            "plain": ("s10", "plain"),
            "suspended": ("s11", "suspended"),
            "expired": ("s12", "plain"),
        }
        for token_key, (session_key, _user) in token_sessions.items():
            conn.execute(
                text(
                    "UPDATE sessions SET access_token_hash = :h WHERE id = :s"
                ),
                {"h": _hash_token(TOKENS[token_key]), "s": session_ids[session_key]},
            )

        # --- mfa transactions ---------------------------------------------
        mfa_rows = [
            ("mfa", "completed", datetime(2026, 10, 1, 1, 10, tzinfo=UTC)),
            ("mfa", "failed", datetime(2026, 10, 1, 1, 20, tzinfo=UTC)),
            ("mfa", "expired", datetime(2026, 10, 1, 1, 30, tzinfo=UTC)),
            ("mfa", "pending", datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)),
        ]
        for user, status, created in mfa_rows:
            conn.execute(
                text(
                    "INSERT INTO mfa_transactions (user_id, status, expires_at, "
                    "created_at) VALUES (:u, :s, :e, :c)"
                ),
                {
                    "u": ids[user], "s": status,
                    "e": datetime(2026, 10, 1, 2, 0, tzinfo=UTC), "c": created,
                },
            )

        # --- audit logs ----------------------------------------------------
        audit_rows = [
            ("login_success", "user", ids["plain"], "session",
             datetime(2026, 10, 1, 1, 0, tzinfo=UTC)),
            ("login_success", "user", ids["plain"], "session",
             datetime(2026, 10, 1, 2, 0, tzinfo=UTC)),
            ("protective_action:REVOKE_SESSIONS", "system", None, "user",
             datetime(2026, 10, 1, 3, 0, tzinfo=UTC)),
            ("logout", "user", ids["analyst"], "session",
             datetime(2026, 10, 1, 4, 0, tzinfo=UTC)),
            ("login_success", "user", ids["plain"], "session",
             datetime(2026, 10, 2, 0, 0, tzinfo=UTC)),
        ]
        for action, actor_type, actor_id, resource, created in audit_rows:
            conn.execute(
                text(
                    "INSERT INTO audit_logs (actor_id, actor_type, action, "
                    "resource, created_at) VALUES (:a, :t, :ac, :r, :c)"
                ),
                {
                    "a": actor_id, "t": actor_type, "ac": action,
                    "r": resource, "c": created,
                },
            )

    ids["sessions"] = session_ids
    return ids


def _seed_detection(engine: Engine, core_ids: Dict[str, Any]) -> Dict[str, Any]:
    """Seed the Detection database with the deterministic fixture."""
    ids: Dict[str, Any] = {}

    with engine.begin() as conn:
        for table in (
            "alert_timeline", "alerts", "detection_logs",
            "risk_assessments", "login_attempts", "soc_analysts",
        ):
            conn.execute(text(f"DELETE FROM {table}"))

        # --- login attempts ------------------------------------------------
        attempts = [
            # key, outcome, risk, decision, timestamp
            ("la1", "success", "low", "allow",
             datetime(2026, 10, 1, 1, 0, tzinfo=UTC)),
            ("la2", "failure", "medium", "challenge",
             datetime(2026, 10, 1, 2, 0, tzinfo=UTC)),
            ("la3", "blocked", "critical", "block",
             datetime(2026, 10, 1, 3, 0, tzinfo=UTC)),
            ("la4", "success", "low", "allow",
             datetime(2026, 10, 1, 23, 0, tzinfo=UTC)),
            ("la5", "mfa_failed", "high", "challenge",
             datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)),
            ("la6", "success", "low", "allow",
             datetime(2026, 9, 30, 23, 0, tzinfo=UTC)),
        ]
        attempt_ids: Dict[str, str] = {}
        for key, outcome, risk, decision, when in attempts:
            attempt_id = str(uuid4())
            attempt_ids[key] = attempt_id
            conn.execute(
                text(
                    "INSERT INTO login_attempts (id, event_id, user_id, "
                    "username_attempted, outcome, mfa_used, timestamp, status, "
                    "risk_level, detection_decision, created_at) "
                    "VALUES (:id, :e, :u, :un, :o, FALSE, :t, 'processed', "
                    ":r, :d, :t)"
                ),
                {
                    "id": attempt_id, "e": str(uuid4()),
                    "u": core_ids["plain"], "un": "live_plain",
                    "o": outcome, "t": when, "r": risk, "d": decision,
                },
            )

        # --- risk assessments ---------------------------------------------
        assessments = [
            ("la1", "success", 0.1000, datetime(2026, 10, 1, 1, 1, tzinfo=UTC)),
            ("la2", "unavailable", 0.5000, datetime(2026, 10, 1, 2, 1, tzinfo=UTC)),
            ("la3", "error", 0.9000, datetime(2026, 10, 1, 3, 1, tzinfo=UTC)),
            ("la4", "success", 0.2000, datetime(2026, 10, 1, 23, 1, tzinfo=UTC)),
            # excluded: created exactly at ``to``
            ("la5", "success", 0.7000, datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)),
        ]
        for attempt, ml_status, score, created in assessments:
            conn.execute(
                text(
                    "INSERT INTO risk_assessments (login_attempt_id, rule_score, "
                    "ml_score, combined_score, ml_status, created_at) "
                    "VALUES (:a, 0.5, :m, :c, :s, :cr)"
                ),
                {
                    "a": attempt_ids[attempt], "m": score, "c": score,
                    "s": ml_status, "cr": created,
                },
            )

        # --- SOC analysts --------------------------------------------------
        analyst_id = str(uuid4())
        idle_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO soc_analysts (id, user_id, display_name, "
                "is_active) VALUES (:id, :u, 'Live Analyst', TRUE)"
            ),
            {"id": analyst_id, "u": core_ids["analyst"]},
        )
        conn.execute(
            text(
                "INSERT INTO soc_analysts (id, user_id, display_name, "
                "is_active) VALUES (:id, :u, 'Idle Analyst', FALSE)"
            ),
            {"id": idle_id, "u": core_ids["admin"]},
        )

        # --- alerts --------------------------------------------------------
        alerts = [
            # key, attempt, status, risk, created, assigned, resolved,
            #         detection_scores
            ("al1", "la1", "open", "low",
             datetime(2026, 10, 1, 1, 30, tzinfo=UTC), None, None,
             {"rule_hits": [{"rule_name": "unusual_hour", "triggered": True}],
              "ml_reason_codes": ["unusual_hour"]}),
            ("al2", "la2", "acknowledged", "high",
             datetime(2026, 10, 1, 2, 30, tzinfo=UTC), analyst_id, None,
             {"rule_hits": [{"rule_name": "multiple_failures", "triggered": True},
                            {"rule_name": "new_device", "triggered": False}],
              "ml_reason_codes": ["new_ip"]}),
            ("al3", "la3", "resolved", "critical",
             datetime(2026, 10, 1, 3, 30, tzinfo=UTC), None,
             datetime(2026, 10, 1, 6, 0, tzinfo=UTC),
             {"rule_hits": [{"rule_name": "new_device", "triggered": True}],
              "ml_reason_codes": ["new_device", "high_fail_count"]}),
            ("al4", "la4", "false_positive", "medium",
             datetime(2026, 10, 1, 23, 30, tzinfo=UTC), None, None,
             {"rule_hits": [{"rule_name": "unusual_hour", "triggered": False}],
              "ml_reason_codes": []}),
            # excluded from every window-scoped aggregate (created at ``to``),
            # but still part of the current critical backlog.
            ("al5", "la5", "open", "critical",
             datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC), None, None,
             {"rule_hits": [{"rule_name": "multiple_failures", "triggered": True}],
              "ml_reason_codes": ["new_ip"]}),
            # acknowledged AFTER ``to`` - contributes to neither the
            # acknowledgement count nor MTTA.
            ("al6", "la6", "open", "high",
             datetime(2026, 10, 1, 10, 0, tzinfo=UTC), None, None,
             {"rule_hits": [{"rule_name": "multiple_failures", "triggered": True}],
              "ml_reason_codes": ["new_ip"]}),
        ]
        alert_ids: Dict[str, str] = {}
        for key, attempt, status, risk, created, assigned, resolved, scores in alerts:
            alert_id = str(uuid4())
            alert_ids[key] = alert_id
            conn.execute(
                text(
                    "INSERT INTO alerts (id, login_attempt_id, status, "
                    "risk_level, detection_reason, detection_scores, "
                    "assigned_to_id, resolved_at, created_at) "
                    "VALUES (:id, :a, :s, :r, :dr, CAST(:sc AS jsonb), :as, :rs, :c)"
                ),
                {
                    "id": alert_id, "a": attempt_ids[attempt], "s": status,
                    "r": risk, "dr": f"{status} alert",
                    "sc": json.dumps(scores), "as": assigned,
                    "rs": resolved, "c": created,
                },
            )

        # --- alert timeline ------------------------------------------------
        timeline = [
            ("al1", "created", datetime(2026, 10, 1, 1, 30, tzinfo=UTC)),
            ("al1", "acknowledged", datetime(2026, 10, 1, 5, 0, tzinfo=UTC)),
            ("al2", "created", datetime(2026, 10, 1, 2, 30, tzinfo=UTC)),
            ("al2", "acknowledged", datetime(2026, 10, 1, 4, 0, tzinfo=UTC)),
            ("al2", "escalated", datetime(2026, 10, 1, 5, 0, tzinfo=UTC)),
            ("al3", "created", datetime(2026, 10, 1, 3, 30, tzinfo=UTC)),
            ("al3", "acknowledged", datetime(2026, 10, 1, 7, 0, tzinfo=UTC)),
            ("al3", "resolved", datetime(2026, 10, 1, 6, 0, tzinfo=UTC)),
            ("al4", "created", datetime(2026, 10, 1, 23, 30, tzinfo=UTC)),
            ("al4", "false_positive", datetime(2026, 10, 1, 23, 45, tzinfo=UTC)),
            ("al5", "created", datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)),
            ("al6", "created", datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),
            # after ``to`` - must not count
            ("al6", "acknowledged", datetime(2026, 10, 2, 1, 0, tzinfo=UTC)),
        ]
        for alert, event, when in timeline:
            conn.execute(
                text(
                    "INSERT INTO alert_timeline (alert_id, event_type, "
                    "actor_type, created_at) VALUES (:a, :e, 'system', :c)"
                ),
                {"a": alert_ids[alert], "e": event, "c": when},
            )

        # --- detection logs (enforcement) ----------------------------------
        enforcement = [
            (True, datetime(2026, 10, 1, 2, 10, tzinfo=UTC)),
            (False, datetime(2026, 10, 1, 2, 20, tzinfo=UTC)),
            # excluded: created exactly at ``to``
            (True, datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)),
        ]
        for enforced, when in enforcement:
            conn.execute(
                text(
                    "INSERT INTO detection_logs (login_attempt_id, stage, "
                    "stage_detail, details, created_at) "
                    "VALUES (:a, 'action_sent', 'REQUIRE_MFA', "
                    "CAST(:d AS jsonb), :c)"
                ),
                {
                    "a": attempt_ids["la2"],
                    "d": json.dumps({"enforced": enforced}),
                    "c": when,
                },
            )
        # A log of another stage must not be counted as an enforcement attempt.
        conn.execute(
            text(
                "INSERT INTO detection_logs (login_attempt_id, stage, "
                "stage_detail, details, created_at) "
                "VALUES (:a, 'rule_evaluation', 'multiple_failures', "
                "CAST(:d AS jsonb), :c)"
            ),
            {
                "a": attempt_ids["la2"],
                "d": json.dumps({"enforced": True}),
                "c": datetime(2026, 10, 1, 2, 5, tzinfo=UTC),
            },
        )

    ids["attempts"] = attempt_ids
    ids["alerts"] = alert_ids
    ids["analyst"] = analyst_id
    return ids


def _seed_ml(engine: Engine, model_id: str, model_path: str) -> None:
    """Seed the ML database with the deterministic fixture."""
    with engine.begin() as conn:
        for table in ("feature_statistics", "inference_logs", "model_versions"):
            conn.execute(text(f"DELETE FROM {table}"))

        conn.execute(
            text(
                "INSERT INTO model_versions (id, name, version, algorithm, "
                "model_path, config, status, is_production, training_date, "
                "deployed_at) VALUES (:id, 'Live Isolation Forest', :v, "
                "'IsolationForest', :p, CAST(:c AS jsonb), 'active', TRUE, "
                ":td, :dd)"
            ),
            {
                "id": model_id, "v": LIVE_MODEL_VERSION, "p": model_path,
                "c": json.dumps({"contamination": "auto"}),
                "td": datetime(2026, 9, 20, tzinfo=UTC),
                "dd": datetime(2026, 9, 21, tzinfo=UTC),
            },
        )

        inferences = [
            # created, score, anomaly, status, ms, codes, registry_id
            (datetime(2026, 10, 1, 5, 0, tzinfo=UTC), 0.9, True, "ready", 10,
             ["high_fail_count"], True),
            (datetime(2026, 10, 1, 6, 0, tzinfo=UTC), 0.1, False, "ready", 20,
             [], True),
            (datetime(2026, 10, 1, 7, 0, tzinfo=UTC), 0.2, False, "error", 30,
             [], True),
            (datetime(2026, 10, 1, 8, 0, tzinfo=UTC), 0.3, False, "degraded", 40,
             ["new_device"], True),
            # excluded: created exactly at ``to``; no registry id either, so
            # the version attribution falls back to ``model_version_used``.
            (datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC), 0.4, False, "ready", 50,
             [], False),
        ]
        for created, score, anomaly, status, ms, codes, with_id in inferences:
            conn.execute(
                text(
                    "INSERT INTO inference_logs (request_id, model_version_id, "
                    "model_version_used, features, normalized_score, "
                    "is_anomaly, reason_codes, model_status, processing_time_ms, "
                    "created_at) VALUES (:r, :id, :v, CAST(:f AS jsonb), :s, "
                    ":a, CAST(:c AS jsonb), :st, :ms, :cr)"
                ),
                {
                    "r": str(uuid4()),
                    "id": model_id if with_id else None,
                    "v": LIVE_MODEL_VERSION,
                    "f": json.dumps({"hour_of_day": 12, "fail_count_24h": 2,
                                     "ip_change_rate_7d": 0.1, "new_device": False,
                                     "average_login_interval_seconds": 600,
                                     "deviation_score": 0.5}),
                    "s": score, "a": anomaly,
                    "c": json.dumps(codes), "st": status, "ms": ms, "cr": created,
                },
            )

        conn.execute(
            text(
                "INSERT INTO feature_statistics (feature_name, timestamp, "
                "count, mean, std, min, max, p25, p50, p75, p95, anomaly_rate) "
                "VALUES ('fail_count_24h', :t, 100, 1.21, 0.83, 0, 9, 0, 1, 2, "
                "4, 0.12)"
            ),
            {"t": datetime(2026, 10, 1, 9, 0, tzinfo=UTC)},
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_engines() -> Dict[str, Engine]:
    """The three disposable PostgreSQL engines with fresh canonical schemas."""
    _assert_disposable(CORE_TEST_URL, "the live Manager Core database")
    _assert_disposable(DETECTION_TEST_URL, "the live Manager Detection database")
    _assert_disposable(ML_TEST_URL, "the live Manager ML database")

    engines = {
        "core": create_engine(CORE_TEST_URL, pool_pre_ping=True),
        "detection": create_engine(DETECTION_TEST_URL, pool_pre_ping=True),
        "ml": create_engine(ML_TEST_URL, pool_pre_ping=True),
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
        raise AssertionError(f"could not apply the canonical schemas: {exc}") from exc

    yield engines

    for engine in engines.values():
        engine.dispose()


@pytest.fixture(scope="module")
def ml_artifact(pg_engines, tmp_path_factory) -> Dict[str, Any]:
    """Train the real Isolation Forest artifact and register it in the ML DB."""
    path = tmp_path_factory.mktemp("m10-live-ml-artifact") / "model.joblib"
    version = _build_artifact(path)

    model_id = str(uuid4())
    with pg_engines["ml"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO model_versions (id, name, version, algorithm, "
                "model_path, config, status, is_production, training_date, "
                "deployed_at) VALUES (:id, 'Live Isolation Forest', :v, "
                "'IsolationForest', :p, CAST(:c AS jsonb), 'active', TRUE, "
                ":td, :dd)"
            ),
            {
                "id": model_id, "v": version, "p": str(path),
                "c": json.dumps({"contamination": "auto"}),
                "td": datetime(2026, 9, 20, tzinfo=UTC),
                "dd": datetime(2026, 9, 21, tzinfo=UTC),
            },
        )

    return {"path": path, "version": version, "model_id": model_id}


@pytest.fixture(scope="module", autouse=True)
def live_environment(pg_engines, ml_artifact):
    """Point the application at the three disposable test databases.

    The environment variables are set for the whole module and restored
    afterwards, so a test run never leaks the test URLs into another module.
    """
    from app import ml as ml_module
    from app.db import dispose_engines

    previous = {
        name: os.environ.get(name)
        for name in (
            "CORE_DATABASE_URL", "DETECTION_DATABASE_URL", "ML_DATABASE_URL",
            "INTERNAL_SECRET", "CORE_APP_URL", "DETECTION_URL", "ML_MODEL_PATH",
        )
    }

    os.environ["CORE_DATABASE_URL"] = CORE_TEST_URL
    os.environ["DETECTION_DATABASE_URL"] = DETECTION_TEST_URL
    os.environ["ML_DATABASE_URL"] = ML_TEST_URL
    os.environ["INTERNAL_SECRET"] = INTERNAL_SECRET
    os.environ["CORE_APP_URL"] = CORE_URL
    os.environ["DETECTION_URL"] = DETECTION_URL
    os.environ["ML_MODEL_PATH"] = str(ml_artifact["path"])

    dispose_engines()
    ml_module.reset_runtime()

    yield

    dispose_engines()
    ml_module.reset_runtime()
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture()
def seeded(pg_engines, ml_artifact) -> Dict[str, Any]:
    """Seed the deterministic fixture into the three databases."""
    core_ids = _seed_core(pg_engines["core"])
    detection_ids = _seed_detection(pg_engines["detection"], core_ids)
    _seed_ml(pg_engines["ml"], ml_artifact["model_id"], str(ml_artifact["path"]))
    return {"core": core_ids, "detection": detection_ids}


@pytest.fixture()
def router(monkeypatch) -> _ServiceRouter:
    """The in-process service router with fault injection."""
    instance = _ServiceRouter()
    _install_router(monkeypatch, instance)
    return instance


@pytest.fixture()
def ml_unavailable():
    """Make the ML context unavailable for the duration of a test.

    The route binds ``Depends(get_optional_ml_db)`` at import time, so the
    dependency is replaced through FastAPI's own override mechanism - the
    supported way to swap a bound dependency.
    """
    from app.main import app as fastapi_app
    from app.manager import get_optional_ml_db

    def _no_ml_db():
        return None

    fastapi_app.dependency_overrides[get_optional_ml_db] = _no_ml_db
    try:
        yield
    finally:
        fastapi_app.dependency_overrides.pop(get_optional_ml_db, None)


@pytest.fixture()
def client(seeded, router):
    """A TestClient bound to the real application and the real databases."""
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as test_client:
        yield test_client


def _auth(token_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[token_key]}"}


def _window_params(**extra: Any) -> Dict[str, Any]:
    params = {
        "from": WINDOW_FROM.isoformat(),
        "to": WINDOW_TO.isoformat(),
    }
    params.update(extra)
    return params


def _get(client: TestClient, path: str, token_key: str = "manager",
         **params: Any) -> httpx.Response:
    """GET a Manager endpoint with the fixed window unless overridden."""
    merged = _window_params()
    merged.update(params)
    return client.get(path, params=merged, headers=_auth(token_key))


def _walk_numbers(payload: Any, prefix: str = "") -> List[Any]:
    """Yield ``(path, value)`` for every numeric leaf of a JSON payload.

    A numeric leaf that reached the response as a **string** is the
    serialisation bug design section 7.0.1 forbids, so the walker reports
    every leaf that is a string but *looks* like a number.
    """
    found: List[Any] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.extend(_walk_numbers(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_walk_numbers(value, f"{prefix}[{index}]"))
    elif isinstance(payload, str):
        try:
            float(payload)
        except ValueError:
            return found
        # A string that parses as a number is a numeric field that was
        # serialised as a string.
        found.append((prefix, payload))
    return found


# ---------------------------------------------------------------------------
# The live wiring
# ---------------------------------------------------------------------------

class TestLiveProviderWiring:
    """The facade really talks to the two providers over HTTP."""

    def test_the_core_provider_is_reached_over_http_with_the_internal_secret(
        self, client, router
    ):
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text

        core_calls = router.calls_for("core.test")
        assert core_calls, "the Core provider was never called"
        call = core_calls[0]
        assert call["path"] == "/api/v1/internal/analytics/core"
        assert call["method"] == "GET"
        assert call["headers"].get("x-internal-secret") == INTERNAL_SECRET

    def test_the_detection_provider_is_reached_over_http_with_the_internal_secret(
        self, client, router
    ):
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text

        detection_calls = router.calls_for("detection.test")
        assert detection_calls, "the Detection provider was never called"
        call = detection_calls[0]
        assert call["path"] == "/api/v1/internal/analytics/detection"
        assert call["method"] == "GET"
        assert call["headers"].get("x-internal-secret") == INTERNAL_SECRET

    def test_the_window_is_forwarded_to_the_providers_verbatim(self, client, router):
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text

        for host in ("core.test", "detection.test"):
            call = router.calls_for(host)[0]
            query = parse_qs(urlparse(call["url"]).query)
            assert query["from"] == [WINDOW_FROM.isoformat()]
            assert query["to"] == [WINDOW_TO.isoformat()]

    def test_all_three_databases_are_separate_and_are_the_real_ones(
        self, client, pg_engines
    ):
        """The facade answered from three DIFFERENT PostgreSQL databases."""
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text

        core_users = _scalar(pg_engines["core"], "SELECT count(*) FROM users")
        detection_attempts = _scalar(
            pg_engines["detection"], "SELECT count(*) FROM login_attempts"
        )
        ml_inferences = _scalar(
            pg_engines["ml"], "SELECT count(*) FROM inference_logs"
        )
        assert core_users == 9
        assert detection_attempts == 6
        assert ml_inferences == 5

        body = response.json()
        assert body["core"]["total_users"] == core_users
        assert body["detection"]["login_attempts"] == 4
        assert body["ml"]["inferences"] == 4

    def test_the_core_provider_only_touches_the_core_database(
        self, client, pg_engines
    ):
        """The Core provider must not be able to read the other contexts.

        The Core database holds no ``login_attempts`` and no
        ``inference_logs`` table at all, so a provider that tried to join
        across contexts would raise - the endpoint would be a 500, never a
        200.  A clean 200 with the Core numbers is the proof that the
        provider stayed inside its own database.
        """
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text

        for table in ("login_attempts", "inference_logs", "alerts"):
            exists = _scalar(
                pg_engines["core"],
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t",
                t=table,
            )
            assert exists == 0, (
                f"the Core database unexpectedly owns the table {table!r} - "
                f"the three-database topology is broken"
            )

        body = response.json()
        assert body["core"]["total_users"] == 9
        assert body["core"]["sessions_created"] == 4

    def test_the_detection_provider_only_touches_the_detection_database(
        self, client, pg_engines
    ):
        """Same for Detection: no Core table and no ML table over there."""
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text

        for table in ("users", "sessions", "inference_logs"):
            exists = _scalar(
                pg_engines["detection"],
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t",
                t=table,
            )
            assert exists == 0, (
                f"the Detection database unexpectedly owns the table "
                f"{table!r} - the three-database topology is broken"
            )

        body = response.json()
        assert body["detection"]["login_attempts"] == 4

    def test_the_manager_reads_only_the_ml_database_directly(self, client,
                                                              pg_engines):
        """The facade owns no SQL for Core or Detection - it reads ML only."""
        for table in ("users", "sessions", "login_attempts", "alerts"):
            exists = _scalar(
                pg_engines["ml"],
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t",
                t=table,
            )
            assert exists == 0, (
                f"the ML database unexpectedly owns the table {table!r} - the "
                f"bounded-context boundary is broken"
            )

        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        assert response.json()["ml"]["inferences"] == 4


class TestExplicitRouterMounting:
    """``app/main.py`` mounts the providers explicitly (requirement 1)."""

    def test_the_provider_routers_are_mounted_in_the_route_table(self):
        from app.main import app as fastapi_app

        paths = {route.path for route in fastapi_app.routes}
        assert "/api/v1/internal/analytics/core" in paths
        assert "/api/v1/internal/analytics/detection" in paths
        for path in MANAGER_ENDPOINTS:
            assert path in paths

    def test_the_guarded_optional_mount_is_gone(self):
        """The old ``_include_optional_router`` helper must no longer exist."""
        import app.main as main_module

        assert not hasattr(main_module, "_include_optional_router"), (
            "app/main.py still contains the guarded optional mount; a missing "
            "provider module would be silently skipped instead of failing the "
            "startup"
        )

    def test_a_missing_provider_module_fails_the_startup(self, monkeypatch):
        """A missing provider module must raise ``ImportError``.

        The entrypoint is loaded in isolation, with the provider module
        poisoned, so the real ``app.main`` module is not disturbed.  Under the
        old guarded mount this call would have returned ``False`` and the
        application would have started without the provider.
        """
        main_path = os.path.join(REPO_ROOT, "app", "main.py")
        spec = importlib.util.spec_from_file_location(
            "app_main_missing_provider_probe", main_path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)

        # ``None`` in ``sys.modules`` makes ``import app.core_analytics`` fail
        # with an ``ImportError`` - exactly like a module that is not there.
        monkeypatch.setitem(sys.modules, "app.core_analytics", None)
        with pytest.raises(ImportError):
            spec.loader.exec_module(module)

    def test_a_broken_provider_module_also_fails_the_startup(self, monkeypatch):
        """A provider that exists but cannot be imported must fail too."""
        import types

        main_path = os.path.join(REPO_ROOT, "app", "main.py")
        spec = importlib.util.spec_from_file_location(
            "app_main_broken_provider_probe", main_path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)

        broken = types.ModuleType("app.core_analytics")
        monkeypatch.setitem(sys.modules, "app.core_analytics", broken)
        # Force the import to fail: the module object has no ``router`` and
        # its import raises.
        monkeypatch.setitem(
            sys.modules, "app.core_analytics", broken
        )
        with pytest.raises((ImportError, AttributeError)):
            spec.loader.exec_module(module)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class TestLiveDashboard:
    """``GET /api/v1/manager/dashboard`` against the live providers."""

    @pytest.fixture()
    def body(self, client) -> Dict[str, Any]:
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        return response.json()

    def test_the_envelope_is_complete(self, body):
        assert body["degraded"] is False
        assert body["sources"] == {
            "core": {"status": "ok", "detail": None},
            "detection": {"status": "ok", "detail": None},
            "ml": {"status": "ok", "detail": None},
        }
        assert body["window"]["from"] == WINDOW_FROM.isoformat()
        assert body["window"]["to"] == WINDOW_TO.isoformat()

    def test_the_core_section_matches_the_core_database(self, body):
        core = body["core"]
        # Point-in-time facts.
        assert core["total_users"] == 9
        assert core["users_by_status"] == {"active": 7, "suspended": 1, "locked": 1}
        assert core["users_with_mfa_required"] == 1
        assert core["users_under_forced_mfa"] == 1
        assert core["users_with_failed_logins"] == 1
        # Window-scoped facts.
        assert core["new_users"] == 2
        assert core["sessions_created"] == 4
        assert core["sessions_revoked"] == 1
        assert core["mfa_challenges"] == 3
        assert core["mfa_completed"] == 1
        assert core["mfa_failed"] == 1
        assert core["audit_events"] == 4

    def test_the_active_session_count_is_point_in_time(self, body, pg_engines):
        """``sessions.active`` ignores the window - it is the current state."""
        expected = _scalar(
            pg_engines["core"],
            "SELECT count(*) FROM sessions "
            "WHERE revoked_at IS NULL AND expires_at > NOW()",
        )
        assert body["core"]["active_sessions"] == expected

    def test_the_audit_activity_feed_matches_the_core_database(self, body):
        activity = body["core"]["audit_activity"]
        assert activity["by_action"] == {
            "login_success": 2,
            "protective_action:REVOKE_SESSIONS": 1,
            "logout": 1,
        }
        assert activity["by_actor_type"] == {"user": 3, "system": 1}

        recent = activity["recent"]
        assert [row["action"] for row in recent] == [
            "logout",
            "protective_action:REVOKE_SESSIONS",
            "login_success",
            "login_success",
        ]
        # The actor is the username, or the literal actor type for a system row.
        assert recent[0]["actor"] == "live_analyst"
        assert recent[1]["actor"] == "system"
        assert recent[2]["actor"] == "live_plain"

        # The feed deliberately omits the sensitive fields.
        for row in recent:
            for forbidden in ("before_state", "after_state", "ip_address",
                              "user_agent"):
                assert forbidden not in row

    def test_the_detection_section_matches_the_detection_database(self, body):
        detection = body["detection"]
        assert detection["login_attempts"] == 4
        assert detection["by_outcome"] == {
            "success": 2, "failure": 1, "mfa_required": 0, "mfa_success": 0,
            "mfa_failed": 0, "blocked": 1, "locked": 0, "rate_limited": 0,
        }
        assert detection["by_risk_level"] == {
            "low": 2, "medium": 1, "high": 0, "critical": 1,
        }
        assert detection["by_decision"] == {"allow": 2, "challenge": 1, "block": 1}
        assert detection["avg_combined_score"] == 0.425

        assert detection["alerts"] == {
            "total": 5, "open": 2, "acknowledged": 1, "resolved": 1,
            "false_positive": 1, "critical_open": 1,
        }
        assert detection["enforcement"] == {
            "attempted": 2, "succeeded": 1, "success_rate": 0.5,
        }
        assert detection["ml_fallback"] == {
            "assessments": 4, "fallback": 2, "fallback_rate": 0.5,
        }
        assert detection["policy"]["active_version"] == "v1.0"
        assert detection["policy"]["active_policy_id"]

    def test_the_critical_incident_list_is_the_current_backlog(self, body):
        """The backlog is NOT window-scoped: the alert created at ``to`` is in."""
        incidents = body["detection"]["critical_incidents"]
        assert len(incidents) == 3

        # critical first, then high, each oldest first.
        assert [i["risk_level"] for i in incidents] == ["critical", "high", "high"]
        assert [i["status"] for i in incidents] == ["open", "acknowledged", "open"]

        # The incident created exactly at ``to`` is the critical one.
        assert incidents[0]["created_at"] == WINDOW_TO.isoformat()
        assert incidents[0]["assigned_to"] is None
        assert incidents[0]["subject"]["username"] == "live_plain"
        assert incidents[0]["age_hours"] > 0

        # The acknowledged high alert is assigned to the analyst.
        assert incidents[1]["assigned_to"] == "Live Analyst"
        assert incidents[1]["combined_score"] == 0.5

    def test_the_ml_section_is_read_from_the_ml_database(self, body):
        ml = body["ml"]
        assert ml["active_model_version"] == LIVE_MODEL_VERSION
        assert ml["model_status"] == "ready"
        assert ml["inferences"] == 4
        assert ml["anomalies"] == 1
        assert ml["anomaly_rate"] == 0.25
        assert ml["avg_processing_ms"] == 25.0
        assert ml["daily"] == [
            {
                "day": "2026-10-01", "total": 4, "anomalies": 1, "successful": 2,
                "errors": 1, "degraded": 1, "avg_processing_ms": 25.0,
                "avg_anomaly_score": 0.375,
            }
        ]

    def test_the_model_status_vocabulary_is_ready_or_error_only(self, body):
        assert body["ml"]["model_status"] in ("ready", "error")
        assert body["ml"]["model_status"] != "degraded"


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

class TestLiveTrends:
    """``GET /api/v1/manager/trends`` against the live providers."""

    @pytest.fixture()
    def body(self, client) -> Dict[str, Any]:
        response = _get(client, "/api/v1/manager/trends", bucket="hour")
        assert response.status_code == 200, response.text
        return response.json()

    def test_the_bucket_and_the_series_length(self, body):
        assert body["bucket"] == "hour"
        # 24 hourly buckets in a 24-hour window.
        assert len(body["series"]["login_attempts"]) == 24
        assert len(body["series"]["alerts"]) == 24
        assert len(body["series"]["ml"]) == 24

    def test_both_public_arrays_carry_the_same_bucket_starts(self, body):
        starts = [p["bucket_start"] for p in body["series"]["login_attempts"]]
        assert starts == [p["bucket_start"] for p in body["series"]["alerts"]]
        assert starts[0] == WINDOW_FROM.isoformat()
        assert starts[-1] == "2026-10-01T23:00:00+00:00"

    def test_the_login_attempt_series_matches_the_detection_database(self, body):
        series = body["series"]["login_attempts"]
        by_bucket = {p["bucket_start"]: p for p in series}

        assert by_bucket["2026-10-01T01:00:00+00:00"]["total"] == 1
        assert by_bucket["2026-10-01T02:00:00+00:00"]["total"] == 1
        assert by_bucket["2026-10-01T03:00:00+00:00"]["total"] == 1
        assert by_bucket["2026-10-01T23:00:00+00:00"]["total"] == 1
        # The attempt at ``to`` and the one before ``from`` are excluded.
        assert by_bucket["2026-10-01T00:00:00+00:00"]["total"] == 0

        assert sum(p["total"] for p in series) == 4

        bucket = by_bucket["2026-10-01T01:00:00+00:00"]
        assert bucket["by_outcome"]["success"] == 1
        assert bucket["by_risk_level"]["low"] == 1
        assert bucket["avg_combined_score"] == 0.1

    def test_the_alert_series_matches_the_detection_database(self, body):
        series = body["series"]["alerts"]
        by_bucket = {p["bucket_start"]: p for p in series}

        assert by_bucket["2026-10-01T01:00:00+00:00"]["total"] == 1
        assert by_bucket["2026-10-01T02:00:00+00:00"]["total"] == 1
        assert by_bucket["2026-10-01T03:00:00+00:00"]["total"] == 1
        assert by_bucket["2026-10-01T10:00:00+00:00"]["total"] == 1
        assert by_bucket["2026-10-01T23:00:00+00:00"]["total"] == 1
        # The alert created exactly at ``to`` is excluded.
        assert sum(p["total"] for p in series) == 5

    def test_the_ml_series_matches_the_ml_database(self, body):
        series = body["series"]["ml"]
        by_bucket = {p["bucket_start"]: p for p in series}

        for hour, total in ((5, 1), (6, 1), (7, 1), (8, 1)):
            point = by_bucket[f"2026-10-01T{hour:02d}:00:00+00:00"]
            assert point["total"] == total
        assert sum(p["total"] for p in series) == 4

    def test_the_day_bucket_agrees_with_the_ml_stats_daily_row(self, client, body):
        day_response = _get(client, "/api/v1/manager/ml-stats")
        assert day_response.status_code == 200, day_response.text
        daily = day_response.json()["daily"]

        day_point = daily[0]
        assert day_point["day"] == "2026-10-01"
        assert day_point["total"] == sum(p["total"] for p in body["series"]["ml"])
        assert day_point["anomalies"] == sum(
            p["anomalies"] for p in body["series"]["ml"]
        )
        assert day_point["errors"] == sum(p["errors"] for p in body["series"]["ml"])


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class TestLiveAlerts:
    """``GET /api/v1/manager/alerts`` against the live Detection provider."""

    @pytest.fixture()
    def body(self, client) -> Dict[str, Any]:
        response = _get(client, "/api/v1/manager/alerts")
        assert response.status_code == 200, response.text
        return response.json()

    def test_the_totals_match_the_alert_population(self, body):
        assert body["totals"] == {
            "created": 5, "open": 2, "acknowledged": 1, "resolved": 1,
            "false_positive": 1,
        }
        assert body["by_status"] == {
            "open": 2, "acknowledged": 1, "resolved": 1, "false_positive": 1,
        }
        assert body["by_risk_level"] == {
            "low": 1, "medium": 1, "high": 2, "critical": 1,
        }

    def test_the_event_based_and_current_status_counts_differ(self, body):
        """The alert acknowledged after ``to`` does not count as acknowledged."""
        assert body["acknowledged_count"] == 3
        assert body["by_status"]["acknowledged"] == 1
        assert body["acknowledged_count"] != body["by_status"]["acknowledged"]

    def test_the_mtta_uses_only_the_acknowledged_events_inside_the_window(self, body):
        # al1: 01:30 -> 05:00 = 12600 s
        # al2: 02:30 -> 04:00 =  5400 s
        # al3: 03:30 -> 07:00 = 12600 s
        # al6 is acknowledged at 2026-10-02T01:00 (after ``to``) -> excluded
        assert body["mtta_seconds"] == 10200.0

    def test_the_mttr_uses_the_resolved_alerts_resolved_inside_the_window(self, body):
        # al3: 03:30 -> 06:00 = 9000 s
        assert body["mttr_seconds"] == 9000.0
        assert body["resolved_count"] == 1

    def test_the_backlog_is_reported(self, body):
        # al1 and al6 are open and unassigned; al5 (open, unassigned) was
        # created at ``to`` and is therefore outside the population.
        assert body["backlog"]["open_count"] == 2
        assert body["backlog"]["unassigned"] == 2
        assert body["backlog"]["escalated"] == 1
        assert body["backlog"]["oldest_open_age_hours"] > 0

    def test_the_breakdowns_are_multi_valued_and_top_n(self, body):
        assert body["by_rule"] == [
            {"rule": "multiple_failures", "count": 2},
            {"rule": "new_device", "count": 1},
            {"rule": "unusual_hour", "count": 1},
        ]
        assert body["by_ml_reason"] == [
            {"code": "new_ip", "count": 2},
            {"code": "high_fail_count", "count": 1},
            {"code": "new_device", "count": 1},
            {"code": "unusual_hour", "count": 1},
        ]

    def test_the_false_positive_rate_uses_the_current_status(self, body):
        assert body["false_positive_rate"] == 0.5

    def test_the_status_filter_selects_the_alert_population(self, client):
        response = _get(client, "/api/v1/manager/alerts", status="acknowledged")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"]["created"] == 1
        assert body["totals"]["acknowledged"] == 1

    def test_the_risk_level_filter_selects_the_alert_population(self, client):
        response = _get(client, "/api/v1/manager/alerts", risk_level="critical")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"]["created"] == 1
        assert body["by_status"]["resolved"] == 1

    def test_an_empty_window_yields_null_rates_not_zero(self, client):
        response = _get(
            client, "/api/v1/manager/alerts",
            **{"from": EMPTY_FROM.isoformat(), "to": EMPTY_TO.isoformat()},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"]["created"] == 0
        assert body["mtta_seconds"] is None
        assert body["mttr_seconds"] is None
        assert body["false_positive_rate"] is None


# ---------------------------------------------------------------------------
# SOC KPI
# ---------------------------------------------------------------------------

class TestLiveSocKpi:
    """``GET /api/v1/manager/soc-kpi`` against the live providers."""

    @pytest.fixture()
    def kpis(self, client) -> Dict[str, Any]:
        response = _get(client, "/api/v1/manager/soc-kpi")
        assert response.status_code == 200, response.text
        return response.json()["kpis"]

    def test_the_detection_kpis_match_the_fixture(self, kpis):
        assert kpis["mtta_seconds"] == 10200.0
        assert kpis["mttr_seconds"] == 9000.0
        # 3 acknowledged events / 5 created alerts
        assert kpis["acknowledgement_rate"] == 0.6
        # (1 resolved + 1 false positive) / 5 created alerts
        assert kpis["resolution_rate"] == 0.4
        # 1 false positive / (1 resolved + 1 false positive)
        assert kpis["false_positive_rate"] == 0.5
        # 1 escalation / 5 created alerts
        assert kpis["escalation_rate"] == 0.2
        # 5 created alerts / 1 active analyst
        assert kpis["alerts_per_analyst"] == 5.0

    def test_the_enforcement_kpis_match_the_detection_logs(self, kpis):
        assert kpis["enforcement_attempted"] == 2
        assert kpis["enforcement_succeeded"] == 1
        assert kpis["enforcement_success_rate"] == 0.5

    def test_the_ml_fallback_kpis_match_the_risk_assessments(self, kpis):
        assert kpis["ml_assessments"] == 4
        assert kpis["ml_fallback_count"] == 2
        assert kpis["ml_fallback_rate"] == 0.5

    def test_the_core_kpis_match_the_users_table(self, kpis):
        # 1 user with admin_mfa_required / 9 users
        assert kpis["mfa_enrollment_rate"] == 0.1111
        assert kpis["forced_mfa_users"] == 1
        assert kpis["audit_events"] == 4

    def test_an_empty_window_yields_null_kpis(self, client):
        response = _get(
            client, "/api/v1/manager/soc-kpi",
            **{"from": EMPTY_FROM.isoformat(), "to": EMPTY_TO.isoformat()},
        )
        assert response.status_code == 200, response.text
        kpis = response.json()["kpis"]
        assert kpis["acknowledgement_rate"] is None
        assert kpis["resolution_rate"] is None
        assert kpis["false_positive_rate"] is None
        assert kpis["escalation_rate"] is None
        assert kpis["enforcement_success_rate"] is None
        assert kpis["ml_fallback_rate"] is None
        assert kpis["mtta_seconds"] is None
        assert kpis["mttr_seconds"] is None
        # ``alerts_per_analyst`` has a **point-in-time** denominator
        # (design section 5.1 rule 9), so an empty window over a team that
        # still has active analysts is 0 alerts per analyst, not ``null``.
        assert kpis["alerts_per_analyst"] == 0.0

    def test_alerts_per_analyst_is_null_without_an_active_analyst(self, client,
                                                                  pg_engines):
        """With no active analyst the denominator is 0 -> ``null``."""
        with pg_engines["detection"].begin() as conn:
            conn.execute(text("UPDATE soc_analysts SET is_active = FALSE"))
        try:
            response = _get(client, "/api/v1/manager/soc-kpi")
            assert response.status_code == 200, response.text
            assert response.json()["kpis"]["alerts_per_analyst"] is None
        finally:
            with pg_engines["detection"].begin() as conn:
                conn.execute(
                    text(
                        "UPDATE soc_analysts SET is_active = TRUE "
                        "WHERE display_name = 'Live Analyst'"
                    )
                )


# ---------------------------------------------------------------------------
# ML stats
# ---------------------------------------------------------------------------

class TestLiveMlStats:
    """``GET /api/v1/manager/ml-stats`` against the live ML database."""

    @pytest.fixture()
    def body(self, client) -> Dict[str, Any]:
        response = _get(client, "/api/v1/manager/ml-stats")
        assert response.status_code == 200, response.text
        return response.json()

    def test_the_registry_row_is_reported(self, body):
        model = body["model"]
        assert model["active_version"] == LIVE_MODEL_VERSION
        assert model["status"] == "active"
        assert model["is_production"] is True
        assert model["algorithm"] == "IsolationForest"

    def test_every_registry_version_is_listed_with_its_window_count(self, body):
        versions = {v["version"]: v for v in body["versions"]}
        assert LIVE_MODEL_VERSION in versions
        assert versions[LIVE_MODEL_VERSION]["inferences"] == 4
        assert versions[LIVE_MODEL_VERSION]["is_production"] is True

    def test_the_inference_aggregate_matches_the_ml_database(self, body):
        inference = body["inference"]
        assert inference["total"] == 4
        assert inference["anomalies"] == 1
        assert inference["anomaly_rate"] == 0.25
        assert inference["avg_normalized_score"] == 0.375
        assert inference["avg_processing_ms"] == 25.0
        assert inference["p95_processing_ms"] == 40.0
        assert inference["errors"] == 1
        assert inference["degraded"] == 1

    def test_the_status_breakdown_is_zero_filled(self, body):
        assert body["by_status"] == {"ready": 2, "degraded": 1, "error": 1}

    def test_the_reason_codes_are_top_n_descending(self, body):
        assert body["reason_codes"] == [
            {"code": "high_fail_count", "count": 1},
            {"code": "new_device", "count": 1},
        ]

    def test_the_daily_buckets_are_utc_days(self, body):
        assert [p["day"] for p in body["daily"]] == ["2026-10-01"]
        assert body["daily"][0]["total"] == 4
        assert body["daily"][0]["avg_processing_ms"] == 25.0
        assert body["daily"][0]["avg_anomaly_score"] == 0.375

    def test_the_feature_statistics_are_reported(self, body):
        features = body["features"]
        assert len(features) == 1
        assert features[0]["feature_name"] == "fail_count_24h"
        assert features[0]["count"] == 100


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

class TestLiveRbac:
    """The RBAC is enforced against the real Core database."""

    @pytest.mark.parametrize("path", MANAGER_ENDPOINTS)
    def test_the_security_manager_is_allowed(self, client, path):
        response = _get(client, path)
        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("path", MANAGER_ENDPOINTS)
    @pytest.mark.parametrize("token_key", ["analyst", "admin", "plain"])
    def test_every_other_role_is_forbidden(self, client, path, token_key):
        response = _get(client, path, token_key=token_key)
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == "Insufficient permissions"

    @pytest.mark.parametrize("path", MANAGER_ENDPOINTS)
    def test_a_missing_token_is_unauthorized(self, client, path):
        response = client.get(path, params=_window_params())
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Missing Authorization header"

    def test_an_unknown_token_is_unauthorized(self, client):
        response = client.get(
            "/api/v1/manager/dashboard",
            params=_window_params(),
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Invalid or expired session"

    def test_a_suspended_account_is_unauthorized(self, client):
        response = _get(client, "/api/v1/manager/dashboard", token_key="suspended")
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Account is not active"

    def test_an_expired_session_is_unauthorized(self, client):
        response = _get(client, "/api/v1/manager/dashboard", token_key="expired")
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Invalid or expired session"

    def test_the_role_is_resolved_in_real_time(self, client, pg_engines):
        """Revoking the role takes effect on the next request - no cache."""
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text

        with pg_engines["core"].begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM user_roles WHERE role_id = 'SECURITY_MANAGER' "
                    "AND user_id = (SELECT id FROM users WHERE username = 'live_mgr')"
                )
            )
        try:
            revoked = _get(client, "/api/v1/manager/dashboard")
            assert revoked.status_code == 403, revoked.text
        finally:
            with pg_engines["core"].begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id) "
                        "SELECT id, 'SECURITY_MANAGER' FROM users "
                        "WHERE username = 'live_mgr'"
                    )
                )


# ---------------------------------------------------------------------------
# UTC boundaries and ``series.logins``
# ---------------------------------------------------------------------------

class TestUtcBoundaries:
    """The window is half-open ``[from, to)`` everywhere."""

    def test_the_instant_at_from_is_included_and_the_one_at_to_is_excluded(
        self, client, pg_engines
    ):
        """A session created exactly at ``from`` counts, one at ``to`` does not."""
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["core"]["sessions_created"] == 4
        inside = _scalar(
            pg_engines["core"],
            "SELECT count(*) FROM sessions "
            "WHERE created_at >= :f AND created_at < :t",
            f=WINDOW_FROM, t=WINDOW_TO,
        )
        assert inside == 4
        assert body["core"]["sessions_created"] == inside

    def test_the_alert_population_is_half_open(self, client, pg_engines):
        response = _get(client, "/api/v1/manager/alerts")
        assert response.status_code == 200, response.text
        body = response.json()

        expected = _scalar(
            pg_engines["detection"],
            "SELECT count(*) FROM alerts WHERE created_at >= :f AND created_at < :t",
            f=WINDOW_FROM, t=WINDOW_TO,
        )
        assert expected == 5
        assert body["totals"]["created"] == expected

    def test_the_login_attempt_population_is_half_open(self, client, pg_engines):
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        expected = _scalar(
            pg_engines["detection"],
            "SELECT count(*) FROM login_attempts "
            "WHERE timestamp >= :f AND timestamp < :t",
            f=WINDOW_FROM, t=WINDOW_TO,
        )
        assert expected == 4
        assert response.json()["detection"]["login_attempts"] == expected

    def test_the_ml_population_is_half_open(self, client, pg_engines):
        response = _get(client, "/api/v1/manager/ml-stats")
        assert response.status_code == 200, response.text
        expected = _scalar(
            pg_engines["ml"],
            "SELECT count(*) FROM inference_logs "
            "WHERE created_at >= :f AND created_at < :t",
            f=WINDOW_FROM, t=WINDOW_TO,
        )
        assert expected == 4
        assert response.json()["inference"]["total"] == expected


class TestSeriesLoginsMatchesSessionCreations:
    """``series.logins`` is the bucketed counterpart of the session creations.

    The Core provider counts the sessions **created** in each bucket - it is
    not a count of ``login_success`` audit rows.  A login count derived from
    the audit trail could never exceed the audit-event count, so the two
    populations are genuinely different.
    """

    @pytest.fixture()
    def core_payload(self, client) -> Dict[str, Any]:
        response = client.get(
            "/api/v1/internal/analytics/core",
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat(),
                    "bucket": "hour"},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_the_series_sums_to_the_created_in_window_count(self, core_payload):
        assert core_payload["sessions"]["created_in_window"] == 4
        assert sum(bucket["logins"] for bucket in core_payload["series"]) == 4

    def test_every_bucket_matches_the_sessions_created_in_it(self, core_payload,
                                                             pg_engines):
        rows = _rows(
            pg_engines["core"],
            "SELECT date_trunc('hour', created_at AT TIME ZONE 'UTC') AS bucket, "
            "count(*) FROM sessions "
            "WHERE created_at >= :f AND created_at < :t "
            "GROUP BY 1",
            f=WINDOW_FROM, t=WINDOW_TO,
        )
        ground_truth = {
            row.bucket.replace(tzinfo=UTC).isoformat(): int(row[1])
            for row in rows
        }

        for bucket in core_payload["series"]:
            label = bucket["bucket_start"]
            assert bucket["logins"] == ground_truth.get(label, 0), (
                f"the bucket {label} reports {bucket['logins']} logins but the "
                f"database has {ground_truth.get(label, 0)} sessions created "
                f"in it"
            )

    def test_the_series_is_not_the_audit_event_count(self, core_payload):
        """The two populations really differ on this fixture."""
        audit_total = core_payload["audit"]["total"]
        logins_total = sum(bucket["logins"] for bucket in core_payload["series"])
        assert logins_total == 4
        assert audit_total == 4

        # They differ per bucket: the session creations and the audit rows
        # are not the same instants.
        audit_rows = {
            bucket["bucket_start"]: bucket["audit_events"]
            for bucket in core_payload["series"]
        }
        login_rows = {
            bucket["bucket_start"]: bucket["logins"]
            for bucket in core_payload["series"]
        }
        assert audit_rows != login_rows

    def test_the_series_is_zero_filled_and_covers_every_bucket(self, core_payload):
        assert len(core_payload["series"]) == 24
        assert core_payload["series"][0]["bucket_start"] == WINDOW_FROM.isoformat()
        assert core_payload["series"][-1]["bucket_start"] == (
            "2026-10-01T23:00:00+00:00"
        )
        assert all(bucket["logins"] >= 0 for bucket in core_payload["series"])


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestLiveDegradation:
    """The degradation contract of design section 6.1, against live providers."""

    def test_a_detection_outage_degrades_the_dashboard(self, client, router):
        router.fault("detection.test", "connect_error")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["degraded"] is True
        assert body["detection"] is None
        assert body["sources"]["detection"] == {
            "status": "unavailable", "detail": "unreachable",
        }
        # The Core and ML sections still render.
        assert body["core"] is not None
        assert body["ml"] is not None
        assert body["core"]["total_users"] == 9

    def test_a_core_outage_degrades_the_dashboard(self, client, router):
        router.fault("core.test", "connect_error")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["degraded"] is True
        assert body["core"] is None
        assert body["sources"]["core"] == {
            "status": "unavailable", "detail": "unreachable",
        }
        assert body["detection"] is not None
        assert body["detection"]["login_attempts"] == 4

    def test_a_detection_timeout_is_reported_as_timeout(self, client, router):
        router.fault("detection.test", "timeout")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        assert response.json()["sources"]["detection"] == {
            "status": "unavailable", "detail": "timeout",
        }

    def test_an_upstream_http_error_is_reported_with_its_status(self, client, router):
        router.fault("detection.test", "http_500")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        assert response.json()["sources"]["detection"] == {
            "status": "unavailable", "detail": "http_500",
        }

    def test_an_unparseable_upstream_body_is_invalid_payload(self, client, router):
        router.fault("detection.test", "invalid_json")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        assert response.json()["sources"]["detection"] == {
            "status": "unavailable", "detail": "invalid_payload",
        }

    def test_a_missing_internal_secret_is_not_configured(self, client, router,
                                                         monkeypatch):
        monkeypatch.delenv("INTERNAL_SECRET", raising=False)
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sources"]["core"]["detail"] == "not_configured"
        assert body["sources"]["detection"]["detail"] == "not_configured"
        # The request was never attempted, so nothing reached the providers.
        assert router.calls == []

    def test_an_unavailable_ml_context_degrades_the_ml_source(self, client,
                                                                ml_unavailable):
        """The ML source is a database read - a missing context is a source failure."""
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["degraded"] is True
        assert body["ml"] is None
        assert body["sources"]["ml"] == {
            "status": "unavailable", "detail": "database_error",
        }
        assert body["core"] is not None

    def test_every_source_down_is_a_503(self, client, router, ml_unavailable):
        """The dashboard answers 503 only when **all three** sources are down."""
        router.fault("core.test", "connect_error")
        router.fault("detection.test", "connect_error")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["detail"] == "analytics sources unavailable"
        assert body["sources"]["core"]["detail"] == "unreachable"
        assert body["sources"]["detection"]["detail"] == "unreachable"
        assert body["sources"]["ml"]["detail"] == "database_error"

    def test_two_sources_down_still_degrades_instead_of_failing(self, client,
                                                                 router):
        """Core and Detection down, ML healthy -> 200 with ``degraded: true``."""
        router.fault("core.test", "connect_error")
        router.fault("detection.test", "connect_error")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["degraded"] is True
        assert body["core"] is None
        assert body["detection"] is None
        assert body["ml"] is not None

    def test_a_single_source_endpoint_fails_with_a_503(self, client, router):
        router.fault("detection.test", "connect_error")
        response = _get(client, "/api/v1/manager/alerts")
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["detail"] == "analytics sources unavailable"
        assert body["sources"]["detection"]["status"] == "unavailable"

    def test_the_ml_stats_endpoint_fails_with_a_503_without_its_source(
        self, client, ml_unavailable
    ):
        response = _get(client, "/api/v1/manager/ml-stats")
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["detail"] == "analytics sources unavailable"
        assert body["sources"]["ml"]["detail"] == "database_error"

    def test_no_upstream_failure_produces_a_500(self, client, router):
        for kind in ("connect_error", "timeout", "http_500", "invalid_json"):
            router.clear_faults()
            router.fault("core.test", kind)
            router.fault("detection.test", kind)
            for path in MANAGER_ENDPOINTS:
                response = _get(client, path)
                assert response.status_code != 500, (
                    f"{path} answered 500 for the fault {kind!r}"
                )
                assert response.status_code in (200, 503)

    def test_the_reason_code_never_leaks_an_exception(self, client, router):
        router.fault("core.test", "connect_error")
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        detail = response.json()["sources"]["core"]["detail"]
        assert detail == "unreachable"
        assert "http" not in detail
        assert "Traceback" not in detail


# ---------------------------------------------------------------------------
# The HTTP contract
# ---------------------------------------------------------------------------

class TestLiveHttpContract:
    """The five-shape response contract of design section 6.1.2."""

    @pytest.mark.parametrize("path", MANAGER_ENDPOINTS)
    def test_a_reversed_window_is_a_400(self, client, path):
        response = _get(
            client, path,
            **{"from": WINDOW_TO.isoformat(), "to": WINDOW_FROM.isoformat()},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "'from' must be strictly earlier than 'to'"

    @pytest.mark.parametrize("path", MANAGER_ENDPOINTS)
    def test_a_malformed_window_is_a_400_not_a_422(self, client, path):
        response = _get(client, path, **{"from": "not-a-timestamp"})
        assert response.status_code == 400, response.text
        assert "detail" in response.json()

    @pytest.mark.parametrize("path", MANAGER_ENDPOINTS)
    def test_no_endpoint_ever_answers_422(self, client, path):
        for params in (
            {"from": "not-a-timestamp"},
            {"from": WINDOW_FROM.isoformat(), "to": "nonsense"},
            {"bucket": "bogus"},
        ):
            response = _get(client, path, **params)
            assert response.status_code != 422, (
                f"{path} answered 422 for {params!r}"
            )
            assert response.status_code in (200, 400, 401, 403, 503)

    def test_an_unknown_status_filter_is_a_400(self, client):
        response = _get(client, "/api/v1/manager/alerts", status="banana")
        assert response.status_code == 400, response.text

    def test_an_unknown_risk_level_filter_is_a_400(self, client):
        response = _get(client, "/api/v1/manager/alerts", risk_level="extreme")
        assert response.status_code == 400, response.text

    def test_a_bad_window_never_reaches_a_provider(self, client, router):
        response = _get(
            client, "/api/v1/manager/dashboard",
            **{"from": WINDOW_TO.isoformat(), "to": WINDOW_FROM.isoformat()},
        )
        assert response.status_code == 400, response.text
        assert router.calls == []

    def test_the_401_body_is_a_detail_object(self, client):
        response = client.get("/api/v1/manager/dashboard", params=_window_params())
        assert response.status_code == 401
        assert set(response.json()) == {"detail"}

    def test_the_403_body_is_a_detail_object(self, client):
        response = _get(client, "/api/v1/manager/dashboard", token_key="analyst")
        assert response.status_code == 403
        assert set(response.json()) == {"detail"}

    def test_the_503_body_carries_detail_and_sources(self, client, router):
        router.fault("detection.test", "connect_error")
        response = _get(client, "/api/v1/manager/alerts")
        assert response.status_code == 503
        body = response.json()
        assert set(body) == {"detail", "sources"}
        assert body["detail"] == "analytics sources unavailable"
        assert set(body["sources"]["detection"]) == {"status", "detail"}

    def test_the_timestamps_carry_an_explicit_utc_offset(self, client):
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["generated_at"].endswith("+00:00")
        assert body["window"]["from"].endswith("+00:00")
        assert body["window"]["to"].endswith("+00:00")

    def test_the_internal_endpoints_require_the_secret(self, client):
        response = client.get(
            "/api/v1/internal/analytics/core",
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
        )
        assert response.status_code == 401, response.text

    def test_the_internal_endpoints_reject_a_wrong_secret(self, client):
        response = client.get(
            "/api/v1/internal/analytics/detection",
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
            headers={"X-Internal-Secret": "wrong-secret-that-is-long-enough-32"},
        )
        assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Cross-backend parity - design section 7.0.1
# ---------------------------------------------------------------------------

class TestLiveSerializationParity:
    """PostgreSQL and SQLite must produce the same numbers and the same JSON.

    Design section 7.0.1 is explicit about the two places where the two
    backends disagree in representation: a ``Numeric`` column comes back as
    ``Decimal`` from PostgreSQL and ``float`` from SQLite, and
    ``details->>'enforced'`` is the *text* ``"true"`` on the PostgreSQL side
    but a real boolean on the SQLite side.  Both are normalised before they
    reach the response, so the live PostgreSQL numbers must equal the
    contract-stub numbers for the same fixture.
    """

    def test_a_numeric_column_is_a_json_number_not_a_string(self, client):
        response = _get(client, "/api/v1/manager/soc-kpi")
        assert response.status_code == 200, response.text
        # A ``Decimal`` that was not normalised would reach the response as a
        # string; the parsed type proves it is a JSON number.
        value = response.json()["kpis"]["mfa_enrollment_rate"]
        assert isinstance(value, float)
        assert value == 0.1111

    def test_the_enforcement_count_normalises_a_json_string_true(
        self, client, pg_engines
    ):
        """``details->>'enforced' = 'true'`` is a TEXT comparison on PostgreSQL.

        The fixture stores a JSON boolean ``true``; this test rewrites the
        same column with the JSON *string* ``"true"`` - exactly what
        ``details->>'enforced'`` extracts - and asserts the enforcement
        count does not move.  That is the cross-backend parity rule of
        design section 7.0.1.
        """
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        before = response.json()["detection"]["enforcement"]
        assert before == {"attempted": 2, "succeeded": 1, "success_rate": 0.5}

        with pg_engines["detection"].begin() as conn:
            # Turn every JSON boolean into the JSON string of the same
            # value: ``true`` -> ``"true"`` and ``false`` -> ``"false"``.
            conn.execute(
                text(
                    "UPDATE detection_logs SET details = "
                    "jsonb_set(details, '{enforced}', "
                    "to_jsonb(details ->> 'enforced')) "
                    "WHERE details ? 'enforced'"
                )
            )
        try:
            with pg_engines["detection"].connect() as conn:
                kinds = conn.execute(
                    text(
                        "SELECT DISTINCT jsonb_typeof(details -> 'enforced') "
                        "FROM detection_logs WHERE details ? 'enforced'"
                    )
                ).fetchall()
            assert [row[0] for row in kinds] == ["string"], (
                "the fixture must hold the JSON string form for this test"
            )

            response = _get(client, "/api/v1/manager/dashboard")
            assert response.status_code == 200, response.text
            after = response.json()["detection"]["enforcement"]
            assert after == before, (
                "the enforcement count changed when the JSON boolean became "
                "the JSON string 'true' - the two representations must be "
                "normalised to the same number"
            )
        finally:
            with pg_engines["detection"].begin() as conn:
                conn.execute(
                    text(
                        "UPDATE detection_logs SET details = "
                        "jsonb_set(details, '{enforced}', "
                        "to_jsonb((details ->> 'enforced')::boolean)) "
                        "WHERE details ? 'enforced'"
                    )
                )

    def test_a_uuid_is_serialised_as_a_string(self, client):
        response = _get(client, "/api/v1/manager/dashboard")
        assert response.status_code == 200, response.text
        body = response.json()
        incidents = body["detection"]["critical_incidents"]
        assert incidents
        for incident in incidents:
            assert isinstance(incident["alert_id"], str)
            assert incident["alert_id"]

    def test_no_numeric_field_is_serialised_as_a_string(self, client):
        """No numeric field of any endpoint may be a JSON string."""
        for path in MANAGER_ENDPOINTS:
            response = _get(client, path)
            assert response.status_code == 200, response.text
            for field, value in _walk_numbers(response.json()):
                assert not isinstance(value, str), (
                    f"{path}: the numeric field {field!r} was serialised as "
                    f"the string {value!r}"
                )


class TestLiveSessionTimezoneIndependence:
    """A non-UTC session timezone must not shift a day boundary.

    Design section 7.1: the ML daily buckets are UTC floors, so the session
    timezone of the database connection must not move a day.

    The timezone is set at the **role** level, so every connection the
    application opens inherits it - a ``SET TIME ZONE`` on the test's own
    connection would not reach the application's pool.
    """

    def test_the_daily_buckets_do_not_depend_on_the_session_timezone(
        self, client, pg_engines
    ):
        def _daily(client):
            response = _get(client, "/api/v1/manager/ml-stats")
            assert response.status_code == 200, response.text
            return response.json()["daily"]

        baseline = _daily(client)
        assert [row["day"] for row in baseline] == ["2026-10-01"]

        # Force every future connection of this role into a non-UTC zone and
        # drop the pooled connections so the next read really uses it.
        with pg_engines["ml"].begin() as conn:
            conn.execute(text("ALTER ROLE sentinel SET TIME ZONE 'Asia/Ho_Chi_Minh'"))
        pg_engines["ml"].dispose()
        try:
            with pg_engines["ml"].connect() as conn:
                zone = conn.execute(text("SHOW TIME ZONE")).scalar()
            assert zone == "Asia/Ho_Chi_Minh", (
                f"the connection timezone is {zone!r}, the test did not apply"
            )

            shifted = _daily(client)
            assert [row["day"] for row in shifted] == [row["day"] for row in baseline]
            assert shifted == baseline, (
                "the ML daily buckets changed when the session timezone was "
                "not UTC - the day boundary must be a UTC floor"
            )
        finally:
            with pg_engines["ml"].begin() as conn:
                conn.execute(text("ALTER ROLE sentinel RESET TIME ZONE"))
            pg_engines["ml"].dispose()

    def test_the_trends_buckets_do_not_depend_on_the_session_timezone(
        self, client, pg_engines
    ):
        """The same rule applies to the hour buckets of ``/trends``."""
        def _starts(client):
            response = _get(client, "/api/v1/manager/trends", bucket="hour")
            assert response.status_code == 200, response.text
            return [p["bucket_start"] for p in response.json()["series"]["ml"]]

        baseline = _starts(client)

        with pg_engines["ml"].begin() as conn:
            conn.execute(text("ALTER ROLE sentinel SET TIME ZONE 'Asia/Ho_Chi_Minh'"))
        pg_engines["ml"].dispose()
        try:
            assert _starts(client) == baseline, (
                "the ML hourly buckets moved when the session timezone was "
                "not UTC - the bucket floors must be UTC"
            )
        finally:
            with pg_engines["ml"].begin() as conn:
                conn.execute(text("ALTER ROLE sentinel RESET TIME ZONE"))
            pg_engines["ml"].dispose()
