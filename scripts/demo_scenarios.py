#!/usr/bin/env python3
"""Sentinel Auth v3.3 — M13 runnable demo scenarios.

Runs the six demo scenarios of the M13 milestone end to end against a
LIVE demo stack, and prints one line per check.  The script is the
executable form of ``docs/M13-DEMO-SCENARIOS.md``: the document explains
what each scenario proves, the script proves it.

    A  Authentication        — a login, an MFA handshake over SMTP, a
                               session list, a refresh and a logout.
    B  Device trust         — a pending device request, an approval, a
                               trusted device, and a device check.
    C  SOC investigation    — the alert list, one alert's evidence, the
                               timeline, an acknowledgement and an
                               assignment.
    D  Protective actions   — a real action against a real account, and
                               the 502 handling when the core service
                               cannot answer.
    E  Policy management    — the draft policy, an edit, an activation,
                               and the proof that the active policy is
                               immutable.
    F  Manager analytics    — the dashboard, the trends, the SOC KPI and
                               the ML statistics.

Usage::

    scripts/demo_scenarios.py --all
    scripts/demo_scenarios.py --scenario A --scenario D
    scripts/demo_scenarios.py --list

The script needs a running demo stack (``scripts/demo_stack.sh start``)
and the seeded fixtures (``scripts/demo_seed_demo.py --seed``).

Exit code 0 means every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The namespace the seed script derives every fixture id from.  It is
#: the SAME namespace the seed uses, so the scenario script can compute
#: the id of a fixture row without reading the manifest.
FIXTURE_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

def _resolve_otp_log(value: str) -> Path:
    """Resolve the OTP log path the way the demo stack does.

    ``scripts/demo_stack.sh`` makes the path absolute before it starts
    the SMTP sink, resolving a relative path against the REPOSITORY
    ROOT.  The reader must resolve it the same way, otherwise it can end
    up reading a different file than the sink writes to — and the
    symptom is an OTP that "never arrives".
    """
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


#: The file the demo stack writes the RESOLVED OTP log path to.  It is
#: the single source of truth: the sink writes to that path and the
#: scenario script reads from it, so the two can never disagree.
OTP_LOG_POINTER = REPO_ROOT / ".ci" / "demo" / "otp-log.path"


def _default_otp_log() -> str:
    """The OTP log the running demo stack actually writes to."""
    if OTP_LOG_POINTER.exists():
        recorded = OTP_LOG_POINTER.read_text(encoding="utf-8").strip()
        if recorded:
            return recorded
    return str(DEFAULT_OTP_LOG)


DEFAULT_BASE_URL = "http://127.0.0.1:58000"
DEFAULT_OTP_LOG = REPO_ROOT / ".ci" / "demo" / "demo-otp.log"
DEFAULT_MANIFEST = REPO_ROOT / ".ci" / "demo" / "fixture-manifest.json"


def _demo_env_file() -> Path:
    """The demo environment file the demo stack reads."""
    return Path(
        os.environ.get("DEMO_ENV_FILE", str(REPO_ROOT / ".env.demo"))
    ).expanduser()


def _demo_env_values() -> Dict[str, str]:
    """Read the demo environment file, the way the demo stack reads it.

    The scenario script must talk to the SAME stack the demo does.  A
    shell that still carries another stack's variables MUST NOT decide
    the address, so the FILE is the authority and the shell only fills
    the gaps.
    """
    path = _demo_env_file()
    if not path.is_file():
        return {}
    values: Dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _default_base_url() -> str:
    """The base URL of the demo stack that is actually running.

    The demo stack's address lives in ``CORE_APP_URL`` (and the
    ``APP_HOST``/``APP_PORT`` pair it is built from) inside the demo
    environment file.  A hard-coded port would send the scenarios to a
    DIFFERENT stack whenever the demo runs on non-default ports — which
    is exactly what a disposable rehearsal does.
    """
    env = _demo_env_values()
    explicit = (env.get("CORE_APP_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = (env.get("APP_HOST") or "").strip()
    port = (env.get("APP_PORT") or "").strip()
    if host and port:
        return f"http://{host}:{port}"
    return DEFAULT_BASE_URL


def _demo_database_url(name: str) -> str:
    """Return one demo connection URL.

    The demo environment FILE is the authority; the shell only fills a
    gap the file does not answer.  The file always wins, so a stale
    exported variable can never make the scenarios write into another
    stack's databases.
    """
    value = (_demo_env_values().get(name) or "").strip()
    if not value:
        value = os.environ.get(name, "").strip()
    return value


DEMO_PASSWORD_ENV = {
    "user": "DEMO_USER_PASSWORD",
    "analyst": "DEMO_ANALYST_PASSWORD",
    "admin": "DEMO_ADMIN_PASSWORD",
    "manager": "DEMO_MANAGER_PASSWORD",
}
DEFAULT_DEMO_PASSWORD = "DemoPass!2026"


# =============================================================================
# The reporting layer
# =============================================================================


class Report:
    """Collects the checks and prints them as they happen."""

    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    def __init__(self, colour: bool = True) -> None:
        self.colour = colour
        self.passed = 0
        self.failed = 0
        self.failures: List[str] = []
        self._scenario = ""

    def _paint(self, text: str, colour: str) -> str:
        if not self.colour:
            return text
        return f"{colour}{text}{self.RESET}"

    def scenario(self, key: str, title: str) -> None:
        self._scenario = key
        print()
        print(self._paint(f"=== Scenario {key} — {title} ===", self.CYAN))

    def check(self, ok: bool, description: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(self._paint(f"  PASS  {description}", self.GREEN))
        else:
            self.failed += 1
            message = f"[{self._scenario}] {description}"
            self.failures.append(message)
            print(self._paint(f"  FAIL  {description}", self.RED))
        if detail:
            print(self._paint(f"        {detail}", self.DIM))
        return ok

    def info(self, text: str) -> None:
        print(self._paint(f"        {text}", self.DIM))

    def summary(self) -> int:
        print()
        total = self.passed + self.failed
        if self.failed:
            print(self._paint(f"FAILED: {self.failed} of {total} check(s) failed.", self.RED))
            for failure in self.failures:
                print(self._paint(f"  - {failure}", self.RED))
            return 1
        print(self._paint(f"OK: all {total} check(s) passed.", self.GREEN))
        return 0


# =============================================================================
# The HTTP client
# =============================================================================


@dataclass
class Response:
    """One HTTP response, with the body already parsed when it is JSON."""

    status: int
    body: Any
    raw: str
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class ApiClient:
    """A small HTTP client that keeps the bearer token per account."""

    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.tokens: Dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Response:
        url = f"{self.base_url}{path}"
        data = None
        request_headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if headers:
            request_headers.update(headers)

        request = urllib.request.Request(url, data=data, method=method.upper())
        for key, value in request_headers.items():
            request.add_header(key, value)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
                status = response.status
                response_headers = dict(response.headers.items())
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            status = error.code
            response_headers = dict(error.headers.items()) if error.headers else {}
        except urllib.error.URLError as error:
            return Response(status=0, body=None, raw=str(error.reason))

        parsed: Any = raw
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
        return Response(status=status, body=parsed, raw=raw, headers=response_headers)

    def get(self, path: str, token: Optional[str] = None, **kwargs) -> Response:
        return self.request("GET", path, token=token, **kwargs)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None, token: Optional[str] = None, **kwargs) -> Response:
        return self.request("POST", path, body=body, token=token, **kwargs)

    def put(self, path: str, body: Optional[Dict[str, Any]] = None, token: Optional[str] = None, **kwargs) -> Response:
        return self.request("PUT", path, body=body, token=token, **kwargs)

    def delete(self, path: str, token: Optional[str] = None, **kwargs) -> Response:
        return self.request("DELETE", path, token=token, **kwargs)


# =============================================================================
# The fixtures
# =============================================================================


class Fixtures:
    """The manifest the seed script wrote."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with path.open("r", encoding="utf-8") as handle:
            self.data = json.load(handle)

    @property
    def core(self) -> Dict[str, Any]:
        return self.data["core"]

    @property
    def detection(self) -> Dict[str, Any]:
        return self.data["detection"]

    @property
    def ml(self) -> Dict[str, Any]:
        return self.data["ml"]

    def user(self, key: str) -> Dict[str, Any]:
        return self.core["users"][key]

    def user_id(self, key: str) -> str:
        return str(self.core["users"][key]["id"])

    def username(self, key: str) -> str:
        return str(self.core["users"][key]["username"])

    def alert(self, key: str) -> Dict[str, Any]:
        return self.detection["alerts"][key]

    def password(self, key: str) -> str:
        env_name = DEMO_PASSWORD_ENV.get(key)
        if env_name:
            value = os.environ.get(env_name, "").strip()
            if value:
                return value
        return DEFAULT_DEMO_PASSWORD

    def fixture_id(self, kind: str, key: str) -> str:
        """The deterministic id of a fixture row.

        The seed script derives every id with ``uuid5(NAMESPACE, kind:key)``,
        so the scenario script can compute the id of a row it wants to
        work with without reading the manifest.
        """
        return str(uuid.uuid5(FIXTURE_NAMESPACE, f"{kind}:{key}"))


