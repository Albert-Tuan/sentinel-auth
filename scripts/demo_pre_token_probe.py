#!/usr/bin/env python
"""Sentinel Auth v3.3 — the pre-token detection gate probe.

THE QUESTION THIS PROBE ANSWERS
=================================

The M13 acceptance evidence proves the pre-token gate in two places that
both run against **disposable test databases**:

    10|  * ``tests/test_full_system_e2e.py`` — the ASGI-routed, real-HTTP
    scenarios B and C;
  * ``tests/test_risk_gate.py`` — the unit tests of ``_pre_token_risk``.

Neither of them answers the question the demo actually needs answered:

    **On the running demo stack — with the REAL Detection policy, the
    REAL scoring and the REAL HTTP boundary — does the pre-token gate
    really hold the token back?**

    20|That is what this probe measures, and it measures it the only honest
way: by running the SAME risky login twice, once with the gate ON and
once with the gate OFF, and comparing what the client received.

  * gate ON  -> the token must be HELD (``access_token == ""`` and
                ``mfa_required == true``);
  * gate OFF -> the token must be ISSUED (``access_token != ""``).

Only a DIFFERENCE between the two runs shows that the gate is what made
the decision.  But a difference alone does not PROVE the cause, so the
probe does not lean on the difference alone: it also reads the DETECTION
    30|evidence the two runs left behind in the detection database — the
``rule_evaluation`` rows that name the rules that fired, the
``scoring`` row that records the decision, and the ``policy_id`` of the
attempt — and it checks that the gated run really was scored by the
demo policy with the expected rules.

WHAT IT TOUCHES
===============

Only the **demo** databases, and only after
``scripts/e2e_fixtures_guard.py`` has validated them.  The probe does
NOT write a guard of its own: it calls
``require_demo_database_url()`` and builds every engine from the URL
object that call returns, so the destination the guard approves is the
destination the driver reaches.

    40|What the probe writes:

  * a few ``login_attempts`` rows in the DETECTION database — the risky
    history the rules need.  They are marked with the
    ``m13-pre-token-probe`` marker and are removed again at the end;
  * the one-time MFA flag of ONE demo account, which it restores to the
    value it found;
  * the ACTIVE SLOT of the policy table, which it restores to the
    policy that was in service — or to "no policy in service" when
    there was none.

It does NOT drop, truncate or delete any table, and it never touches a
``*_test`` or a production database.

WHAT IT DOES **NOT** RESTORE
============================

The probe does not claim to leave the stack untouched.  Two real login
attempts are real traffic: the demo account's session rows, the
``refresh_tokens``, the security events and the DETECTION alerts the two
attempts raised all REMAIN after the probe has finished.  The probe
reports exactly what it owns and what it leaves behind, so the claim is
never wider than the evidence.
    60|"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from scripts.e2e_fixtures_guard import (  # noqa: E402
    Context,
    DemoDatabaseRefusal,
    E2E_WRITE_PERMISSION_VAR,
    require_demo_database_url,
)

#: The marker every row this probe writes carries.
PROBE_MARKER = "m13-pre-token-probe"

#: The demo account the probe logs in as.
PROBE_USERNAME = "demo_user"

#: The password of the demo account.  The seed script falls back to this
#: constant when the environment does not supply one.
DEFAULT_DEMO_PASSWORD = "DemoPass!2026"

#: The IP the risky history is written under.  A documentation range
#: (RFC 5737), so it can never be a real client.
RISKY_IP = "203.0.113.77"

#: The range the probe draws the login address from.  RFC 5737 reserves
#: ``203.0.113.0/24`` for documentation, so no address in it can be a
#: real client.
PROBE_IP_RANGE = "203.0.113"

#: The user agent the risky history is written under.
PROBE_UA = "SentinelAuthPreTokenProbe/1.0"

#: The version of the demo's own policy — the one whose rules make a
#: risky login score ``high``.  The browser scenario E2E-05 activates a
#: policy of its own, which deactivates this one, so the probe has to
#: put it back in service before it scores anything.
DEMO_POLICY_VERSION = "m13-demo-active"

#: The rules the demo policy must have fired for the risky login.
#:
#: The probe does not merely observe that the two runs differ — it checks
#: that the DETECTION engine really scored the gated attempt with these
#: rules, under the demo policy.  Without that, a difference between the
#: two responses could have any other cause.
EXPECTED_RULES: Tuple[str, ...] = ("impossible_travel", "multiple_failures")


class ProbeError(Exception):
    """Raised when the probe cannot carry out its measurement.

    It is a distinct type so that the cleanup path can tell a failed
    measurement from a failed cleanup, and so that a test can assert on
    the reason.
    """


def log(message: str) -> None:
    print(f"[pre-token-probe] {message}", flush=True)


def fail(message: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"[pre-token-probe] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env() -> Dict[str, str]:
    """Read the demo environment, the way the demo stack reads it.

    ``.env.demo`` is the single authority for the demo configuration.
    A shell that still carries another stack's variables MUST NOT win
    here: the probe has to talk to the SAME stack the demo does.
    """
    env_file = os.environ.get("DEMO_ENV_FILE", os.path.join(REPO_ROOT, ".env.demo"))
    if not os.path.isfile(env_file):
        fail(
            f"the demo environment file {env_file!r} does not exist. "
            f"Create it with: cp .env.demo.example .env.demo"
        )

    values: Dict[str, str] = {}
    with open(env_file, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()

    for name in ("CORE_DATABASE_URL", "DETECTION_DATABASE_URL", "INTERNAL_SECRET"):
        if not values.get(name):
            fail(f"{name} is not set in {env_file!r}")

    return values


#: The environment variables the probe's own guard reads.
#:
#: The guard compares the URL it is given with the URL the context's own
#: variable names, and it refuses when the libpq environment can move the
#: destination.  The probe therefore hands the guard an environment that
#: is assembled EXPLICITLY, exactly like ``scripts/demo_stack.sh`` does
#: for the API: the demo file's own URLs, plus the write declaration the
#: run carries.
#:
#: The write declaration is NOT derived by the probe.  The probe demands
#: that the run declares, by name, that it may write to a demo database —
#: the same declaration ``scripts/e2e_run.sh`` makes.  A probe that
#: declared its own permission would make the layer a no-op, and the
#: layer exists precisely so that a run has to SAY that it is going to
#: write.
#: The libpq environment variables the guard inspects.
#:
#: The guard reads the environment it is handed, so the probe has to
#: hand it the REAL one for these variables.  The probe's own engines
#: connect in this very process, and libpq reads these variables from
#: the process environment — so a stray ``PGHOSTADDR`` in the operator's
#: shell can move the destination of a connection the guard approved.
#: The guard can only refuse it if the probe shows it.
LIBPQ_ENVIRONMENT_VARIABLES: Tuple[str, ...] = (
    "PGHOSTADDR",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGHOST",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
)


def _guard_environ(env: Dict[str, str]) -> Dict[str, str]:
    """Return the environment the guard reads.

    It carries the demo file's own database URLs — so the guard's "the
    URL must match the context's variable" layer compares the URL with
    itself — the write declaration the RUN carries, and the REAL
    libpq environment variables of this process.

    The OPERATOR's shell is not inherited wholesale: a stray
    ``CORE_DATABASE_URL`` from another stack must not decide what the
    probe touches.  But the libpq variables ARE inherited, because they
    are the ones libpq itself reads when the probe's engines connect —
    hiding them from the guard would hide them from the driver too, and
    that is exactly the hole the guard exists to close.

    :raises DemoDatabaseRefusal: when the run has not declared that it
        may write.  The refusal comes from the guard itself, so the
        probe does not have to re-implement the rule.
    """
    guard_env = {
        "CORE_DATABASE_URL": env.get("CORE_DATABASE_URL", ""),
        "DETECTION_DATABASE_URL": env.get("DETECTION_DATABASE_URL", ""),
        "ML_DATABASE_URL": env.get("ML_DATABASE_URL", ""),
    }

    for variable in LIBPQ_ENVIRONMENT_VARIABLES:
        value = (os.environ.get(variable) or "").strip()
        if value:
            guard_env[variable] = value

    # The write declaration is a property of the RUN, not of the demo
    # environment file, so it is read from the process environment only.
    declared = (os.environ.get(E2E_WRITE_PERMISSION_VAR) or "").strip()
    if declared:
        guard_env[E2E_WRITE_PERMISSION_VAR] = declared

    return guard_env


def _validated_urls(env: Dict[str, str]) -> Dict[str, URL]:
    """Validate every database URL the probe will use.

    The validation happens BEFORE any connection is opened and BEFORE
    any mutation happens, so a refused target never reaches a driver and
    never reaches a row.

    :return: a mapping of the context onto the validated URL object.  The
        object is the one the engine must be built from.
    :raises DemoDatabaseRefusal: when a URL is not an allowed demo
        database.
    """
    guard_env = _guard_environ(env)
    validated: Dict[str, URL] = {}
    for context, variable in (
        (Context.CORE, "CORE_DATABASE_URL"),
        (Context.DETECTION, "DETECTION_DATABASE_URL"),
    ):
        validated[context] = require_demo_database_url(
            context,
            env[variable],
            environ=guard_env,
        )
    return validated


def _engine(url: URL):
    """Build an engine from an ALREADY VALIDATED URL object.

    The URL object is passed straight to ``create_engine``: the guard
    parsed it with SQLAlchemy's own parser and checked that the driver's
    view of it agrees with the guard's, so re-parsing a string here would
    only invite a divergence between what was checked and what is used.
    """
    return create_engine(url, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# The risky history
# ---------------------------------------------------------------------------

def _pick_probe_ip(detection_url: URL, user_id: str) -> str:
    """Choose an address the account has never logged in from.

    ``ip_change_rate_7d`` is ``1 - (attempts from this IP) / (attempts
    in the last 7 days)``.  An address that already appears in the
    account's history LOWERS the novelty, and a novelty below 0.8 does
    not trigger the ``impossible_travel`` rule — so the gate would issue
    the token for the right reason and the wrong proof.

    The probe therefore picks an address that is genuinely new.  It
    draws from the RFC 5737 documentation range, so the address can
    never be a real client, and it skips every address the account has
    already used.  The candidate is drawn DETERMINISTICALLY from the
    account's own history, so the same history always yields the same
    address and two runs of the probe never collide with each other in
    a way that would blur the comparison.
    """
    engine = _engine(detection_url)
    try:
        with engine.connect() as connection:
            used = {
                str(row[0])
                for row in connection.execute(
                    text(
                        "SELECT DISTINCT ip_address FROM login_attempts "
                        "WHERE user_id = :user_id AND ip_address IS NOT NULL"
                    ),
                    {"user_id": user_id},
                ).fetchall()
            }
    finally:
        engine.dispose()

    # A stable starting point, so the same history always yields the
    # same candidate.
    seed = int(hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:8], 16)
    for offset in range(256):
        candidate = f"{PROBE_IP_RANGE}.{(seed + offset) % 256}"
        if candidate == RISKY_IP:
            continue
        if candidate not in used:
            return candidate

    raise ProbeError(
        "every address of the documentation range has already been used by "
        "this account. The probe cannot find an address the "
        "'impossible_travel' rule would score as new."
    )


def _seed_risky_history(detection_url: URL, user_id: str, username: str) -> List[str]:
    """Write the failed attempts that make the next login risky.

    Three failures in the last three minutes, from an IP the account has
    never used.  The demo stack's active policy scores both:

      * ``impossible_travel``  — ``ip_change_rate_7d >= 0.8``
      * ``multiple_failures``  — ``fail_count_24h >= 3``

    The probe writes the rows itself instead of failing the logins,
    because a failed login does not create the history the rules read:
    the attempt of the login under test is the one being scored.

    This is a SEEDED history, not traffic.  The probe proves that the
    gate holds a token back for an attempt whose history looks like
    that; it does NOT claim that the history was produced by real failed
    logins.
    """
    engine = _engine(detection_url)
    event_ids: List[str] = []
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        with engine.begin() as connection:
            for minutes in (3, 2, 1):
                event_id = str(uuid.uuid4())
                event_ids.append(event_id)
                connection.execute(
                    text(
                        "INSERT INTO login_attempts "
                        "(id, event_id, user_id, username_attempted, outcome, "
                        " ip_address, user_agent, timestamp, status, "
                        " detection_decision, primary_alert_id) "
                        "VALUES (:id, :event_id, :user_id, :username, 'failure', "
                        " :ip, :ua, :ts, 'processed', 'allow', NULL)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "event_id": event_id,
                        "user_id": user_id,
                        "username": username,
                        "ip": RISKY_IP,
                        "ua": PROBE_UA,
                        "ts": now - timedelta(minutes=minutes),
                    },
                )
    finally:
        engine.dispose()
    return event_ids


def _cleanup_risky_history(detection_url: URL, event_ids: Sequence[str]) -> int:
    """Remove the rows the probe wrote.  Only those rows."""
    if not event_ids:
        return 0
    engine = _engine(detection_url)
    removed = 0
    try:
        with engine.begin() as connection:
            for event_id in event_ids:
                removed += connection.execute(
                    text("DELETE FROM login_attempts WHERE event_id = :eid"),
                    {"eid": event_id},
                ).rowcount or 0
    finally:
        engine.dispose()
    return removed


# ---------------------------------------------------------------------------
# The login
# ---------------------------------------------------------------------------

def _login(
    base_url: str,
    username: str,
    password: str,
    ip: str,
    user_agent: str,
) -> Tuple[int, Dict[str, Any]]:
    """Log in from a chosen IP and return the status and the body.

    The login endpoint is rate-limited to five attempts per minute and per
    client IP.  The probe makes two logins in quick succession, so it
    waits for the window to reopen instead of reporting a ``429`` as a
    verdict — a rate-limited run would make the comparison meaningless.
    """
    deadline = time.monotonic() + 90.0
    attempt = 0
    while True:
        attempt += 1
        response = httpx.post(
            f"{base_url}/api/v1/auth/login",
            json={"username": username, "password": password},
            headers={
                "X-Forwarded-For": ip,
                "User-Agent": user_agent,
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
        if response.status_code != 429:
            break
        if time.monotonic() > deadline:
            break
        wait = min(15.0, max(deadline - time.monotonic(), 1.0))
        log(f"the login rate limit answered 429; waiting {wait:.0f}s")
        time.sleep(wait)

    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


# ---------------------------------------------------------------------------
# The policy in service
# ---------------------------------------------------------------------------

class PolicySnapshot:
    """The ACTIVE SLOT of the policy table, as the probe found it.

    The snapshot distinguishes three states that a plain ``Optional[str]``
    cannot tell apart:

      * ``already_active`` — the demo policy was the one in service, so
        the probe changed nothing and owns nothing;
      * ``other_active`` — another policy was in service, and the probe
        must put THAT one back;
      * ``none_active`` — no policy was in service at all, and the probe
        must leave it that way.

    The third state is the one a ``None`` return value used to lose: the
    probe activated the demo policy, and then the restore step saw
    ``None`` and did nothing — leaving a policy in service that had not
    been there before.
    """

    def __init__(
        self,
        state: str,
        policy_id: Optional[str] = None,
        activated_at: Optional[datetime] = None,
        deactivated_at: Optional[datetime] = None,
    ) -> None:
        self.state = state
        self.policy_id = policy_id
        self.activated_at = activated_at
        self.deactivated_at = deactivated_at

    @property
    def changed(self) -> bool:
        """Whether the probe's mutation has to be undone."""
        return self.state != "already_active"

    @property
    def owns_policy_id(self) -> Optional[str]:
        """The id of the policy the probe ACTIVATED, if it activated one."""
        return self.policy_id if self.state == "other_active" else None

    def describe(self) -> str:
        if self.state == "already_active":
            return f"the demo policy {DEMO_POLICY_VERSION!r} was already in service"
        if self.state == "other_active":
            return (
                f"another policy ({self.policy_id}) was in service; the probe "
                f"put the demo policy back and will restore the other one"
            )
        return (
            "no policy was in service; the probe put the demo policy back and "
            "will leave the stack with no policy in service"
        )


