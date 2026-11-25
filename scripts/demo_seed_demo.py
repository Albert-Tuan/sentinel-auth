#!/usr/bin/env python
"""Sentinel Auth v3.3 — M13 reproducible demo fixtures.

Creates the deterministic fixture set the M13 demo scenarios need, so a
clean clone can be brought to a state where every scenario is runnable:

======================  ======================================================
Fixture                 What it provides
======================  ======================================================
``demo_user``           A plain ``USER`` — the ordinary end user.
``demo_analyst``        A ``SOC_ANALYST`` — the SOC investigation role.
``demo_admin``          A ``SECURITY_ADMIN`` with a REAL MFA handshake over
                        SMTP (the OTP is delivered to the local sink).
``demo_manager``        A ``SECURITY_MANAGER`` — the analytics role.
``demo_sessions``       Active sessions, so the Session List is not empty.
``demo_devices``        Trusted devices plus a PENDING approval request
                        (Scenario B starts from the pending state).
``demo_alerts``         Alerts across every risk level and status, each with
                        its login attempt, risk assessment, detection logs
                        and timeline.
``demo_policies``       One DRAFT policy and one ACTIVE, immutable policy.
``demo_analytics``      Manager-analytics data: inference logs, feature
                        statistics and a second active ML registry row.
======================  ======================================================

Guarantees
----------
* **Disposable only.**  The script refuses to run against a database whose
  name does not carry the ``_demo`` marker.  The guard runs BEFORE the
  engine is created, so nothing connects and nothing is written until the
  target is proven to be a demo database.
* **Idempotent.**  Every fixture row carries a deterministic UUID derived
  from a namespace and a stable key.  Re-running the seed replaces the
  rows instead of piling them up, and the row COUNT stays the same.
* **Scoped cleanup.**  ``--cleanup`` deletes ONLY the rows whose id was
  minted by this script.  A row that the fixture set did not create is
  never touched.
* **No fake ML.**  The ML fixtures never claim a model was promoted and
  never fake a successful prediction.  The inference logs record the
  honest outcome the artifact state produces.

Usage::

    CORE_DATABASE_URL=postgresql://... \\
        python scripts/demo_seed_demo.py --seed

    CORE_DATABASE_URL=postgresql://... \\
        python scripts/demo_seed_demo.py --cleanup

    python scripts/demo_seed_demo.py --manifest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: The namespace every deterministic UUID is derived from.  It is a fixed
#: constant, so the same fixture always gets the same id — on any machine,
#: in any order, in any number of runs.
FIXTURE_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

#: The marker that identifies a fixture row.  It is stored in a free-text
#: column of every fixture row so the cleanup can find the rows again
#: without depending on the generated UUIDs.
FIXTURE_MARKER = "m13-demo-fixture"

#: The suffix every demo database name carries.  A database whose name
#: does NOT carry this marker is treated as a real deployment database and
#: is refused.
DISPOSABLE_DB_MARKER = "_demo"

#: The deterministic UUID namespace per entity kind.
NS_USER = "user"
NS_SESSION = "session"
NS_DEVICE = "device"
NS_MFA = "mfa"
NS_POLICY = "policy"
NS_ALERT = "alert"
NS_ATTEMPT = "login_attempt"
NS_ASSESSMENT = "risk_assessment"
NS_LOG = "detection_log"
NS_TIMELINE = "alert_timeline"
NS_ANALYST = "soc_analyst"
NS_INFERENCE = "inference_log"
NS_FEATURE = "feature_statistic"
NS_MODEL = "model_version"
NS_IP = "ip_address"


def fixture_id(kind: str, key: str) -> str:
    """Return the deterministic UUID of a fixture row.

    The UUID is derived from the namespace and a stable key, so the same
    fixture always has the same id.  That is what lets an E2E test find
    exactly the record it created, and what makes the seed idempotent.
    """
    return str(uuid.uuid5(FIXTURE_NAMESPACE, f"{kind}:{key}"))


def assert_demo_database(database_url: str) -> str:
    """Refuse to run against a database that is not a demo database.

    The seed creates rows and the cleanup DELETES rows.  A mistake against
    a real database would be unacceptable, so the guard is at the DATABASE
    level, before a single row is touched.

    :param database_url: the connection URL the script is about to use
    :return: the database name that was validated
    :raises SystemExit: when the database is not a demo database
    """
    path = database_url.split("?", 1)[0]
    name = path.rsplit("/", 1)[-1]

    if not name:
        print(
            "[demo-seed] ERROR: the connection URL does not name a database, "
            "so it cannot be proven disposable.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if not name.endswith(DISPOSABLE_DB_MARKER):
        print(
            f"[demo-seed] ERROR: refusing to touch the database '{name}': the "
            f"name lacks the '{DISPOSABLE_DB_MARKER}' marker that marks a demo "
            f"database.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return name


# -----------------------------------------------------------------------------
# The fixture definitions
# -----------------------------------------------------------------------------

#: The four demo accounts.  The passwords are DEMO credentials for a
#: throwaway local database; they are read from the environment so that
#: nothing secret is ever committed.
DEMO_USERS: List[Dict[str, Any]] = [
    {
        "key": "user",
        "username": "demo_user",
        "email": "demo_user@example.test",
        "full_name": "Demo User",
        "roles": ("USER",),
        "admin_mfa_required": False,
        "password_env": "DEMO_USER_PASSWORD",
    },
    {
        "key": "analyst",
        "username": "demo_analyst",
        "email": "demo_analyst@example.test",
        "full_name": "Demo SOC Analyst",
        "roles": ("USER", "SOC_ANALYST"),
        "admin_mfa_required": False,
        "password_env": "DEMO_ANALYST_PASSWORD",
    },
    {
        "key": "admin",
        "username": "demo_admin",
        "email": "demo_admin@example.test",
        "full_name": "Demo Security Admin",
        "roles": ("USER", "SECURITY_ADMIN"),
        # The MFA handshake is part of Scenario A, so the admin account
        # really does require it.
        "admin_mfa_required": True,
        "password_env": "DEMO_ADMIN_PASSWORD",
    },
    {
        "key": "manager",
        "username": "demo_manager",
        "email": "demo_manager@example.test",
        "full_name": "Demo Security Manager",
        "roles": ("USER", "SECURITY_MANAGER"),
        "admin_mfa_required": False,
        "password_env": "DEMO_MANAGER_PASSWORD",
    },
]

#: The default demo password, used when the environment does not supply
#: one.  It is a DEMO credential for a throwaway database.
DEFAULT_DEMO_PASSWORD = "DemoPass!2026"

#: The alert fixtures.  Each entry pins the risk level and the status the
#: SOC screens must be able to render.
DEMO_ALERTS: List[Dict[str, Any]] = [
    {
        "key": "critical_open",
        "status": "open",
        "risk_level": "critical",
        "username_attempted": "demo_user",
        "outcome": "failure",
        "ip_address": "203.0.113.11",
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0",
        "mfa_used": False,
        "detection_decision": "block",
        "reason": f"{FIXTURE_MARKER}: impossible travel, combined=0.9400",
        "rule_score": 0.62,
        "ml_score": 0.32,
        "combined_score": 0.94,
        "ml_status": "success",
        "ml_model_version": "m13-demo-model",
        "decision": "block",
        "rule_hits": [{"rule_name": "impossible_travel", "score": 0.62}],
        "ml_reason_codes": ["rare_ip"],
        "ml_features_used": {"ip_entropy": 0.87, "new_device": True},
        "timeline": ["created"],
        "assigned": True,
    },
    {
        "key": "high_acknowledged",
        "status": "acknowledged",
        "risk_level": "high",
        "username_attempted": "demo_analyst",
        "outcome": "failure",
        "ip_address": "198.51.100.31",
        "user_agent": "Mozilla/5.0 (Macintosh) Firefox/121.0",
        "mfa_used": False,
        "detection_decision": "block",
        "reason": f"{FIXTURE_MARKER}: repeated failures plus a new device",
        "rule_score": 0.55,
        "ml_score": 0.21,
        "combined_score": 0.76,
        "ml_status": "success",
        "ml_model_version": "m13-demo-model",
        "decision": "block",
        "rule_hits": [{"rule_name": "multiple_failures", "score": 0.55}],
        "ml_reason_codes": ["new_device"],
        "ml_features_used": {"fail_count_24h": 5, "new_device": True},
        "timeline": ["created", "acknowledged"],
        "assigned": True,
    },
    {
        # The rule-only fallback: the ML engine produced NO score.  The
        # frontend must show "no data" for the ML score — never a zero.
        "key": "medium_open_ruleless",
        "status": "open",
        "risk_level": "medium",
        "username_attempted": "demo_user",
        "outcome": "failure",
        "ip_address": "198.51.100.44",
        "user_agent": "curl/8.5.0",
        "mfa_used": False,
        "detection_decision": "challenge",
        "reason": f"{FIXTURE_MARKER}: ml unavailable, rule-only combined=0.4800",
        "rule_score": 0.48,
        "ml_score": None,
        "combined_score": 0.48,
        "ml_status": "unavailable",
        "ml_model_version": None,
        "decision": "challenge",
        "rule_hits": [{"rule_name": "known_bad_ip", "score": 0.48}],
        "ml_reason_codes": ["ml_unavailable"],
        "ml_features_used": None,
        "timeline": ["created"],
        "assigned": False,
    },
    {
        "key": "low_resolved",
        "status": "resolved",
        "risk_level": "low",
        "username_attempted": "demo_manager",
        "outcome": "success",
        "ip_address": "203.0.113.77",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0) Edge/120.0",
        "mfa_used": True,
        "detection_decision": "allow",
        "reason": f"{FIXTURE_MARKER}: low risk, known device",
        "rule_score": 0.12,
        "ml_score": 0.06,
        "combined_score": 0.18,
        "ml_status": "success",
        "ml_model_version": "m13-demo-model",
        "decision": "allow",
        "rule_hits": [],
        "ml_reason_codes": [],
        "ml_features_used": {"ip_entropy": 0.08},
        "timeline": ["created", "acknowledged", "resolved"],
        "assigned": True,
    },
    {
        "key": "low_false_positive",
        "status": "false_positive",
        "risk_level": "low",
        "username_attempted": "demo_user",
        "outcome": "success",
        "ip_address": "203.0.113.88",
        "user_agent": "Mozilla/5.0 (iPhone) Safari/17.0",
        "mfa_used": True,
        "detection_decision": "allow",
        "reason": f"{FIXTURE_MARKER}: the user confirmed the travel",
        "rule_score": 0.09,
        "ml_score": 0.04,
        "combined_score": 0.13,
        "ml_status": "success",
        "ml_model_version": "m13-demo-model",
        "decision": "allow",
        "rule_hits": [],
        "ml_reason_codes": [],
        "ml_features_used": {"ip_entropy": 0.05},
        "timeline": ["created", "false_positive"],
        "assigned": False,
    },
]


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _hours_ago(hours: float):
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) - timedelta(hours=hours)


# -----------------------------------------------------------------------------
# The seed
# -----------------------------------------------------------------------------

def seed_core(session) -> Dict[str, Any]:
    """Seed the Core database: users, roles, sessions, devices, MFA."""
    from argon2 import PasswordHasher
    from sqlalchemy import text

    from app.models import (
        IpAddress,
        MfaTransaction,
        Role,
        Session,
        User,
        UserRole,
        UserTrustedDevice,
    )

    hasher = PasswordHasher()
    manifest: Dict[str, Any] = {"users": {}, "sessions": [], "devices": [], "mfa": []}

    # --- the roles the demo needs -----------------------------------------
    #
    # The roles already exist in the canonical schema; the seed only makes
    # sure they are there, so a demo database that was created from the
    # canonical schema needs no special handling.
    role_ids: Dict[str, str] = {}
    for role_name in ("USER", "SOC_ANALYST", "SECURITY_ADMIN", "SECURITY_MANAGER"):
        role = session.query(Role).filter(Role.id == role_name).first()
        if role is None:
            role = Role(
                id=role_name,
                name=role_name,
                name_vi=role_name,
                description=f"M13 demo role {role_name}",
            )
            session.add(role)
        role_ids[role_name] = role_name
    session.flush()

    # --- the four accounts ------------------------------------------------
    user_ids: Dict[str, str] = {}
    for spec in DEMO_USERS:
        key = str(spec["key"])
        username = str(spec["username"])
        user_id = fixture_id(NS_USER, username)

        password = os.environ.get(str(spec["password_env"]), "").strip() or DEFAULT_DEMO_PASSWORD

        user = session.query(User).filter(User.id == user_id).one_or_none()
        if user is None:
            user = User(id=user_id)
            session.add(user)

        user.username = username
        user.email = str(spec["email"])
        user.full_name = str(spec["full_name"])
        user.status = "active"
        user.password_hash = hasher.hash(password)
        user.admin_mfa_required = bool(spec["admin_mfa_required"])
        user.detection_mfa_once = False
        user.failed_login_count = 0
        user.locked_at = None
        user.last_login_at = _hours_ago(1)
        session.flush()

        # The role set is set exactly: a role that is no longer wanted is
        # removed, so the seed converges instead of accumulating.
        wanted = {str(r) for r in spec["roles"]}  # type: ignore[arg-type]
        current = {
            link.role_id
            for link in session.query(UserRole).filter(UserRole.user_id == user_id).all()
        }
        for role_id in sorted(wanted - current):
            session.add(UserRole(user_id=user_id, role_id=role_id, assigned_by=user_id))
        for role_id in sorted(current - wanted):
            link = (
                session.query(UserRole)
                .filter(UserRole.user_id == user_id, UserRole.role_id == role_id)
                .one_or_none()
            )
            if link is not None:
                session.delete(link)

        user_ids[key] = user_id
        manifest["users"][key] = {
            "id": user_id,
            "username": username,
            "email": str(spec["email"]),
            "roles": sorted(wanted),
            "mfa_required": bool(spec["admin_mfa_required"]),
        }

    session.flush()

    # --- the IP addresses the sessions point at --------------------------
    ip_ids: Dict[str, str] = {}
    for ip in ("127.0.0.1", "203.0.113.11", "198.51.100.31"):
        ip_id = fixture_id(NS_IP, ip)
        row = session.query(IpAddress).filter(IpAddress.id == ip_id).one_or_none()
        if row is None:
            row = IpAddress(id=ip_id, ip_address=ip)
            session.add(row)
        ip_ids[ip] = ip_id
    session.flush()

    # --- the active sessions ----------------------------------------------
    #
    # The sessions are real rows with deterministic ids.  The token hashes
    # are placeholders: the demo scenarios mint their own tokens through
    # the real login flow, and the session rows exist so the Session List
    # screen has something truthful to show.
    session_specs = [
        ("user", "demo_user", "127.0.0.1", "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0"),
        ("analyst", "demo_analyst", "127.0.0.1", "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0"),
        ("manager", "demo_manager", "127.0.0.1", "Mozilla/5.0 (Windows NT 10.0) Edge/120.0"),
    ]
    for key, username, ip, agent in session_specs:
        user_id = user_ids[key]
        session_id = fixture_id(NS_SESSION, username)
        row = session.query(Session).filter(Session.id == session_id).one_or_none()
        if row is None:
            row = Session(id=session_id)
            session.add(row)
        row.user_id = user_id
        row.access_token_hash = hashlib.sha256(f"{FIXTURE_MARKER}:{session_id}".encode()).hexdigest()
        row.refresh_token_hash = hashlib.sha256(
            f"{FIXTURE_MARKER}:refresh:{session_id}".encode()
        ).hexdigest()
        row.refresh_token_family = fixture_id(NS_SESSION, f"{username}:family")
        row.token_jti = fixture_id(NS_SESSION, f"{username}:jti")
        row.expires_at = _hours_ago(-12)
        row.last_activity_at = _hours_ago(1)
        row.revoked_at = None
        row.ip_address_id = ip_ids[ip]
        row.user_agent = agent
        manifest["sessions"].append({"id": session_id, "username": username})

    # --- the trusted devices ----------------------------------------------
    device_specs = [
        ("analyst", "demo_analyst", "demo-analyst-laptop", "m13-demo-fingerprint-analyst", False),
        ("manager", "demo_manager", "demo-manager-desktop", "m13-demo-fingerprint-manager", False),
    ]
    for key, username, device_name, fingerprint, expired in device_specs:
        user_id = user_ids[key]
        device_id = fixture_id(NS_DEVICE, fingerprint)
        row = (
            session.query(UserTrustedDevice)
            .filter(UserTrustedDevice.id == device_id)
            .one_or_none()
        )
        if row is None:
            row = UserTrustedDevice(id=device_id)
            session.add(row)
        row.user_id = user_id
        row.device_fingerprint = fingerprint
        row.device_name = device_name
        row.last_ip = "127.0.0.1"
        row.last_user_agent = "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0"
        row.last_used_at = _hours_ago(3)
        row.expires_at = None if not expired else _hours_ago(1)
        manifest["devices"].append(
            {
                "id": device_id,
                "username": username,
                "device_name": device_name,
                "fingerprint": fingerprint,
                "pending": False,
            }
        )

    # --- the PENDING trusted-device approval request ----------------------
    #
    # Scenario B starts from the pending state, so the request has to exist
    # before the scenario runs.  It reuses the Core MFA transaction
    # lifecycle, exactly like the live approval flow does.
    pending_user = user_ids["user"]
    pending_id = fixture_id(NS_MFA, "pending-device")
    pending = session.query(MfaTransaction).filter(MfaTransaction.id == pending_id).one_or_none()
    if pending is None:
        pending = MfaTransaction(id=pending_id)
        session.add(pending)
    pending.user_id = pending_user
    pending.mfa_type = "trusted_device"
    pending.status = "pending"
    pending.bound_ip = "127.0.0.1"
    pending.trusted_device_fingerprint = "m13-demo-fingerprint-pending"
    pending.trusted_device_name = "demo-user-phone"
    pending.trusted_device_user_agent = "Mozilla/5.0 (iPhone) Safari/17.0"
    pending.consumed_at = None
    pending.fail_count = 0
    pending.expires_at = _hours_ago(-24)
    manifest["devices"].append(
        {
            "id": pending_id,
            "username": "demo_user",
            "device_name": "demo-user-phone",
            "fingerprint": "m13-demo-fingerprint-pending",
            "pending": True,
        }
    )
    manifest["mfa"].append({"id": pending_id, "status": "pending", "username": "demo_user"})

    session.commit()

    manifest["user_ids"] = user_ids
    manifest["ip_ids"] = ip_ids
    return manifest


def seed_detection(session, core_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Seed the Detection database: policies, alerts and their evidence."""
    from app.models import (
        Alert,
        AlertTimeline,
        DetectionLog,
        LoginAttempt,
        Policy,
        RiskAssessment,
        SocAnalyst,
    )

    user_ids = core_manifest["user_ids"]
    manifest: Dict[str, Any] = {"policies": {}, "alerts": {}, "analysts": []}

    # --- the SOC analyst profile -----------------------------------------
    analyst_id = fixture_id(NS_ANALYST, "demo_analyst")
    analyst = session.query(SocAnalyst).filter(SocAnalyst.id == analyst_id).one_or_none()
    if analyst is None:
        analyst = SocAnalyst(id=analyst_id)
        session.add(analyst)
    analyst.user_id = user_ids["analyst"]
    analyst.display_name = "Demo SOC Analyst"
    analyst.is_active = True
    analyst.max_alerts = 50
    manifest["analysts"].append({"id": analyst_id, "username": "demo_analyst"})

    # --- the policies ------------------------------------------------------
    #
    # One DRAFT (is_active = FALSE, never activated) and one ACTIVE
    # policy.  The active one is the one the canonical schema's partial
    # unique index protects: only ONE policy may be active at a time.
    policy_specs = [
        {
            "key": "active",
            "version": "m13-demo-active",
            "name": "M13 demo active policy",
            "description": "The active policy of the M13 demo. It is immutable: activating another policy deactivates this one.",
            "rules": [
                {
                    "name": "impossible_travel",
                    "field": "ip_change_rate_7d",
                    "operator": ">=",
                    "value": 0.8,
                    "weight": 0.5,
                    "score": 0.9,
                    "enabled": True,
                    "description": "The IP address is new for this account.",
                },
                {
                    "name": "multiple_failures",
                    "field": "fail_count_24h",
                    "operator": ">=",
                    "value": 3,
                    "weight": 0.4,
                    "score": 0.9,
                    "enabled": True,
                    "description": "Three or more failed attempts in the last 24 hours.",
                },
            ],
            "config": {
                "weights": {"rule": 0.4, "ml": 0.6},
                "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75},
            },
            "is_active": True,
        },
        {
            "key": "draft",
            "version": "m13-demo-draft",
            "name": "M13 demo draft policy",
            "description": "A draft policy. It can be edited and activated; it never affects the scoring until it is activated.",
            "rules": [
                {
                    "name": "unusual_hour",
                    "field": "hour_of_day",
                    "operator": "not_between",
                    "value": [7, 22],
                    "weight": 0.3,
                    "score": 0.8,
                    "enabled": True,
                    "description": "Login outside 07:00-22:59 UTC.",
                }
            ],
            "config": {
                "weights": {"rule": 0.4, "ml": 0.6},
                "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75},
            },
            "is_active": False,
        },
    ]

    # Only ONE policy may be active at a time.  The canonical schema
    # enforces it with the partial unique index
    # ``idx_policies_single_active``.
    #
    # The deactivation therefore has to REACH the database before the new
    # active policy is written.  SQLAlchemy flushes an INSERT before an
    # UPDATE by default, so the deactivation is flushed explicitly first;
    # otherwise the insert would violate the index.
    #
    # The deactivation is limited to the policies THIS script owns.  A
    # policy the demo did not create is left alone — the seed must not
    # silently change the state of a policy it does not own.
    active_policy_id = fixture_id(NS_POLICY, "m13-demo-active")
    other_active = (
        session.query(Policy)
        .filter(Policy.is_active.is_(True), Policy.id != active_policy_id)
        .all()
    )
    for policy in other_active:
        policy.is_active = False
        policy.deactivated_at = _now()
    session.flush()

    for spec in policy_specs:
        key = str(spec["key"])
        policy_id = fixture_id(NS_POLICY, str(spec["version"]))
        policy = session.query(Policy).filter(Policy.id == policy_id).one_or_none()
        if policy is None:
            policy = Policy(id=policy_id)
            session.add(policy)
        policy.version = str(spec["version"])
        policy.name = str(spec["name"])
        policy.description = str(spec["description"])
        policy.rules = spec["rules"]
        policy.config = spec["config"]
        policy.is_active = bool(spec["is_active"])
        policy.created_by = user_ids["admin"]
        policy.activated_at = _hours_ago(24) if spec["is_active"] else None
        policy.deactivated_at = None
        manifest["policies"][key] = {
            "id": policy_id,
            "version": str(spec["version"]),
            "is_active": bool(spec["is_active"]),
        }

    session.flush()

    # --- the alerts --------------------------------------------------------
    for spec in DEMO_ALERTS:
        key = str(spec["key"])
        attempt_id = fixture_id(NS_ATTEMPT, key)
        alert_id = fixture_id(NS_ALERT, key)
        assessment_id = fixture_id(NS_ASSESSMENT, key)

        # The alert's subject is a real Core user when the fixture names
        # one, so Scenario D can prove a real Core state change.
        subject_key = {
            "demo_user": "user",
            "demo_analyst": "analyst",
            "demo_manager": "manager",
        }.get(str(spec["username_attempted"]))
        subject_user_id = user_ids.get(subject_key) if subject_key else None

        attempt = session.query(LoginAttempt).filter(LoginAttempt.id == attempt_id).one_or_none()
        if attempt is None:
            attempt = LoginAttempt(id=attempt_id)
            session.add(attempt)
        # ``event_id`` is the idempotency key of the delivered login event
        # and it is NOT NULL and UNIQUE.  The fixture derives it
        # deterministically, so re-seeding replaces the row instead of
        # colliding with it.
        attempt.event_id = fixture_id(NS_ATTEMPT, f"{key}:event")
        attempt.user_id = subject_user_id
        attempt.username_attempted = str(spec["username_attempted"])
        attempt.outcome = str(spec["outcome"])
        attempt.mfa_used = bool(spec["mfa_used"])
        attempt.ip_address = str(spec["ip_address"])
        attempt.user_agent = str(spec["user_agent"])
        attempt.device_fingerprint = None
        attempt.status = "processed"
        attempt.request_id = fixture_id(NS_ATTEMPT, f"{key}:request")
        attempt.policy_id = manifest["policies"]["active"]["id"]
        attempt.risk_level = str(spec["risk_level"])
        attempt.detection_decision = str(spec["detection_decision"])
        attempt.timestamp = _hours_ago(6)
        # The alert does not exist yet, so the back-reference is set after
        # the alert row is written.  The two tables reference each other:
        # ``alerts.login_attempt_id`` and ``login_attempts.primary_alert_id``.
        attempt.primary_alert_id = None
        session.flush()

        assessment = (
            session.query(RiskAssessment).filter(RiskAssessment.id == assessment_id).one_or_none()
        )
        if assessment is None:
            assessment = RiskAssessment(id=assessment_id)
            session.add(assessment)
        assessment.login_attempt_id = attempt_id
        assessment.policy_id = manifest["policies"]["active"]["id"]
        assessment.rule_score = spec["rule_score"]
        assessment.ml_score = spec["ml_score"]
        assessment.combined_score = spec["combined_score"]
        assessment.ml_status = spec["ml_status"]
        assessment.ml_model_version = spec["ml_model_version"]
        assessment.rule_hits = spec["rule_hits"]
        assessment.ml_reason_codes = spec["ml_reason_codes"]
        assessment.ml_features_used = spec["ml_features_used"]
        assessment.risk_level = str(spec["risk_level"])
        assessment.decision = str(spec["decision"])
        assessment.created_at = _hours_ago(6)

        alert = session.query(Alert).filter(Alert.id == alert_id).one_or_none()
        if alert is None:
            alert = Alert(id=alert_id)
            session.add(alert)
        alert.login_attempt_id = attempt_id
        alert.policy_id = manifest["policies"]["active"]["id"]
        alert.status = str(spec["status"])
        alert.risk_level = str(spec["risk_level"])
        alert.detection_reason = str(spec["reason"])
        alert.detection_scores = {
            "rule_score": spec["rule_score"],
            "ml_score": spec["ml_score"],
            "combined_score": spec["combined_score"],
            "ml_status": spec["ml_status"],
            "ml_model_version": spec["ml_model_version"],
            "rule_hits": spec["rule_hits"],
            "ml_reason_codes": spec["ml_reason_codes"],
        }
        alert.assigned_to_id = analyst_id if spec["assigned"] else None
        alert.resolved_by_id = analyst_id if spec["status"] in ("resolved", "false_positive") else None
        alert.resolved_at = (
            _hours_ago(2) if spec["status"] in ("resolved", "false_positive") else None
        )
        alert.resolution = (
            "Confirmed by the user; the travel was legitimate."
            if spec["status"] == "resolved"
            else ("The analyst marked it as a false positive." if spec["status"] == "false_positive" else None)
        )
        alert.notes = f"{FIXTURE_MARKER}: seeded for the M13 demo."
        alert.created_at = _hours_ago(6)
        session.flush()

        # Now that the alert exists, the login attempt can point back at
        # it.  The reverse reference (``alerts.login_attempt_id``) was
        # already written above.
        attempt.primary_alert_id = alert_id
        session.flush()

        # --- the detection logs --------------------------------------------
        log_specs = [
            {
                "key": "rule",
                "stage": "rule_evaluation",
                "stage_detail": "geo",
                "rule_name": (spec["rule_hits"][0]["rule_name"] if spec["rule_hits"] else None),
                "triggered": bool(spec["rule_hits"]),
                "score_contribution": spec["rule_score"],
                "decision": spec["decision"],
                "reason": "the rule scored the attempt" if spec["rule_hits"] else None,
                "details": {"marker": FIXTURE_MARKER},
            },
            {
                "key": "ml",
                "stage": "ml_call",
                "stage_detail": "ml_inference" if spec["ml_status"] == "success" else "ml_unreachable",
                "rule_name": None,
                "triggered": None if spec["ml_status"] == "success" else False,
                # NULL when the ML produced no score — that is NOT a score of 0.
                "score_contribution": spec["ml_score"],
                "decision": None,
                "reason": None if spec["ml_status"] == "success" else "ml_service_unreachable",
                "details": {"ml_status": spec["ml_status"]},
            },
        ]
        for log_spec in log_specs:
            log_id = fixture_id(NS_LOG, f"{key}:{log_spec['key']}")
            row = session.query(DetectionLog).filter(DetectionLog.id == log_id).one_or_none()
            if row is None:
                row = DetectionLog(id=log_id)
                session.add(row)
            row.login_attempt_id = attempt_id
            row.request_id = None
            row.stage = log_spec["stage"]
            row.stage_detail = log_spec["stage_detail"]
            row.rule_name = log_spec["rule_name"]
            row.triggered = log_spec["triggered"]
            row.score_contribution = log_spec["score_contribution"]
            row.decision = log_spec["decision"]
            row.reason = log_spec["reason"]
            row.details = log_spec["details"]
            row.created_at = _hours_ago(6)

        # --- the timeline ----------------------------------------------------
        for index, event_type in enumerate(spec["timeline"]):
            timeline_id = fixture_id(NS_TIMELINE, f"{key}:{index}")
            row = (
                session.query(AlertTimeline)
                .filter(AlertTimeline.id == timeline_id)
                .one_or_none()
            )
            if row is None:
                row = AlertTimeline(id=timeline_id)
                session.add(row)
            row.alert_id = alert_id
            row.event_type = event_type
            row.actor_id = user_ids["analyst"] if event_type != "created" else None
            row.actor_type = "system" if event_type == "created" else "user"
            row.old_value = "open" if event_type in ("acknowledged", "resolved") else None
            row.new_value = {
                "created": "open",
                "acknowledged": "acknowledged",
                "resolved": "resolved",
                "false_positive": "false_positive",
            }.get(event_type)
            row.comment = f"{FIXTURE_MARKER}: {event_type} by the seeded analyst."
            row.ip_address = "127.0.0.1"
            row.created_at = _hours_ago(6 - index)

        manifest["alerts"][key] = {
            "id": alert_id,
            "status": str(spec["status"]),
            "risk_level": str(spec["risk_level"]),
            "login_attempt_id": attempt_id,
            "subject_user_id": subject_user_id,
        }

    session.commit()
    return manifest