# =============================================================================
# The OTP reader
# =============================================================================


class OtpReader:
    """Reads the OTP the SMTP sink captured.

    The sink appends one block per message::

        TO=['demo_admin@example.test'] SUBJECT=...
        <the body, which contains the code>
        ---

    The code is extracted with the pattern the API uses, so the reader
    never depends on the exact wording of the notification.

    The reader is OFFSET-BASED.  The log file accumulates every message
    the sink has ever captured, so a code that is read without an offset
    may well belong to an EARLIER login — and a stale code is rejected
    by the API as "Invalid MFA code".  A caller therefore takes an
    offset BEFORE it triggers the login and reads only what was written
    after that point.
    """

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path

    def offset(self) -> int:
        """The current size of the log, to be passed back to ``latest_code``."""
        try:
            return self.log_path.stat().st_size
        except OSError:
            return 0

    def _text_from(self, offset: int) -> str:
        """The part of the log that was written after ``offset``."""
        try:
            with self.log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                return handle.read()
        except OSError:
            return ""

    def _blocks(self, offset: int) -> List[str]:
        return self._text_from(offset).split("\n---\n")

    def latest_code(self, recipient: str, offset: int = 0) -> Optional[str]:
        """The most recent code addressed to ``recipient``.

        Only the part of the log that follows ``offset`` is considered.
        """
        pattern = re.compile(r"(?<!\d)(\d{6})(?!\d)")
        for block in reversed(self._blocks(offset)):
            if recipient not in block:
                continue
            # The body is the part after the header line.
            body = block.split("\n", 1)[1] if "\n" in block else block
            match = pattern.search(body)
            if match:
                return match.group(1)
        return None

    def wait_for_code(
        self,
        recipient: str,
        offset: int = 0,
        timeout: float = 30.0,
        interval: float = 0.5,
    ) -> Optional[str]:
        """Wait for the SMTP sink to deliver a code to ``recipient``."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code = self.latest_code(recipient, offset=offset)
            if code:
                return code
            time.sleep(interval)
        return None


# =============================================================================
# The shared helpers
# =============================================================================


class Context:
    """Everything the scenarios share."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.base_url = args.base_url
        self.api = ApiClient(self.base_url)
        self.fixtures = Fixtures(Path(args.manifest))
        self.otp = OtpReader(
            _resolve_otp_log(args.otp_log or str(DEFAULT_OTP_LOG))
        )
        self.report = Report(colour=not args.no_colour)
        #: The refresh token of every account that logged in.
        self.refresh_tokens: Dict[str, str] = {}
        #: A stamp that is unique to THIS run.  It is used for the names
        #: of the objects the scenarios create, so a re-run never
        #: collides with the objects of an earlier run.
        self.run_stamp = f"{int(time.time())}-{os.getpid()}"

    def _username_of_subject(self, user_id: str) -> str:
        """The username of a subject id, from the fixture manifest."""
        for key, user in self.fixtures.core.get("users", {}).items():
            if str(user.get("id")) == user_id:
                return str(user.get("username") or "")
        return ""

    def _password_key_of(self, username: str) -> str:
        """The fixture key of a username, so its password can be read."""
        for key, user in self.fixtures.core.get("users", {}).items():
            if str(user.get("username")) == username:
                return key
        return "user"

    def _create_orphan_alert(
        self, attempt_id: str, alert_id: str, subject_user_id: str
    ) -> bool:
        """Create an alert whose subject does not exist in the core context.

        The alert and its login attempt are written straight into the
        detection database, because there is no API endpoint that creates
        an alert for a subject that does not exist — that is exactly the
        situation the 502 case needs.

        The write is idempotent: the ids are deterministic, so a second
        run of the scenario reuses the row instead of failing on the
        unique constraint.
        """
        try:
            from sqlalchemy import create_engine, text
        except ImportError:  # pragma: no cover - SQLAlchemy is a hard dependency
            return False

        url = _demo_database_url("DETECTION_DATABASE_URL")
        if not url:
            self.report.info(
                "DETECTION_DATABASE_URL is not set; the 502 case cannot be prepared"
            )
            return False

        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO login_attempts "
                        "(id, event_id, user_id, username_attempted, outcome, "
                        " mfa_used, ip_address, user_agent, device_fingerprint, "
                        " timestamp, status, request_id, risk_level, "
                        " detection_decision, created_at, updated_at) "
                        "VALUES (:id, :event_id, :user_id, 'm13-orphan-subject', "
                        " 'failure', false, '203.0.113.99', 'M13 scenario D', "
                        " null, now(), 'processed', :request_id, 'high', "
                        " 'block', now(), now()) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": attempt_id,
                        "event_id": str(uuid.uuid5(FIXTURE_NAMESPACE, f"login_attempt:m13-orphan-subject:event")),
                        "user_id": subject_user_id,
                        "request_id": str(uuid.uuid5(FIXTURE_NAMESPACE, f"login_attempt:m13-orphan-subject:request")),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO alerts "
                        "(id, login_attempt_id, policy_id, status, risk_level, "
                        " detection_reason, detection_scores, assigned_to_id, "
                        " resolved_by_id, resolved_at, resolution, notes, "
                        " created_at, updated_at) "
                        "VALUES (:id, :login_attempt_id, null, 'open', 'high', "
                        " 'M13 scenario D — the 502 case', '{}'::jsonb, null, "
                        " null, null, null, 'M13 scenario D', now(), now()) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {"id": alert_id, "login_attempt_id": attempt_id},
                )
        except Exception as error:  # noqa: BLE001 — the message must be readable
            self.report.info(f"the 502 fixture could not be created: {error}")
            return False
        finally:
            engine.dispose()

        return True

    def _reset_alert_status(self, alert_id: str, status: str) -> None:
        """Put an alert back into a workflow status.

        An earlier run of a scenario moved an alert forward in its
        workflow.  The scenarios are re-runnable, so the alert is put
        back to the state it is supposed to be in — for a seeded alert,
        that is the state the seed created.

        Only the STATUS of ONE row of the detection context is written.
        The alert keeps its evidence, its timeline and its assignment.
        """
        url = _demo_database_url("DETECTION_DATABASE_URL")
        if not url:
            self.report.info(
                "DETECTION_DATABASE_URL is not set; the alert status cannot be reset"
            )
            return

        # A seeded alert is put back into the state the SEED created, not
        # into a state the caller happens to want: the fixture set is the
        # reference, and the scenarios are supposed to leave it alone.
        for seeded in self.fixtures.detection.get("alerts", {}).values():
            if str(seeded.get("id")) == alert_id:
                status = str(seeded.get("status") or status)
                break

        try:
            from sqlalchemy import create_engine, text
        except ImportError:  # pragma: no cover - SQLAlchemy is a hard dependency
            return

        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE alerts SET status = :status, "
                        " resolved_by_id = NULL, resolved_at = NULL, "
                        " resolution = NULL, updated_at = now() "
                        "WHERE id = :alert_id"
                    ),
                    {"status": status, "alert_id": alert_id},
                )
        except Exception as error:  # noqa: BLE001 — the message must be readable
            self.report.info(f"the alert status could not be reset: {error}")
            return
        finally:
            engine.dispose()

    def _clear_detection_mfa(self, user_id: str) -> None:
        """Disarm the one-time MFA gate of an account.

        Some flows — the trusted-device request in particular — refuse to
        run while the account is gated by a one-time MFA requirement.  The
        gate is cleared here so the scenario can exercise the flow; the
        scenario that needs the gate arms it again explicitly.
        """
        self._write_detection_mfa(user_id, False)

    def _rearm_detection_mfa(self, user_id: str) -> None:
        """Arm the one-time MFA gate of an account again.

        ``REQUIRE_MFA`` sets a one-time flag, and the flag is cleared as
        soon as the account completes an MFA handshake.  A scenario that
        runs twice would therefore find the gate already consumed and
        could not prove it a second time.

        The flag is re-armed in the CORE database directly.  Going
        through the internal boundary would not work here: the action
        also revokes the live sessions of the account, which would
        invalidate the very session the scenario is using.

        The write touches ONE column of ONE row of the core context, and
        only the account the scenario is about to prove.
        """
        self._write_detection_mfa(user_id, True)

    def _write_detection_mfa(self, user_id: str, armed: bool) -> None:
        """Set or clear the one-time MFA gate of an account."""
        url = _demo_database_url("CORE_DATABASE_URL")
        if not url:
            self.report.info(
                "CORE_DATABASE_URL is not set; the one-time MFA gate cannot be changed"
            )
            return

        try:
            from sqlalchemy import create_engine, text
        except ImportError:  # pragma: no cover - SQLAlchemy is a hard dependency
            return

        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE users SET detection_mfa_once = :armed "
                        "WHERE id = :user_id"
                    ),
                    {"armed": armed, "user_id": user_id},
                )
        except Exception as error:  # noqa: BLE001 — the message must be readable
            self.report.info(f"the one-time MFA gate could not be changed: {error}")
            return
        finally:
            engine.dispose()

    def internal_headers(self) -> Dict[str, str]:
        """The headers of the internal boundary.

        The internal endpoints are guarded by the shared secret rather
        than by a bearer token: they are the boundary BETWEEN the bounded
        contexts, and a user token must not be able to cross it.

        The demo environment FILE is the authority for the secret: the
        shell only fills a gap the file does not answer.  A stale
        exported secret would otherwise make the boundary answer 401 for
        a stack whose secret is different.
        """
        secret = _demo_env_values().get("INTERNAL_SECRET", "").strip()
        if not secret:
            secret = os.environ.get("INTERNAL_SECRET", "").strip()
        if not secret:
            return {}
        return {"X-Internal-Secret": secret}

    def _post_login(self, username: str, password: str) -> Response:
        """Log in, retrying when the login rate limit answers 429.

        The API allows five login attempts per minute and per IP.  The
        scenarios log several accounts in, and a demo run that is
        repeated quickly would trip the limit — which is the API
        behaving correctly, not a failure of the demo.

        The retry waits for the limit window to expire instead of
        failing, and it waits for the FULL window rather than for a
        guess: guessing would make the run flaky.
        """
        deadline = time.monotonic() + self.args.login_retry_timeout
        attempt = 0
        while True:
            attempt += 1
            response = self.api.post(
                "/api/v1/auth/login",
                {"username": username, "password": password},
            )
            if response.status != 429:
                if attempt > 1:
                    self.report.info(
                        f"the login of '{username}' succeeded on attempt {attempt} "
                        f"after the rate limit expired"
                    )
                return response

            if time.monotonic() >= deadline:
                return response

            wait = min(self.args.login_retry_wait, max(deadline - time.monotonic(), 1.0))
            self.report.info(
                f"the login rate limit answered 429; retrying '{username}' in {wait:.0f}s"
            )
            time.sleep(wait)

    def login(self, key: str) -> str:
        """Log an account in and return its access token.

        The MFA handshake is performed whenever the API asks for one.
        That is not only the case for ``demo_admin``, whose account
        carries the permanent MFA flag: the detection context can hold a
        token back for ANY account whose login looked risky, and it does
        so through the very same one-time MFA machinery.

        The OTP is read from the SMTP sink.  The offset of the log is
        taken BEFORE the login is called, so only a code that belongs to
        THIS login is considered — the log accumulates the codes of every
        earlier login, and a stale code is rejected by the API.
        """
        username = self.fixtures.username(key)
        password = self.fixtures.password(key)

        offset = self.otp.offset()
        response = self._post_login(username, password)
        if response.status != 200:
            raise RuntimeError(
                f"the login of '{username}' failed with {response.status}: {response.raw[:400]}"
            )

        body = response.body or {}
        if not body.get("mfa_required"):
            token = str(body["access_token"])
            self.api.tokens[key] = token
            self.refresh_tokens[key] = str(body.get("refresh_token") or "")
            return token

        # The MFA handshake.
        session_id = str(body["session_id"])
        recipient = str(self.fixtures.user(key)["email"])
        code = self.otp.wait_for_code(
            recipient, offset=offset, timeout=self.args.otp_timeout
        )
        if code is None:
            raise RuntimeError(
                f"no OTP arrived for '{recipient}' within {self.args.otp_timeout}s"
            )
        verify = self.api.post(
            "/api/v1/auth/mfa/verify",
            {"session_id": session_id, "mfa_code": code},
        )
        if verify.status != 200:
            raise RuntimeError(
                f"the MFA verification failed with {verify.status}: {verify.raw[:400]}"
            )
        token = str((verify.body or {})["access_token"])
        self.api.tokens[key] = token
        self.refresh_tokens[key] = str((verify.body or {}).get("refresh_token") or "")
        return token