def _ensure_demo_policy_active(detection_url: URL) -> PolicySnapshot:
    """Make the demo's own policy the one in service.

    The scoring reads the policy that carries ``is_active`` — there can
    only ever be ONE of them.  The browser scenario E2E-05 activates a
    policy of its own, and by the partial unique index that DEACTIVATES
    the demo's policy.  Its rules are milder, so with it in service the
    risky login is scored below the ``high`` threshold and the gate
    issues the token — which is a true statement about the policy, and
    a useless statement about the gate.

    So the probe puts the demo policy back in service before it scores
    anything — and it records WHAT it found, so that it can put it back
    exactly the way it was.

    :return: the snapshot of the ACTIVE SLOT before the mutation.
    """
    engine = _engine(detection_url)
    try:
        with engine.begin() as connection:
            demo = connection.execute(
                text("SELECT id FROM policies WHERE version = :v"),
                {"v": DEMO_POLICY_VERSION},
            ).fetchone()
            if demo is None:
                raise ProbeError(
                    f"the demo policy {DEMO_POLICY_VERSION!r} does not exist. "
                    f"Seed the demo fixtures first: "
                    f"python scripts/demo_seed_demo.py --seed"
                )

            current = connection.execute(
                text(
                    "SELECT id, activated_at, deactivated_at FROM policies "
                    "WHERE is_active IS TRUE"
                )
            ).fetchone()

            if current is not None and str(current[0]) == str(demo[0]):
                return PolicySnapshot(
                    "already_active",
                    policy_id=str(demo[0]),
                    activated_at=current[1],
                    deactivated_at=current[2],
                )

            snapshot = PolicySnapshot(
                "other_active" if current is not None else "none_active",
                policy_id=str(current[0]) if current is not None else None,
                activated_at=current[1] if current is not None else None,
                deactivated_at=current[2] if current is not None else None,
            )

            now = datetime.now(timezone.utc)
            if current is not None:
                connection.execute(
                    text(
                        "UPDATE policies SET is_active = FALSE, "
                        "deactivated_at = :now WHERE id = :id"
                    ),
                    {"now": now, "id": current[0]},
                )
            connection.execute(
                text(
                    "UPDATE policies SET is_active = TRUE, "
                    "activated_at = :now, deactivated_at = NULL WHERE id = :id"
                ),
                {"now": now, "id": demo[0]},
            )
            return snapshot
    finally:
        engine.dispose()