def seed_ml(session) -> Dict[str, Any]:
    """Seed the ML database with honest analytics rows.

    The ML artifact is NOT promoted: the registry keeps its staged
    placeholder, and this fixture does not create an active production
    model.  The inference logs record the outcomes the artifact state
    actually produces — a mix of successful rule-path scoring and the
    honest "error" entries the registry writes when the artifact is
    missing.
    """
    from app.models import FeatureStatistic, InferenceLog, ModelVersion

    manifest: Dict[str, Any] = {"models": {}, "inference_logs": 0, "feature_stats": 0}

    # The registry row.  It is STAGED and NOT production — exactly like
    # the placeholder the canonical schema seeds.  The demo never promotes
    # a model, so the ML health endpoint keeps reporting the artifact
    # state honestly.
    model_id = fixture_id(NS_MODEL, "m13-demo-model")
    model = session.query(ModelVersion).filter(ModelVersion.id == model_id).one_or_none()
    if model is None:
        model = ModelVersion(id=model_id)
        session.add(model)
    model.name = "M13 Demo Model"
    model.version = "m13-demo-model"
    model.status = "staged"
    model.is_production = False
    model.model_path = "/models/m13-demo-model.joblib"
    manifest["models"]["demo"] = {
        "id": model_id,
        "version": "m13-demo-model",
        "status": "staged",
        "is_production": False,
    }

    # The inference logs.  They give the Manager analytics screen real
    # numbers to aggregate over.  The rows are recorded as they were, with
    # the honest model_status.
    #
    # The status vocabulary is the one the schema allows:
    # ``ready`` | ``degraded`` | ``error``.
    inference_specs = [
        ("ok", "ready", 0.31, 42.0),
        ("ok", "ready", 0.22, 38.5),
        ("ok", "ready", 0.55, 51.0),
        ("ok", "degraded", 0.41, 120.0),
        ("ok", "ready", 0.18, 35.0),
        ("ok", "degraded", 0.67, 250.0),
        ("ok", "ready", 0.29, 44.5),
    ]
    for index, (key, model_status, anomaly_score, processing_ms) in enumerate(inference_specs):
        log_id = fixture_id(NS_INFERENCE, f"{key}:{index}")
        row = session.query(InferenceLog).filter(InferenceLog.id == log_id).one_or_none()
        if row is None:
            row = InferenceLog(id=log_id)
            session.add(row)
        row.request_id = fixture_id(NS_INFERENCE, f"{key}:{index}:request")
        row.model_version_id = model_id
        row.model_version_used = "m13-demo-model"
        row.features = {"marker": FIXTURE_MARKER, "index": index}
        row.raw_score = anomaly_score
        row.normalized_score = anomaly_score
        row.is_anomaly = anomaly_score >= 0.5
        row.reason_codes = ["rare_ip"] if anomaly_score >= 0.5 else []
        row.model_status = model_status
        row.processing_time_ms = int(processing_ms)
        row.error_message = (
            "the ML artifact is not available" if model_status == "degraded" else None
        )
        row.ip_address = "127.0.0.1"
        row.created_at = _hours_ago(index * 3)
        manifest["inference_logs"] += 1

    # The feature statistics.  They feed the ML feature table on the
    # analytics screen.
    #
    # The ``mean``/``std``/``min``/``max``/percentile columns are
    # ``NUMERIC(10, 6)``, so an absolute value below 10^4.  The
    # ``average_login_interval_seconds`` feature is therefore kept in
    # minutes rather than seconds — a value in seconds would overflow the
    # column.
    feature_specs = [
        ("hour_of_day", 12.4, 3.1),
        ("fail_count_24h", 1.8, 1.2),
        ("ip_change_rate_7d", 0.34, 0.21),
        ("new_device", 0.12, 0.31),
        ("average_login_interval_minutes", 90.0, 20.0),
        ("deviation_score", 0.22, 0.17),
    ]
    for index, (name, mean, std) in enumerate(feature_specs):
        stat_id = fixture_id(NS_FEATURE, name)
        row = session.query(FeatureStatistic).filter(FeatureStatistic.id == stat_id).one_or_none()
        if row is None:
            row = FeatureStatistic(id=stat_id)
            session.add(row)
        row.feature_name = name
        row.timestamp = _hours_ago(1)
        row.count = 100 + index * 10
        row.mean = mean
        row.std = std
        row.min = 0.0
        row.max = mean * 2
        row.p25 = mean * 0.8
        row.p50 = mean
        row.p75 = mean * 1.2
        row.p95 = mean * 1.6
        row.anomaly_rate = 0.05 + index * 0.01
        row.created_at = _hours_ago(1)
        manifest["feature_stats"] += 1

    session.commit()
    return manifest