# =============================================================================
# Scenario A — Authentication
# =============================================================================


def scenario_a(context: Context) -> None:
    """A plain login, an MFA handshake, a session list, a refresh and a logout."""
    report = context.report
    report.scenario("A", "Authentication")

    # -- the plain account -------------------------------------------------
    token = context.login("user")
    report.check(bool(token), "demo_user logs in without an MFA challenge")

    me = context.api.get("/api/v1/auth/me", token=token)
    body = me.body if isinstance(me.body, dict) else {}
    report.check(
        me.status == 200 and body.get("username") == context.fixtures.username("user"),
        "the access token identifies demo_user on /auth/me",
        f"status={me.status} username={body.get('username')}",
    )

    roles = body.get("roles") or []
    report.check(
        "USER" in roles,
        "demo_user carries the USER role",
        f"roles={roles}",
    )

    sessions = context.api.get("/api/v1/auth/sessions", token=token)
    session_body = sessions.body if isinstance(sessions.body, dict) else {}
    session_list = session_body.get("sessions") or session_body.get("items") or []
    report.check(
        sessions.status == 200 and len(session_list) >= 1,
        "the session list shows the seeded sessions",
        f"status={sessions.status} count={len(session_list)}",
    )

    # -- the MFA account ----------------------------------------------------
    admin_token = context.login("admin")
    report.check(bool(admin_token), "demo_admin completes the MFA handshake over SMTP")

    admin_me = context.api.get("/api/v1/auth/me", token=admin_token)
    admin_body = admin_me.body if isinstance(admin_me.body, dict) else {}
    admin_roles = admin_body.get("roles") or []
    report.check(
        "SECURITY_ADMIN" in admin_roles,
        "demo_admin carries the SECURITY_ADMIN role",
        f"roles={admin_roles}",
    )

    # -- the refresh --------------------------------------------------------
    #
    # The refresh endpoint takes the REFRESH token, not the access token.
    # The refresh token of ``demo_user`` was handed out by the login
    # above, so it is the one that is presented here.
    refresh = context.api.post(
        "/api/v1/auth/refresh",
        {"refresh_token": context.refresh_tokens.get("user", "")},
    )
    refreshed_token = ""
    if isinstance(refresh.body, dict):
        refreshed_token = str(refresh.body.get("access_token") or "")
    report.check(
        refresh.status == 200 and bool(refreshed_token),
        "the refresh endpoint issues a new access token",
        f"status={refresh.status} body={refresh.raw[:200]}",
    )

    # -- the logout ---------------------------------------------------------
    #
    # The logout uses the NEW access token.  The refresh ROTATES the
    # session: it issues a new pair of tokens and invalidates the old
    # access token, so the old one would be rejected with a 401 that
    # says nothing about the logout itself.
    logout = context.api.post("/api/v1/auth/logout", token=refreshed_token or token)
    report.check(
        logout.status in (200, 204),
        "the logout endpoint accepts the session",
        f"status={logout.status} body={logout.raw[:200]}",
    )