def _restore_active_policy(
    detection_url: URL, snapshot: Optional[PolicySnapshot]
) -> None:
    """Put the ACTIVE SLOT back the way the probe found it.

    The deactivate has to reach the database BEFORE the activate, because
    the partial unique index allows exactly one active policy — the same
    ordering the application's activation endpoint relies on.

    Three cases, and the third one is the one a plain ``None`` used to
    lose:

      * ``already_active`` — the probe changed nothing, so it restores
        nothing;
      * ``other_active`` — the policy that was in service goes back in
        service, and the demo policy goes out;
      * ``none_active`` — the demo policy goes OUT again and NO policy
        is left in service, exactly as the probe found it.

    The restore only ever moves the ONE row the probe activated and the
    ONE row it deactivated.  It never runs a blanket
    ``UPDATE policies SET is_active = FALSE WHERE is_active IS TRUE``.
    """
    if snapshot is None or not snapshot.changed:
        return

    engine = _engine(detection_url)
    try:
        with engine.begin() as connection:
            demo = connection.execute(
                text("SELECT id FROM policies WHERE version = :v"),
                {"v": DEMO_POLICY_VERSION},
            ).fetchone()
            if demo is None:
                raise ProbeError(
                    f"the demo policy {DEMO_POLICY_VERSION!r} disappeared while "
                    f"the probe was running, so the active slot cannot be "
                    f"restored."
                )
            demo_id = str(demo[0])

            # The demo policy goes out of service — and ONLY it.
            connection.execute(
                text(
                    "UPDATE policies SET is_active = FALSE, "
                    "deactivated_at = :now WHERE id = :id AND is_active IS TRUE"
                ),
                {"now": datetime.now(timezone.utc), "id": demo_id},
            )

            if snapshot.state == "other_active" and snapshot.policy_id:
                # The policy that WAS in service goes back in service, with
                # the metadata it carried.
                connection.execute(
                    text(
                        "UPDATE policies SET is_active = TRUE, "
                        "activated_at = :activated_at, "
                        "deactivated_at = :deactivated_at WHERE id = :id"
                    ),
                    {
                        "activated_at": snapshot.activated_at,
                        "deactivated_at": snapshot.deactivated_at,
                        "id": snapshot.policy_id,
                    },
                )
            # ``none_active``: nothing goes back in service.  The stack is
            # left with NO active policy, exactly as the probe found it.
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The one-time MFA flag
# ---------------------------------------------------------------------------