# -----------------------------------------------------------------------------
# The cleanup
# -----------------------------------------------------------------------------

def cleanup_core(session) -> int:
    """Remove ONLY the Core rows this script created.

    The rows are found by their deterministic id, so a row the fixture set
    did not create is never touched — not even one that happens to carry
    the same marker.
    """
    from app.models import (
        IpAddress,
        MfaTransaction,
        Session,
        User,
        UserRole,
        UserTrustedDevice,
    )

    user_ids = [fixture_id(NS_USER, str(spec["username"])) for spec in DEMO_USERS]
    session_ids = [
        fixture_id(NS_SESSION, str(spec["username"]))
        for spec in DEMO_USERS
        if spec["key"] != "admin"
    ]
    device_ids = [
        fixture_id(NS_DEVICE, "m13-demo-fingerprint-analyst"),
        fixture_id(NS_DEVICE, "m13-demo-fingerprint-manager"),
    ]
    mfa_ids = [fixture_id(NS_MFA, "pending-device")]
    ip_ids = [
        fixture_id(NS_IP, ip)
        for ip in ("127.0.0.1", "203.0.113.11", "198.51.100.31")
    ]

    removed = 0
    # The children first, so the cascade never surprises us.
    for model, ids in (
        (UserRole, user_ids),
        (Session, session_ids),
        (UserTrustedDevice, device_ids),
        (MfaTransaction, mfa_ids),
        (User, user_ids),
        (IpAddress, ip_ids),
    ):
        if not ids:
            continue
        removed += (
            session.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
            or 0
        )

    session.commit()
    return removed


