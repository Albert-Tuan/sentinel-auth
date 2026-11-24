#!/usr/bin/env python
"""Sentinel Auth — seed the SOC alert fixtures for the real-HTTP suite.

The frontend's Stage 4 integration suite
(``frontend/src/test/integration/realBackendAlerts.test.ts``) talks to a
**live** FastAPI backend over real HTTP and reads the SOC alert screens.
It therefore needs real rows in the Detection database: an alert, the
login attempt behind it, the risk assessment, the detection logs and the
timeline.

The fixtures are deliberately shaped to exercise the CONTRACT that the
frontend depends on:

=========================  ==================================================
Fixture                    What it pins down
=========================  ==================================================
``m12-alert-critical``     A fully scored alert: every score present, the
                           risk level ``critical``, the status ``open``.
``m12-alert-ruleless``     The **rule-only fallback**: ``ml_score`` is NULL
                           and ``ml_status`` is ``unavailable``. The
                           frontend must show "no data" for the ML score —
                           never a zero — and must say "rule-only".
``m12-alert-low``          A low-risk, already-acknowledged alert, used for
                           the status and risk-level filters.
=========================  ==================================================

The seed is **idempotent**: the rows are identified by a fixed marker in
``detection_reason`` (``m12-stage4-fixture``), so re-running the script
replaces the fixtures instead of piling them up. The rows are removed
again by ``--cleanup``.

Usage::

    DETECTION_DATABASE_URL=postgresql://... \\
        python scripts/ci_seed_frontend_alerts.py

    DETECTION_DATABASE_URL=postgresql://... \\
        python scripts/ci_seed_frontend_alerts.py --cleanup
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: The marker that identifies the fixture rows. It is stored in
#: ``alerts.detection_reason`` so the cleanup can find the rows again
#: without depending on the generated UUIDs.
FIXTURE_MARKER = "m12-stage4-fixture"

#: The username the fixture login attempts report. It is a Detection-side
#: value (``login_attempts.username_attempted``), not a Core user.
FIXTURE_USERNAME = "m12stage4subject"

#: The suffix every disposable database name carries.
#:
#: The CI provisions its databases as ``sentinel_detection_test`` and
#: friends. A database whose name does NOT carry this marker is treated
#: as a real deployment database and is refused: the seed writes rows and
#: the cleanup DELETES rows, so neither may ever run against production.
DISPOSABLE_DB_MARKER = "_test"


def assert_disposable_database(database_url: str) -> str:
    """Refuse to run against a database that is not a disposable one.

    The seed creates rows and the cleanup deletes them. Both are scoped to
    the fixture marker, but a mistake against a real database would still
    be unacceptable — so the guard is at the DATABASE level, before a
    single row is touched.

    The guard accepts a database whose name carries the ``_test`` marker.
    That is the same rule ``scripts/ci_bootstrap_postgres.sh`` applies
    when it drops and recreates the disposable databases, so the two
    scripts can never disagree about what is disposable.

    :param database_url: the connection URL the script is about to use
    :return: the database name that was validated
    :raises SystemExit: when the database is not a disposable one
    """
    # The name is the last path segment of the URL, without the query
    # string. A URL without a database name has no database to check and
    # is therefore refused as well.
    path = database_url.split("?", 1)[0]
    name = path.rsplit("/", 1)[-1]

    if not name:
        print(
            "[seed-alerts] ERROR: the connection URL does not name a "
            "database, so it cannot be proven disposable.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if not name.endswith(DISPOSABLE_DB_MARKER):
        print(
            f"[seed-alerts] ERROR: refusing to touch the database "
            f"'{name}': the name lacks the "
            f"'{DISPOSABLE_DB_MARKER}' marker that marks a disposable "
            f"database.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return name


def _fixture_alerts() -> List[Dict[str, object]]:
    """The alert fixtures, in the order they are created."""
    return [
        {
            "key": "critical",
            "status": "open",
            "risk_level": "critical",
            "detection_reason": (
                f"{FIXTURE_MARKER}: impossible travel, combined=0.9123"
            ),
            "detection_scores": {
                "rule_score": 0.6,
                "ml_score": 0.3123,
                "combined_score": 0.9123,
                "ml_status": "success",
                "ml_model_version": "m12-fixture-model",
                "rule_hits": [{"rule_name": "impossible_travel"}],
                "ml_reason_codes": ["rare_ip"],
            },
            "attempt": {
                "outcome": "failure",
                "username_attempted": FIXTURE_USERNAME,
                "ip_address": "203.0.113.7",
                "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0",
                "mfa_used": False,
                "risk_level": "critical",
                "detection_decision": "block",
            },
            "assessment": {
                "rule_score": 0.6,
                "ml_score": 0.3123,
                "combined_score": 0.9123,
                "ml_status": "success",
                "ml_model_version": "m12-fixture-model",
                "rule_hits": [{"rule_name": "impossible_travel"}],
                "ml_reason_codes": ["rare_ip"],
                "ml_features_used": {"ip_entropy": 0.83},
                "risk_level": "critical",
                "decision": "block",
            },
            "logs": [
                {
                    "stage": "rule_evaluation",
                    "stage_detail": "geo",
                    "rule_name": "impossible_travel",
                    "triggered": True,
                    "score_contribution": 0.6,
                    "decision": "block",
                    "reason": "distance too large",
                    "details": {"distance_km": 4210},
                },
                {
                    "stage": "ml_call",
                    "stage_detail": "ml_inference",
                    "rule_name": None,
                    "triggered": None,
                    "score_contribution": 0.3123,
                    "decision": None,
                    "reason": None,
                    "details": {"ml_status": "success"},
                },
            ],
            "timeline": [
                {
                    "event_type": "created",
                    "actor_type": "system",
                    "old_value": None,
                    "new_value": "open",
                    "comment": "Alert created automatically by the Detection Engine.",
                },
                {
                    "event_type": "note_added",
                    "actor_type": "user",
                    "old_value": None,
                    "new_value": None,
                    "comment": f"{FIXTURE_MARKER}: seeded for the Stage 4 suite.",
                },
            ],
        },
        {
            # The rule-only fallback: the ML engine produced NO score.
            "key": "ruleless",
            "status": "open",
            "risk_level": "medium",
            "detection_reason": (
                f"{FIXTURE_MARKER}: ml unavailable, rule-only combined=0.4000"
            ),
            "detection_scores": {
                "rule_score": 0.4,
                "ml_score": None,
                "combined_score": 0.4,
                "ml_status": "unavailable",
                "ml_model_version": None,
                "rule_hits": [{"rule_name": "known_bad_ip"}],
                "ml_reason_codes": ["ml_unavailable"],
            },
            "attempt": {
                "outcome": "failure",
                "username_attempted": FIXTURE_USERNAME,
                "ip_address": "198.51.100.22",
                "user_agent": "curl/8.5.0",
                "mfa_used": False,
                "risk_level": "medium",
                "detection_decision": "challenge",
            },
            "assessment": {
                "rule_score": 0.4,
                # NULL — the fallback. The frontend must not invent a score.
                "ml_score": None,
                "combined_score": 0.4,
                "ml_status": "unavailable",
                "ml_model_version": None,
                "rule_hits": [{"rule_name": "known_bad_ip"}],
                "ml_reason_codes": ["ml_unavailable"],
                "ml_features_used": None,
                "risk_level": "medium",
                "decision": "challenge",
            },
            "logs": [
                {
                    "stage": "rule_evaluation",
                    "stage_detail": "ip_reputation",
                    "rule_name": "known_bad_ip",
                    "triggered": True,
                    "score_contribution": 0.4,
                    "decision": "challenge",
                    "reason": "ip on the blocklist",
                    "details": None,
                },
                {
                    "stage": "ml_call",
                    "stage_detail": "ml_unreachable",
                    "rule_name": None,
                    "triggered": False,
                    # NULL — no contribution, which is not a contribution of 0.
                    "score_contribution": None,
                    "decision": None,
                    "reason": "ml_service_unreachable",
                    "details": {"ml_status": "unavailable"},
                },
            ],
            "timeline": [
                {
                    "event_type": "created",
                    "actor_type": "system",
                    "old_value": None,
                    "new_value": "open",
                    "comment": "Alert created automatically by the Detection Engine.",
                },
            ],
        },
        {
            "key": "low",
            "status": "acknowledged",
            "risk_level": "low",
            "detection_reason": f"{FIXTURE_MARKER}: low risk, new device",
            "detection_scores": {
                "rule_score": 0.1,
                "ml_score": 0.05,
                "combined_score": 0.15,
                "ml_status": "success",
                "ml_model_version": "m12-fixture-model",
                "rule_hits": [],
                "ml_reason_codes": [],
            },
            "attempt": {
                "outcome": "success",
                "username_attempted": FIXTURE_USERNAME,
                "ip_address": "203.0.113.99",
                "user_agent": "Mozilla/5.0 (Macintosh) Safari/17.0",
                "mfa_used": True,
                "risk_level": "low",
                "detection_decision": "allow",
            },
            "assessment": {
                "rule_score": 0.1,
                "ml_score": 0.05,
                "combined_score": 0.15,
                "ml_status": "success",
                "ml_model_version": "m12-fixture-model",
                "rule_hits": [],
                "ml_reason_codes": [],
                "ml_features_used": {"ip_entropy": 0.1},
                "risk_level": "low",
                "decision": "allow",
            },
            "logs": [
                {
                    "stage": "rule_evaluation",
                    "stage_detail": "device",
                    "rule_name": "new_device",
                    "triggered": False,
                    "score_contribution": 0.1,
                    "decision": "allow",
                    "reason": None,
                    "details": None,
                },
            ],
            "timeline": [
                {
                    "event_type": "created",
                    "actor_type": "system",
                    "old_value": None,
                    "new_value": "open",
                    "comment": "Alert created automatically by the Detection Engine.",
                },
                {
                    "event_type": "acknowledged",
                    "actor_type": "user",
                    "old_value": "open",
                    "new_value": "acknowledged",
                    "comment": f"{FIXTURE_MARKER}: acknowledged by the seeded analyst.",
                },
            ],
        },
    ]


def seed(session, marker: str) -> int:
    """Create (or refresh) the fixture rows. Returns the alert count."""
    from sqlalchemy import text

    from app.models import (
        Alert,
        AlertTimeline,
        DetectionLog,
        LoginAttempt,
        RiskAssessment,
    )

    # Remove the previous fixtures first: the seed is idempotent.
    cleanup(session, marker)

    created = 0
    for fixture in _fixture_alerts():
        attempt_spec = fixture["attempt"]
        assessment_spec = fixture["assessment"]

        attempt = LoginAttempt(
            event_id=session.execute(
                text("SELECT gen_random_uuid()")
            ).scalar(),
            user_id=None,
            username_attempted=attempt_spec["username_attempted"],
            outcome=attempt_spec["outcome"],
            mfa_used=attempt_spec["mfa_used"],
            ip_address=attempt_spec["ip_address"],
            user_agent=attempt_spec["user_agent"],
            device_fingerprint=None,
            status="processed",
            risk_level=attempt_spec["risk_level"],
            detection_decision=attempt_spec["detection_decision"],
        )
        session.add(attempt)
        session.flush()

        assessment = RiskAssessment(
            login_attempt_id=attempt.id,
            policy_id=None,
            rule_score=assessment_spec["rule_score"],
            ml_score=assessment_spec["ml_score"],
            combined_score=assessment_spec["combined_score"],
            ml_status=assessment_spec["ml_status"],
            ml_model_version=assessment_spec["ml_model_version"],
            rule_hits=assessment_spec["rule_hits"],
            ml_reason_codes=assessment_spec["ml_reason_codes"],
            ml_features_used=assessment_spec["ml_features_used"],
            risk_level=assessment_spec["risk_level"],
            decision=assessment_spec["decision"],
        )
        session.add(assessment)

        alert = Alert(
            login_attempt_id=attempt.id,
            policy_id=None,
            status=fixture["status"],
            risk_level=fixture["risk_level"],
            detection_reason=fixture["detection_reason"],
            detection_scores=fixture["detection_scores"],
            assigned_to_id=None,
            resolved_by_id=None,
            resolved_at=None,
            resolution=None,
            notes=None,
        )
        session.add(alert)
        session.flush()

        # The login attempt points back at its primary alert.
        attempt.primary_alert_id = alert.id

        for log_spec in fixture["logs"]:
            session.add(
                DetectionLog(
                    login_attempt_id=attempt.id,
                    request_id=None,
                    stage=log_spec["stage"],
                    stage_detail=log_spec["stage_detail"],
                    rule_name=log_spec["rule_name"],
                    triggered=log_spec["triggered"],
                    score_contribution=log_spec["score_contribution"],
                    decision=log_spec["decision"],
                    reason=log_spec["reason"],
                    details=log_spec["details"],
                )
            )

        for event_spec in fixture["timeline"]:
            session.add(
                AlertTimeline(
                    alert_id=alert.id,
                    event_type=event_spec["event_type"],
                    actor_id=None,
                    actor_type=event_spec["actor_type"],
                    old_value=event_spec["old_value"],
                    new_value=event_spec["new_value"],
                    comment=event_spec["comment"],
                    ip_address=None,
                )
            )

        print(
            f"[seed-alerts] {fixture['key']}: status={fixture['status']} "
            f"risk={fixture['risk_level']} alert={alert.id}"
        )
        created += 1

    session.commit()
    return created


def cleanup(session, marker: str) -> int:
    """Remove the fixture rows. Returns the number of removed alerts."""
    from app.models import Alert, AlertTimeline, DetectionLog, LoginAttempt

    alerts = (
        session.query(Alert)
        .filter(Alert.detection_reason.like(f"%{marker}%"))
        .all()
    )
    if not alerts:
        return 0

    alert_ids = [alert.id for alert in alerts]
    attempt_ids = [alert.login_attempt_id for alert in alerts]

    # The timeline and the logs cascade with the alert / the attempt.
    session.query(AlertTimeline).filter(
        AlertTimeline.alert_id.in_(alert_ids)
    ).delete(synchronize_session=False)
    session.query(DetectionLog).filter(
        DetectionLog.login_attempt_id.in_(attempt_ids)
    ).delete(synchronize_session=False)
    session.query(LoginAttempt).filter(
        LoginAttempt.id.in_(attempt_ids)
    ).delete(synchronize_session=False)
    session.query(Alert).filter(Alert.id.in_(alert_ids)).delete(
        synchronize_session=False
    )
    session.commit()
    return len(alert_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove the fixture rows instead of creating them",
    )
    args = parser.parse_args()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import resolve_database_url

    database_url = (
        os.environ.get("DETECTION_DATABASE_URL")
        or resolve_database_url("detection")
    )

    # The guard runs BEFORE the engine is created: nothing connects, and
    # nothing can be written or deleted, until the database is proven to
    # be a disposable one.
    database_name = assert_disposable_database(database_url)
    print(f"[seed-alerts] the target database is '{database_name}'")

    engine = create_engine(database_url, pool_pre_ping=True)
    session = sessionmaker(bind=engine)()

    try:
        if args.cleanup:
            removed = cleanup(session, FIXTURE_MARKER)
            print(f"[seed-alerts] removed {removed} fixture alert(s)")
        else:
            created = seed(session, FIXTURE_MARKER)
            print(f"[seed-alerts] {created} fixture alert(s) are ready")
    except Exception as exc:  # noqa: BLE001 - the CI must fail loudly
        session.rollback()
        print(f"[seed-alerts] ERROR: the fixtures could not be seeded: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    return 0


if __name__ == "__main__":
    sys.exit(main())