class MfaSnapshot:
    """The one-time MFA flag, as the probe found it.

    ``captured`` is what tells "the flag was False" from "the flag was
    never read".  A restore that runs without a snapshot would write
    ``False`` over a value the probe never saw — and a value it never
    saw is a value it must not write.
    """

    def __init__(self, captured: bool, previous: Optional[bool] = None) -> None:
        self.captured = captured
        self.previous = previous

    @property
    def changed(self) -> bool:
        return self.captured and self.previous is not None


def _clear_one_time_mfa(core_url: URL, username: str) -> MfaSnapshot:
    """Return the one-time MFA flag to False and report its old value.

    The flag is the OTHER thing that can hold a token back, so it has to
    be out of the way — otherwise the probe cannot tell the two causes
    apart.

    :return: the snapshot of the flag.  When the flag could not be read,
        the snapshot says so and the caller must NOT restore anything.
    """
    engine = _engine(core_url)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT detection_mfa_once FROM users WHERE username = :u"),
                {"u": username},
            ).fetchone()
            if row is None:
                raise ProbeError(f"the demo account {username!r} does not exist")
            previous = bool(row[0])
            connection.execute(
                text("UPDATE users SET detection_mfa_once = FALSE WHERE username = :u"),
                {"u": username},
            )
            return MfaSnapshot(captured=True, previous=previous)
    except Exception:
        # The flag was never read, so nothing was changed and nothing may
        # be restored.
        return MfaSnapshot(captured=False, previous=None)
    finally:
        engine.dispose()