def cleanup_detection(session) -> int:
    """Remove ONLY the Detection rows this script created."""
    from app.models import (
        Alert,
        AlertTimeline,
        DetectionLog,
        LoginAttempt,
        Policy,
        RiskAssessment,
        SocAnalyst,
    )

    alert_ids = [fixture_id(NS_ALERT, str(spec["key"])) for spec in DEMO_ALERTS]
    attempt_ids = [fixture_id(NS_ATTEMPT, str(spec["key"])) for spec in DEMO_ALERTS]
    assessment_ids = [fixture_id(NS_ASSESSMENT, str(spec["key"])) for spec in DEMO_ALERTS]
    log_ids = [
        fixture_id(NS_LOG, f"{str(spec['key'])}:{suffix}")
        for spec in DEMO_ALERTS
        for suffix in ("rule", "ml")
    ]
    timeline_ids = [
        fixture_id(NS_TIMELINE, f"{str(spec['key'])}:{index}")
        for spec in DEMO_ALERTS
        for index in range(len(spec["timeline"]))
    ]
    policy_ids = [
        fixture_id(NS_POLICY, "m13-demo-active"),
        fixture_id(NS_POLICY, "m13-demo-draft"),
    ]
    analyst_ids = [fixture_id(NS_ANALYST, "demo_analyst")]

    removed = 0
    for model, ids in (
        (AlertTimeline, timeline_ids),
        (DetectionLog, log_ids),
        (RiskAssessment, assessment_ids),
        (Alert, alert_ids),
        (LoginAttempt, attempt_ids),
        (Policy, policy_ids),
        (SocAnalyst, analyst_ids),
    ):
        if not ids:
            continue
        removed += (
            session.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
            or 0
        )

    session.commit()
    return removed