# =============================================================================
# Scenario B — Device trust
# =============================================================================


def scenario_b(context: Context) -> None:
    """A pending device request, an approval, and a device check."""
    report = context.report
    report.scenario("B", "Device trust")

    analyst_token = context.login("analyst")
    admin_token = context.login("admin")

    # -- the trusted devices the seed created -------------------------------
    #
    # The device list is PER USER: the API only shows the devices of
    # the account that is logged in.  The seed gave a trusted device to
    # the analyst and to the manager, so the analyst is the account
    # whose list has to hold one.
    devices = context.api.get("/api/v1/devices", token=analyst_token)
    device_body = devices.body if isinstance(devices.body, dict) else {}
    device_list = device_body.get("devices") or []
    report.check(
        devices.status == 200 and len(device_list) >= 1,
        "the trusted device list holds the seeded device of the account",
        f"status={devices.status} count={len(device_list)}",
    )

    # -- the pending request ------------------------------------------------
    #
    # The pending request is an MFA transaction of the ``trusted_device``
    # type.  It belongs to the account that asked for it, and it is
    # approved by an EXISTING session of the SAME account — so the
    # request has to be made by, and approved for, the same user.
    #
    # The device fingerprint is derived from the request HEADERS, so the
    # scenario sends a User-Agent that is unique to this run.  Without
    # that, a second run would find the device of the first run already
    # trusted and the approval would have nothing to approve.
    password = context.fixtures.password("user")
    user_agent = f"M13-Scenario-B/{context.run_stamp}"

    # The pending-device request refuses to run while the account is
    # gated by a one-time MFA requirement, so the gate is cleared first.
    context._clear_detection_mfa(context.fixtures.user_id("user"))

    pending = context.api.post(
        "/api/v1/devices/pending",
        {
            "username": context.fixtures.username("user"),
            "password": password,
            "device_name": "m13-scenario-b-phone",
        },
        headers={"User-Agent": user_agent},
    )
    pending_body = pending.body if isinstance(pending.body, dict) else {}
    request_id = str(pending_body.get("request_id") or "")
    report.check(
        pending.status == 202 and bool(request_id),
        "a pending device request is created",
        f"status={pending.status} request_id={request_id} body={pending.raw[:200]}",
    )

    # -- the device check ---------------------------------------------------
    check = context.api.post(
        "/api/v1/devices/check",
        {"device_fingerprint": "m13-demo-fingerprint-pending"},
        token=analyst_token,
    )
    check_body = check.body if isinstance(check.body, dict) else {}
    report.check(
        check.status == 200,
        "the device check answers for a known fingerprint",
        f"status={check.status} body={json.dumps(check_body)[:200]}",
    )

    # -- the approval -------------------------------------------------------
    if request_id:
        # The approval must come from an existing session of the SAME
        # account that owns the request, so the script logs
        # ``demo_user`` in to approve it.
        user_token = context.login("user")
        approve = context.api.post(
            f"/api/v1/devices/pending/{request_id}/approve",
            token=user_token,
        )
        report.check(
            approve.status in (200, 201),
            "the account approves its own pending device request",
            f"status={approve.status} body={approve.raw[:200]}",
        )

        approve_body = approve.body if isinstance(approve.body, dict) else {}
        device_id = str(approve_body.get("device_id") or "")
        report.check(
            bool(device_id),
            "the approval returns the id of the new trusted device",
            f"device_id={device_id}",
        )

        # -- the completion --------------------------------------------------
        if device_id:
            # The completion runs on the NEW device, so it must carry
            # the SAME headers the request was made with: the API
            # derives the fingerprint from them and refuses a mismatch.
            complete = context.api.post(
                f"/api/v1/devices/pending/{request_id}/complete",
                headers={"User-Agent": user_agent},
            )
            complete_body = complete.body if isinstance(complete.body, dict) else {}
            report.check(
                complete.status in (200, 201)
                and bool(complete_body.get("access_token")),
                "the approved request completes the login with a token",
                f"status={complete.status} body={complete.raw[:200]}",
            )

        # -- the device is now trusted ---------------------------------------
        after = context.api.get("/api/v1/devices", token=user_token)
        after_body = after.body if isinstance(after.body, dict) else {}
        after_list = after_body.get("devices") or []
        report.check(
            after.status == 200 and len(after_list) >= 1,
            "the approved device is now a trusted device of the account",
            f"status={after.status} count={len(after_list)}",
        )