def _restore_one_time_mfa(
    core_url: URL, username: str, snapshot: Optional[MfaSnapshot]
) -> None:
    """Put the one-time MFA flag back the way the probe found it.

    A snapshot that was never captured restores nothing: the probe does
    not know what the flag was, so it must not write to it.
    """
    if snapshot is None or not snapshot.changed:
        return
    engine = _engine(core_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET detection_mfa_once = :flag WHERE username = :u"),
                {"flag": snapshot.previous, "u": username},
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The rate-limit counter
# ---------------------------------------------------------------------------

def _clear_login_rate_limit(core_url: URL, ip: str) -> int:
    """Clear the login rate-limit counter of the probe's client.

    The counter is a RATE LIMIT, not business state: clearing it does not
    hide a defect of the application — it removes the interference of the
    test client with a control that is designed for real traffic.  The
    risky attempts, the sessions and the one-time MFA flag are
    untouched.

    Only the rows of the probe's own address are removed; the limiter
    itself stays exactly as it is.
    """
    engine = _engine(core_url)
    try:
        with engine.begin() as connection:
            removed = connection.execute(
                text("DELETE FROM rate_limits WHERE ip_address = :ip AND action = 'login'"),
                {"ip": ip},
            ).rowcount
            return int(removed or 0)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The second backend, with the gate OFF
# ---------------------------------------------------------------------------

#: The environment variables the comparison backend is given.
#:
#: The list is EXPLICIT, exactly like the list ``scripts/demo_stack.sh``
#: assembles for the API: a variable that is not on the list is NOT
#: inherited from the operator's shell, so a stray ``RUN_PRE_TOKEN_CHECK``,
#: a stray ``PGHOST`` or a stray ``MFA_SMTP_PORT`` from another stack
#: cannot change what the comparison measures.
#:
#: ``RUN_PRE_TOKEN_CHECK`` is the ONLY value that differs from the demo
#: stack's own.
COMPARISON_ENV_ALLOWLIST: Tuple[str, ...] = (
    "CORE_DATABASE_URL",
    "DETECTION_DATABASE_URL",
    "ML_DATABASE_URL",
    "INTERNAL_SECRET",
    "CORE_APP_URL",
    "DETECTION_URL",
    "REDIS_URL",
    "FORWARDED_ALLOW_IPS",
    "CORS_ALLOWED_ORIGINS",
    "MFA_SMTP_HOST",
    "MFA_SMTP_PORT",
    "MFA_SMTP_LOG",
    "MFA_SMTP_TIMEOUT",
    "MFA_SMTP_STARTTLS",
    "MFA_FROM_EMAIL",
    "ML_MODEL_PATH",
    "ML_SERVICE_URL",
    "LOGIN_EVENT_TIMEOUT",
    "APP_ENV",
    "TZ",
)


def _comparison_environment(env: Dict[str, str]) -> Dict[str, str]:
    """Build the comparison backend's environment.

    The environment is ASSEMBLED, not inherited: it starts from a clean
    slate and takes only the variables on the allowlist, from the demo
    environment file — which is the authoritative source.  The operator's
    shell contributes nothing, so the comparison backend cannot inherit a
    configuration that would change the outcome of the login.

    The libpq variables are deliberately NOT forwarded: the guard has
    already refused them for the probe's own connections, and the
    comparison backend must reach the very same database.
    """
    child_env: Dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "PYTHONUNBUFFERED": "1",
    }

    for name in COMPARISON_ENV_ALLOWLIST:
        value = env.get(name)
        if value:
            child_env[name] = value

    # The gate is the only thing that changes.
    child_env["RUN_PRE_TOKEN_CHECK"] = "0"
    # The event delivery stays ON, so the second run produces the same
    # DETECTION side effects as the first one.
    child_env["RUN_LOGIN_EVENT_DELIVERY"] = "1"

    # The legacy single-database fallback stays OFF, so a missing
    # detection URL can never silently point the detection context at
    # the core schema.
    child_env["ALLOW_LEGACY_SINGLE_DB"] = "0"

    return child_env


#: The pattern uvicorn prints when it reports the port it bound.
#:
#: The comparison backend is started with ``--port 0``, so the OPERATING
#: SYSTEM picks a free port and uvicorn reports which one it got.  That
#: removes the race a probe would otherwise have: a port that was free
#: when the probe checked it can be taken by somebody else before the
#: child binds it, and a server that was already listening on that port
#: would answer the readiness probe while the probe's own child is still
#: starting up.
_UVICORN_PORT_PATTERN = re.compile(
    r"Uvicorn running on https?://[^:/]+:(\d+)"
)


class ComparisonBackend:
    """The comparison backend: a second API on the same databases.

    The backend is OWNED by the probe.  It records its own PID, it is
    only ever stopped through its own handle, and its readiness is
    proven by the fact that the CHILD ITSELF reported the port it bound
    — not by the fact that something answered on that port.
    """

    def __init__(self, process: "subprocess.Popen[str]", port: int) -> None:
        self.process = process
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        """Stop the backend and wait for it.

        Only THIS process is signalled.  The port is never used to find
        a process to kill, so another stack's server cannot be harmed.
        """
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - the escape hatch
            self.process.kill()
            self.process.wait(timeout=10)