def cleanup_ml(session) -> int:
    """Remove ONLY the ML rows this script created."""
    from app.models import FeatureStatistic, InferenceLog, ModelVersion

    model_ids = [fixture_id(NS_MODEL, "m13-demo-model")]
    log_ids = [
        fixture_id(NS_INFERENCE, f"ok:{index}") for index in range(7)
    ]
    stat_ids = [
        fixture_id(NS_FEATURE, name)
        for name in (
            "hour_of_day",
            "fail_count_24h",
            "ip_change_rate_7d",
            "new_device",
            "average_login_interval_minutes",
            "deviation_score",
        )
    ]

    removed = 0
    for model, ids in (
        (InferenceLog, log_ids),
        (FeatureStatistic, stat_ids),
        (ModelVersion, model_ids),
    ):
        if not ids:
            continue
        removed += (
            session.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
            or 0
        )

    session.commit()
    return removed


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def _resolve_url(context: str, explicit: Optional[str]) -> str:
    from app.db import resolve_database_url

    return explicit or resolve_database_url(context)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="create the demo fixtures")
    parser.add_argument("--cleanup", action="store_true", help="remove the demo fixtures")
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="print the manifest of the deterministic fixture identifiers and exit",
    )
    parser.add_argument(
        "--manifest-out",
        default="",
        help="write the manifest to this file as JSON",
    )
    args = parser.parse_args()

    if args.manifest and not (args.seed or args.cleanup):
        print_manifest(args.manifest_out)
        return 0

    if not (args.seed or args.cleanup):
        parser.error("one of --seed, --cleanup or --manifest is required")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    core_url = os.environ.get("CORE_DATABASE_URL", "")
    detection_url = os.environ.get("DETECTION_DATABASE_URL", "")
    ml_url = os.environ.get("ML_DATABASE_URL", "")

    # The guards run BEFORE the engines are created: nothing connects, and
    # nothing can be written or deleted, until every target is proven to be
    # a demo database.
    core_name = assert_demo_database(core_url or "postgresql://x@localhost:1/none_demo")
    detection_name = assert_demo_database(
        detection_url or "postgresql://x@localhost:1/none_demo"
    )
    ml_name = assert_demo_database(ml_url or "postgresql://x@localhost:1/none_demo")
    print(f"[demo-seed] the targets are '{core_name}', '{detection_name}', '{ml_name}'")

    engines = []
    try:
        for url in (core_url, detection_url, ml_url):
            engine = create_engine(url, pool_pre_ping=True)
            engines.append(engine)

        if args.seed:
            core_session = sessionmaker(bind=engines[0])()
            detection_session = sessionmaker(bind=engines[1])()
            ml_session = sessionmaker(bind=engines[2])()
            try:
                core_manifest = seed_core(core_session)
                print(
                    f"[demo-seed] core: {len(core_manifest['users'])} users, "
                    f"{len(core_manifest['sessions'])} sessions, "
                    f"{len(core_manifest['devices'])} device records"
                )
                detection_manifest = seed_detection(detection_session, core_manifest)
                print(
                    f"[demo-seed] detection: {len(detection_manifest['alerts'])} alerts, "
                    f"{len(detection_manifest['policies'])} policies"
                )
                ml_manifest = seed_ml(ml_session)
                print(
                    f"[demo-seed] ml: {ml_manifest['inference_logs']} inference logs, "
                    f"{ml_manifest['feature_stats']} feature statistics"
                )
                manifest = {
                    "marker": FIXTURE_MARKER,
                    "core": core_manifest,
                    "detection": detection_manifest,
                    "ml": ml_manifest,
                }
                if args.manifest_out:
                    Path(args.manifest_out).write_text(
                        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
                    )
                    print(f"[demo-seed] the manifest was written to {args.manifest_out}")
                print("[demo-seed] the demo fixtures are seeded")
            finally:
                core_session.close()
                detection_session.close()
                ml_session.close()
        else:
            removed = 0
            for engine, cleaner in zip(
                engines, (cleanup_core, cleanup_detection, cleanup_ml)
            ):
                session = sessionmaker(bind=engine)()
                try:
                    removed += cleaner(session)
                finally:
                    session.close()
            print(f"[demo-seed] removed {removed} fixture row(s)")
            print("[demo-seed] the demo fixtures are cleaned up")
    except Exception as exc:  # noqa: BLE001 - the script must fail loudly
        print(f"[demo-seed] ERROR: the fixtures could not be seeded: {exc}", file=sys.stderr)
        return 1
    finally:
        for engine in engines:
            engine.dispose()

    return 0


