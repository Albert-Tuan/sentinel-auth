"""Contract tests for the Detection analytics provider.

Covers ``GET /api/v1/internal/analytics/detection`` - the aggregate endpoint
owned by the Detection context and consumed by the Manager facade.

What is proved
--------------
The module exercises the behaviours the design document calls out explicitly
because they are the ones two implementations get wrong:

* **the contract shape** - every section the Manager facade maps is present
  and has the documented type (design 4.1);
* **event-based vs current-status acknowledgement** - ``acknowledged_count``
  and ``by_status.acknowledged`` are different numbers on the same fixture
  (design 7.1, "Field-name separation");
* **the MTTA population** - the earliest acknowledgement before ``to``; an
  alert acknowledged only after ``to`` contributes to neither MTTA nor the
  acknowledgement count (design 5.1 rules 2 and 3);
* **the MTTR population** - ``resolved_at`` must fall inside ``[from, to)``,
  and a false positive never contributes (design 5.1 rule 4);
* **structured breakdowns** - ``by_rule`` / ``by_ml_reason`` come from
  ``detection_scores``, are multi-valued, top-20 descending with ties broken
  by name, and a malformed payload is skipped rather than raised (design 3.5);
* **the critical incident backlog** - it is not window-scoped and not
  affected by the ``status`` / ``risk_level`` filters (design 4.0, 8 item 8);
* **half-open windows** - an event exactly at ``to`` is excluded, one exactly
  at ``from`` is included;
* **zero-filled buckets** - every bucket of the window is present, the labels
  are UTC floors and there is neither a gap nor a duplicate (design 5.3);
* **the error model** - 400 for an invalid window / bucket / filter, 401 for a
  missing or wrong ``X-Internal-Secret`` (design 4.0, 7.1).

Database
--------
The tests run against a **disposable PostgreSQL** database - the production
database is PostgreSQL, and the SQL semantics that matter here (``date_trunc``
with an explicit ``AT TIME ZONE 'UTC'``, ``jsonb``, ``EXTRACT(EPOCH ...)``)
only exist there.  The database must carry the ``_test`` marker in its name;
the module refuses to run against anything else.

Configuration::

    DETECTION_TEST_URL   full URL of the disposable Detection database

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
from app.models import (
    Alert,
    AlertTimeline,
    DetectionLog,
    LoginAttempt,
    Policy,
    RiskAssessment,
    SocAnalyst,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DETECTION_TEST_URL = os.environ.get("DETECTION_TEST_URL", "")

#: Every database this module touches must carry this marker.  The module
#: recreates the ``public`` schema, so a production database would be
#: destroyed.  The guard fails loudly instead of skipping.
TEST_MARKER = "_test"

#: The internal shared secret used by the tests.  It must satisfy
#: ``get_internal_secret``: at least 32 characters, not the placeholder.
INTERNAL_SECRET = "detection-analytics-contract-secret-0123456789"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DETECTION = os.path.join(REPO_ROOT, "infra", "postgres", "schema-detection-v3.3.sql")

#: The reporting window every scenario uses.  It is a fixed, absolute window
#: so that the fixtures are deterministic and independent of the wall clock.
WINDOW_FROM = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
WINDOW_TO = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)

#: A window that contains no data at all, for the empty-population cases.
EMPTY_FROM = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
EMPTY_TO = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)

ENDPOINT = "/api/v1/internal/analytics/detection"


def _require_postgres() -> None:
    """Skip the module when the disposable Detection database is absent."""
    if not DETECTION_TEST_URL:
        pytest.skip(
            "NOT RUN - DETECTION_TEST_URL is not set, so the Detection "
            "analytics contract tests were skipped. Point it at a disposable "
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
            f"schema, so a real development database "
            f"(sentinel_detection) must never be used as a test target."
        )
    return name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_engine() -> Engine:
    """A PostgreSQL engine on the disposable Detection database."""
    _assert_disposable(DETECTION_TEST_URL, "the Detection analytics contract tests")
    eng = create_engine(DETECTION_TEST_URL, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module", autouse=True)
def detection_schema(pg_engine: Engine):
    """Rebuild the Detection schema from the canonical SQL file.

    The module owns the schema of its disposable database, so the fixture
    always starts from the canonical definition - a test can never inherit a
    table shape from a previous run.
    """
    with open(SCHEMA_DETECTION, "r", encoding="utf-8") as handle:
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
        conn.execute(text("DELETE FROM alert_timeline"))
        conn.execute(text("DELETE FROM detection_logs"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM risk_assessments"))
        conn.execute(text("DELETE FROM login_attempts"))
        conn.execute(text("DELETE FROM soc_analysts"))
        conn.execute(text("DELETE FROM policies"))

        ids = _seed_rows(conn)
    return ids


#: A fixed namespace for the deterministic fixture identifiers.  The rows get
#: reproducible UUIDs so that the PostgreSQL and the SQLite payload can be
#: compared field by field (design 5.2) - the identifiers are part of the
#: payload (``policy.active_policy_id``, ``critical_incidents[].alert_id``).
FIXTURE_NAMESPACE = NAMESPACE_URL


def _fid(label: str) -> Any:
    """A deterministic UUID for a fixture row."""
    return uuid5(FIXTURE_NAMESPACE, f"sentinel-detection-analytics/{label}")


def _seed_rows(conn) -> Dict[str, Any]:
    """Insert the deterministic fixture rows and return their identifiers.

    The inserts go through SQLAlchemy Core rather than raw SQL so that the
    **same** fixture can be loaded into PostgreSQL and into SQLite.  That is
    what makes the cross-database parity test (design 5.2) possible: the two
    engines receive identical logical rows, and the endpoint must answer with
    identical numbers.
    """
    ids: Dict[str, Any] = {}

    # --- policy ---------------------------------------------------------
    policy_id = _fid("policy")
    conn.execute(
        insert(Policy.__table__).values(
            id=policy_id,
            version="contract-v1",
            name="contract policy",
            description="fixture",
            rules=[],
            config={},
            is_active=True,
            created_at=WINDOW_FROM,
            updated_at=WINDOW_FROM,
        )
    )
    ids["policy_id"] = str(policy_id)

    # --- analysts -------------------------------------------------------
    analyst_active = _fid("analyst-active")
    analyst_inactive = _fid("analyst-inactive")
    conn.execute(
        insert(SocAnalyst.__table__),
        [
            {
                "id": _fid("analyst-active"),
                "user_id": _fid("analyst-active-user"),
                "display_name": "Active Analyst",
                "is_active": True,
                "max_alerts": 50,
                "created_at": WINDOW_FROM,
                "updated_at": WINDOW_FROM,
            },
            {
                "id": _fid("analyst-inactive"),
                "user_id": _fid("analyst-inactive-user"),
                "display_name": "Retired Analyst",
                "is_active": False,
                "max_alerts": 50,
                "created_at": WINDOW_FROM,
                "updated_at": WINDOW_FROM,
            },
        ],
    )
    ids["analyst_active"] = str(analyst_active)
    ids["analyst_inactive"] = str(analyst_inactive)

    # --- login attempts --------------------------------------------------
    # (key, timestamp, outcome, risk_level, decision, combined_score, ml_status)
    attempts = [
        ("a1", WINDOW_FROM + timedelta(hours=1), "success", "low", "allow", 0.10, "success"),
        ("a2", WINDOW_FROM + timedelta(hours=2), "failure", "medium", "challenge", 0.50, "unavailable"),
        ("a3", WINDOW_FROM + timedelta(hours=3), "blocked", "critical", "block", 0.90, "error"),
        ("a4", WINDOW_FROM + timedelta(hours=4), "mfa_required", "high", "challenge", 0.70, "success"),
        ("a5", WINDOW_FROM + timedelta(days=1), "success", "low", "allow", 0.20, "success"),
        # Outside the window: before ``from``.
        ("before", WINDOW_FROM - timedelta(days=1), "failure", "critical", "block", 0.95, "success"),
        # Exactly at ``to``: excluded by the half-open window.
        ("at_to", WINDOW_TO, "failure", "critical", "block", 0.99, "success"),
    ]
    ids["attempts"] = {}
    # The raw UUID objects are kept aside: the ``UUID`` column type binds a
    # UUID object on SQLite but accepts a string on PostgreSQL, so the
    # cross-database fixture must insert the object, never the text.
    raw_attempts: Dict[str, Any] = {}
    for key, ts, outcome, risk, decision, combined, ml_status in attempts:
        attempt_id = _fid(f"attempt-{key}")
        conn.execute(
            insert(LoginAttempt.__table__).values(
                id=attempt_id,
                event_id=_fid(f"attempt-{key}-event"),
                user_id=_fid(f"attempt-{key}-user"),
                username_attempted=f"{key}.user",
                outcome=outcome,
                mfa_used=False,
                timestamp=ts,
                status="processed",
                policy_id=policy_id,
                request_id=_fid(f"attempt-{key}-request"),
                risk_level=risk,
                detection_decision=decision,
                created_at=ts,
                updated_at=ts,
            )
        )
        conn.execute(
            insert(RiskAssessment.__table__).values(
                id=_fid(f"assessment-{key}"),
                login_attempt_id=attempt_id,
                policy_id=policy_id,
                rule_score=0.50,
                ml_score=0.50,
                combined_score=combined,
                ml_status=ml_status,
                risk_level=risk,
                decision=decision,
                created_at=ts,
            )
        )
        ids["attempts"][key] = str(attempt_id)
        raw_attempts[key] = attempt_id

    # --- alerts -----------------------------------------------------------
    # (key, attempt_key, status, risk_level, created_at, resolved_at,
    #  assigned, rule_hits, ml_reason_codes)
    alerts = [
        (
            "al1", "a2", "open", "medium",
            WINDOW_FROM + timedelta(hours=2, minutes=10), None, None,
            [("multiple_failures", True), ("new_device", False)],
            ["high_fail_count", "new_device"],
        ),
        (
            "al2", "a3", "acknowledged", "critical",
            WINDOW_FROM + timedelta(hours=3, minutes=10), None, analyst_active,
            [("multiple_failures", True), ("high_deviation", True)],
            ["high_fail_count"],
        ),
        (
            "al3", "a1", "resolved", "low",
            WINDOW_FROM + timedelta(hours=1, minutes=10),
            WINDOW_FROM + timedelta(hours=1, minutes=40), None,
            [("new_device", True)],
            ["new_device"],
        ),
        (
            "al4", "a4", "false_positive", "high",
            WINDOW_FROM + timedelta(hours=4, minutes=10),
            WINDOW_FROM + timedelta(hours=4, minutes=20), None,
            [("new_device", True)],
            ["new_ip"],
        ),
        (
            "al5", "a5", "resolved", "medium",
            WINDOW_FROM + timedelta(days=1, minutes=10),
            WINDOW_FROM + timedelta(days=1, minutes=30), None,
            [],
            [],
        ),
        # A malformed structured payload: it must be skipped, never raised.
        (
            "al6", "a5", "open", "low",
            WINDOW_FROM + timedelta(days=1, minutes=40), None, None,
            "not-a-list",
            {"not": "a list"},
        ),
        # Created inside the window but acknowledged only AFTER ``to``:
        # contributes to neither the acknowledgement count nor MTTA.
        (
            "al7", "a5", "open", "medium",
            WINDOW_FROM + timedelta(days=1, minutes=50), None, None,
            [("new_device", True)],
            ["new_device"],
        ),
        # Currently ``resolved`` but resolved BEFORE the window start: it is
        # counted in ``resolved_count`` and excluded from ``mttr_population``
        # (design 4.1: the MTTR population "can be smaller than
        # ``resolved_count``").
        (
            "al8", "a5", "resolved", "medium",
            WINDOW_FROM + timedelta(days=1, minutes=5),
            WINDOW_FROM - timedelta(hours=1), None,
            [],
            [],
        ),
        # Currently ``resolved`` but resolved AFTER the window end: excluded
        # from the MTTR population entirely (design 5.1 rule 4).
        (
            "al9", "a5", "resolved", "low",
            WINDOW_FROM + timedelta(days=1, minutes=15),
            WINDOW_TO + timedelta(hours=1), None,
            [],
            [],
        ),
        # Outside the window: before ``from`` - must not appear in the
        # window-scoped aggregates, but must stay in the incident backlog.
        (
            "old", "before", "open", "critical",
            WINDOW_FROM - timedelta(days=1, minutes=30), None, None,
            [("multiple_failures", True)],
            ["high_fail_count"],
        ),
    ]
    ids["alerts"] = {}
    raw_alerts: Dict[str, Any] = {}
    for (
        key, attempt_key, status, risk, created_at, resolved_at, assigned,
        rule_hits, ml_reason_codes,
    ) in alerts:
        alert_id = _fid(f"alert-{key}")
        if key == "al6":
            # A malformed structured payload: not a JSON object at all.  The
            # breakdown reader must skip it, never raise.
            scores: Any = "not-a-dict"
        else:
            scores = {
                "combined_score": 0.5,
                "rule_hits": [
                    {"rule_name": name, "triggered": triggered}
                    for name, triggered in rule_hits
                ],
                "ml_reason_codes": list(ml_reason_codes),
            }
        conn.execute(
            insert(Alert.__table__).values(
                id=alert_id,
                login_attempt_id=raw_attempts[attempt_key],
                policy_id=policy_id,
                status=status,
                risk_level=risk,
                detection_reason="REQUIRE_MFA: combined=0.5000 (rule=0.5000, ml=0.5000)",
                detection_scores=scores,
                assigned_to_id=assigned,
                resolved_at=resolved_at,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        ids["alerts"][key] = str(alert_id)
        raw_alerts[key] = alert_id

    # --- timeline events ---------------------------------------------------
    # (alert_key, event_type, created_at)
    timeline = [
        ("al1", "created", WINDOW_FROM + timedelta(hours=2, minutes=10)),
        ("al1", "acknowledged", WINDOW_FROM + timedelta(hours=2, minutes=15)),
        ("al2", "created", WINDOW_FROM + timedelta(hours=3, minutes=10)),
        ("al2", "acknowledged", WINDOW_FROM + timedelta(hours=3, minutes=20)),
        ("al2", "assigned", WINDOW_FROM + timedelta(hours=3, minutes=12)),
        ("al3", "created", WINDOW_FROM + timedelta(hours=1, minutes=10)),
        ("al3", "acknowledged", WINDOW_FROM + timedelta(hours=1, minutes=20)),
        ("al3", "resolved", WINDOW_FROM + timedelta(hours=1, minutes=40)),
        ("al4", "created", WINDOW_FROM + timedelta(hours=4, minutes=10)),
        ("al4", "false_positive", WINDOW_FROM + timedelta(hours=4, minutes=20)),
        ("al5", "created", WINDOW_FROM + timedelta(days=1, minutes=10)),
        ("al5", "resolved", WINDOW_FROM + timedelta(days=1, minutes=30)),
        ("al5", "escalated", WINDOW_FROM + timedelta(days=1, minutes=35)),
        ("al6", "created", WINDOW_FROM + timedelta(days=1, minutes=40)),
        ("al8", "created", WINDOW_FROM + timedelta(days=1, minutes=5)),
        ("al9", "created", WINDOW_FROM + timedelta(days=1, minutes=15)),
        # Created inside the window, acknowledged only AFTER ``to``.
        ("al7", "created", WINDOW_FROM + timedelta(days=1, minutes=50)),
        ("al7", "acknowledged", WINDOW_TO + timedelta(minutes=5)),
        # Acknowledged only AFTER the window end: contributes to nothing.
        ("old", "created", WINDOW_FROM - timedelta(days=1, minutes=30)),
        ("old", "acknowledged", WINDOW_FROM - timedelta(days=1, minutes=20)),
    ]
    conn.execute(
        insert(AlertTimeline.__table__),
        [
            {
                "id": _fid(f"timeline-{alert_key}-{event_type}"),
                "alert_id": raw_alerts[alert_key],
                "event_type": event_type,
                "actor_type": "system",
                "created_at": created_at,
            }
            for alert_key, event_type, created_at in timeline
        ],
    )

    # --- detection logs -----------------------------------------------------
    # (stage, created_at, details)
    logs = [
        ("action_sent", WINDOW_FROM + timedelta(hours=2, minutes=12), {"enforced": True}),
        ("action_sent", WINDOW_FROM + timedelta(hours=2, minutes=13), {"enforced": False}),
        ("action_sent", WINDOW_FROM + timedelta(hours=3, minutes=12), {"enforced": True}),
        ("action_sent", WINDOW_FROM + timedelta(hours=4, minutes=12), {"enforced": True}),
        # Outside the window.
        ("action_sent", WINDOW_FROM - timedelta(hours=1), {"enforced": True}),
        # A different stage: never counted.
        ("rule_evaluation", WINDOW_FROM + timedelta(hours=2), {"enforced": True}),
    ]
    conn.execute(
        insert(DetectionLog.__table__),
        [
            {
                "id": _fid(f"log-{stage}-{created_at.isoformat()}"),
                "login_attempt_id": raw_attempts["a2"],
                "request_id": _fid(f"log-request-{created_at.isoformat()}"),
                "stage": stage,
                "details": details,
                "created_at": created_at,
            }
            for stage, created_at, details in logs
        ],
    )

    return ids


@pytest.fixture()
def client(pg_engine: Engine, seeded, monkeypatch):
    """A TestClient wired to the disposable Detection database."""
    monkeypatch.setenv("DETECTION_DATABASE_URL", DETECTION_TEST_URL)
    monkeypatch.setenv("INTERNAL_SECRET", INTERNAL_SECRET)
    app_db.dispose_engines()

    from app.main import app

    app.dependency_overrides = {}
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides = {}
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


# ---------------------------------------------------------------------------
# A. The contract shape
# ---------------------------------------------------------------------------

class TestContractShape:
    def test_every_documented_section_is_present(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        for section in (
            "login_attempts", "risk_assessments", "alerts", "analysts",
            "critical_incidents", "enforcement", "series", "policy",
        ):
            assert section in body, f"missing section {section!r}"

    def test_envelope_carries_generated_at_window_and_bucket(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert body["generated_at"].endswith("+00:00")
        assert body["window"]["from"] == WINDOW_FROM.isoformat()
        assert body["window"]["to"] == WINDOW_TO.isoformat()
        assert body["bucket"] == "day"

    def test_breakdowns_carry_the_full_canonical_key_set(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        login = body["login_attempts"]
        assert set(login["by_outcome"]) == {
            "success", "failure", "mfa_required", "mfa_success",
            "mfa_failed", "blocked", "locked", "rate_limited",
        }
        assert set(login["by_risk_level"]) == {"low", "medium", "high", "critical"}
        assert set(login["by_decision"]) == {"allow", "challenge", "block"}
        assert set(body["alerts"]["by_status"]) == {
            "open", "acknowledged", "resolved", "false_positive",
        }
        assert set(body["alerts"]["by_risk_level"]) == {
            "low", "medium", "high", "critical",
        }

    def test_policy_reports_the_active_policy(self, get, seeded):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert body["policy"]["active_version"] == "contract-v1"
        assert body["policy"]["active_policy_id"] == seeded["policy_id"]

    def test_analysts_active_is_a_point_in_time_count(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert body["analysts"]["active"] == 1


# ---------------------------------------------------------------------------
# B. Window-scoped aggregates
# ---------------------------------------------------------------------------

class TestWindowScopedAggregates:
    def test_login_attempts_total_excludes_rows_outside_the_window(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # Five attempts inside the window; one before ``from`` and one exactly
        # at ``to`` are excluded by the half-open window.
        assert body["login_attempts"]["total"] == 5

    def test_login_attempts_by_outcome_counts(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        by_outcome = body["login_attempts"]["by_outcome"]
        assert by_outcome["success"] == 2
        assert by_outcome["failure"] == 1
        assert by_outcome["blocked"] == 1
        assert by_outcome["mfa_required"] == 1
        assert by_outcome["mfa_failed"] == 0

    def test_login_attempts_avg_combined_score_joins_the_assessment(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # (0.10 + 0.50 + 0.90 + 0.70 + 0.20) / 5
        assert body["login_attempts"]["avg_combined_score"] == pytest.approx(0.48)

    def test_risk_assessments_fallback_rate_counts_null_status_as_fallback(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assessments = body["risk_assessments"]
        assert assessments["total"] == 5
        assert assessments["ml_success"] == 3
        assert assessments["ml_unavailable"] == 1
        assert assessments["ml_error"] == 1
        # Two of the five assessments did not get a successful ML call.
        assert assessments["fallback_rate"] == 0.4

    def test_enforcement_counts_only_action_sent_inside_the_window(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        enforcement = body["enforcement"]
        assert enforcement["attempted"] == 4
        assert enforcement["succeeded"] == 3
        assert enforcement["success_rate"] == 0.75


# ---------------------------------------------------------------------------
# C. Event-based acknowledgement vs current status
# ---------------------------------------------------------------------------

class TestAcknowledgementSemantics:
    def test_acknowledged_count_is_event_based_and_differs_from_the_status_count(
        self, get
    ):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        # Three alerts carry an ``acknowledged`` event inside the window:
        # al1 (open), al2 (acknowledged) and al3 (resolved).
        assert alerts["acknowledged_count"] == 3
        # The current-status count is a different number: only al2 is still
        # in the ``acknowledged`` status.
        assert alerts["by_status"]["acknowledged"] == 1
        assert alerts["acknowledged_count"] != alerts["by_status"]["acknowledged"]

    def test_an_alert_acknowledged_only_after_the_window_contributes_nothing(
        self, get, seeded
    ):
        """An acknowledgement after ``to`` is neither MTTA nor acknowledgement.

        The fixture's ``old`` alert is created *before* the window, so it is
        outside the alert population entirely.  The rule is exercised by the
        ``al7`` alert: created inside the window, acknowledged only after
        ``to``.
        """
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        # al7 has an ``acknowledged`` event, but it happens after ``to``.
        assert alerts["acknowledged_count"] == 3
        # It is therefore not part of the MTTA population either.
        assert alerts["mtta_seconds"] == 500.0
        # The old alert must not appear in the window-scoped aggregates.
        assert body["alerts"]["created"] == 9

    def test_escalated_count_is_event_based(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert body["alerts"]["escalated_count"] == 1

    def test_mtta_uses_the_earliest_acknowledgement_before_to(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # al1: ack 5 min after creation; al2: 10 min; al3: 10 min.
        # Mean = (300 + 600 + 600) / 3 = 500 seconds.
        assert body["alerts"]["mtta_seconds"] == 500.0

    def test_mtta_is_null_without_an_acknowledged_alert(self, get):
        body = get(from_=EMPTY_FROM.isoformat(), to=EMPTY_TO.isoformat())
        assert body["alerts"]["mtta_seconds"] is None
        assert body["alerts"]["acknowledged_count"] == 0


# ---------------------------------------------------------------------------
# D. MTTR population
# ---------------------------------------------------------------------------

class TestMttrPopulation:
    def test_mttr_uses_resolved_at_inside_the_window(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        # al3 resolved 30 min after creation; al5 resolved 20 min after
        # creation.  Mean = (1800 + 1200) / 2 = 1500 seconds.
        assert alerts["mttr_population"] == 2
        assert alerts["mttr_seconds"] == 1500.0

    def test_false_positives_never_contribute_to_mttr(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        assert alerts["false_positive_count"] == 1
        # The false positive (al4) is excluded from the MTTR population.
        assert alerts["mttr_population"] == 2

    def test_an_alert_resolved_before_the_window_is_excluded_from_mttr(self, get):
        """``mttr_population`` can be smaller than ``resolved_count``.

        ``al8`` is currently ``resolved`` but was resolved before the window
        start; it is counted in ``resolved_count`` and excluded from the MTTR
        population (design 4.1 / 5.1 rule 4).
        """
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        assert alerts["resolved_count"] == 4
        assert alerts["mttr_population"] == 2
        assert alerts["mttr_population"] < alerts["resolved_count"]

    def test_an_alert_resolved_after_the_window_is_excluded_from_mttr(self, get):
        """``al9`` was resolved after ``to`` - it contributes nothing."""
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        # al3 (1800 s) and al5 (1200 s) only; al9 is excluded.
        assert alerts["mttr_seconds"] == 1500.0

    def test_resolved_count_is_the_current_status_count(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        assert alerts["resolved_count"] == 4
        assert alerts["by_status"]["resolved"] == 4

    def test_mttr_is_null_over_an_empty_population(self, get):
        body = get(from_=EMPTY_FROM.isoformat(), to=EMPTY_TO.isoformat())
        assert body["alerts"]["mttr_seconds"] is None
        assert body["alerts"]["mttr_population"] == 0


# ---------------------------------------------------------------------------
# E. Structured breakdowns
# ---------------------------------------------------------------------------

class TestStructuredBreakdowns:
    def test_by_rule_counts_only_triggered_hits(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        by_rule = body["alerts"]["by_rule"]
        # al1 fires multiple_failures but NOT new_device.
        assert {row["rule"]: row["count"] for row in by_rule} == {
            "multiple_failures": 2,
            "high_deviation": 1,
            "new_device": 3,
        }

    def test_by_ml_reason_is_multi_valued(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        by_reason = body["alerts"]["by_ml_reason"]
        counts = {row["code"]: row["count"] for row in by_reason}
        assert counts["high_fail_count"] == 2
        assert counts["new_device"] == 3
        assert counts["new_ip"] == 1
        # The breakdown is a "reasons observed" list, not a partition: al1
        # contributes two distinct codes, al5 contributes none.
        assert sum(counts.values()) != body["alerts"]["created"]

    def test_breakdowns_are_sorted_descending_with_ties_broken_by_name(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        for key in ("by_rule", "by_ml_reason"):
            rows = body["alerts"][key]
            name_key = "rule" if key == "by_rule" else "code"
            names = [row[name_key] for row in rows]
            counts = [row["count"] for row in rows]
            assert counts == sorted(counts, reverse=True)
            # Ties (equal counts) must be ordered by name ascending.
            for index in range(len(rows) - 1):
                if counts[index] == counts[index + 1]:
                    assert names[index] < names[index + 1]

    def test_a_malformed_payload_is_skipped_and_never_raises(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # The fixture holds one alert whose ``detection_scores`` is not the
        # expected shape; the request still succeeds and the alert is counted.
        assert body["alerts"]["created"] == 9
        assert isinstance(body["alerts"]["by_rule"], list)

    def test_breakdowns_are_empty_over_an_empty_population(self, get):
        body = get(from_=EMPTY_FROM.isoformat(), to=EMPTY_TO.isoformat())
        assert body["alerts"]["by_rule"] == []
        assert body["alerts"]["by_ml_reason"] == []


# ---------------------------------------------------------------------------
# F. The critical incident backlog
# ---------------------------------------------------------------------------

class TestCriticalIncidentBacklog:
    def test_the_backlog_is_not_window_scoped(self, get):
        """An open critical alert from before the window is still listed."""
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alert_ids = [item["alert_id"] for item in body["critical_incidents"]]
        # al2 (critical, acknowledged) and the ``old`` alert (critical, open,
        # created before ``from``) are both present.
        assert len(alert_ids) == 2

    def test_resolved_and_false_positive_alerts_never_appear(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        statuses = {item["status"] for item in body["critical_incidents"]}
        assert statuses <= {"open", "acknowledged"}
        risks = {item["risk_level"] for item in body["critical_incidents"]}
        assert risks <= {"high", "critical"}

    def test_ordering_is_severity_first_then_oldest_first(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        incidents = body["critical_incidents"]
        severities = [
            0 if item["risk_level"] == "critical" else 1 for item in incidents
        ]
        assert severities == sorted(severities)
        # Within the same severity the oldest alert comes first.
        criticals = [i for i in incidents if i["risk_level"] == "critical"]
        created = [i["created_at"] for i in criticals]
        assert created == sorted(created)

    def test_the_list_is_capped_at_ten(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        assert len(body["critical_incidents"]) <= 10

    def test_an_incident_carries_its_subject_and_score(self, get, seeded):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        incident = next(
            item for item in body["critical_incidents"]
            if item["alert_id"] == seeded["alerts"]["al2"]
        )
        assert incident["subject"]["username"] == "a3.user"
        assert incident["subject"]["user_id"] is not None
        assert incident["combined_score"] == 0.9
        assert incident["assigned_to"] == "Active Analyst"
        assert incident["detection_reason"].startswith("REQUIRE_MFA:")
        assert incident["age_hours"] >= 0

    def test_an_unassigned_incident_reports_a_null_assignee(self, get, seeded):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        incident = next(
            item for item in body["critical_incidents"]
            if item["alert_id"] == seeded["alerts"]["old"]
        )
        assert incident["assigned_to"] is None

    def test_status_filter_does_not_filter_the_backlog(self, get, seeded):
        without = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        with_filter = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), status="resolved"
        )
        assert [
            item["alert_id"] for item in without["critical_incidents"]
        ] == [
            item["alert_id"] for item in with_filter["critical_incidents"]
        ]

    def test_risk_level_filter_does_not_filter_the_backlog(self, get):
        without = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        with_filter = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), risk_level="low"
        )
        assert without["critical_incidents"] == with_filter["critical_incidents"]

    def test_an_empty_window_still_lists_the_backlog(self, get):
        body = get(from_=EMPTY_FROM.isoformat(), to=EMPTY_TO.isoformat())
        assert len(body["critical_incidents"]) == 2


# ---------------------------------------------------------------------------
# F2. The alert backlog counters
# ---------------------------------------------------------------------------

class TestAlertBacklogCounters:
    """``unassigned_open`` / ``oldest_open_age_hours`` / ``critical_open``.

    ``unassigned_open`` and ``oldest_open_age_hours`` describe the **filtered
    alert population** (design 3.2: the filters are applied before every
    breakdown).  ``critical_open`` is the one documented exception: it is a
    **current-backlog** count, exactly like ``critical_incidents``
    (design 4.1 field notes).
    """

    def test_unassigned_open_counts_the_open_alerts_without_an_assignee(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        # al1, al6 and al7 are open and unassigned; al2 is assigned.
        assert alerts["unassigned_open"] == 3
        assert alerts["unassigned_open"] <= alerts["by_status"]["open"]

    def test_unassigned_open_follows_the_filtered_population(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), status="resolved"
        )
        # ``status=resolved`` selects a population with no open alert at all.
        assert body["alerts"]["unassigned_open"] == 0

    def test_oldest_open_age_hours_describes_the_oldest_open_alert(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        age = body["alerts"]["oldest_open_age_hours"]
        assert age is not None
        assert age > 0

    def test_oldest_open_age_hours_is_null_without_an_open_alert(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), status="resolved"
        )
        assert body["alerts"]["oldest_open_age_hours"] is None

    def test_critical_open_is_a_current_backlog_count(self, get):
        """``critical_open`` is not window-scoped and not filtered."""
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        # Only the ``old`` alert is open + critical, and it was created before
        # the window - so the count proves the backlog semantics.
        assert body["alerts"]["critical_open"] == 1

    def test_critical_open_is_not_affected_by_the_filters(self, get):
        without = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        with_filter = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), status="resolved"
        )
        assert (
            with_filter["alerts"]["critical_open"]
            == without["alerts"]["critical_open"]
        )

    def test_critical_open_is_not_confused_with_the_incident_list(self, get):
        """``critical_open`` and ``critical_incidents`` are different populations.

        ``critical_open`` counts **every** currently-open ``critical`` alert
        (system-wide, unfiltered, uncapped).  ``critical_incidents`` is a
        **top-10** list over ``high`` **and** ``critical`` alerts in ``open``
        **and** ``acknowledged`` status.  The two therefore must not be
        compared with one another (design 3.3, 4.0, 4.1).
        """
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        alerts = body["alerts"]
        incidents = body["critical_incidents"]

        # ``critical_open`` counts open + critical alerts only.  The fixture
        # has exactly one (the ``old`` alert, created before the window).
        assert alerts["critical_open"] == 1

        # The incident list is a *different* population: it also contains
        # ``acknowledged`` critical alerts (al2), which ``critical_open``
        # does not count.
        assert any(
            item["risk_level"] == "critical" and item["status"] == "acknowledged"
            for item in incidents
        )
        assert alerts["critical_open"] != len(incidents)


# ---------------------------------------------------------------------------
# G. The status / risk_level filters
# ---------------------------------------------------------------------------

class TestFilters:
    def test_a_status_filter_selects_the_alert_population(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), status="open"
        )
        alerts = body["alerts"]
        # al1, al6 and al7 are open.
        assert alerts["created"] == 3
        assert alerts["by_status"]["open"] == 3
        assert alerts["by_status"]["resolved"] == 0

    def test_a_risk_level_filter_selects_the_alert_population(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), risk_level="critical"
        )
        assert body["alerts"]["created"] == 1
        assert body["alerts"]["by_risk_level"]["critical"] == 1

    def test_the_filters_do_not_change_the_login_attempt_aggregates(self, get):
        without = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat())
        with_filter = get(
            from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), status="open"
        )
        assert (
            with_filter["login_attempts"]["total"]
            == without["login_attempts"]["total"]
        )


# ---------------------------------------------------------------------------
# H. Bucketing
# ---------------------------------------------------------------------------

class TestBucketing:
    def test_the_series_is_zero_filled_and_never_has_a_gap(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day")
        series = body["series"]
        # Seven days from 2026-10-01 to 2026-10-07 inclusive.
        assert len(series) == 7
        starts = [item["bucket_start"] for item in series]
        assert starts == sorted(starts)
        assert len(set(starts)) == len(starts)
        assert starts[0] == "2026-10-01T00:00:00+00:00"
        assert starts[-1] == "2026-10-07T00:00:00+00:00"

    def test_an_empty_bucket_is_present_with_zeroed_counters(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day")
        series = body["series"]
        empty = [item for item in series if item["login_attempts"] == 0]
        assert empty, "the fixture must leave at least one day empty"
        for item in empty:
            assert item["alerts_created"] == 0
            assert set(item["by_outcome"].values()) == {0}
            assert set(item["alerts_by_status"].values()) == {0}

    def test_the_bucket_labels_are_utc_floors(self, get):
        body = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_FROM + timedelta(hours=5),
            bucket="hour",
        )
        series = body["series"]
        assert [item["bucket_start"] for item in series] == [
            "2026-10-01T00:00:00+00:00",
            "2026-10-01T01:00:00+00:00",
            "2026-10-01T02:00:00+00:00",
            "2026-10-01T03:00:00+00:00",
            "2026-10-01T04:00:00+00:00",
        ]

    def test_the_bucketed_counts_sum_to_the_window_totals(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day")
        series = body["series"]
        assert sum(item["login_attempts"] for item in series) == (
            body["login_attempts"]["total"]
        )
        assert sum(item["alerts_created"] for item in series) == (
            body["alerts"]["created"]
        )

    def test_the_series_carries_the_full_canonical_key_sets(self, get):
        body = get(from_=WINDOW_FROM.isoformat(), to=WINDOW_TO.isoformat(), bucket="day")
        for item in body["series"]:
            assert set(item["by_outcome"]) == {
                "success", "failure", "mfa_required", "mfa_success",
                "mfa_failed", "blocked", "locked", "rate_limited",
            }
            assert set(item["by_risk_level"]) == {"low", "medium", "high", "critical"}
            assert set(item["alerts_by_status"]) == {
                "open", "acknowledged", "resolved", "false_positive",
            }

    def test_bucket_auto_resolves_from_the_window_length(self, get):
        short = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_FROM + timedelta(hours=48),
            bucket="auto",
        )
        assert short["bucket"] == "hour"
        long = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_FROM + timedelta(days=30),
            bucket="auto",
        )
        assert long["bucket"] == "day"


# ---------------------------------------------------------------------------
# I. The error model
# ---------------------------------------------------------------------------

class TestErrorModel:
    def test_a_reversed_window_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": WINDOW_TO.isoformat(),
                "to": WINDOW_FROM.isoformat(),
            },
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_an_oversized_window_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": (WINDOW_FROM - timedelta(days=400)).isoformat(),
                "to": WINDOW_TO.isoformat(),
            },
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_hour_bucket_over_a_long_window_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": (WINDOW_FROM - timedelta(days=60)).isoformat(),
                "to": WINDOW_TO.isoformat(),
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

    def test_an_unknown_status_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": WINDOW_FROM.isoformat(),
                "to": WINDOW_TO.isoformat(),
                "status": "banana",
            },
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_an_unknown_risk_level_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={
                "from": WINDOW_FROM.isoformat(),
                "to": WINDOW_TO.isoformat(),
                "risk_level": "extreme",
            },
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

    def test_an_unparseable_timestamp_is_a_400(self, client):
        response = client.get(
            ENDPOINT,
            params={"from": "yesterday", "to": WINDOW_TO.isoformat()},
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert response.status_code == 400

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


# ---------------------------------------------------------------------------
# J. The endpoint is read-only
# ---------------------------------------------------------------------------

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
    """The row count of every Detection table."""
    counts: Dict[str, int] = {}
    with engine.connect() as conn:
        for table in (
            "policies", "login_attempts", "risk_assessments", "detection_logs",
            "soc_analysts", "alerts", "alert_timeline",
        ):
            counts[table] = int(
                conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            )
    return counts


# ---------------------------------------------------------------------------
# K. Cross-database parity (design 5.2)
# ---------------------------------------------------------------------------

def _sqlite_detection_engine() -> Engine:
    """An in-memory SQLite engine carrying the Detection tables.

    The production database is PostgreSQL, but the unit-test suite runs on
    SQLite, so both engines must answer with the **same numbers** (design
    5.2).  The schema comes from the ORM metadata - the same definitions the
    rest of the test suite uses - so the fixture rows are identical on both
    sides.
    """
    # ``app.models`` is already imported at module level, so the table
    # definitions are registered on ``Base.metadata``.
    from app.db import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    wanted = [
        Base.metadata.tables[name]
        for name in (
            "policies", "login_attempts", "risk_assessments", "detection_logs",
            "soc_analysts", "alerts", "alert_timeline",
        )
    ]
    Base.metadata.create_all(engine, tables=wanted, checkfirst=True)
    return engine


class TestCrossDatabaseParity:
    """The same fixture must produce the same numbers on both engines.

    The PostgreSQL payload is the reference; the SQLite payload must match it
    field by field.  This is what proves that the dialect-specific pieces of
    the implementation (the bucket expression, the JSON reading and the
    duration arithmetic) really are equivalent.
    """

    @pytest.fixture()
    def sqlite_payload(self) -> Dict[str, Any]:
        return self._sqlite_payload("day")

    def _sqlite_payload(self, bucket: str) -> Dict[str, Any]:
        engine = _sqlite_detection_engine()
        with engine.begin() as conn:
            _seed_rows(conn)

        from app.detection_analytics import get_detection_db
        from app.main import app
        from sqlalchemy.orm import sessionmaker

        maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = maker()

        def _override():
            return session

        app.dependency_overrides[get_detection_db] = _override
        try:
            with TestClient(app) as client:
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
            app.dependency_overrides.pop(get_detection_db, None)
            session.close()
            engine.dispose()

    def test_the_aggregate_blocks_match(self, get, sqlite_payload):
        postgres = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_TO.isoformat(),
            bucket="day",
        )
        for block in (
            "login_attempts",
            "risk_assessments",
            "alerts",
            "analysts",
            "enforcement",
            "policy",
        ):
            assert sqlite_payload[block] == postgres[block], (
                f"the {block!r} block differs between PostgreSQL and SQLite"
            )

    def test_the_series_matches(self, get, sqlite_payload):
        postgres = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_TO.isoformat(),
            bucket="day",
        )
        assert sqlite_payload["series"] == postgres["series"]

    def test_the_critical_incidents_match(self, get, sqlite_payload):
        postgres = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_TO.isoformat(),
            bucket="day",
        )
        # ``age_hours`` depends on ``now``, so only the stable fields are
        # compared - the ordering and the population must still match.
        def _stable(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [
                {
                    "risk_level": row["risk_level"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "username": row["subject"]["username"],
                    "detection_reason": row["detection_reason"],
                    "combined_score": row["combined_score"],
                    "assigned_to": row["assigned_to"],
                }
                for row in rows
            ]

        assert _stable(sqlite_payload["critical_incidents"]) == _stable(
            postgres["critical_incidents"]
        )

    def test_the_hour_bucketed_series_matches(self, get):
        """The hour bucket uses a different SQL expression on each dialect."""
        sqlite_payload = self._sqlite_payload("hour")
        postgres = get(
            from_=WINDOW_FROM.isoformat(),
            to=WINDOW_TO.isoformat(),
            bucket="hour",
        )
        assert sqlite_payload["series"] == postgres["series"]
        # The hour grid is finer than the day grid.
        assert len(postgres["series"]) > 7
        assert all(
            item["bucket_start"].endswith(":00:00+00:00")
            for item in postgres["series"]
        )