def _start_backend_without_the_gate(env: Dict[str, str]) -> ComparisonBackend:
    """Start a SECOND backend on the same databases, with the gate OFF.

    The point of the A/B comparison is that BOTH runs talk to the same
    databases, with the same policy and the same history.  The ONLY
    difference is ``RUN_PRE_TOKEN_CHECK``.  Anything else would make the
    comparison meaningless.

    The backend is started with ``--port 0``, so the operating system
    picks a port that is free at that very moment and the child reports
    which one it got.  The probe therefore never talks to a server it
    did not start — a server that was already listening on the port
    cannot answer, because the child owns the port.

    :raises ProbeError: when the backend does not become ready.
    """
    child_env = _comparison_environment(env)

    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", "0", "--log-level", "info",
        ],
        cwd=REPO_ROOT,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    port: Optional[int] = None
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            if process.poll() is not None:
                break
            continue
        match = _UVICORN_PORT_PATTERN.search(line)
        if match:
            port = int(match.group(1))
            break

    if port is None:
        output = ""
        if process.stdout is not None:
            try:
                output = process.stdout.read() or ""
            except Exception:  # noqa: BLE001 - the output is best-effort
                output = ""
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()
        raise ProbeError(
            "the comparison backend did not report a port within 45 seconds"
            + (f":\n{output[:2000]}" if output else "")
        )

    # The child has bound the port and reported it, so the port belongs to
    # the child's own socket.  The readiness probe below therefore reaches
    # the probe's own backend.
    backend = ComparisonBackend(process, port)
    for _ in range(60):
        if process.poll() is not None:
            raise ProbeError(
                f"the comparison backend exited before it became ready "
                f"(exit code {process.returncode})"
            )
        try:
            response = httpx.get(f"{backend.base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return backend
        except Exception:  # noqa: BLE001 - the server is not up yet
            pass
        time.sleep(0.5)

    backend.stop()
    raise ProbeError("the comparison backend did not become ready within 30 seconds")


# ---------------------------------------------------------------------------
# The DETECTION evidence
# ---------------------------------------------------------------------------

class DetectionEvidence:
    """What the DETECTION engine recorded about one attempt.

    The probe reads this to show that the gated attempt really was
    scored by the demo policy with the expected rules — not merely that
    the two responses differed.
    """

    def __init__(
        self,
        attempt_id: Optional[str],
        policy_id: Optional[str],
        policy_version: Optional[str],
        rules: Set[str],
        decision: Optional[str],
        risk_level: Optional[str],
    ) -> None:
        self.attempt_id = attempt_id
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.rules = rules
        self.decision = decision
        self.risk_level = risk_level

    def describe(self) -> str:
        return (
            f"policy={self.policy_version or 'none'} "
            f"rules={','.join(sorted(self.rules)) or 'none'} "
            f"decision={self.decision or 'none'} "
            f"level={self.risk_level or 'none'}"
        )


def _read_detection_evidence(
    detection_url: URL,
    probe_ip: str,
    user_agent: str,
    after: datetime,
) -> DetectionEvidence:
    """Read the DETECTION evidence of the attempt the probe just made.

    The attempt is identified by the probe's own address and user agent
    AND by the moment the probe made the login, so the evidence belongs
    to the attempt under test and not to an earlier run that used the
    same address.

    The window is bounded on BOTH sides: an attempt older than the
    window is not this run's, and an attempt that has not been scored
    yet is not evidence either.
    """
    engine = _engine(detection_url)
    try:
        with engine.connect() as connection:
            attempt = connection.execute(
                text(
                    "SELECT id, policy_id, risk_level, detection_decision "
                    "FROM login_attempts "
                    "WHERE ip_address = :ip AND user_agent = :ua "
                    "AND created_at >= :after "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"ip": probe_ip, "ua": user_agent, "after": after},
            ).fetchone()

            if attempt is None:
                return DetectionEvidence(None, None, None, set(), None, None)

            attempt_id = str(attempt[0])
            policy_version = None
            if attempt[1]:
                row = connection.execute(
                    text("SELECT version FROM policies WHERE id = :id"),
                    {"id": attempt[1]},
                ).fetchone()
                policy_version = str(row[0]) if row is not None else None

            rules = {
                str(row[0])
                for row in connection.execute(
                    text(
                        "SELECT rule_name FROM detection_logs "
                        "WHERE login_attempt_id = :id AND stage = 'rule_evaluation' "
                        "AND rule_name IS NOT NULL"
                    ),
                    {"id": attempt_id},
                ).fetchall()
            }

            return DetectionEvidence(
                attempt_id=attempt_id,
                policy_id=str(attempt[1]) if attempt[1] else None,
                policy_version=policy_version,
                rules=rules,
                decision=str(attempt[3]) if attempt[3] else None,
                risk_level=str(attempt[2]) if attempt[2] else None,
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

#: The pattern that finds a credential inside a URL in an error message.
#:
#: An error raised by the DRIVER can carry the connection string, and the
#: connection string carries the password.  A cleanup error is printed by
#: the probe and lands in a CI log, so the credential is redacted before
#: the message is shown.
_CREDENTIAL_PATTERN = re.compile(
    r"(?P<scheme>[a-zA-Z0-9+]+://)(?P<user>[^:/@\s]+):(?P<password>[^@/\s]*)@"
)


def _redact(message: str) -> str:
    """Remove the password from a URL that appears in an error message.

    The scheme and the user stay — they are what makes the message
    readable — but the password is replaced by a fixed marker, so the
    message can be printed and logged safely.
    """
    return _CREDENTIAL_PATTERN.sub(
        lambda match: f"{match.group('scheme')}{match.group('user')}:<redacted>@",
        message,
    )


class ProbeState:
    """Everything the probe owns, and therefore everything it must undo.

    Each field is a SNAPSHOT: it is captured BEFORE the matching
    mutation, and it is only restored when it was actually captured.
    """

    def __init__(self) -> None:
        self.event_ids: List[str] = []
        self.policy: Optional[PolicySnapshot] = None
        self.mfa: Optional[MfaSnapshot] = None
        self.comparison: Optional[ComparisonBackend] = None
        #: The cleanup errors, in the order the cleanup steps ran.
        self.cleanup_errors: List[str] = []
        #: The login side effects the probe does NOT undo.
        self.retained: List[str] = []

    def record_cleanup_error(self, step: str, error: BaseException) -> None:
        """Record a cleanup failure without losing the main error.

        The message is redacted: a driver error can carry the connection
        string, and the connection string carries the password.
        """
        message = _redact(f"{type(error).__name__}: {error}")
        self.cleanup_errors.append(f"{step}: {message}")


def _cleanup(
    state: ProbeState,
    core_url: URL,
    detection_url: URL,
    username: str,
) -> None:
    """Undo everything the probe owns — every step, independently.

    Each step runs in its OWN ``try``, so a step that fails does not
    skip the steps that follow it.  A cleanup failure is recorded and
    reported, and it makes the OVERALL result fail — a run that could
    not clean up after itself is not a clean run.
    """
    steps: List[Tuple[str, Any]] = [
        ("stop the comparison backend", lambda: _stop_comparison(state)),
        ("remove the seeded risky history",
         lambda: _cleanup_risky_history(detection_url, state.event_ids)),
        ("restore the one-time MFA flag",
         lambda: _restore_one_time_mfa(core_url, username, state.mfa)),
        ("restore the policy in service",
         lambda: _restore_active_policy(detection_url, state.policy)),
    ]

    for name, step in steps:
        try:
            step()
        except Exception as error:  # noqa: BLE001 - every step must be tried
            state.record_cleanup_error(name, error)
            log(f"the cleanup step '{name}' FAILED: {type(error).__name__}: {error}")


def _stop_comparison(state: ProbeState) -> None:
    if state.comparison is None:
        return
    state.comparison.stop()
    state.comparison = None


#: The side effects the probe leaves behind, and how they are counted.
#:
#: Two REAL logins happen: one against the demo stack and one against
#: the comparison backend.  They are real traffic, so they leave real
#: rows behind — and the probe does NOT remove them.  The probe reports
#: them, so that its claim is never wider than what it actually did.
_RETAINED_EFFECTS: Tuple[Tuple[str, str, str], ...] = (
    (
        "the sessions of the demo account (core database)",
        "SELECT count(*) FROM sessions WHERE user_id = ("
        "SELECT id FROM users WHERE username = :u)",
        "core",
    ),
    (
        "the MFA transactions of the demo account (core database)",
        "SELECT count(*) FROM mfa_transactions WHERE user_id = ("
        "SELECT id FROM users WHERE username = :u)",
        "core",
    ),
    (
        "the login attempts the probe made (detection database)",
        "SELECT count(*) FROM login_attempts WHERE user_agent = :ua",
        "detection",
    ),
)


def _retained_side_effects(
    validated: Dict[str, URL], username: str
) -> List[str]:
    """Return the side effects the probe deliberately leaves behind.

    The probe does NOT delete them: they are the evidence of two real
    logins, and removing them would remove the very evidence the run
    produced.  It reports them instead, so the operator knows exactly
    what is left on the stack.

    The counts are the TOTALS the tables carry, not a difference the
    probe measured — the probe does not know how many of them it added,
    so it does not claim to.
    """
    reported: List[str] = []
    for description, statement, context in _RETAINED_EFFECTS:
        url = validated.get(context)
        if url is None:
            continue
        try:
            engine = _engine(url)
            try:
                with engine.connect() as connection:
                    count = connection.execute(
                        text(statement),
                        {"u": username, "ua": PROBE_UA},
                    ).scalar()
            finally:
                engine.dispose()
        except Exception:  # noqa: BLE001 - the report is best-effort
            continue
        reported.append(f"{description} — {count} row(s) in total")
    return reported


def main() -> int:
    env = _env()

    # --- the guard ------------------------------------------------------
    #
    # EVERY database URL is validated BEFORE a connection is opened and
    # BEFORE anything is written.  A refused target never reaches a
    # driver, never reaches the comparison backend and never reaches a
    # row.
    try:
        validated = _validated_urls(env)
    except DemoDatabaseRefusal as refusal:
        fail(
            f"the probe refuses to run against this target — [{refusal.layer}] "
            f"{refusal.reason}"
        )

    core_url = validated[Context.CORE]
    detection_url = validated[Context.DETECTION]
    log(
        "the guard validated the targets: "
        f"{core_url.database} (core), {detection_url.database} (detection)"
    )

    base_url = env.get("CORE_APP_URL") or env.get("DETECTION_URL") or ""
    if not base_url:
        fail("the demo environment does not define CORE_APP_URL")

    username = PROBE_USERNAME
    password = os.environ.get("DEMO_USER_PASSWORD", "").strip() or DEFAULT_DEMO_PASSWORD

    log(f"the demo stack is {base_url}")
    log(f"the probe logs in as {username!r}")

    state = ProbeState()

    # --- the account's id ------------------------------------------------
    engine = _engine(core_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT id FROM users WHERE username = :u"),
                {"u": username},
            ).fetchone()
    finally:
        engine.dispose()
    if row is None:
        fail(
            f"the demo account {username!r} does not exist. Seed the demo "
            f"fixtures first: python scripts/demo_seed_demo.py --seed"
        )
    user_id = str(row[0])

    # --- the address the login comes from ------------------------------
    #
    # It has to be an address the account has never used, or the
    # 'impossible_travel' rule does not trigger and the gate issues the
    # token for the right reason and the wrong proof.
    probe_ip = _pick_probe_ip(detection_url, user_id)

    # --- the risky history ----------------------------------------------
    state.event_ids = _seed_risky_history(detection_url, user_id, username)
    log(f"seeded {len(state.event_ids)} risky attempt(s) under {RISKY_IP}")
    log(f"the login under test comes from {probe_ip} (never used before)")

    main_error: Optional[BaseException] = None
    failed_checks = 0
    checks: List[Tuple[bool, str]] = []

    try:
        # --- the policy in service --------------------------------------
        state.policy = _ensure_demo_policy_active(detection_url)
        log(state.policy.describe())

        # --- the rate-limit counter --------------------------------------
        #
        # The browser suite logs in from the same loopback address, so it
        # leaves the counter of the login action well past its limit.  A
        # rate-limited probe would measure the limiter instead of the
        # gate.
        cleared = _clear_login_rate_limit(core_url, probe_ip)
        if cleared:
            log(f"cleared {cleared} login rate-limit counter(s) for {probe_ip}")

        # --- RUN 1: the gate ON (the demo stack) -------------------------
        state.mfa = _clear_one_time_mfa(core_url, username)
        if not state.mfa.captured:
            raise ProbeError(
                f"the one-time MFA flag of {username!r} could not be read, so "
                f"the probe cannot tell the gate's hold apart from the flag's "
                f"hold. The probe stops here rather than measure something it "
                f"cannot attribute."
            )

        # The moment the login is made bounds the window the DETECTION
        # evidence is read from, so the evidence belongs to THIS attempt.
        gated_from = datetime.now(timezone.utc) - timedelta(seconds=5)
        status_gated, body_gated = _login(base_url, username, password, probe_ip, PROBE_UA)
        gated_token = str(body_gated.get("access_token") or "")
        gated_mfa = bool(body_gated.get("mfa_required"))
        gated_evidence = _read_detection_evidence(
            detection_url, probe_ip, PROBE_UA, gated_from
        )
        log(
            f"RUN 1 (the gate ON):  status={status_gated} "
            f"token={'ISSUED' if gated_token else 'HELD'} "
            f"mfa_required={gated_mfa}  detection[{gated_evidence.describe()}]"
        )

        # --- RUN 2: the gate OFF (a second backend, same databases) ------
        #
        # RUN 1 set the one-time MFA flag of the account — that is what a
        # held token does — so the flag is cleared again.  Otherwise RUN 2
        # would be held by the FLAG, and the comparison would prove
        # nothing about the gate.
        state.mfa = _clear_one_time_mfa(core_url, username)

        ungated_from = datetime.now(timezone.utc) - timedelta(seconds=5)

        state.comparison = _start_backend_without_the_gate(env)
        log(
            f"the comparison backend is listening on {state.comparison.base_url} "
            f"(pid {state.comparison.process.pid})"
        )

        status_ungated, body_ungated = _login(
            state.comparison.base_url, username, password, probe_ip, PROBE_UA
        )
        ungated_token = str(body_ungated.get("access_token") or "")
        ungated_mfa = bool(body_ungated.get("mfa_required"))
        ungated_evidence = _read_detection_evidence(
            detection_url, probe_ip, PROBE_UA, ungated_from
        )
        log(
            f"RUN 2 (the gate OFF): status={status_ungated} "
            f"token={'ISSUED' if ungated_token else 'HELD'} "
            f"mfa_required={ungated_mfa}  detection[{ungated_evidence.describe()}]"
        )

        # --- the verdict --------------------------------------------------
        #
        # The DETECTION evidence is checked FIRST, because a difference
        # between two responses is only evidence about the gate when the
        # two runs really were scored the same way.  The checks below do
        # not use the token inequality as an independent proof of the
        # cause — they check that the gate's own contract held, and that
        # the detection evidence says WHY.
        checks = [
            (
                status_gated == 200,
                f"the gated login is answered with 200 (got {status_gated})",
            ),
            (
                gated_token == "",
                "the gated login is HELD: the response carries no access token",
            ),
            (
                gated_mfa,
                "the gated login demands an MFA challenge",
            ),
            (
                status_ungated == 200,
                f"the ungated login is answered with 200 (got {status_ungated})",
            ),
            (
                ungated_token != "",
                "the ungated login ISSUES an access token",
            ),
            (
                not ungated_mfa,
                "the ungated login does not demand an MFA challenge",
            ),
            (
                gated_evidence.policy_version == DEMO_POLICY_VERSION,
                f"the gated attempt was scored by the demo policy "
                f"{DEMO_POLICY_VERSION!r} (got "
                f"{gated_evidence.policy_version!r})",
            ),
            (
                set(EXPECTED_RULES) <= gated_evidence.rules,
                f"the gated attempt triggered the rules "
                f"{', '.join(EXPECTED_RULES)} (got "
                f"{', '.join(sorted(gated_evidence.rules)) or 'none'})",
            ),
            (
                gated_evidence.decision is not None,
                f"the gated attempt carries a DETECTION decision (got "
                f"{gated_evidence.decision!r})",
            ),
            (
                ungated_evidence.policy_version == DEMO_POLICY_VERSION,
                f"the ungated attempt was scored by the SAME demo policy "
                f"(got {ungated_evidence.policy_version!r})",
            ),
        ]

    except BaseException as error:  # noqa: BLE001 - the cleanup follows
        main_error = error
    finally:
        _cleanup(state, core_url, detection_url, username)
        state.retained = _retained_side_effects(validated, username)

    # --- the report ------------------------------------------------------
    print()
    print("=" * 74)
    failed = sum(1 for ok, _ in checks if not ok)
    for ok, description in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {description}")
    print("=" * 74)
    print(f"PRE-TOKEN PROBE: {len(checks) - failed} passed, {failed} failed")

    if state.retained:
        print()
        print("the side effects the probe does NOT undo (real login traffic):")
        for item in state.retained:
            print(f"  - {item}")

    if state.cleanup_errors:
        print()
        print("the cleanup did NOT complete — the run is not clean:", file=sys.stderr)
        for error in state.cleanup_errors:
            print(f"  {error}", file=sys.stderr)

    if main_error is not None:
        print()
        print("the probe could not complete its measurement:", file=sys.stderr)
        print(
            f"  {type(main_error).__name__}: {_redact(str(main_error))}",
            file=sys.stderr,
        )
        return 1

    if state.cleanup_errors:
        return 1

    if failed:
        print()
        print("the gate did NOT decide the outcome on its own:", file=sys.stderr)
        print(
            "  either the token was issued in both runs, or it was held in "
            "both runs.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