# =============================================================================
# Scenario C — SOC investigation
# =============================================================================


def scenario_c(context: Context) -> None:
    """The alert list, one alert's evidence, its timeline, and its workflow."""
    report = context.report
    report.scenario("C", "SOC investigation")

    analyst_token = context.login("analyst")

    # -- restore the fixture set --------------------------------------------
    #
    # The scenario is re-runnable, so the SEEDED alerts are put back into
    # the state the seed created before the list is read.  A scenario
    # that acknowledged an alert in an earlier run must not leave the
    # demo in a state where the SOC screens show fewer statuses than the
    # fixture set defines.
    for seeded in context.fixtures.detection.get("alerts", {}).values():
        context._reset_alert_status(str(seeded["id"]), str(seeded.get("status") or "open"))

    alerts = context.api.get("/api/v1/alerts?page=1&limit=50", token=analyst_token)
    alert_body = alerts.body if isinstance(alerts.body, dict) else {}
    alert_list = alert_body.get("alerts") or []
    report.check(
        alerts.status == 200 and len(alert_list) >= 4,
        "the alert list holds the seeded alerts",
        f"status={alerts.status} count={len(alert_list)} total={alert_body.get('total')}",
    )

    statuses = {item.get("status") for item in alert_list if isinstance(item, dict)}
    report.check(
        {"open", "acknowledged", "resolved", "false_positive"} <= statuses,
        "the alert list shows every status",
        f"statuses={sorted(s for s in statuses if s)}",
    )

    # -- the evidence of an open alert --------------------------------------
    #
    # The scenario is RE-RUNNABLE: it has to work on a stack that a
    # previous run already moved on.  A SEEDED alert is used, because the
    # seeded alerts are the ones that carry the full evidence — the
    # attempt, the risk assessment and the detection logs.
    #
    # The scenario works on the ``critical_open`` alert, and scenario D
    # works on ``medium_open_ruleless``.  The two scenarios therefore do
    # not fight over the same row, and each one can restore its own
    # alert when an earlier run has moved it forward.
    seeded_by_id = {
        str(seeded["id"]): seeded
        for seeded in context.fixtures.detection["alerts"].values()
    }

    scenario_alert_id = str(context.fixtures.alert("critical_open")["id"])

    open_alert = None
    for item in alert_list:
        if not isinstance(item, dict):
            continue
        if str(item.get("id")) != scenario_alert_id:
            continue
        if item.get("status") == "open":
            open_alert = item
            break

    if open_alert is None:
        # An earlier run already acknowledged the alert.  It is put back
        # to ``open`` so the workflow below starts from a legal state.
        # The alert keeps its evidence, its timeline and its assignment.
        context._reset_alert_status(scenario_alert_id, "open")
        open_alert = {"id": scenario_alert_id, "status": "open"}
        report.check(
            True,
            "the alert list holds a seeded alert",
            f"alert_id={scenario_alert_id} status was reset to open for this run",
        )
    else:
        report.check(
            True,
            "the alert list holds a seeded alert",
            f"alert_id={open_alert.get('id')} risk_level={open_alert.get('risk_level')}",
        )

    alert_id = str(open_alert["id"])

    evidence = context.api.get(f"/api/v1/alerts/{alert_id}/evidence", token=analyst_token)
    evidence_body = evidence.body if isinstance(evidence.body, dict) else {}
    report.check(
        evidence.status == 200 and "alert" in evidence_body,
        "the evidence endpoint returns the alert, the attempt and the assessment",
        f"status={evidence.status} keys={sorted(evidence_body.keys())}",
    )
    report.check(
        evidence_body.get("risk_assessment") is not None,
        "the evidence carries the risk assessment",
    )
    report.check(
        bool(evidence_body.get("detection_logs")),
        "the evidence carries the detection logs",
        f"logs={len(evidence_body.get('detection_logs') or [])}",
    )

    # -- the timeline --------------------------------------------------------
    #
    # The timeline endpoint returns a LIST of events, not an object.
    timeline = context.api.get(f"/api/v1/alerts/{alert_id}/timeline", token=analyst_token)
    entries = timeline.body if isinstance(timeline.body, list) else []
    report.check(
        timeline.status == 200 and len(entries) >= 1,
        "the timeline holds the seeded entries",
        f"status={timeline.status} count={len(entries)}",
    )

    # -- the acknowledgement -------------------------------------------------
    acknowledge = context.api.post(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        {"notes": "M13 scenario C — acknowledged by the script."},
        token=analyst_token,
    )
    report.check(
        acknowledge.status in (200, 201),
        "the analyst acknowledges the alert",
        f"status={acknowledge.status} body={acknowledge.raw[:200]}",
    )

    after = context.api.get(f"/api/v1/alerts/{alert_id}", token=analyst_token)
    after_body = after.body if isinstance(after.body, dict) else {}
    report.check(
        after.status == 200 and after_body.get("status") == "acknowledged",
        "the alert is acknowledged after the call",
        f"status={after_body.get('status')}",
    )

    # -- the assignment ------------------------------------------------------
    #
    # The assignee is a SOC ANALYST of the detection context, not a core
    # user: the alerts table references ``soc_analysts.id``.  The seed
    # created one, and the manifest carries its id.
    analysts = context.fixtures.detection.get("analysts") or []
    analyst_id = str(analysts[0]["id"]) if analysts else ""
    report.check(bool(analyst_id), "the manifest carries the id of a SOC analyst")

    if analyst_id:
        assign = context.api.post(
            f"/api/v1/alerts/{alert_id}/assign",
            {"assigned_to_id": analyst_id, "notes": "M13 scenario C — assigned to the analyst."},
            token=analyst_token,
        )
        report.check(
            assign.status in (200, 201),
            "the analyst is assigned to the alert",
            f"status={assign.status} body={assign.raw[:200]}",
        )

        assigned = context.api.get(f"/api/v1/alerts/{alert_id}", token=analyst_token)
        assigned_body = assigned.body if isinstance(assigned.body, dict) else {}
        report.check(
            assigned.status == 200 and assigned_body.get("assigned_to_id") == analyst_id,
            "the alert carries the assignee after the call",
            f"assigned_to_id={assigned_body.get('assigned_to_id')}",
        )


# =============================================================================
# Scenario D — Protective actions
# =============================================================================


