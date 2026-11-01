"""Contract tests for the Core analytics provider.

Covers ``GET /api/v1/internal/analytics/core`` - the aggregate endpoint owned
by the Core context and consumed by the Manager facade.

What is proved
--------------
The module exercises the behaviours the design document calls out explicitly
because they are the ones two implementations get wrong:

* **the contract shape** - every section the Manager facade maps is present
  and has the documented type (design 4.2);
* **internal authentication** - a missing / wrong ``X-Internal-Secret`` is a
  401, an unconfigured secret is a 503 (design 4.0, 7.1);
* **the window** - half-open ``[from, to)``, a reversed window is a 400, an
  oversized window is a 400, an unparseable timestamp is a 400 (design 3.2);
* **point-in-time vs window-scoped** - ``users.total``, ``users.by_status``,
  ``users.mfa_required``, ``users.forced_mfa``, ``users.with_failed_logins``
  and ``sessions.active`` ignore the window, while
  ``users.new_in_window``, ``sessions.created_in_window``,
  ``sessions.revoked_in_window``, ``mfa.*`` and ``audit.*`` do not
  (design 5.1 rule 13);
* **the audit feed** - the 10 newest rows, newest first, with the actor
  resolved to a username (or the literal actor type), and **no** state
  payload, IP address or user-agent (design 3.3, 4.2);
* **protective actions** - the ``protective_action:<ACTION>`` subset, split on
  the ``:`` separator (design 4.2, reference R1.9);
* **bucketing** - every bucket of the window is present with UTC-floored
  labels, zero-filled, with no gap and no duplicate (design 5.3);
* **an empty dataset** - every count is ``0``, never a crash;
* **serialization** - UUIDs are strings and timestamps are ISO-8601 UTC.

Database
--------
The tests run against a **disposable PostgreSQL** database - the production
database is PostgreSQL, and the SQL semantics that matter here (``date_trunc``
with an explicit ``AT TIME ZONE 'UTC'``, ``TIMESTAMPTZ``, ``UUID``) only
exist there.  The database must carry the ``_test`` marker in its name; the
module refuses to run against anything else.

The module also builds the **same** fixture on SQLite and asserts that both
backends answer with identical numbers (design 5.2).

Configuration::

    CORE_ANALYTICS_TEST_URL   full URL of the disposable Core database

When the variable is absent the module SKIPS with an explicit message - it
never fabricates a pass.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app.models import AuditLog, MfaTransaction, Session, User

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CORE_ANALYTICS_TEST_URL = os.environ.get("CORE_ANALYTICS_TEST_URL", "")

#: Every database this module touches must carry this marker.  The module
#: recreates the ``public`` schema, so a production database would be
#: destroyed.  The guard fails loudly instead of skipping.
TEST_MARKER = "_test"

#: The internal shared secret used by the tests.  It must satisfy
#: ``get_internal_secret``: at least 32 characters, not the placeholder.
INTERNAL_SECRET = "core-analytics-contract-secret-0123456789"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_CORE = os.path.join(REPO_ROOT, "infra", "postgres", "schema-core-v3.3.sql")

#: The reporting window every scenario uses.  It is a fixed, absolute window
#: so that the fixtures are deterministic and independent of the wall clock.
WINDOW_FROM = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
WINDOW_TO = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)

#: A window that contains no data at all, for the empty-population cases.
EMPTY_FROM = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
EMPTY_TO = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)

ENDPOINT = "/api/v1/internal/analytics/core"


def _require_postgres() -> None:
    """Skip the module when the disposable Core database is absent."""
    if not CORE_ANALYTICS_TEST_URL:
        pytest.skip(
            "NOT RUN - CORE_ANALYTICS_TEST_URL is not set, so the Core analytics "
            "contract tests were skipped. Point it at a disposable "
            "PostgreSQL database whose name contains '_test'.",
            allow_module_level=True,
        )


_require_postgres()


def _database_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _assert_disposable(url: str, label: str) -> str:
    """Refuse to run against anything but a disposable ``*_test*`` database."""
    name = _database_name(url)
    if TEST_MARKER not in name.lower():
        pytest.fail(
            f"Refusing to run {label} against {name!r}: the database name "
            f"must contain {TEST_MARKER!r}. This module recreates the public "
            f"schema, so a real development database (sentinel_core) must "
            f"never be used as a test target."
        )
    return name


# ---------------------------------------------------------------------------
# The test-only ASGI app
# ---------------------------------------------------------------------------

def _build_test_app():
    """A minimal ASGI app carrying only the Core analytics router.

    ``app/main.py`` is a **shared** file owned by the lead, so this branch
    does not touch it (design 8, item 1).  The provider is therefore mounted
    on a test-only application, which keeps the contract test independent of
    the monolith's route table.
    """
    from fastapi import FastAPI

    from app.core_analytics import router

    test_app = FastAPI(title="Core Analytics (test-only)")
    test_app.include_router(router)
    return test_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    """A PostgreSQL engine on the disposable Core database."""
    _assert_disposable(CORE_ANALYTICS_TEST_URL, "the Core analytics contract tests")
    eng = create_engine(CORE_ANALYTICS_TEST_URL, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module", autouse=True)
def core_schema(pg_engine: Engine):
    """Rebuild the Core schema from the canonical SQL file.

    The module owns the schema of its disposable database, so the fixture
    always starts from the canonical definition - a test can never inherit a
    table shape from a previous run.
    """
    with open(SCHEMA_CORE, "r", encoding="utf-8") as handle:
        schema_sql = handle.read()
    with pg_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        conn.execute(text(schema_sql))
    yield


@pytest.fixture()
def seeded(pg_engine: Engine):
    """The deterministic fixture set.

    The fixture is built with **absolute** timestamps so that every assertion
    is reproducible and independent of the moment the test runs.
    """
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_logs"))
        conn.execute(text("DELETE FROM mfa_transactions"))
        conn.execute(text("DELETE FROM sessions"))
        conn.execute(text("DELETE FROM users"))
        conn.execute(text("DELETE FROM roles"))
        conn.execute(text("DELETE FROM user_roles"))

        ids = _seed_rows(conn)
    return ids


@pytest.fixture()
def client(pg_engine: Engine, seeded, monkeypatch):
    """A TestClient wired to the disposable Core database."""
    monkeypatch.setenv("CORE_DATABASE_URL", CORE_ANALYTICS_TEST_URL)
    monkeypatch.setenv("INTERNAL_SECRET", INTERNAL_SECRET)
    app_db.dispose_engines()

    from app.core_analytics import get_core_db

    test_app = _build_test_app()
    session = app_db.get_session_maker(
        pg_engine, context=app_db.CORE
    )()

    def _override():
        return session

    test_app.dependency_overrides[get_core_db] = _override
    try:
        with TestClient(test_app) as test_client:
            yield test_client
    finally:
        test_app.dependency_overrides = {}
        session.close()
        app_db.dispose_engines()


@pytest.fixture()
def get(client):
    """Call the endpoint with the internal secret and return the JSON body."""

    def _get(**params: Any) -> Dict[str, Any]:
        # ``from`` is a Python keyword, so the helper accepts ``from_`` and
        # maps it onto the real query parameter name.
        if "from_" in params:
            params["from"] = params.pop("from_")
        response = client.get(
            ENDPOINT,
            params=params,
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _get


#: A fixed namespace for the deterministic fixture identifiers.  The rows get
#: reproducible UUIDs so that the PostgreSQL and the SQLite payload can be
#: compared field by field (design 5.2) - the identifiers are part of the
#: payload (``audit_activity.recent[].id``).
FIXTURE_NAMESPACE = NAMESPACE_URL


def _fid(label: str) -> Any:
    """A deterministic UUID for a fixture row."""
    return uuid5(FIXTURE_NAMESPACE, f"sentinel-core-analytics/{label}")


def _seed_rows(conn) -> Dict[str, Any]:
    """Insert the deterministic fixture rows and return their identifiers.

    The inserts go through SQLAlchemy Core rather than raw SQL so that the
    **same** fixture can be loaded into PostgreSQL and into SQLite.  That is
    what makes the cross-database parity test (design 5.2) possible: the two
    engines receive identical logical rows, and the endpoint must answer with
    identical numbers.
    """
    ids: Dict[str, Any] = {}

    # --- users ------------------------------------------------------------
    # (key, username, status, mfa_required, forced_mfa, failed_logins, created)
    users = [
        ("u1", "alice", "active", True, False, 0, WINDOW_FROM + timedelta(hours=1)),
        ("u2", "bob", "active", False, True, 3, WINDOW_FROM + timedelta(hours=2)),
        ("u3", "carol", "suspended", False, False, 0, WINDOW_FROM + timedelta(hours=3)),
        ("u4", "dave", "locked", True, False, 1, WINDOW_FROM + timedelta(hours=4)),
        # Created BEFORE the window: point-in-time counts, not ``new_in_window``.
        ("old", "erin", "active", False, False, 0, WINDOW_FROM - timedelta(days=1)),
        # Created AFTER the window: not counted in ``new_in_window`` either.
        ("future", "frank", "active", False, False, 0, WINDOW_TO + timedelta(days=1)),
    ]
    ids["users"] = {}
    for key, username, status, mfa_req, forced, failed, created in users:
        user_id = _fid(f"user-{key}")
        conn.execute(
            insert(User.__table__).values(
                id=user_id,
                username=username,
                password_hash="argon2-hash",
                email=f"{username}@example.com",
                status=status,
                admin_mfa_required=mfa_req,
                detection_mfa_once=forced,
                failed_login_count=failed,
                created_at=created,
                updated_at=created,
            )
        )
        ids["users"][key] = str(user_id)

    # --- sessions ---------------------------------------------------------
    # ``sessions.active`` is point-in-time and compares ``expires_at`` with
    # the **wall clock**, so the live sessions expire far in the future and
    # the dead ones in the past.  Absolute timestamps keep the fixture
    # deterministic.
    FAR_FUTURE = datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    FAR_PAST = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # (key, user, created_at, expires_at, revoked_at)
    sessions = [
        # Live: not revoked and not expired.
        ("live", "u1", WINDOW_FROM + timedelta(hours=1), FAR_FUTURE, None),
        # Revoked inside the window: counts in ``revoked_in_window``.
        (
            "revoked", "u2", WINDOW_FROM + timedelta(hours=2),
            FAR_FUTURE, WINDOW_FROM + timedelta(hours=3),
        ),
        # Expired: neither active nor revoked, but still created in the window.
        (
            "expired", "u3", WINDOW_FROM + timedelta(hours=4),
            FAR_PAST, None,
        ),
        # Created before the window, revoked inside it.
        (
            "old_revoked", "u4", WINDOW_FROM - timedelta(days=1),
            FAR_PAST, WINDOW_FROM + timedelta(hours=5),
        ),
        # Revoked AFTER the window end: not a window revocation.
        (
            "late_revoked", "u1", WINDOW_FROM + timedelta(hours=6),
            FAR_FUTURE, WINDOW_TO + timedelta(hours=1),
        ),
    ]
    ids["sessions"] = {}
    for key, user_key, created, expires, revoked in sessions:
        session_id = _fid(f"session-{key}")
        conn.execute(
            insert(Session.__table__).values(
                id=session_id,
                user_id=_fid(f"user-{user_key}"),
                access_token_hash=f"hash-{key}",
                expires_at=expires,
                revoked_at=revoked,
                created_at=created,
                updated_at=created,
            )
        )
        ids["sessions"][key] = str(session_id)

    # --- MFA transactions -------------------------------------------------
    # (key, user, status, created_at)
    transactions = [
        ("m1", "u1", "completed", WINDOW_FROM + timedelta(hours=1)),
        ("m2", "u1", "failed", WINDOW_FROM + timedelta(hours=2)),
        ("m3", "u2", "expired", WINDOW_FROM + timedelta(hours=3)),
        ("m4", "u2", "completed", WINDOW_FROM + timedelta(hours=4)),
        ("m5", "u3", "pending", WINDOW_FROM + timedelta(hours=5)),
        # Created before the window.
        ("old", "u3", "completed", WINDOW_FROM - timedelta(days=1)),
        # Created after the window.
        ("future", "u4", "completed", WINDOW_TO + timedelta(hours=1)),
    ]
    ids["mfa"] = {}
    for key, user_key, status, created in transactions:
        tx_id = _fid(f"mfa-{key}")
        conn.execute(
            insert(MfaTransaction.__table__).values(
                id=tx_id,
                user_id=_fid(f"user-{user_key}"),
                mfa_type="one_time",
                status=status,
                fail_count=1 if status == "failed" else 0,
                expires_at=created + timedelta(minutes=5),
                created_at=created,
                updated_at=created,
            )
        )
        ids["mfa"][key] = str(tx_id)

    # --- audit logs -------------------------------------------------------
    # (key, action, actor, resource, resource_id, created_at)
    audits = [
        ("a1", "login_success", "u1", "session", "s1",
         WINDOW_FROM + timedelta(hours=1)),
        ("a2", "login_success", "u2", "session", "s2",
         WINDOW_FROM + timedelta(hours=2)),
        ("a3", "logout", "u1", "session", "s1",
         WINDOW_FROM + timedelta(hours=3)),
        ("a4", "protective_action:REQUIRE_MFA", None, "user", "u2",
         WINDOW_FROM + timedelta(hours=4)),
        ("a5", "protective_action:REVOKE_SESSIONS", None, "user", "u2",
         WINDOW_FROM + timedelta(hours=5)),
        ("a6", "protective_action:REQUIRE_MFA", None, "user", "u3",
         WINDOW_FROM + timedelta(hours=6)),
        ("a7", "lock_user", "u4", "user", "u4",
         WINDOW_FROM + timedelta(hours=7)),
        ("a8", "register", "u3", "user", "u3",
         WINDOW_FROM + timedelta(hours=8)),
        # Created before the window.
        ("old", "login_success", "u1", "session", "s1",
         WINDOW_FROM - timedelta(days=1)),
        # Created exactly at ``to``: excluded by the half-open window.
        ("at_to", "login_success", "u1", "session", "s1", WINDOW_TO),
    ]
    ids["audit"] = {}
    for key, action, actor, resource, resource_id, created in audits:
        audit_id = _fid(f"audit-{key}")
        conn.execute(
            insert(AuditLog.__table__).values(
                id=audit_id,
                actor_id=_fid(f"user-{actor}") if actor is not None else None,
                actor_type="user" if actor is not None else "system",
                action=action,
                resource=resource,
                resource_id=_fid(f"user-{resource_id}")
                if resource_id.startswith("u") else _fid(f"session-{resource_id}"),
                before_state={"secret": "never-exposed"},
                after_state={"secret": "never-exposed"},
                change_reason="fixture",
                ip_address="203.0.113.7",
                user_agent="fixture-agent/1.0",
                created_at=created,
            )
        )
        ids["audit"][key] = str(audit_id)

    return ids


# =============================================================================
# A. The contract shape
# =============================================================================

class TestContractShape:
    def test_every_documented_section_is_present(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        for section in (
            "generated_at",
            "window",
            "bucket",
            "users",
            "sessions",
            "mfa",
            "audit",
            "audit_activity",
            "protective_actions",
            "series",
        ):
            assert section in body, f"the {section!r} section is missing"

    def test_the_envelope_carries_generated_at_window_and_bucket(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert body["generated_at"].endswith("+00:00")
        assert body["window"]["from"] == WINDOW_FROM.isoformat()
        assert body["window"]["to"] == WINDOW_TO.isoformat()
        assert body["bucket"] == "day"

    def test_the_users_block_carries_every_documented_field(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        users = body["users"]
        assert set(users) == {
            "total", "by_status", "mfa_required", "forced_mfa",
            "new_in_window", "with_failed_logins",
        }

    def test_the_sessions_block_carries_every_documented_field(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert set(body["sessions"]) == {
            "active", "created_in_window", "revoked_in_window",
        }

    def test_the_mfa_block_carries_every_documented_field(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert set(body["mfa"]) == {"challenges", "completed", "failed", "expired"}

    def test_the_audit_blocks_carry_every_documented_field(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert set(body["audit"]) == {"total", "by_action"}
        assert set(body["audit_activity"]) == {
            "by_action", "by_actor_type", "recent",
        }
        assert set(body["protective_actions"]) == {"total", "by_action"}

    def test_users_by_status_carries_the_full_canonical_key_set(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert set(body["users"]["by_status"]) == {
            "active", "suspended", "locked",
        }

    def test_audit_by_action_and_audit_activity_by_action_are_the_same_count(
        self, get
    ):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert body["audit"]["by_action"] == body["audit_activity"]["by_action"]

    def test_the_two_by_action_breakdowns_are_computed_once(self, get, monkeypatch):
        """Core computes the breakdown once and returns it in both places.

        The design says ``audit.by_action`` is "the same count" as
        ``audit_activity.by_action`` and that "Core computes them once and
        returns both" (design 4.2 field notes).  A provider that recomputed
        the breakdown could drift from the other one, so the endpoint must
        not run the grouping twice.
        """
        import app.core_analytics as module

        original = module._grouped_counts
        calls: List[tuple] = []

        def _spy(db, model, column, conditions):
            calls.append((model, column))
            return original(db, model, column, conditions)

        monkeypatch.setattr(module, "_grouped_counts", _spy)
        get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())

        action_groupings = [
            call for call in calls
            if call[0] is module.AuditLog and call[1] is module.AuditLog.action
        ]
        assert len(action_groupings) == 1, (
            f"the audit action breakdown was computed {len(action_groupings)} "
            f"times; the design requires a single computation."
        )

    def test_a_recent_row_carries_exactly_the_permitted_fields(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        row = body["audit_activity"]["recent"][0]
        assert set(row) == {
            "id", "action", "actor", "resource", "resource_id", "created_at",
        }

    def test_the_recent_feed_never_exposes_state_or_network_identifiers(self, get):
        """The feed must not become a second copy of the admin audit page."""
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        forbidden = {"before_state", "after_state", "ip_address", "user_agent"}
        for row in body["audit_activity"]["recent"]:
            assert not (forbidden & set(row))

    def test_the_ids_are_serialised_as_strings(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        for row in body["audit_activity"]["recent"]:
            assert isinstance(row["id"], str)
            assert row["id"].count("-") == 4
            if row["resource_id"] is not None:
                assert isinstance(row["resource_id"], str)


# =============================================================================
# B. Internal authentication
# =============================================================================

class TestInternalAuth:
    def test_a_missing_secret_is_a_401(self, client):
        response = client.get(
            ENDPOINT,
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
        )
        assert response.status_code == 401

    def test_a_wrong_secret_is_a_401(self, client):
        response = client.get(
            ENDPOINT,
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
            headers={"X-Internal-Secret": "wrong-secret-value-at-least-32-chars"},
        )
        assert response.status_code == 401

    def test_an_unconfigured_secret_is_a_503(self, client, monkeypatch):
        monkeypatch.setenv("INTERNAL_SECRET", "changeme-in-production")
        response = client.get(
            ENDPOINT,
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 503

    def test_a_valid_secret_is_a_200(self, client):
        response = client.get(
            ENDPOINT,
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 200


# =============================================================================
# C. The window
# =============================================================================

class TestWindow:
    def test_a_reversed_window_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={"from": WINDOW_TO.isoformat(), "to": WINDOW_FROM.isoformat()},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_an_empty_window_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_FROM.isoformat()},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_an_oversized_window_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": "2025-01-01T00:00:00+00:00",
                "to": "2026-10-01T00:00:00+00:00",
            },
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_hour_bucket_over_a_long_window_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": "2026-01-01T00:00:00+00:00",
                "to": "2026-03-01T00:00:00+00:00",
                "bucket": "hour",
            },
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_an_unknown_bucket_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": WINDOW_FROM.isoformat(),
                "to": WINDOW_TO.isoformat(),
                "bucket": "week",
            },
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_an_unparseable_timestamp_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={"from": "not-a-timestamp", "to": WINDOW_TO.isoformat()},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_the_window_is_half_open(self, get):
        """An event exactly at ``to`` is excluded; one at ``from`` is included."""
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # The ``at_to`` audit row is exactly at ``to`` and must not count.
        assert body["audit"]["total"] == 8
        assert "at_to" not in body["audit"]["by_action"].values()

    def test_a_naive_timestamp_is_treated_as_utc(self, get):
        body = get(from_="2026-10-01T00:00:00", to="2026-10-08T00:00:00")
        assert body["window"]["from"] == WINDOW_FROM.isoformat()
        assert body["window"]["to"] == WINDOW_TO.isoformat()

    def test_bucket_auto_resolves_from_the_window_length(self, get):
        short = get(
            from_="2026-10-01T00:00:00+00:00",
            to="2026-10-03T00:00:00+00:00",
            bucket="auto",
        )
        assert short["bucket"] == "hour"
        long = get(
            from_="2026-10-01T00:00:00+00:00",
            to="2026-10-31T00:00:00+00:00",
            bucket="auto",
        )
        assert long["bucket"] == "day"


# =============================================================================
# D. Point-in-time vs window-scoped
# =============================================================================

class TestPointInTimeVsWindowScoped:
    def test_the_user_counts_ignore_the_window(self, get):
        """``users.total`` and friends are point-in-time (design 5.1 rule 13)."""
        wide = get(
            from_="2026-01-01T00:00:00+00:00",
            to="2026-12-01T00:00:00+00:00",
        )
        narrow = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat()
        )
        for key in ("total", "by_status", "mfa_required", "forced_mfa",
                    "with_failed_logins"):
            assert wide["users"][key] == narrow["users"][key]

    def test_the_user_counts_include_the_rows_outside_the_window(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        users = body["users"]
        # Six users in total: four created inside the window, one before it
        # and one after it.
        assert users["total"] == 6
        assert users["by_status"] == {
            "active": 4, "suspended": 1, "locked": 1,
        }
        # u1 and u4 have ``admin_mfa_required``.
        assert users["mfa_required"] == 2
        # Only u2 is under a forced MFA.
        assert users["forced_mfa"] == 1
        # u2 and u4 have failed logins.
        assert users["with_failed_logins"] == 2

    def test_new_in_window_is_the_only_window_scoped_user_field(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # u1..u4 were created inside the window; ``old`` and ``future`` were
        # not.
        assert body["users"]["new_in_window"] == 4

    def test_the_session_active_count_ignores_the_window(self, get):
        wide = get(
            from_="2026-01-01T00:00:00+00:00",
            to="2026-12-01T00:00:00+00:00",
        )
        narrow = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat()
        )
        assert wide["sessions"]["active"] == narrow["sessions"]["active"]

    def test_sessions_active_counts_only_the_live_sessions(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # Only the ``live`` session is neither revoked nor expired.
        assert body["sessions"]["active"] == 1

    def test_sessions_created_and_revoked_are_window_scoped(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        sessions = body["sessions"]
        # live, revoked, expired, late_revoked were created in the window;
        # ``old_revoked`` was not.
        assert sessions["created_in_window"] == 4
        # ``revoked`` and ``old_revoked`` were revoked inside the window;
        # ``late_revoked`` was revoked after ``to``.
        assert sessions["revoked_in_window"] == 2

    def test_the_mfa_counts_are_window_scoped(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        mfa = body["mfa"]
        # m1..m5 were created in the window; ``old`` and ``future`` were not.
        assert mfa["challenges"] == 5
        assert mfa["completed"] == 2
        assert mfa["failed"] == 1
        assert mfa["expired"] == 1

    def test_the_audit_counts_are_window_scoped(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        audit = body["audit"]
        # a1..a8 are inside the window; ``old`` is before it and ``at_to`` is
        # exactly at ``to``.
        assert audit["total"] == 8
        assert audit["by_action"]["login_success"] == 2
        assert audit["by_action"]["logout"] == 1
        assert audit["by_action"]["register"] == 1
        assert audit["by_action"]["lock_user"] == 1
        assert audit["by_action"]["protective_action:REQUIRE_MFA"] == 2


# =============================================================================
# E. The audit activity review
# =============================================================================

class TestAuditActivity:
    def test_the_breakdowns_describe_the_same_window(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        activity = body["audit_activity"]
        assert sum(activity["by_action"].values()) == body["audit"]["total"]
        assert sum(activity["by_actor_type"].values()) == body["audit"]["total"]

    def test_by_actor_type_counts_users_and_system_actions(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # a1..a3, a7 and a8 have an actor; a4..a6 are system actions.
        assert body["audit_activity"]["by_actor_type"] == {"user": 5, "system": 3}

    def test_by_actor_type_carries_the_full_canonical_key_set(self, get):
        """The actor-type vocabulary is closed, so the breakdown is zero-filled."""
        body = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_FROM + timedelta(hours=2),
        )
        # Only a1 falls into that window (a2 sits exactly at ``to`` and is
        # excluded by the half-open window); it is a user action.
        assert body["audit_activity"]["by_actor_type"] == {"user": 1, "system": 0}

    def test_the_feed_is_capped_at_ten_rows(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert len(body["audit_activity"]["recent"]) <= 10

    def test_the_feed_is_sorted_newest_first(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        created = [row["created_at"] for row in body["audit_activity"]["recent"]]
        assert created == sorted(created, reverse=True)

    def test_the_actor_is_resolved_to_a_username(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        actors = {row["actor"] for row in body["audit_activity"]["recent"]}
        assert "alice" in actors
        assert "bob" in actors

    def test_a_system_action_falls_back_to_the_actor_type(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        system_rows = [
            row for row in body["audit_activity"]["recent"]
            if row["action"].startswith("protective_action:")
        ]
        assert system_rows
        for row in system_rows:
            assert row["actor"] == "system"

    def test_a_row_carries_the_resource_and_the_instant(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        row = body["audit_activity"]["recent"][0]
        assert row["resource"]
        assert row["created_at"].endswith("+00:00")


# =============================================================================
# F. Protective actions
# =============================================================================

class TestProtectiveActions:
    def test_the_subset_is_split_on_the_separator(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        actions = body["protective_actions"]
        assert actions["by_action"] == {
            "REQUIRE_MFA": 2, "REVOKE_SESSIONS": 1,
        }
        assert actions["total"] == 3

    def test_only_protective_actions_are_counted(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        actions = body["protective_actions"]
        assert "login_success" not in actions["by_action"]
        assert "logout" not in actions["by_action"]
        # The subset is smaller than the whole audit trail.
        assert actions["total"] < body["audit"]["total"]

    def test_the_counts_are_window_scoped(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_FROM + timedelta(hours=1)
        )
        # Only a1 falls into that hour, and it is not a protective action.
        assert body["protective_actions"]["total"] == 0


# =============================================================================
# G. Bucketing
# =============================================================================

class TestBucketing:
    def test_the_series_is_zero_filled_and_never_has_a_gap(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day"
        )
        series = body["series"]
        # Seven days from 2026-10-01 to 2026-10-07 inclusive.
        assert len(series) == 7
        starts = [item["bucket_start"] for item in series]
        assert starts == sorted(starts)
        assert len(set(starts)) == len(starts)

    def test_the_bucket_labels_are_utc_floors(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day"
        )
        for item in body["series"]:
            assert item["bucket_start"].endswith("T00:00:00+00:00")

    def test_the_hour_buckets_are_floored_to_the_hour(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_FROM + timedelta(hours=3),
            bucket="hour",
        )
        assert [item["bucket_start"] for item in body["series"]] == [
            "2026-10-01T00:00:00+00:00",
            "2026-10-01T01:00:00+00:00",
            "2026-10-01T02:00:00+00:00",
        ]

    def test_an_empty_bucket_is_present_with_zeroed_counters(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day"
        )
        # 2026-10-05 holds no event at all.
        empty = next(
            item for item in body["series"]
            if item["bucket_start"] == "2026-10-05T00:00:00+00:00"
        )
        assert empty["logins"] == 0
        assert empty["mfa_challenges"] == 0
        assert empty["audit_events"] == 0

    def test_the_series_counts_the_events_of_its_bucket(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day"
        )
        first = body["series"][0]
        # The first day of the window holds the ``live`` / ``revoked`` /
        # ``expired`` / ``late_revoked`` sessions, the five MFA transactions
        # m1..m5 and the eight audit rows a1..a8.
        assert first["logins"] == 4
        assert first["mfa_challenges"] == 5
        assert first["audit_events"] == 8

    def test_the_series_sums_to_the_window_totals(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day"
        )
        series = body["series"]
        assert sum(item["audit_events"] for item in series) == (
            body["audit"]["total"]
        )
        assert sum(item["mfa_challenges"] for item in series) == (
            body["mfa"]["challenges"]
        )
        assert sum(item["logins"] for item in series) == (
            body["sessions"]["created_in_window"]
        )

    def test_logins_is_the_bucketed_session_count(self, get):
        """``series.logins`` mirrors ``sessions.created_in_window``.

        The design's own example pairs ``logins: 88`` with
        ``sessions.created_in_window: 88`` while the audit trail only holds
        ``45`` rows - a login count derived from the audit trail could never
        exceed the audit-event count, so the sessions are the source.
        """
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day"
        )
        assert sum(item["logins"] for item in body["series"]) == (
            body["sessions"]["created_in_window"]
        )


# =============================================================================
# H. An empty dataset
# =============================================================================

class TestEmptyDataset:
    def test_an_empty_window_reports_zeroes_not_a_crash(self, get):
        body = get(from_=EMPTY_FROM.isoformat(), to=EMPTY_TO.isoformat())
        assert body["audit"]["total"] == 0
        assert body["audit"]["by_action"] == {}
        assert body["audit_activity"]["recent"] == []
        # ``actor_type`` has a closed vocabulary, so the breakdown carries the
        # full canonical key set, zero-filled.
        assert body["audit_activity"]["by_actor_type"] == {
            "user": 0, "system": 0,
        }
        assert body["protective_actions"]["total"] == 0
        assert body["mfa"]["challenges"] == 0

    def test_an_empty_window_still_reports_the_point_in_time_counts(self, get):
        body = get(from_=EMPTY_FROM.isoformat(), to=EMPTY_TO.isoformat())
        # The user base is a current-state fact - it does not depend on the
        # window.
        assert body["users"]["total"] == 6
        assert body["users"]["new_in_window"] == 0

    def test_an_empty_window_still_produces_the_full_series(self, get):
        body = get(
            from_=EMPTY_FROM.isoformat(), to=EMPTY_TO.isoformat(), bucket="day"
        )
        assert len(body["series"]) == 1
        assert body["series"][0]["audit_events"] == 0


# =============================================================================
# I. Read-only
# =============================================================================

class TestReadOnly:
    def test_the_request_does_not_write_to_the_database(self, pg_engine, client):
        before = _row_counts(pg_engine)
        client.get(
            ENDPOINT,
            params={"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert _row_counts(pg_engine) == before


def _row_counts(engine: Engine) -> Dict[str, int]:
    """The row count of every Core table the provider reads."""
    counts: Dict[str, int] = {}
    with engine.connect() as conn:
        for table in (
            "users", "sessions", "mfa_transactions", "audit_logs",
        ):
            counts[table] = int(conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar_one())
    return counts


# =============================================================================
# J. Cross-database parity
# =============================================================================

def _sqlite_core_engine() -> Engine:
    """An in-memory SQLite engine carrying the Core tables.

    The production database is PostgreSQL, but the unit-test suite runs on
    SQLite, so both engines must answer with the **same numbers** (design
    5.2).  The schema comes from the ORM metadata - the same definitions the
    rest of the test suite uses - so the fixture rows are identical on both
    sides.
    """
    from app.db import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    wanted = [
        Base.metadata.tables[name]
        for name in (
            "roles", "users", "user_roles", "sessions",
            "mfa_transactions", "audit_logs",
        )
    ]
    Base.metadata.create_all(engine, tables=wanted, checkfirst=True)
    return engine


class TestCrossDatabaseParity:
    """The same fixture must produce the same numbers on both engines.

    The PostgreSQL payload is the reference; the SQLite payload must match it
    field by field.  This is what proves that the dialect-specific pieces of
    the implementation (the bucket expression and the prefix split) really are
    equivalent.
    """

    @pytest.fixture()
    def sqlite_payload(self, request) -> Dict[str, Any]:
        bucket = getattr(request, "param", "day")
        engine = _sqlite_core_engine()
        with engine.begin() as conn:
            _seed_rows(conn)

        from app.core_analytics import get_core_db
        from sqlalchemy.orm import sessionmaker

        maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = maker()

        def _override():
            return session

        test_app = _build_test_app()
        test_app.dependency_overrides[get_core_db] = _override
        try:
            with TestClient(test_app) as client:
                response = client.get(
                    ENDPOINT,
                    params={
                        "from": WINDOW_FROM.isoformat(),
                        "to": WINDOW_TO.isoformat(),
                        "bucket": bucket,
                    },
                    headers={"X-Internal-Secret": INTERNAL_SECRET},
                )
                assert response.status_code == 200, response.text
                return response.json()
        finally:
            test_app.dependency_overrides.pop(get_core_db, None)
            session.close()
            engine.dispose()

    @pytest.mark.parametrize("sqlite_payload", ["day", "hour"], indirect=True)
    def test_the_aggregate_blocks_match(self, get, sqlite_payload):
        postgres = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_TO.isoformat(),
            bucket=sqlite_payload["bucket"],
        )
        for block in (
            "users",
            "sessions",
            "mfa",
            "audit",
            "audit_activity",
            "protective_actions",
        ):
            assert sqlite_payload[block] == postgres[block], (
                f"the {block!r} block differs between PostgreSQL and SQLite"
            )

    @pytest.mark.parametrize("sqlite_payload", ["day", "hour"], indirect=True)
    def test_the_series_matches(self, get, sqlite_payload):
        postgres = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_TO.isoformat(),
            bucket=sqlite_payload["bucket"],
        )
        assert sqlite_payload["series"] == postgres["series"]


# =============================================================================
# K. Bounded-context isolation
# =============================================================================

class TestBoundedContextIsolation:
    """The Core provider must read ``sentinel_core`` and nothing else.

    These are **static** checks: they inspect the module source, so they
    cover every statement and not only the paths the tests happen to walk.
    """

    @staticmethod
    def _source() -> str:
        import app.core_analytics as module

        with open(module.__file__, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_the_provider_does_not_import_the_other_contexts(self):
        source = self._source()
        for forbidden in ("get_detection_db", "get_ml_db"):
            assert forbidden not in source, (
                f"app/core_analytics.py depends on {forbidden}. The Core "
                f"provider must read sentinel_core only."
            )

    def test_the_provider_does_not_import_detection_or_ml_models(self):
        import ast

        import app.core_analytics as module

        with open(module.__file__, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=module.__file__)

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.models":
                imported.update(alias.name for alias in node.names)

        offenders = imported & {
            "Alert", "AlertTimeline", "LoginAttempt", "RiskAssessment",
            "SocAnalyst", "DetectionLog", "Policy",
            "InferenceLog", "ModelVersion",
        }
        assert not offenders, (
            f"app/core_analytics.py imports models owned by another context: "
            f"{sorted(offenders)}."
        )

    def test_the_provider_only_declares_the_core_session(self):
        import ast

        import app.core_analytics as module

        with open(module.__file__, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=module.__file__)

        declared = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            # The DB session is a **default value** of the parameter, not a
            # decorator, so both places have to be inspected.
            defaults = list(node.args.defaults) + [
                default for default in node.args.kw_defaults if default
            ]
            for default in defaults:
                text = ast.unparse(default)
                if "get_core_db" in text or "get_detection_db" in text \
                        or "get_ml_db" in text:
                    declared.append(f"{node.name}: {text}")

        assert declared == ["core_analytics: Depends(get_core_db)"], (
            f"the provider declares an unexpected DB dependency: {declared}"
        )

    def test_the_provider_never_writes(self):
        """The endpoint is a pure read: no INSERT/UPDATE/DELETE anywhere."""
        source = self._source()
        for forbidden in (".delete(", ".insert(", ".update(", "db.add("):
            assert forbidden not in source, (
                f"app/core_analytics.py contains {forbidden!r}; the internal "
                f"endpoint is read-only (design 4.0)."
            )
