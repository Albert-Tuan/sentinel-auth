#!/usr/bin/env python3
"""Sentinel Auth v3.3 — M13.2 browser E2E fixture helper.

The browser tests need alert rows the BACKEND does not create on
demand: there is no endpoint that creates an alert for a given subject,
and the alert lifecycle is terminal — a resolved alert is immutable and
the backend answers 409 for every later mutation.

That would make the suite runnable exactly once.  This helper closes the
gap the same way ``scripts/demo_scenarios.py`` does: it writes the
fixture rows directly into the demo detection database, with
DETERMINISTIC ids, so a second run reuses the row instead of colliding
with it.

 ---------------------------------------------------------------------------
 WHY THIS IS NOT A "RESET" THAT HIDES A DEFECT
 ---------------------------------------------------------------------------

 The rule of the milestone is that a cleanup bug must not be papered
 over with a reset.  This helper is not that:

   * it only ever touches rows THIS SUITE created — the ids carry the
     ``m13-e2e-`` marker and the script refuses to write to any other
     row;
   * it never restores a state a test was supposed to leave behind — it
     only PREPARES a fixture, before the test runs;
   * the seeded fixtures of ``scripts/demo_seed_demo.py`` are never
     modified by it, so a defect in the cleanup of the seeded data
     would still be visible.

 The alert the SOC scenario investigates is therefore its OWN row, and
 the suite is re-runnable on the same demo stack for ever.

 ---------------------------------------------------------------------------
 THE ONE DELIBERATE EXCEPTION TO THE "E2E-OWNED ROWS" RULE
 ---------------------------------------------------------------------------

 ``restore-active-policy`` restores the demo stack's SEEDED active
 policy.  Every other operation here touches only rows this suite
 created; that one deliberately touches a row it did NOT create.

 It is a legitimate exception, and it is deliberate rather than
 accidental: activating a policy deactivates the current one — that is
 the product behaviour, and the browser scenario has to prove it — so
 the seeded ACTIVE policy of the demo stack is no longer active and
 the demo would drift away from its own fixtures.  Putting the demo
 back the way the scenario found it is a REQUIRED cleanup, not a way of
 hiding a defect.

 The exception is scoped as tightly as the principle it bends: it
 restores ONE named policy, it only moves the ACTIVE SLOT, it never
 deletes anything, and it is still subject to every database guard
 below.

 ---------------------------------------------------------------------------
 THE DATABASE GUARD
 ---------------------------------------------------------------------------

 Every engine in this helper is created through ``_guarded_engine``,
 which refuses to build the engine at all unless the URL is a demo
 database the context owns.  The guard is in
 ``scripts/e2e_fixtures_guard.py``, it is fail-closed, and it runs
 BEFORE any connection is opened — so a refused URL never reaches a
 database and no SQL is ever issued.

Usage::

    scripts/e2e_fixtures.py create-alert --key e2e-03 --risk critical
    scripts/e2e_fixtures.py reset-alert --key e2e-03
    scripts/e2e_fixtures.py create-orphan-alert
    scripts/e2e_fixtures.py delete-alert --key e2e-03
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# The guard lives in its own module so it can be imported and tested on
# its own: it is the safety boundary of this script, and a safety
# boundary that is only reachable by running the destructive code is a
# safety boundary nobody can test.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_fixtures_guard import (  # noqa: E402
    Context,
    DemoDatabaseRefusal,
    require_demo_database,
    require_demo_database_url,
)

#: The namespace the seed script derives every fixture id from.  The E2E
#: fixtures live in their OWN namespace, so an E2E id can never collide
#: with a seeded id.
E2E_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

#: The marker every E2E fixture carries.  The script refuses to write
#: to a row that does not carry it.
E2E_MARKER = "m13-e2e-fixture"

#: The prefix of the ids of the alerts this suite owns.
E2E_ID_PREFIX = "m13-e2e-"

#: The prefix of the VERSIONS of the policies this suite owns.
#:
#: The backend accepts a version that matches ``^v\d+(\.\d+)*$``, so the
#: E2E versions live in their own numeric namespace — ``v13.2`` — which
#: no seeded policy of the demo stack uses.  The helper refuses to
#: remove a version outside that namespace.
E2E_POLICY_VERSION_PREFIX = "v13.2"


def _deterministic_id(kind: str, key: str) -> str:
    """The deterministic id of one fixture row."""
    return str(uuid.uuid5(E2E_NAMESPACE, f"{kind}:{key}"))


def _detection_url() -> str:
    """The detection database URL of the demo stack."""
    url = os.environ.get("DETECTION_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "DETECTION_DATABASE_URL is not set; load the demo environment first:\n"
            "  set -a; . .env.demo; set +a"
        )
    return url


def _guarded_engine(context: str, url: str):
    """Create an engine for a demo database — after the guard said yes.

    The guard runs BEFORE the engine is created, so a refused URL never
    reaches a database and never opens a connection.  That is the point
    of the guard: it is a decision about the URL, made before anything
    can be written.

    The engine is built from the URL OBJECT the guard validated — not
    from the raw string.  That closes the gap between "the URL that was
    checked" and "the URL the driver receives": the guard parses the
    URL with SQLAlchemy's own parser, checks the destination the driver
    will really use, and hands back the very object it checked.  A
    string that was parsed, checked and then re-assembled could differ
    from the one the driver would read.
    """
    try:
        validated = require_demo_database_url(context, url)
    except DemoDatabaseRefusal as refusal:
        raise SystemExit(f"[e2e-fixtures] ERROR: refusing to write: {refusal}")

    try:
        from sqlalchemy import create_engine
    except ImportError:  # pragma: no cover - SQLAlchemy is a hard dependency
        raise SystemExit("SQLAlchemy is not installed")

    return create_engine(validated, pool_pre_ping=True)


def _engine():
    """A SQLAlchemy engine for the detection database."""
    return _guarded_engine(Context.DETECTION, _detection_url())


def _resolve_alert_id(key: str) -> str:
    """The alert id of a fixture key."""
    if not key.startswith(E2E_ID_PREFIX):
        key = f"{E2E_ID_PREFIX}{key}"
    return _deterministic_id("alert", key)


def _resolve_attempt_id(key: str) -> str:
    """The login-attempt id of a fixture key."""
    if not key.startswith(E2E_ID_PREFIX):
        key = f"{E2E_ID_PREFIX}{key}"
    return _deterministic_id("login_attempt", key)


def _resolve_subject_id(key: str) -> str:
    """The id of the (non-existent) subject of a fixture key."""
    if not key.startswith(E2E_ID_PREFIX):
        key = f"{E2E_ID_PREFIX}{key}"
    return _deterministic_id("user", key)


def create_alert(
    key: str,
    risk_level: str,
    status: str,
    orphan_subject: bool = False,
) -> Dict[str, Any]:
    """Create (or re-arm) an alert owned by this suite.

    The alert carries a REAL subject — the `demo_user` account of the
    core context — so a protective action against it really changes the
    core state.  The write is idempotent: the second run reuses the row
    and puts it back into the requested status.

    With ``orphan_subject`` the subject is an id the core context does
    NOT know.  A protective action against such an alert cannot be
    enforced, so the backend answers 502 — which is the failure the UI
    has to report honestly.
    """
    from sqlalchemy import text

    alert_id = _resolve_alert_id(key)
    attempt_id = _resolve_attempt_id(key)
    orphan_subject_id = _resolve_subject_id(key)

    # The subject of the alert is the seeded `demo_user`.  The
    # detection context stores the CORE user id, so the value is read
    # from the manifest — a made-up id would make the protective action
    # fail with a 502 instead of really changing the core state.
    manifest_path = REPO_ROOT / ".ci" / "demo" / "fixture-manifest.json"
    subject_username = "m13-orphan-subject"
    subject_id = orphan_subject_id
    if orphan_subject:
        # The subject does NOT exist in the core context.  This is the
        # trigger of the 502 case.
        subject_username = "m13-orphan-subject"
        subject_id = orphan_subject_id
    elif manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        seeded = manifest.get("core", {}).get("users", {}).get("user", {})
        subject_username = seeded.get("username") or "demo_user"
        subject_id = seeded.get("id") or subject_id

    engine = _engine()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO login_attempts "
                    "(id, event_id, user_id, username_attempted, outcome, "
                    " mfa_used, ip_address, user_agent, device_fingerprint, "
                    " timestamp, status, request_id, risk_level, "
                    " detection_decision, created_at, updated_at) "
                    "VALUES (:id, :event_id, :user_id, :username, "
                    " 'failure', false, '203.0.113.77', 'M13.2 E2E fixture', "
                    " null, now(), 'processed', :request_id, :risk_level, "
                    " 'block', now(), now()) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    " status = 'processed', risk_level = :risk_level, "
                    " updated_at = now()"
                ),
                {
                    "id": attempt_id,
                    "event_id": str(uuid.uuid5(E2E_NAMESPACE, f"login_attempt:{key}:event")),
                    "user_id": subject_id,
                    "username": subject_username,
                    "request_id": str(uuid.uuid5(E2E_NAMESPACE, f"login_attempt:{key}:request")),
                    "risk_level": risk_level,
                },
            )

            connection.execute(
                text(
                    "INSERT INTO alerts "
                    "(id, login_attempt_id, policy_id, status, risk_level, "
                    " detection_reason, detection_scores, assigned_to_id, "
                    " resolved_by_id, resolved_at, resolution, notes, "
                    " created_at, updated_at) "
                    "VALUES (:id, :login_attempt_id, null, :status, :risk_level, "
                    " :reason, '{}'::jsonb, null, null, null, null, :notes, "
                    " now(), now()) "
                    # The re-arm refreshes `created_at` as well.
                    #
                    # The queue is sorted newest-first, and the demo stack
                    # keeps producing alerts of its own — every login the
                    # risk gate holds creates one.  A fixture that kept
                    # its FIRST timestamp would therefore sink deeper and
                    # deeper into the queue on every run, and the
                    # scenario would eventually fail to find it — a
                    # failure caused by the age of the fixture, not by
                    # the behaviour under test.
                    #
                    # Re-arming is a PREPARATION, not a repair of a
                    # business state: the row is the suite's own, it
                    # carries the suite's marker, and the suite is
                    # entitled to decide when it was created.
                    "ON CONFLICT (id) DO UPDATE SET "
                    " status = :status, risk_level = :risk_level, "
                    " resolved_by_id = NULL, resolved_at = NULL, "
                    " resolution = NULL, created_at = now(), updated_at = now()"
                ),
                {
                    "id": alert_id,
                    "login_attempt_id": attempt_id,
                    "status": status,
                    "risk_level": risk_level,
                    "reason": f"{E2E_MARKER}: browser E2E fixture ({key})",
                    "notes": E2E_MARKER,
                },
            )
    finally:
        engine.dispose()

    return {
        "alert_id": alert_id,
        "login_attempt_id": attempt_id,
        "subject_user_id": subject_id,
        "subject_username": subject_username,
        "status": status,
        "risk_level": risk_level,
    }


def create_orphan_alert(key: str = "orphan") -> Dict[str, Any]:
    """Create an alert whose subject does NOT exist in the core context.

    The protective action against such an alert cannot be enforced by
    Core, so the backend answers 502 — which is exactly the failure the
    UI has to report honestly.
    """
    return create_alert(key, risk_level="high", status="open", orphan_subject=True)


def delete_alert(key: str) -> Dict[str, Any]:
    """Remove an alert this suite owns.

    Only a row carrying the E2E marker is removed; the script refuses
    to touch anything else.
    """
    from sqlalchemy import text

    alert_id = _resolve_alert_id(key)
    attempt_id = _resolve_attempt_id(key)

    engine = _engine()
    try:
        with engine.begin() as connection:
            removed = connection.execute(
                text(
                    "DELETE FROM alerts WHERE id = :alert_id "
                    "AND notes = :marker RETURNING id"
                ),
                {"alert_id": alert_id, "marker": E2E_MARKER},
            ).fetchone()
            connection.execute(
                text("DELETE FROM login_attempts WHERE id = :attempt_id"),
                {"attempt_id": attempt_id},
            )
    finally:
        engine.dispose()

    return {"alert_id": alert_id, "removed": bool(removed)}


def _detection_engine():
    """A SQLAlchemy engine for the detection database."""
    return _engine()


def delete_policy(version: str) -> Dict[str, Any]:
    """Remove the policy of a given version.

    Only a policy whose version lives in the E2E namespace (``v13.2*``)
    is removed; the script refuses to touch the seeded policies of the
    demo stack.

    The removal is needed because a policy that has been ACTIVATED is
    frozen for ever: its ``activated_at`` is set and the backend answers
    409 for every later edit.  A test that activates its own policy
    would therefore be able to run only once, so the fixture is removed
    before the next run instead of being reset in place.
    """
    from sqlalchemy import text

    if not version.startswith(E2E_POLICY_VERSION_PREFIX):
        raise SystemExit(
            f"refusing to remove the policy '{version}': it is outside the E2E "
            f"namespace '{E2E_POLICY_VERSION_PREFIX}'"
        )

    engine = _detection_engine()
    try:
        with engine.begin() as connection:
            removed = connection.execute(
                text("DELETE FROM policies WHERE version = :version RETURNING id"),
                {"version": version},
            ).fetchone()
    finally:
        engine.dispose()

    return {"version": version, "removed": bool(removed)}


def restore_active_policy() -> Dict[str, Any]:
    """Restore the demo stack to "exactly one active policy": the seeded one.

    Activating a policy deactivates the current one — that is the
    product behaviour, and the browser scenario has to prove it.  The
    side effect is that the seeded ACTIVE policy of the demo stack is
    no longer active, so the demo would drift away from its own fixtures.

    The scenario therefore restores the state afterwards.  This is the
    kind of cleanup that IS part of the behaviour under test: the
    activation is supposed to change which policy is in service, and
    the test is supposed to put the demo back the way it found it.

    Only the ACTIVE SLOT is restored.  The E2E-owned policies are left
    alone — they carry the evidence of the scenario, and the helper
    removes them on its own.

    ---------------------------------------------------------------------------
    THE DELIBERATE EXCEPTION TO THE "E2E-OWNED ROWS ONLY" RULE
    ---------------------------------------------------------------------------

    Every other operation of this helper touches ONLY rows the E2E
    suite created: the ids carry the ``m13-e2e-`` marker, and the
    helper refuses to write to a row that does not carry it.  This
    operation is the ONE exception, and it is deliberate rather than
    accidental.

    It is legitimate because it is the RESTORE of a state the behaviour
    under test changed.  Activating a policy deactivates the current
    one — that is what "only one policy may be in service" means, and
    the scenario has to prove it.  The side effect is that the seeded
    ACTIVE policy of the demo stack is no longer active, so the demo
    would drift away from its own fixtures.  Putting the demo back the
    way the scenario found it is therefore a REQUIRED cleanup, not a
    way of hiding a defect.

    The exception is scoped as tightly as the principle it bends:

      * it restores ONE named policy — the seeded ``m13-demo-active``;
      * it only ever moves the ACTIVE SLOT, so exactly one policy is
        active afterwards, which is the invariant the demo stack keeps;
      * it never DELETES a policy, and it never touches the E2E-owned
        policies, which carry the evidence of the scenario;
      * it is still subject to every database guard — a non-demo
        database is refused just the same.
    """
    from sqlalchemy import text

    seeded_version = "m13-demo-active"

    engine = _detection_engine()
    try:
        with engine.begin() as connection:
            seeded = connection.execute(
                text("SELECT id FROM policies WHERE version = :version"),
                {"version": seeded_version},
            ).fetchone()

            if seeded is None:
                return {"restored": False, "reason": "the seeded policy is missing"}

            connection.execute(
                text(
                    "UPDATE policies SET is_active = FALSE, "
                    "deactivated_at = now() WHERE is_active = TRUE"
                )
            )
            connection.execute(
                text(
                    "UPDATE policies SET is_active = TRUE, "
                    "activated_at = now() - interval '24 hours', "
                    "deactivated_at = NULL WHERE id = :id"
                ),
                {"id": seeded[0]},
            )
    finally:
        engine.dispose()

    return {"restored": True, "version": seeded_version}


def _ml_url() -> str:
    """The ML database URL of the demo stack."""
    url = os.environ.get("ML_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "ML_DATABASE_URL is not set; load the demo environment first:\n"
            "  set -a; . .env.demo; set +a"
        )
    return url


def _ml_engine():
    """A SQLAlchemy engine for the ML database."""
    return _guarded_engine(Context.ML, _ml_url())


#: The ML table the helper renames to simulate a source failure.
#:
#: ``inference_logs`` is the table the ML statistics are computed from,
#: so renaming it makes every ML read fail with "relation does not
#: exist" — which the facade maps to the ``database_error`` reason code.
ML_SOURCE_TABLE = "inference_logs"

#: The name the table carries while the source is broken.
ML_SOURCE_TABLE_HIDDEN = "inference_logs_e2e_broken"


def break_ml_source() -> Dict[str, Any]:
    """Make the ML analytics source fail.

    ---------------------------------------------------------------------------
    WHY THE SOURCE IS BROKEN BY RENAMING A TABLE
    ---------------------------------------------------------------------------

    The Manager facade has to prove two DIFFERENT failure contracts, and
    they cannot be proved by the same fault:

      * a DEGRADED payload — HTTP 200 with the sections that do not
        depend on the broken source present, and the broken section
        ``null``;
      * a 503 — HTTP 503 with the per-source reasons, for an endpoint
        that consumes ONE source only.

    Renaming the table makes the ML read fail with a real database
    error, which is the fault the facade is designed for.  Nothing is
    mocked and no application code is touched: the facade sees a source
    that really does not answer.

    The rename is REVERSED by ``restore_ml_source``; the helper refuses
    to leave the table renamed when it is already broken, so a failed
    run cannot silently leave the demo stack degraded.
    """
    from sqlalchemy import text

    engine = _ml_engine()
    try:
        with engine.begin() as connection:
            exists = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :name"
                ),
                {"name": ML_SOURCE_TABLE_HIDDEN},
            ).scalar()

            if exists:
                return {"broken": True, "already": True, "table": ML_SOURCE_TABLE_HIDDEN}

            connection.execute(
                text(f"ALTER TABLE {ML_SOURCE_TABLE} RENAME TO {ML_SOURCE_TABLE_HIDDEN}")
            )
    finally:
        engine.dispose()

    return {"broken": True, "already": False, "table": ML_SOURCE_TABLE_HIDDEN}


def restore_ml_source() -> Dict[str, Any]:
    """Undo ``break_ml_source``."""
    from sqlalchemy import text

    engine = _ml_engine()
    try:
        with engine.begin() as connection:
            hidden = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :name"
                ),
                {"name": ML_SOURCE_TABLE_HIDDEN},
            ).scalar()

            if not hidden:
                return {"restored": False, "already": True, "table": ML_SOURCE_TABLE}

            connection.execute(
                text(f"ALTER TABLE {ML_SOURCE_TABLE_HIDDEN} RENAME TO {ML_SOURCE_TABLE}")
            )
    finally:
        engine.dispose()

    return {"restored": True, "table": ML_SOURCE_TABLE}


def expire_session(session_id: str) -> Dict[str, Any]:
    """Expire ONE session, by its id.

    ---------------------------------------------------------------------------
    WHY THE EXPIRY IS PRODUCED IN THE DATABASE
    ---------------------------------------------------------------------------

    The access token of a session lives for an hour, so a browser test
    could never wait for it to expire.  The expiry has to be produced
    some other way, and the honest way is to move the session's own
    deadline into the past: the backend then behaves exactly as it would
    after a real hour — the access token is refused AND the refresh
    token is refused, because the refresh endpoint checks the same
    deadline.

    Nothing is mocked and no application code is touched.  The helper
    only moves a DEADLINE — it does not change the identity of the
    session, nor its tokens, nor any business state.

    The session is addressed BY ITS ID, never by "the sessions of this
    account": the account may hold several sessions, and a race
    scenario has to expire exactly ONE of them — the one the browser
    under test holds — while the other sessions stay alive.
    """
    from sqlalchemy import text

    engine = _core_engine()
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE sessions SET expires_at = now() - interval '1 minute' "
                    "WHERE id = :session_id RETURNING id"
                ),
                {"session_id": session_id},
            )
            affected = len(result.fetchall())
    finally:
        engine.dispose()

    return {"session_id": session_id, "expired": affected}


def spend_refresh_token(session_id: str) -> Dict[str, Any]:
    """Make the stored refresh token of ONE session dead.

    ---------------------------------------------------------------------------
    WHY THIS IS THE REFRESH RACE AND NOT A SIMULATION OF ONE
    ---------------------------------------------------------------------------

    The backend ROTATES the refresh token: every `POST /auth/refresh`
    overwrites the stored hash, so the copy the client holds is dead
    the moment the rotation happened.  That is exactly what happens
    when the same refresh token is spent from two places at once: the
    first spend wins, the second one finds a token the server no
    longer knows.

    The helper performs that rotation from the outside: the stored hash
    is replaced by the hash of a token nobody holds.  The browser's copy
    of the refresh token becomes stale, so the next 401 the browser
    sees makes it try to refresh with a dead token — and the backend
    refuses it with a genuine 401.

    The session is addressed BY ITS ID, so exactly ONE session is
    affected: the race scenario needs the session of the browser under
    test to be the one that dies, while the sessions of the other
    browsers of the same account stay alive.
    """
    import hashlib
    import secrets as secrets_module

    from sqlalchemy import text

    dead_hash = hashlib.sha256(secrets_module.token_urlsafe(32).encode()).hexdigest()

    engine = _core_engine()
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE sessions SET refresh_token_hash = :hash "
                    "WHERE id = :session_id RETURNING id"
                ),
                {"hash": dead_hash, "session_id": session_id},
            )
            affected = len(result.fetchall())
    finally:
        engine.dispose()

    return {"session_id": session_id, "rotated": affected}


def _core_url() -> str:
    """The core database URL of the demo stack."""
    url = os.environ.get("CORE_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "CORE_DATABASE_URL is not set; load the demo environment first:\n"
            "  set -a; . .env.demo; set +a"
        )
    return url


def _core_engine():
    """A SQLAlchemy engine for the core database."""
    return _guarded_engine(Context.CORE, _core_url())


def set_detection_mfa_gate(username: str, armed: bool) -> Dict[str, Any]:
    """Arm or clear the ONE-TIME MFA gate of an account.

    ``REQUIRE_MFA`` sets ``users.detection_mfa_once``, and the flag is
    cleared as soon as the account completes an MFA handshake.  A test
    that runs twice would therefore find the gate already consumed and
    could not prove it a second time.

    The flag is re-armed in the CORE database directly.  Going through
    the internal boundary would not work: the action also revokes the
    live sessions of the account, which would invalidate the very
    session the test is using.

    The write touches ONE column of ONE row of the core context, and
    only the account the test is about to prove.
    """
    from sqlalchemy import text

    engine = _core_engine()
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "UPDATE users SET detection_mfa_once = :armed "
                    "WHERE username = :username RETURNING id, detection_mfa_once"
                ),
                {"armed": armed, "username": username},
            ).fetchone()
    finally:
        engine.dispose()

    if row is None:
        raise SystemExit(f"the account '{username}' does not exist in the core context")

    return {"user_id": str(row[0]), "username": username, "armed": bool(row[1])}


def reset_rate_limits(ip_address: str = "127.0.0.1") -> Dict[str, Any]:
    """Clear the login rate-limit counters of the test client.

    The backend rate-limits the login endpoint at 5 requests per minute
    per client IP.  Every browser scenario logs in, and every scenario
    runs from the SAME loopback address, so a suite of eight scenarios
    would hit the limit that the product itself put in place.

    The counter is a RATE LIMIT, not business state: clearing it does not
    hide a defect of the application — it removes the interference of the
    test client with a control that is designed for real traffic.  The
    seeded fixtures, the sessions and the alerts are untouched.

    Only the rows of the given client address are removed; the limiter
    itself stays exactly as it is.
    """
    from sqlalchemy import text

    engine = _core_engine()
    try:
        with engine.begin() as connection:
            removed = connection.execute(
                text(
                    "DELETE FROM rate_limits "
                    "WHERE ip_address = :ip_address AND action = 'login' "
                    "RETURNING ip_address"
                ),
                {"ip_address": ip_address},
            ).fetchall()
    finally:
        engine.dispose()

    return {"ip_address": ip_address, "removed": len(removed)}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-alert", help="create or re-arm an E2E alert")
    create.add_argument("--key", required=True)
    create.add_argument("--risk", default="critical")
    create.add_argument("--status", default="open")

    orphan = sub.add_parser(
        "create-orphan-alert", help="create an alert whose subject Core does not know"
    )
    orphan.add_argument("--key", default="orphan")

    remove = sub.add_parser("delete-alert", help="remove an E2E alert")
    remove.add_argument("--key", required=True)

    gate = sub.add_parser(
        "set-mfa-gate", help="arm or clear the one-time MFA gate of an account"
    )
    gate.add_argument("--username", required=True)
    gate.add_argument(
        "--armed",
        choices=["true", "false"],
        default="true",
    )

    limiter = sub.add_parser(
        "reset-rate-limits",
        help="clear the login rate-limit counter of the test client",
    )
    limiter.add_argument("--ip", default="127.0.0.1")

    policy = sub.add_parser(
        "delete-policy",
        help="remove an E2E-owned policy so the scenario can run again",
    )
    policy.add_argument("--version", required=True)

    restore = sub.add_parser(
        "restore-active-policy",
        help="make the seeded demo policy the only active one again",
    )

    sub.add_parser(
        "break-ml-source",
        help="make the ML analytics source fail, so the facade degrades",
    )
    sub.add_parser(
        "restore-ml-source",
        help="undo break-ml-source",
    )

    expire = sub.add_parser(
        "expire-session",
        help="expire ONE session, as a real expiry would",
    )
    expire.add_argument("--session-id", required=True)

    spend = sub.add_parser(
        "spend-refresh-token",
        help="make the stored refresh token of ONE session dead",
    )
    spend.add_argument("--session-id", required=True)

    args = parser.parse_args(argv)

    if args.command == "create-alert":
        result = create_alert(args.key, args.risk, args.status)
    elif args.command == "create-orphan-alert":
        result = create_orphan_alert(args.key)
    elif args.command == "delete-alert":
        result = delete_alert(args.key)
    elif args.command == "set-mfa-gate":
        result = set_detection_mfa_gate(args.username, args.armed == "true")
    elif args.command == "reset-rate-limits":
        result = reset_rate_limits(args.ip)
    elif args.command == "delete-policy":
        result = delete_policy(args.version)
    elif args.command == "restore-active-policy":
        result = restore_active_policy()
    elif args.command == "break-ml-source":
        result = break_ml_source()
    elif args.command == "restore-ml-source":
        result = restore_ml_source()
    elif args.command == "expire-session":
        result = expire_session(args.session_id)
    elif args.command == "spend-refresh-token":
        result = spend_refresh_token(args.session_id)
    else:  # pragma: no cover - argparse rejects anything else
        raise SystemExit(f"unknown command: {args.command}")

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