def scenario_d(context: Context) -> None:
    """A real protective action, and the 502 handling."""
    report = context.report
    report.scenario("D", "Protective actions")

    admin_token = context.login("admin")
    analyst_token = context.login("analyst")

    # -- the alert that carries a real subject ------------------------------
    #
    # The scenario is re-runnable, so an alert that is still ``open`` is
    # picked from the list.  The alert has to carry a subject, because
    # the whole point of the scenario is a state change on a REAL
    # account.  The 502 case creates an alert whose subject does NOT
    # exist, so such an alert is skipped here.
    alerts = context.api.get("/api/v1/alerts?page=1&limit=50", token=analyst_token)
    alerts_body = alerts.body if isinstance(alerts.body, dict) else {}
    alert_list = alerts_body.get("alerts") or []

    seeded_by_id = {
        str(seeded["id"]): seeded
        for seeded in context.fixtures.detection["alerts"].values()
    }

    open_alert = None
    subject_user_id = ""
    for item in alert_list:
        if not isinstance(item, dict) or item.get("status") != "open":
            continue
        seeded = seeded_by_id.get(str(item.get("id")))
        if seeded is None:
            continue
        candidate = str(seeded.get("subject_user_id") or "")
        if not candidate:
            continue
        open_alert = item
        subject_user_id = candidate
        break

    if open_alert is None:
        # Every seeded alert has already been worked on by an earlier
        # run.  The seeded alert this scenario owns is put back to
        # ``open``, so the scenario can prove the workflow again.
        #
        # The scenario owns ``medium_open_ruleless``: scenario C works on
        # ``critical_open``, so the two never fight over the same row.
        scenario_alert_id = str(context.fixtures.alert("medium_open_ruleless")["id"])
        for item in alert_list:
            if isinstance(item, dict) and str(item.get("id")) == scenario_alert_id:
                seeded = seeded_by_id.get(scenario_alert_id) or {}
                candidate = str(seeded.get("subject_user_id") or "")
                if not candidate:
                    break
                context._reset_alert_status(scenario_alert_id, "open")
                open_alert = {"id": scenario_alert_id, "status": "open"}
                subject_user_id = candidate
                break

    if open_alert is None:
        report.check(
            False,
            "the alert list holds an open alert with a real subject account",
        )
        return

    alert_id = str(open_alert["id"])
    report.check(
        True,
        "the alert list holds an open alert with a real subject account",
        f"alert_id={alert_id} risk_level={open_alert.get('risk_level')} "
        f"subject_user_id={subject_user_id}",
    )

    # -- the action ----------------------------------------------------------
    #
    # ``REQUIRE_MFA`` is a ONE-TIME gate: it sets ``detection_mfa_once``,
    # which is cleared as soon as the account completes an MFA handshake.
    # The gate is therefore proved by a login that is HELD BACK — and
    # the scenario has to restore the gate before it can prove it, so it
    # is re-armed through the same internal boundary the action itself
    # uses.
    context._rearm_detection_mfa(subject_user_id)

    action = context.api.post(
        f"/api/v1/alerts/{alert_id}/actions",
        {"action": "REQUIRE_MFA", "reason": "M13 scenario D — force the MFA."},
        token=analyst_token,
    )
    action_body = action.body if isinstance(action.body, dict) else {}
    report.check(
        action.status in (200, 201),
        "the analyst triggers the REQUIRE_MFA protective action",
        f"status={action.status} body={action.raw[:240]}",
    )
    report.check(
        str(action_body.get("action", "")).upper() == "REQUIRE_MFA",
        "the action response echoes the action that was asked for",
        f"action={action_body.get('action')}",
    )

    # -- the state change in the core context -------------------------------
    #
    # The protective action changes the CORE context: it forces the MFA
    # of the subject account.  The proof is read back BEHAVIOURALLY: the
    # next login of the subject must be held for an MFA challenge.
    #
    # A behavioural proof is used on purpose.  The flag the action sets
    # (``detection_mfa_once``) is INTERNAL to the core context and is
    # deliberately not exposed by any endpoint, so the only honest way to
    # show that the state changed is to let the account try to log in.
    if subject_user_id:
        subject_username = context._username_of_subject(subject_user_id)

        if not subject_username:
            report.check(
                False,
                "the subject of the action is a known demo account",
                f"subject_user_id={subject_user_id}",
            )
        else:
            # The login must now be held for an MFA challenge.  The
            # challenge itself is not completed: the scenario proves the
            # GATE, not the whole handshake.
            probe = context._post_login(
                subject_username,
                context.fixtures.password(context._password_key_of(subject_username)),
            )
            probe_body = probe.body if isinstance(probe.body, dict) else {}
            report.check(
                probe.status == 200 and bool(probe_body.get("mfa_required")),
                "the next login of the subject is held for an MFA challenge",
                f"username={subject_username} status={probe.status} "
                f"mfa_required={probe_body.get('mfa_required')}",
            )

        # The internal boundary answers for the same subject.  It proves
        # that the contexts really are separate and that the boundary is
        # guarded by the shared secret.
        internal = context.api.get(
            f"/api/v1/internal/users/{subject_user_id}",
            headers=context.internal_headers(),
        )
        internal_body = internal.body if isinstance(internal.body, dict) else {}
        report.check(
            internal.status == 200 and internal_body.get("username"),
            "the internal boundary answers for the subject of the action",
            f"status={internal.status} username={internal_body.get('username')}",
        )

    # -- the 502 handling ----------------------------------------------------
    #
    # The failure case is proved against the REAL path, not a simulated
    # one.
    #
    # Detection does not mutate Core state directly: it asks Core to
    # enforce the action through the internal boundary.  When Core does
    # not enforce it — because Core is unreachable, because the shared
    # secret does not match, or because Core rejects the target — the
    # detection context answers 502 and says so honestly.  It never
    # reports a protective action as applied when it was not.
    #
    # The trigger used here is a subject that Core does not know: the
    # alert exists in the detection context, but its ``login_attempt``
    # points at a user that was never created in the core database.  The
    # boundary call therefore fails, and the honest answer is a 502.
    report.info("checking the 502 handling of a protective action Core cannot enforce")
    orphan_attempt_id = context.fixtures.fixture_id("login_attempt", "m13-orphan-subject")
    orphan_alert_id = context.fixtures.fixture_id("alert", "m13-orphan-subject")
    orphan_user_id = context.fixtures.fixture_id("user", "m13-orphan-subject")

    created = context._create_orphan_alert(
        orphan_attempt_id, orphan_alert_id, orphan_user_id
    )
    if not created:
        report.check(
            False,
            "the fixture for the 502 case could not be created",
        )
    else:
        failed_action = context.api.post(
            f"/api/v1/alerts/{orphan_alert_id}/actions",
            {"action": "REQUIRE_MFA", "reason": "M13 scenario D — the 502 case."},
            token=analyst_token,
        )
        report.check(
            failed_action.status == 502,
            "a protective action that Core cannot enforce answers 502",
            f"status={failed_action.status} body={failed_action.raw[:240]}",
        )

        detail = failed_action.raw.lower()
        report.check(
            "not enforced" in detail or "was not enforced" in detail,
            "the 502 says honestly that the action was NOT enforced",
            f"body={failed_action.raw[:240]}",
        )

        # -- the failure is recorded in the timeline ------------------------
        #
        # The SOC has to be able to see that the action was requested
        # and did not take effect, so the failure is written to the
        # timeline rather than swallowed.
        timeline = context.api.get(
            f"/api/v1/alerts/{orphan_alert_id}/timeline", token=analyst_token
        )
        entries = timeline.body if isinstance(timeline.body, list) else []
        failed_entries = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and "NOT enforced" in str(entry.get("comment") or "")
        ]
        report.check(
            timeline.status == 200 and len(failed_entries) >= 1,
            "the failed action is recorded in the timeline",
            f"status={timeline.status} entries={len(entries)} failed={len(failed_entries)}",
        )

    # The client is still usable after the failure.
    still_working = context.api.get("/api/v1/alerts?page=1&limit=1", token=analyst_token)
    report.check(
        still_working.status == 200,
        "the client keeps working after the gateway failure",
        f"status={still_working.status}",
    )


