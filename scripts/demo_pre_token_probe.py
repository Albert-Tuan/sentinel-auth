#!/usr/bin/env python
"""Sentinel Auth v3.3 — the pre-token detection gate probe.

THE QUESTION THIS PROBE ANSWERS
=================================

The M13 acceptance evidence proves the pre-token gate in two places that
both run against **disposable test databases**:

  * ``tests/test_full_system_e2e.py`` — the ASGI-routed, real-HTTP
    scenarios B and C;
  * ``tests/test_risk_gate.py`` — the unit tests of ``_pre_token_risk``.

Neither of them answers the question the demo actually needs answered:

    **On the running demo stack — with the REAL Detection policy, the
    REAL scoring and the REAL HTTP boundary — does the pre-token gate
    really hold the token back?**

That is what this probe measures, and it measures it the only honest
way: by running the SAME risky login twice, once with the gate ON and
once with the gate OFF, and comparing what the client received.

  * gate ON  -> the token must be HELD (``access_token == ""`` and
                ``mfa_required == true``);
  * gate OFF -> the token must be ISSUED (``access_token != ""``).

If both runs issued a token, the gate would not be load-bearing and the
demo would be showing a coincidence.  If both runs held the token, the
hold would have come from somewhere else — the persistent MFA flag, the
``admin_mfa_required`` flag — and the gate would not be load-bearing
either.  Only a DIFFERENCE between the two runs proves that the gate
is what made the decision.

WHAT IT TOUCHES
===============

Only the **demo** databases.  The script refuses to run against anything
whose name does not carry the ``_demo`` marker, exactly like
``scripts/demo_seed_demo.py`` does.  It writes:

  * a few ``login_attempts`` rows in the DETECTION database — the risky
    history the rules need.  They are marked with the
    ``m13-pre-token-probe`` marker and are removed again at the end;
  * the one-time MFA flag of ONE demo account, which it restores to the
    value it found.

It does NOT drop, truncate or delete any table, and it never touches a
``*_test`` or a production database.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import create_engine, text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
#: The marker every row this probe writes carries.
PROBE_MARKER = "m13-pre-token-probe"

#: The demo account the probe logs in as.
PROBE_USERNAME = "demo_user"

#: The password of the demo account.  The seed script falls back to this
#: constant when the environment does not supply one.
DEFAULT_DEMO_PASSWORD = "DemoPass!2026"

#: The IP the risky history is written under.  A documentation range
#: (RFC 5737), so it can never be a real client.
PROBE_IP = "203.0.113.77"

#: The user agent the risky history is written under.
PROBE_UA = "SentinelAuthPreTokenProbe/1.0"

#: The version of the demo's own policy — the one whose rules make a
#: risky login score ``high``.  The browser scenario E2E-05 activates a
#: policy of its own, which deactivates this one, so the probe has to
#: put it back in service before it scores anything.
DEMO_POLICY_VERSION = "m13-demo-active"


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


def _demo_database_name(url: str) -> str:
    """Return the database name of a URL, or an empty string."""
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).database or ""
    except Exception:  # noqa: BLE001 - an unparsable URL names nothing
        return ""


def _require_demo_databases(env: Dict[str, str]) -> None:
    """Refuse to run against anything that is not a demo database."""
    for name in ("CORE_DATABASE_URL", "DETECTION_DATABASE_URL"):
        database = _demo_database_name(env[name])
        if not database.endswith("_demo"):
            fail(
                f"{name} points at {database!r}, which does not carry the "
                f"'_demo' marker. The probe refuses to touch it — it must "
                f"only ever run against the demo stack's own databases."
            )


# ---------------------------------------------------------------------------
# The risky history
# ---------------------------------------------------------------------------

def _seed_risky_history(detection_url: str, user_id: str, username: str) -> List[str]:
    """Write the failed attempts that make the next login risky.

    Three failures in the last three minutes, from an IP the account has
    never used.  The demo stack's active policy scores both:

      * ``impossible_travel``  — ``ip_change_rate_7d >= 0.8``
      * ``multiple_failures``  — ``fail_count_24h >= 3``

    The probe writes the rows itself instead of failing the logins,
    because a failed login does not create the history the rules read:
    the attempt of the login under test is the one being scored.
    """
    engine = create_engine(detection_url, pool_pre_ping=True)
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
                        "ip": PROBE_IP,
                        "ua": PROBE_UA,
                        "ts": now - timedelta(minutes=minutes),
                    },
                )
    finally:
        engine.dispose()
    return event_ids


def _cleanup_risky_history(detection_url: str, event_ids: List[str]) -> int:
    """Remove the rows the probe wrote.  Only those rows."""
    if not event_ids:
        return 0
    engine = create_engine(detection_url, pool_pre_ping=True)
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


def _ensure_demo_policy_active(detection_url: str) -> Optional[str]:
    """Make the demo's own policy the one in service.

    Returns the id of the policy that WAS in service, when the probe had
    to change it — so the probe can put the stack back the way it found
    it — and ``None`` when the demo policy was already in service.

    The scoring reads the policy that carries ``is_active`` — there can
    only ever be ONE of them.  The browser scenario E2E-05 activates a
    policy of its own, and by the partial unique index that DEACTIVATES
    the demo's policy.  Its rules are milder, so with it in service the
    risky login is scored below the ``high`` threshold and the gate
    issues the token — which is a true statement about the policy, and
    a useless statement about the gate.

    So the probe puts the demo policy back in service before it scores
    anything.
    """
    engine = create_engine(detection_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            demo = connection.execute(
                text(
                    "SELECT id FROM policies WHERE version = :v"
                ),
                {"v": DEMO_POLICY_VERSION},
            ).fetchone()
            if demo is None:
                fail(
                    f"the demo policy {DEMO_POLICY_VERSION!r} does not exist. "
                    f"Seed the demo fixtures first: "
                    f"python scripts/demo_seed_demo.py --seed"
                )
            current = connection.execute(
                text("SELECT id FROM policies WHERE is_active IS TRUE")
            ).fetchone()
            if current is not None and str(current[0]) == str(demo[0]):
                return None
            previous_id = str(current[0]) if current is not None else None
            if current is not None:
                connection.execute(
                    text(
                        "UPDATE policies SET is_active = FALSE, "
                        "deactivated_at = :now WHERE id = :id"
                    ),
                    {"now": datetime.now(timezone.utc), "id": current[0]},
                )
            connection.execute(
                text(
                    "UPDATE policies SET is_active = TRUE, "
                    "activated_at = :now, deactivated_at = NULL WHERE id = :id"
                ),
                {"now": datetime.now(timezone.utc), "id": demo[0]},
            )
            return previous_id
    finally:
        engine.dispose()


def _clear_login_rate_limit(core_url: str, ip: str) -> int:
    """Clear the login rate-limit counter of the probe's client.

    The counter is a RATE LIMIT, not business state: clearing it does not
    hide a defect of the application — it removes the interference of the
    test client with a control that is designed for real traffic.  The
    risky attempts, the sessions and the one-time MFA flag are
    untouched.

    Only the rows of the probe's own address are removed; the limiter
    itself stays exactly as it is.
    """
    engine = create_engine(core_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            removed = connection.execute(
                text(
                    "DELETE FROM rate_limits "
                    "WHERE ip_address = :ip AND action = 'login'"
                ),
                {"ip": ip},
            ).rowcount
            return int(removed or 0)
    finally:
        engine.dispose()


def _restore_active_policy(
    detection_url: str, previous_policy_id: Optional[str]
) -> None:
    """Put the previously in-service policy back, if the probe changed it.

    The deactivate has to reach the database BEFORE the activate, because
    the partial unique index allows exactly one active policy — the same
    ordering the application's activation endpoint relies on.
    """
    if previous_policy_id is None:
        return
    engine = create_engine(detection_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE policies SET is_active = FALSE WHERE is_active IS TRUE")
            )
            connection.execute(
                text(
                    "UPDATE policies SET is_active = TRUE, "
                    "activated_at = :now, deactivated_at = NULL WHERE id = :id"
                ),
                {"now": datetime.now(timezone.utc), "id": previous_policy_id},
            )
    finally:
        engine.dispose()


def _clear_one_time_mfa(core_url: str, username: str) -> bool:
    """Return the one-time MFA flag to False and report its old value.

    The flag is the OTHER thing that can hold a token back, so it has to
    be out of the way — otherwise the probe cannot tell the two causes
    apart.
    """
    engine = create_engine(core_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT detection_mfa_once FROM users WHERE username = :u"),
                {"u": username},
            ).fetchone()
            if row is None:
                fail(f"the demo account {username!r} does not exist")
            previous = bool(row[0])
            connection.execute(
                text(
                    "UPDATE users SET detection_mfa_once = FALSE "
                    "WHERE username = :u"
                ),
                {"u": username},
            )
            return previous
    finally:
        engine.dispose()


def _restore_one_time_mfa(core_url: str, username: str, previous: bool) -> None:
    """Put the one-time MFA flag back the way the probe found it."""
    engine = create_engine(core_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE users SET detection_mfa_once = :flag "
                    "WHERE username = :u"
                ),
                {"flag": previous, "u": username},
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The second backend, with the gate OFF
# ---------------------------------------------------------------------------

def _start_backend_without_the_gate(
    env: Dict[str, str],
    port: int,
) -> "subprocess.Popen[bytes]":
    """Start a SECOND backend on the same databases, with the gate OFF.

    The point of the A/B comparison is that BOTH runs talk to the same
    databases, with the same policy and the same history.  The ONLY
    difference is ``RUN_PRE_TOKEN_CHECK``.  Anything else would make the
    comparison meaningless.
    """
    child_env = dict(os.environ)
    child_env.update(
        {
            "CORE_DATABASE_URL": env["CORE_DATABASE_URL"],
            "DETECTION_DATABASE_URL": env["DETECTION_DATABASE_URL"],
            "ML_DATABASE_URL": env.get("ML_DATABASE_URL", ""),
            "INTERNAL_SECRET": env["INTERNAL_SECRET"],
            # The gate is the only thing that changes.
            "RUN_PRE_TOKEN_CHECK": "0",
            # The event delivery stays ON, so the second run produces the
            # same DETECTION side effects as the first one.
            "RUN_LOGIN_EVENT_DELIVERY": "1",
            "DETECTION_URL": env.get("DETECTION_URL", ""),
            "MFA_SMTP_HOST": env.get("MFA_SMTP_HOST", "127.0.0.1"),
            "MFA_SMTP_PORT": env.get("MFA_SMTP_PORT", "1025"),
            "MFA_SMTP_LOG": env.get("MFA_SMTP_LOG", ""),
            "CORS_ALLOWED_ORIGINS": env.get("CORS_ALLOWED_ORIGINS", "*"),
            "FORWARDED_ALLOW_IPS": env.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        }
    )

    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=REPO_ROOT,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{base_url}/health", timeout=1.0).status_code == 200:
                return process
        except Exception:  # noqa: BLE001 - the server is not up yet
            pass
        if process.poll() is not None:
            output = (process.stdout.read() or b"").decode("utf-8", "replace")
            fail(f"the comparison backend exited early:\n{output[:2000]}")
        time.sleep(0.5)

    process.terminate()
    fail("the comparison backend did not become ready within 30 seconds")
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

def main() -> int:
    env = _env()
    _require_demo_databases(env)

    base_url = env.get("CORE_APP_URL") or env.get("DETECTION_URL") or ""
    if not base_url:
        fail("the demo environment does not define CORE_APP_URL")

    username = PROBE_USERNAME
    password = os.environ.get("DEMO_USER_PASSWORD", "").strip() or DEFAULT_DEMO_PASSWORD

    log(f"the demo stack is {base_url}")
    log(f"the probe logs in as {username!r}")

    core_url = env["CORE_DATABASE_URL"]
    detection_url = env["DETECTION_DATABASE_URL"]

    # --- the account's id ------------------------------------------------
    engine = create_engine(core_url, pool_pre_ping=True)
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

    # --- the risky history ----------------------------------------------
    event_ids = _seed_risky_history(detection_url, user_id, username)
    log(f"seeded {len(event_ids)} risky attempt(s) under {PROBE_IP}")

    # --- the policy in service ------------------------------------------
    #
    # The probe has to score against the demo's OWN policy.  The browser
    # scenario E2E-05 activates a policy of its own, and by the partial
    # unique index that deactivates the demo policy — the probe would
    # then measure the milder policy instead of the gate.
    previous_policy_id: Optional[str] = None
    previous_flag = False
    comparison_port = 58999
    comparison = None
    try:
        # --- the policy in service --------------------------------------
        #
        # The probe has to score against the demo's OWN policy.  The
        # browser scenario E2E-05 activates a policy of its own, and by
        # the partial unique index that deactivates the demo policy — the
        # probe would then measure the milder policy instead of the
        # gate.
        previous_policy_id = _ensure_demo_policy_active(detection_url)
        if previous_policy_id is not None:
            log(
                f"the demo policy {DEMO_POLICY_VERSION!r} was not in service; "
                f"the probe put it back and will restore the stack afterwards"
            )

        # --- the rate-limit counter --------------------------------------
        #
        # The browser suite logs in from the same loopback address, so it
        # leaves the counter of the login action well past its limit.  A
        # rate-limited probe would measure the limiter instead of the
        # gate.
        cleared = _clear_login_rate_limit(core_url, PROBE_IP)
        if cleared:
            log(f"cleared {cleared} login rate-limit counter(s) for {PROBE_IP}")

        # --- RUN 1: the gate ON (the demo stack) -------------------------
        previous_flag = _clear_one_time_mfa(core_url, username)
        status_gated, body_gated = _login(
            base_url, username, password, PROBE_IP, PROBE_UA
        )
        gated_token = str(body_gated.get("access_token") or "")
        gated_mfa = bool(body_gated.get("mfa_required"))
        log(
            f"RUN 1 (the gate ON):  status={status_gated} "
            f"token={'ISSUED' if gated_token else 'HELD'} "
            f"mfa_required={gated_mfa}"
        )

        # --- RUN 2: the gate OFF (a second backend, same databases) ------
        #
        # RUN 1 set the one-time MFA flag of the account — that is what a
        # held token does — so the flag is cleared again.  Otherwise RUN 2
        # would be held by the FLAG, and the comparison would prove
        # nothing about the gate.
        _clear_one_time_mfa(core_url, username)

        comparison = _start_backend_without_the_gate(env, comparison_port)
        status_ungated, body_ungated = _login(
            f"http://127.0.0.1:{comparison_port}",
            username,
            password,
            PROBE_IP,
            PROBE_UA,
        )
        ungated_token = str(body_ungated.get("access_token") or "")
        ungated_mfa = bool(body_ungated.get("mfa_required"))
        log(
            f"RUN 2 (the gate OFF): status={status_ungated} "
            f"token={'ISSUED' if ungated_token else 'HELD'} "
            f"mfa_required={ungated_mfa}"
        )

        # --- the verdict --------------------------------------------------
        checks: List[Tuple[bool, str]] = [
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
                gated_token != ungated_token,
                "the gate is LOAD-BEARING: the two runs differ only because of "
                "the pre-token gate",
            ),
        ]

        print()
        print("=" * 74)
        failed = 0
        for ok, description in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {description}")
            if not ok:
                failed += 1
        print("=" * 74)
        print(
            f"PRE-TOKEN PROBE: {len(checks) - failed} passed, {failed} failed"
        )

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

    finally:
        if comparison is not None:
            comparison.terminate()
            try:
                comparison.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                comparison.kill()
        removed = _cleanup_risky_history(detection_url, event_ids)
        log(f"removed {removed} risky attempt(s) the probe wrote")
        _restore_one_time_mfa(core_url, username, previous_flag)
        log("the one-time MFA flag was restored")
        _restore_active_policy(detection_url, previous_policy_id)
        if previous_policy_id is not None:
            log("the policy in service was restored")


if __name__ == "__main__":
    raise SystemExit(main())