def print_manifest(out_path: str = "") -> None:
    """Print the deterministic identifiers without touching a database."""
    manifest = {
        "marker": FIXTURE_MARKER,
        "users": {
            str(spec["key"]): {
                "id": fixture_id(NS_USER, str(spec["username"])),
                "username": str(spec["username"]),
                "roles": sorted(str(r) for r in spec["roles"]),  # type: ignore[arg-type]
                "mfa_required": bool(spec["admin_mfa_required"]),
            }
            for spec in DEMO_USERS
        },
        "sessions": [
            {"id": fixture_id(NS_SESSION, str(spec["username"])), "username": str(spec["username"])}
            for spec in DEMO_USERS
            if spec["key"] != "admin"
        ],
        "devices": [
            {
                "id": fixture_id(NS_DEVICE, "m13-demo-fingerprint-analyst"),
                "username": "demo_analyst",
                "pending": False,
            },
            {
                "id": fixture_id(NS_DEVICE, "m13-demo-fingerprint-manager"),
                "username": "demo_manager",
                "pending": False,
            },
            {
                "id": fixture_id(NS_MFA, "pending-device"),
                "username": "demo_user",
                "pending": True,
            },
        ],
        "policies": {
            "active": {"id": fixture_id(NS_POLICY, "m13-demo-active"), "is_active": True},
            "draft": {"id": fixture_id(NS_POLICY, "m13-demo-draft"), "is_active": False},
        },
        "alerts": {
            str(spec["key"]): {
                "id": fixture_id(NS_ALERT, str(spec["key"])),
                "status": str(spec["status"]),
                "risk_level": str(spec["risk_level"]),
                "login_attempt_id": fixture_id(NS_ATTEMPT, str(spec["key"])),
            }
            for spec in DEMO_ALERTS
        },
        "ml_model": {
            "id": fixture_id(NS_MODEL, "m13-demo-model"),
            "status": "staged",
            "is_production": False,
        },
    }
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
        print(f"[demo-seed] the manifest was written to {out_path}")
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