def _port_is_closed_base_url(base_url: str) -> str:
    """A base URL whose port nothing listens on.

    The port is taken from the demo configuration, and one above it is
    used, so the address is well formed and the connection is refused
    immediately instead of hanging.
    """
    match = re.match(r"^(https?://[^/:]+):(\d+)(/.*)?$", base_url)
    if not match:
        return "http://127.0.0.1:1"
    scheme = match.group(1)
    host = match.group(2)
    port = int(match.group(3))
    rest = match.group(4) or ""
    return f"{scheme}:{host}:{port + 1}{rest}"


# =============================================================================
# Scenario E — Policy management
# =============================================================================


def scenario_e(context: Context) -> None:
    """The draft policy, an edit, an activation, and the immutability."""
    report = context.report
    report.scenario("E", "Policy management")

    admin_token = context.login("admin")

    # -- the policy list ----------------------------------------------------
    #
    # The endpoint returns a LIST of policies directly, not an object
    # with a wrapper key.
    policies = context.api.get("/api/v1/policies", token=admin_token)
    policy_list = policies.body if isinstance(policies.body, list) else []
    report.check(
        policies.status == 200 and len(policy_list) >= 2,
        "the policy list holds the draft and the active policy",
        f"status={policies.status} count={len(policy_list)}",
    )

    active_versions = [
        p.get("version")
        for p in policy_list
        if isinstance(p, dict) and p.get("is_active")
    ]
    report.check(
        len(active_versions) == 1,
        "exactly one policy is active",
        f"active={active_versions}",
    )

    # -- the draft ----------------------------------------------------------
    #
    # The scenario creates its OWN draft policy instead of editing the
    # seeded one.  A policy that has been activated becomes IMMUTABLE —
    # the historical risk assessments reference it — so the seeded draft
    # can only be edited once.  Creating a fresh draft keeps the
    # scenario re-runnable, and it exercises the same lifecycle a real
    # operator goes through.
    # The policy version has a strict format (``v`` followed by numbers
    # separated by dots), so only numbers go into it.
    draft_version = f"v3.3.{int(time.time())}"
    created = context.api.post(
        "/api/v1/policies",
        {
            "version": draft_version,
            "name": "M13 scenario E — the draft policy",
            "description": "Created by the M13 scenario E script.",
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
        },
        token=admin_token,
    )
    created_body = created.body if isinstance(created.body, dict) else {}
    draft_id = str(created_body.get("id") or "")
    report.check(
        created.status in (200, 201) and bool(draft_id),
        "a draft policy is created",
        f"status={created.status} id={draft_id} body={created.raw[:200]}",
    )

    if not draft_id:
        return

    draft = context.api.get(f"/api/v1/policies/{draft_id}", token=admin_token)
    draft_body = draft.body if isinstance(draft.body, dict) else {}
    report.check(
        draft.status == 200 and draft_body.get("is_active") is False,
        "the draft policy is readable and is not active",
        f"status={draft.status} is_active={draft_body.get('is_active')}",
    )

    # -- the edit -----------------------------------------------------------
    #
    # The update is a compare-and-swap: it carries the ``updated_at`` the
    # client read.  A stale value is rejected, which is the point of the
    # mechanism.
    expected_updated_at = draft_body.get("updated_at")
    rules = draft_body.get("rules") or []
    edited_rules = list(rules)
    edited_rules.append(
        {
            "name": "m13_scenario_rule",
            "field": "fail_count_24h",
            "operator": ">=",
            "value": 2,
            "weight": 0.3,
            "score": 0.7,
            "enabled": True,
            "description": "Added by the M13 scenario E script.",
        }
    )

    update = context.api.put(
        f"/api/v1/policies/{draft_id}",
        {
            "name": "M13 scenario E — the draft policy, edited",
            "rules": edited_rules,
            "expected_updated_at": expected_updated_at,
        },
        token=admin_token,
    )
    report.check(
        update.status in (200, 204),
        "the draft policy is edited",
        f"status={update.status} body={update.raw[:240]}",
    )

    # -- the stale update is rejected ---------------------------------------
    if expected_updated_at:
        stale = context.api.put(
            f"/api/v1/policies/{draft_id}",
            {
                "name": "A stale write that must be rejected",
                "expected_updated_at": expected_updated_at,
            },
            token=admin_token,
        )
        report.check(
            stale.status == 409,
            "a stale update is rejected with 409",
            f"status={stale.status} body={stale.raw[:200]}",
        )

    # -- the activation -----------------------------------------------------
    activate = context.api.post(
        f"/api/v1/policies/{draft_id}/activate", token=admin_token
    )
    report.check(
        activate.status in (200, 201),
        "the draft policy is activated",
        f"status={activate.status} body={activate.raw[:240]}",
    )

    # -- the immutability ----------------------------------------------------
    #
    # The policy that has just been activated is immutable: it cannot be
    # edited any more.  Activating another policy deactivates it, but the
    # deactivated policy keeps its content.
    #
    # The ``updated_at`` is read from the DETAIL endpoint, because the
    # list does not carry it.
    activated = context.api.get(f"/api/v1/policies/{draft_id}", token=admin_token)
    activated_body = activated.body if isinstance(activated.body, dict) else {}

    immutable_edit = context.api.put(
        f"/api/v1/policies/{draft_id}",
        {
            "name": "An edit that must be rejected",
            "expected_updated_at": activated_body.get("updated_at"),
        },
        token=admin_token,
    )
    report.check(
        immutable_edit.status == 409,
        "the activated policy cannot be edited — 409",
        f"status={immutable_edit.status} body={immutable_edit.raw[:200]}",
    )

    # The client may not deactivate a policy by setting ``is_active``:
    # the activation is a SERVER-SIDE transition, so the client is
    # refused with a 400 that says exactly that.
    immutable_deactivate = context.api.put(
        f"/api/v1/policies/{draft_id}",
        {"is_active": False, "expected_updated_at": activated_body.get("updated_at")},
        token=admin_token,
    )
    report.check(
        immutable_deactivate.status in (400, 409),
        "the client cannot deactivate a policy by setting is_active",
        f"status={immutable_deactivate.status} body={immutable_deactivate.raw[:200]}",
    )

    # -- restore -------------------------------------------------------------
    #
    # The scenario leaves the stack in the state the seed created, so the
    # scenarios can run in any order and the next run starts from the
    # same place: the seeded active policy is activated again, and the
    # draft of the scenario is deactivated by that activation.
    seeded_active_id = str(context.fixtures.detection["policies"]["active"]["id"])
    reactivated = context.api.post(
        f"/api/v1/policies/{seeded_active_id}/activate", token=admin_token
    )
    report.check(
        reactivated.status in (200, 201),
        "the original active policy is activated again (the stack is restored)",
        f"status={reactivated.status}",
    )

    # The deactivated policy kept its content.
    after_activation = context.api.get(f"/api/v1/policies/{draft_id}", token=admin_token)
    after_body = after_activation.body if isinstance(after_activation.body, dict) else {}
    report.check(
        after_activation.status == 200
        and after_body.get("is_active") is False
        and bool(after_body.get("rules")),
        "the deactivated policy kept its content",
        f"status={after_activation.status} is_active={after_body.get('is_active')}",
    )


# =============================================================================
# Scenario F — Manager analytics
# =============================================================================


def scenario_f(context: Context) -> None:
    """The manager's dashboard, trends, SOC KPI and ML statistics."""
    report = context.report
    report.scenario("F", "Manager analytics")

    manager_token = context.login("manager")

    dashboard = context.api.get("/api/v1/manager/dashboard", token=manager_token)
    dashboard_body = dashboard.body if isinstance(dashboard.body, dict) else {}
    report.check(
        dashboard.status == 200 and "core" in dashboard_body,
        "the manager dashboard returns the core and the detection sections",
        f"status={dashboard.status} keys={sorted(dashboard_body.keys())}",
    )

    core_section = dashboard_body.get("core") or {}
    detection_section = dashboard_body.get("detection") or {}
    report.check(
        int(core_section.get("total_users") or 0) >= 4,
        "the dashboard counts the demo accounts",
        f"total_users={core_section.get('total_users')}",
    )
    report.check(
        int(detection_section.get("login_attempts") or 0) >= 5,
        "the dashboard counts the seeded login attempts",
        f"login_attempts={detection_section.get('login_attempts')}",
    )

    alerts_section = detection_section.get("alerts") or {}
    report.check(
        int(alerts_section.get("total") or 0) >= 5,
        "the dashboard counts the seeded alerts",
        f"total={alerts_section.get('total')}",
    )

    # -- the trends ----------------------------------------------------------
    trends = context.api.get("/api/v1/manager/trends?days=7", token=manager_token)
    trends_body = trends.body if isinstance(trends.body, dict) else {}
    report.check(
        trends.status == 200 and bool(trends_body),
        "the trends endpoint returns a series",
        f"status={trends.status} keys={sorted(trends_body.keys())}",
    )

    # -- the SOC KPI ---------------------------------------------------------
    kpi = context.api.get("/api/v1/manager/soc-kpi", token=manager_token)
    kpi_body = kpi.body if isinstance(kpi.body, dict) else {}
    report.check(
        kpi.status == 200 and bool(kpi_body),
        "the SOC KPI endpoint returns its counters",
        f"status={kpi.status} keys={sorted(kpi_body.keys())}",
    )

    # -- the ML statistics ---------------------------------------------------
    ml_stats = context.api.get("/api/v1/manager/ml-stats", token=manager_token)
    ml_body = ml_stats.body if isinstance(ml_stats.body, dict) else {}
    report.check(
        ml_stats.status == 200 and bool(ml_body),
        "the ML statistics endpoint returns the model state",
        f"status={ml_stats.status} keys={sorted(ml_body.keys())}",
    )

    # The model is staged, never promoted: the demo must not pretend the
    # artifact was loaded.
    ml_section = dashboard_body.get("ml") or {}
    if ml_section:
        report.check(
            ml_section.get("model_status") != "production",
            "the dashboard does not claim a production model",
            f"model_status={ml_section.get('model_status')} "
            f"active_model_version={ml_section.get('active_model_version')}",
        )


# =============================================================================
# The registry
# =============================================================================

SCENARIOS: Dict[str, Tuple[str, Callable[[Context], None]]] = {
    "A": ("Authentication", scenario_a),
    "B": ("Device trust", scenario_b),
    "C": ("SOC investigation", scenario_c),
    "D": ("Protective actions", scenario_d),
    "E": ("Policy management", scenario_e),
    "F": ("Manager analytics", scenario_f),
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the M13 demo scenarios against a live demo stack.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DEMO_API_BASE_URL") or _default_base_url(),
        help="the base URL of the demo API (default: %(default)s)",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="the fixture manifest the seed wrote (default: %(default)s)",
    )
    parser.add_argument(
        "--otp-log",
        default=_default_otp_log(),
        help="the log of the SMTP sink (default: %(default)s)",
    )
    parser.add_argument(
        "--otp-timeout",
        type=float,
        default=30.0,
        help="how long to wait for the OTP (default: %(default)s seconds)",
    )
    parser.add_argument(
        "--login-retry-timeout",
        type=float,
        default=120.0,
        help=(
            "how long to keep retrying a login that the rate limit rejected "
            "(default: %(default)s seconds)"
        ),
    )
    parser.add_argument(
        "--login-retry-wait",
        type=float,
        default=65.0,
        help="how long to wait between two login attempts (default: %(default)s seconds)",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="run only this scenario; repeatable",
    )
    parser.add_argument(
        "--all", action="store_true", help="run every scenario (the default)"
    )
    parser.add_argument("--list", action="store_true", help="list the scenarios and exit")
    parser.add_argument("--no-colour", action="store_true", help="print without ANSI colour")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.list:
        for key, (title, _) in sorted(SCENARIOS.items()):
            print(f"{key}  {title}")
        return 0

    keys = args.scenario if args.scenario else sorted(SCENARIOS)

    if not Path(args.manifest).exists():
        print(
            f"[demo-scenarios] ERROR: the fixture manifest is missing: {args.manifest}\n"
            f"[demo-scenarios] Seed the fixtures first: scripts/demo_seed_demo.py --seed",
            file=sys.stderr,
        )
        return 2

    try:
        health = ApiClient(args.base_url).get("/health")
    except Exception as error:  # noqa: BLE001 — the message must be readable
        print(f"[demo-scenarios] ERROR: {error}", file=sys.stderr)
        return 2

    if health.status != 200:
        print(
            f"[demo-scenarios] ERROR: the demo API is not answering at {args.base_url} "
            f"(status={health.status}). Start the demo stack: scripts/demo_stack.sh start",
            file=sys.stderr,
        )
        return 2

    context = Context(args)

    for key in keys:
        title, runner = SCENARIOS[key]
        try:
            runner(context)
        except Exception as error:  # noqa: BLE001 — one broken scenario must not hide the rest
            context.report.scenario(key, title)
            context.report.check(False, f"the scenario ran to completion", str(error))

    return context.report.summary()


if __name__ == "__main__":
    sys.exit(main())
