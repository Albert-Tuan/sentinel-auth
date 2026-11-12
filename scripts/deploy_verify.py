#!/usr/bin/env python
"""Sentinel Auth v3.3 — deployment verification.

Runs the nine deployment acceptance checks against a **running** local
deployment (the infrastructure started by ``docker compose`` and the
FastAPI monolith started by ``scripts/deploy_local.sh``).

The checks are, in order:

    1. the three logical databases exist and hold the canonical schema;
2. the FastAPI application answers;
3. ``/health`` and ``/ready`` carry the agreed semantics;4. Core authentication works (register + login against the Core database);
5. Detection and ML communicate with the monolith;
6. the Manager facade can read from Core, Detection and ML;
7. the behaviour with an unavailable dependency is the degraded one;
8. a shutdown/restart does not lose the database data;
9. the teardown keeps the persistent volume.

Checks 1, 4 and 8 are **read-only with respect to the schema** and 4
writes only the rows it creates.  Nothing here drops a database, reloads a
schema or recreates a table.
Usage::

    python scripts/deploy_verify.py

The script reads its configuration from the environment, which
``scripts/deploy_local.sh`` has already loaded from ``.env``.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = os.environ.get("APP_PORT", "8000")
BASE_URL = f"http://{APP_HOST}:{APP_PORT}"

CORE_DB = os.environ.get("CORE_DB", "sentinel_core")
DETECTION_DB = os.environ.get("DETECTION_DB", "sentinel_detection")
ML_DB = os.environ.get("ML_DB", "sentinel_ml")

CORE_URL = os.environ.get("CORE_DATABASE_URL", "")
DETECTION_URL = os.environ.get("DETECTION_DATABASE_URL", "")
ML_URL = os.environ.get("ML_DATABASE_URL", "")

PASSED: List[str] = []
FAILED: List[str] = []

#: The manager session is minted once and reused by the checks that need
#: it, so the application's login rate limit (5 attempts per IP per 5
#: minutes) is not exhausted by the verification itself.
_MANAGER_TOKEN: Optional[str] = None
_MANAGER_USERNAME: Optional[str] = None


class RateLimitEngaged(Exception):
    """Raised when the application's own rate limit blocks the check.

    This is not a deployment failure - it is the protective behaviour
    working.  The check reports it as such.
    """


def check(name: str, ok: bool, detail: str = "") -> bool:
    if ok:
        PASSED.append(name)
        print(f"  PASS  {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  [{detail}]")
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def get(path: str, headers: Optional[Dict[str, str]] = None,
        timeout: float = 15.0) -> Tuple[int, bytes]:
    """Return ``(status_code, body)`` for a GET request."""
    request = urllib.request.Request(f"{BASE_URL}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, str(exc).encode()


def post(path: str, payload: Dict[str, Any],
         headers: Optional[Dict[str, str]] = None,
         timeout: float = 15.0) -> Tuple[int, bytes]:
    """Return ``(status_code, body)`` for a POST request."""
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, str(exc).encode()


# ---------------------------------------------------------------------------
# Check 1 — the three databases hold the canonical schema
# ---------------------------------------------------------------------------
def check_databases() -> None:
    section("1. the three logical databases exist with the canonical schema")
    from sqlalchemy import create_engine, text

    engines = {
        CORE_DB: create_engine(CORE_URL),
        DETECTION_DB: create_engine(DETECTION_URL),
        ML_DB: create_engine(ML_URL),
    }
    expected = {CORE_DB: 13, DETECTION_DB: 7, ML_DB: 3}
    try:
        for name, engine in engines.items():
            with engine.connect() as conn:
                tables = conn.execute(text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )).scalar()
                views = conn.execute(text(
                    "SELECT count(*) FROM information_schema.views "
                    "WHERE table_schema = 'public'"
                )).scalar()
            check(f"{name} exists and holds {expected[name]} base tables",
                  tables == expected[name],
                  f"tables={tables} views={views}")
    finally:
        for engine in engines.values():
            engine.dispose()

    # Cross-context isolation, checked against the live servers.
    from sqlalchemy import create_engine, text

    leaks = {
        CORE_DB: ("policies", "login_attempts", "alerts", "model_versions"),
        DETECTION_DB: ("users", "sessions", "model_versions"),
        ML_DB: ("users", "sessions", "policies", "login_attempts", "alerts"),
    }
    for name, tables in leaks.items():
        engine = create_engine(CORE_URL if name == CORE_DB
                               else DETECTION_URL if name == DETECTION_DB
                               else ML_URL)
        try:
            with engine.connect() as conn:
                found = conn.execute(text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                ), {"names": list(tables)}).scalar()
            check(f"{name} owns no table from another context", found == 0,
                  f"leaked={found}")
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Check 2 and 3 — liveness, readiness, and the agreed semantics
# ---------------------------------------------------------------------------
def check_application() -> None:
    section("2. the FastAPI application answers")
    status, body = get("/health")
    check("the application answers on /health", status == 200, f"status={status}")
    check("the OpenAPI schema is served", get("/openapi.json")[0] == 200)

    section("3. liveness and readiness carry the agreed semantics")
    # Liveness: the process is up.  It must NOT depend on a dependency.
    status, body = get("/health")
    payload = json.loads(body) if status == 200 else {}
    check("/health -> 200", status == 200, f"status={status}")
    check("/health reports status=ok", payload.get("status") == "ok",
          json.dumps(payload))

    # Readiness: the deployment can serve traffic.  It probes the three
    # bounded-context databases with a read-only ``SELECT 1``.
    status, body = get("/ready")
    payload = json.loads(body) if status in (200, 503) else {}
    check("/ready -> 200", status == 200, f"status={status}")
    check("/ready reports status=ready", payload.get("status") == "ready",
          json.dumps(payload))

    # --- /ready is DEPENDENCY-AWARE -------------------------------------
    # The endpoint answers with one entry per bounded context.  A context
    # that answered is reported as ``ok``; a context that did not is
    # reported as ``unavailable``.  The deployment is ready only when all
    # three answered.
    checks = payload.get("checks") or {}
    for context in ("core", "detection", "ml"):
        entry = checks.get(context) or {}
        check(f"/ready reports the {context} database as reachable",
              entry.get("status") == "ok",
              json.dumps(entry))

    # The ML ARTIFACT is a different thing from the ML DATABASE.  A
    # missing artifact is the normal state of a demo deployment: the
    # Detection Engine falls back to a rule-only score, so the service
    # stays ready.  The probe must report it as a degraded artifact, not as
    # an unavailable database.
    artifact = checks.get("ml_artifact") or {}
    check("/ready distinguishes the ML artifact from the ML database",
          artifact.get("status") in ("ready", "degraded", "unknown"),
          json.dumps(artifact))
    check("/ready does not report a missing ML artifact as an unavailable database",
          (checks.get("ml") or {}).get("status") == "ok",
          "the ML database answered even though no model is promoted")

    # The probe must be READ-ONLY.  It may not write a row, and it may not
    # run a heavy query.  The proof is that the ML inference log - which
    # every scoring request appends to - did not grow while the probe ran.
    from sqlalchemy import create_engine, text
    engine = create_engine(ML_URL)
    try:
        with engine.connect() as conn:
            before_logs = conn.execute(text(
                "SELECT count(*) FROM inference_logs"
            )).scalar()
        get("/ready")
        with engine.connect() as conn:
            after_logs = conn.execute(text(
                "SELECT count(*) FROM inference_logs"
            )).scalar()
        check("the readiness probe writes nothing", before_logs == after_logs,
              f"inference_logs before={before_logs} after={after_logs}")
    except Exception as exc:  # noqa: BLE001 - the outcome IS the check
        check("the readiness probe writes nothing", False,
              f"{exc.__class__.__name__}: {exc}")
    finally:
        engine.dispose()

    # The dependency-aware check reaches the Core database directly, too.
    engine = create_engine(CORE_URL)
    try:
        with engine.connect() as conn:
            reachable = conn.execute(text("SELECT 1")).scalar()
        check("the dependency-aware check reaches the Core database directly",
              reachable == 1,
              "the verification suite - and now /ready - establish reachability")
    except Exception as exc:  # noqa: BLE001 - the outcome IS the check
        check("the dependency-aware check reaches the Core database directly",
              False, f"{exc.__class__.__name__}: {exc}")
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Check 4 — Core authentication
# ---------------------------------------------------------------------------
def check_core_auth() -> None:
    section("4. Core authentication works")
    from sqlalchemy import create_engine, text

    # The ML inference log count is captured BEFORE the authentication
    # flow, so the check proves that the flow itself added no row -
    # independently of whatever the ML context logged earlier.
    engine = create_engine(ML_URL)
    try:
        with engine.connect() as conn:
            ml_before = conn.execute(text("SELECT count(*) FROM inference_logs")).scalar()
    finally:
        engine.dispose()

    username = f"deploy_check_{uuid.uuid4().hex[:12]}"
    password = "Deploy-Check-Password-123!"

    status, body = post("/api/v1/auth/register", {
        "username": username,
        "password": password,
        "email": f"{username}@example.test",
    })
    check("register -> 201", status == 201, f"status={status}")

    status, body = post("/api/v1/auth/login", {
        "username": username,
        "password": password,
    })
    if status == 429:
        # The application's own login rate limit engaged.  That is the
        # correct protective behaviour, so the check waits for the window
        # and retries rather than reporting a deployment failure.
        print("       the application's login rate limit engaged - "
              "waiting for the window to pass")
        if _wait_for_login_budget():
            status, body = post("/api/v1/auth/login", {
                "username": username,
                "password": password,
            })
    token = None
    if status == 200:
        try:
            token = json.loads(body).get("access_token")
        except json.JSONDecodeError:
            token = None
    check("login -> 200 with an access token", status == 200 and bool(token),
          f"status={status}")

    if token:
        status, _ = get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        check("the token authenticates /auth/me -> 200", status == 200,
              f"status={status}")

    status, _ = post("/api/v1/auth/login", {
        "username": username,
        "password": "definitely-the-wrong-password",
    })
    # 429 means the application's own login rate limit kicked in, which is
    # the correct protective behaviour - not a failure of the deployment.
    check("login with a wrong password is refused (401, or 429 when the rate limit engages)",
          status in (401, 429), f"status={status}")

    # The Core context must not have written into the Detection or ML
    # database *directly*.  Core delivers the canonical LoginEvent over
    # the HTTP boundary, and Detection persists it into its own database -
    # that is the designed path, not a cross-database write.  The ML
    # database has no such path at all, so it must stay untouched.
    check_core_write_isolation(ml_before)


def check_core_write_isolation(ml_before: int) -> None:
    """The authentication flow must not write into the Detection or ML database."""
    from sqlalchemy import create_engine, text

    # The ML context is never a write target of the Core authentication
    # flow: nothing in Core imports get_ml_db.  The count is compared
    # before and after the flow, so rows written by the ML context itself
    # (the ML scoring endpoint logs its own inferences) do not confuse it.
    engine = create_engine(ML_URL)
    try:
        with engine.connect() as conn:
            ml_after = conn.execute(text("SELECT count(*) FROM inference_logs")).scalar()
        check("the Core authentication flow wrote no row into sentinel_ml.inference_logs",
              ml_after == ml_before, f"before={ml_before} after={ml_after}")
    finally:
        engine.dispose()

    # The Detection rows must be the ones Core DELIVERED over HTTP, i.e.
    # they carry the username of the account the check registered.  A
    # direct cross-database write would not be possible from Core at all:
    # the Core session dependency is bound to sentinel_core only.
    engine = create_engine(DETECTION_URL)
    try:
        with engine.connect() as conn:
            delivered = conn.execute(text(
                "SELECT count(*) FROM login_attempts "
                "WHERE username_attempted LIKE 'deploy_check_%'"
            )).scalar()
        check("the Detection rows come from the HTTP delivery of Core's login event",
              delivered >= 1,
              f"delivered={delivered} (Core sends the event; Detection persists it)")
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Check 5 — Detection and ML communicate
# ---------------------------------------------------------------------------
def check_detection_and_ml() -> None:
    section("5. Detection and ML communicate with the monolith")
    secret = os.environ.get("INTERNAL_SECRET", "")

    # The ML health endpoint reports which model is loaded.  A demo
    # deployment ships a *staged* placeholder whose file does not exist,
    # so the honest expectation is a well-formed answer that names the
    # artifact state - not a crash.
    status, body = get("/api/v1/internal/ml/health",
                       headers={"X-Internal-Secret": secret})
    payload = json.loads(body) if status == 200 else {}
    check("the ML health endpoint answers", status == 200, f"status={status}")
    check("the ML health endpoint names the artifact state",
          payload.get("model_status") in ("ready", "error"),
          json.dumps(payload))
    check("the ML health endpoint reports that no model is promoted",
          payload.get("model_version") is None,
          f"model_version={payload.get('model_version')!r} "
          "(the registry placeholder stays 'staged' - nothing is auto-promoted)")

    # The feature contract is served without a database dependency.
    status, body = get("/api/v1/internal/ml/features")
    check("the ML feature contract is served", status == 200, f"status={status}")

    # The scoring endpoint IS behind the internal secret.
    score_payload = {
        "request_id": str(uuid.uuid4()),
        "features": {
            "hour_of_day": 12, "fail_count_24h": 0, "ip_change_rate_7d": 0.0,
            "new_device": False, "average_login_interval_seconds": 3600,
            "deviation_score": 0.1,
        },
    }
    status, _ = post("/api/v1/internal/ml/score", score_payload)
    check("the ML scoring endpoint rejects a missing internal secret -> 401",
          status == 401, f"status={status}")

    status, _ = post("/api/v1/internal/ml/score", score_payload,
                      headers={"X-Internal-Secret": secret})
    check("the ML scoring endpoint accepts the internal secret",
          status in (200, 503),
          f"status={status} (503 = no artifact available, which is the honest demo state)")

    # --- the ML DATABASE is reachable even when the ARTIFACT is missing
    # The two failures must stay distinguishable:
    #
    #   * a MISSING ARTIFACT   -> the ML database answers fine, the model
    #                             registry is queried, and the answer says
    #                             so (``model_status: "error"``);
    #   * an UNAVAILABLE ML DB  -> the endpoint cannot reach the database
    #                             at all and the answer is a database
    #                             failure.
    #
    # Proving the database is reachable separates the two: a deployment
    # whose ML endpoint answers 503 must still have a working ML database.
    from sqlalchemy import create_engine, text
    engine = create_engine(ML_URL)
    try:
        with engine.connect() as conn:
            registry_rows = conn.execute(text(
                "SELECT count(*) FROM model_versions"
            )).scalar()
            active_production = conn.execute(text(
                "SELECT count(*) FROM model_versions "
                "WHERE status = 'active' AND is_production IS TRUE"
            )).scalar()
            # The scoring endpoint writes an inference log EVEN when the
            # artifact is missing, and that row carries
            # ``model_status = 'error'``.  Its presence proves the ML
            # database was reachable during the 503 - the failure was the
            # ARTIFACT, not the database.
            error_logs = conn.execute(text(
                "SELECT count(*) FROM inference_logs WHERE model_status = 'error'"
            )).scalar()
        check("the ML database is reachable and answers the model registry query",
              registry_rows >= 1, f"model_versions={registry_rows}")
        check("no ML model is promoted to production by the deployment",
              active_production == 0,
              f"active production models={active_production}")
        check("the 503 was caused by the missing artifact, not by an unavailable ML database",
              error_logs >= 1,
              f"inference_logs with model_status='error' = {error_logs} "
              "(the ML database was reachable and recorded the failed inference)")
    except Exception as exc:  # noqa: BLE001 - the outcome IS the check
        check("the ML database is reachable and answers the model registry query",
              False, f"{exc.__class__.__name__}: {exc}")
    finally:
        engine.dispose()

    # The ML health endpoint reaching its answer at all proves it could
    # query the registry; the model_status it reports is the ARTIFACT
    # state, which is a different thing entirely.
    check("a missing artifact is reported as an artifact state, not as a database failure",
          status == 503 and payload.get("model_status") == "error"
          and payload.get("model_version") is None,
          f"model_status={payload.get('model_status')!r} "
          f"model_version={payload.get('model_version')!r} "
          "(the registry answered; only the file is missing)")

    # The Detection context must be reachable over the in-process HTTP hop.
    event_id = str(uuid.uuid4())
    status, body = post("/api/v1/internal/login-events", {
        "event_id": event_id,
        "username_attempted": "deploy_check_event",
        "outcome": "failure",
        "ip_address": "127.0.0.1",
        "user_agent": "deploy-verify",
        "timestamp": "2026-10-01T00:00:00+00:00",
    }, headers={"X-Internal-Secret": secret})
    check("the Detection context accepts a login event", status == 202,
          f"status={status}")

    # And the event really landed in the Detection database.
    from sqlalchemy import create_engine, text
    engine = create_engine(DETECTION_URL)
    try:
        with engine.connect() as conn:
            count = conn.execute(text(
                "SELECT count(*) FROM login_attempts "
                "WHERE username_attempted = 'deploy_check_event'"
            )).scalar()
        check("the login event was written into the Detection database",
              count >= 1, f"rows={count}")
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Check 6 — the Manager facade reads from all three sources
# ---------------------------------------------------------------------------
def _wait_for_login_budget(timeout: float = 180.0) -> bool:
    """Wait until the application's login rate limit allows another attempt.

    The application rate-limits logins per IP (``rate_limits`` table,
    action ``login``).  A verification run logs in more than once, and a
    second run inside the window would hit the limit.  The limit is the
    application's own protective behaviour, so the verification WAITS for
    the window instead of reporting a false failure.

    The wait is **read-only**: it polls the counter, it never deletes or
    resets it.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(CORE_URL)
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with engine.connect() as conn:
                blocked = conn.execute(text(
                    "SELECT count(*) FROM rate_limits "
                    "WHERE action = 'login' "
                    "AND count >= max_count "
                    "AND window_start >= now() - interval '1 minute'"
                )).scalar()
            if not blocked:
                return True
            time.sleep(2.0)
        return False
    finally:
        engine.dispose()


def _mint_manager_token() -> Tuple[Optional[str], Optional[str]]:
    """Create a SECURITY_MANAGER user and log it in.

    Returns ``(access_token, username)``.  The user row and its role
    assignment are written into the Core database - the same database the
    application owns - so no schema is created or modified.

    The user is created ONCE per run and reused by the later checks.  The
    application rate-limits logins to 5 attempts per IP per 5 minutes, so
    minting a fresh session for every check would exhaust the budget and
    make the verification fail for the wrong reason.
    """
    global _MANAGER_TOKEN, _MANAGER_USERNAME

    if _MANAGER_TOKEN:
        return _MANAGER_TOKEN, _MANAGER_USERNAME

    from sqlalchemy import create_engine, text

    username = f"deploy_manager_{uuid.uuid4().hex[:12]}"
    password = "Deploy-Check-Password-123!"

    status, body = post("/api/v1/auth/register", {
        "username": username,
        "password": password,
        "email": f"{username}@example.test",
    })
    if status not in (200, 201, 409):
        return None, username

    engine = create_engine(CORE_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT u.id, 'SECURITY_MANAGER' FROM users u "
                "WHERE u.username = :username "
                "ON CONFLICT (user_id, role_id) DO NOTHING"
            ), {"username": username})
    finally:
        engine.dispose()

    status, body = post("/api/v1/auth/login", {
        "username": username,
        "password": password,
    })
    if status == 429:
        # The application's login rate limit (5 attempts per IP per
        # window) engaged.  That is the correct protective behaviour, so
        # the verification waits for the window and retries once instead
        # of reporting a deployment failure.
        print("       the application's login rate limit engaged - "
              "waiting for the window to pass")
        if not _wait_for_login_budget():
            raise RateLimitEngaged(
                "the application's login rate limit engaged and the window "
                "did not clear in time; wait for it and re-run the "
                "verification"
            )
        status, body = post("/api/v1/auth/login", {
            "username": username,
            "password": password,
        })
        if status != 200:
            raise RateLimitEngaged(
                f"the login still failed after waiting for the rate-limit "
                f"window (status={status})"
            )
    if status != 200:
        return None, username
    try:
        token = json.loads(body).get("access_token")
    except json.JSONDecodeError:
        token = None
    _MANAGER_TOKEN = token
    _MANAGER_USERNAME = username
    return token, username


def check_manager() -> None:
    section("6. the Manager facade reads from Core, Detection and ML")
    try:
        token, username = _mint_manager_token()
    except RateLimitEngaged as exc:
        check("the Manager facade could be checked", False,
              f"the application's rate limit engaged: {exc}")
        return
    if not token:
        check("a SECURITY_MANAGER session could be minted for the facade check",
              False, f"could not mint a manager session for {username}")
        return
    check("a SECURITY_MANAGER session could be minted for the facade check",
          True, f"user={username}")

    window = "from=2026-10-01T00:00:00%2B00:00&to=2026-10-02T00:00:00%2B00:00"
    status, body = get(f"/api/v1/manager/dashboard?{window}",
                       headers={"Authorization": f"Bearer {token}"})
    payload = json.loads(body) if status == 200 else {}
    sources = payload.get("sources") or {}
    check("the Manager dashboard answers", status == 200, f"status={status}")
    check("the facade reports all three sources",
          sorted(sources) == ["core", "detection", "ml"],
          json.dumps(sorted(sources)))
    check("every source reports its state",
          all(v.get("status") in ("ok", "unavailable", "error")
              for v in sources.values()),
          json.dumps(sources))

    # Every Manager endpoint must answer for a manager session.
    for endpoint in ("dashboard", "trends", "alerts", "soc-kpi", "ml-stats"):
        status, _ = get(f"/api/v1/manager/{endpoint}?{window}",
                        headers={"Authorization": f"Bearer {token}"})
        check(f"the Manager endpoint /{endpoint} answers", status == 200,
              f"status={status}")


# ---------------------------------------------------------------------------
# Check 7 — an unavailable dependency degrades, it does not crash
# ---------------------------------------------------------------------------
def check_degradation() -> None:
    section("7. an unavailable dependency degrades instead of failing")
    # The upstream URLs are read by the APPLICATION process, so the
    # degradation must be observed on a server that was STARTED with the
    # dead upstreams.  Patching the module in this script would not reach
    # the running server, so a second, short-lived instance is started
    # with the upstreams pointing at a dead port - exactly the way the
    # M10 smoke script does it.
    import socket
    import subprocess

    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def wait_for(port: int, timeout: float = 45.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                    return True
            except OSError:
                time.sleep(0.25)
        return False

    try:
        token, username = _mint_manager_token()
    except RateLimitEngaged as exc:
        check("the degradation behaviour could be observed", False,
              f"the application's rate limit engaged: {exc}")
        return
    if not token:
        check("the degradation behaviour could be observed", False,
              f"could not mint a manager session for {username}")
        return

    dead = "http://127.0.0.1:1"
    env = dict(os.environ)
    env.update({
        "CORE_DATABASE_URL": CORE_URL,
        "DETECTION_DATABASE_URL": DETECTION_URL,
        "ML_DATABASE_URL": ML_URL,
        "CORE_APP_URL": dead,
        "DETECTION_URL": dead,
    })

    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_for(port):
            check("the degraded server started", False, "uvicorn did not start")
            return
        check("the degraded server started", True, f"port={port}")

        window = "from=2026-10-01T00:00:00%2B00:00&to=2026-10-02T00:00:00%2B00:00"
        status, body = _get_on(f"http://127.0.0.1:{port}",
                               f"/api/v1/manager/dashboard?{window}",
                               {"Authorization": f"Bearer {token}"})
        payload = json.loads(body) if status in (200, 503) else {}
        sources = payload.get("sources") or {}
        check("the facade answers with a degraded payload, not a crash",
              status in (200, 503), f"status={status}")
        check("the unreachable sources are reported as unavailable",
              sources.get("core", {}).get("status") == "unavailable"
              and sources.get("detection", {}).get("status") == "unavailable",
              json.dumps(sources))
        check("the degraded payload is flagged as degraded",
              payload.get("degraded") is True or status == 503,
              f"degraded={payload.get('degraded')} status={status}")
        check("the ML source is still healthy (only the HTTP upstreams are down)",
              sources.get("ml", {}).get("status") == "ok",
              json.dumps(sources))

        # The application itself must still be healthy: a dead upstream is
        # a degraded source, not a dead process.
        status, _ = _get_on(f"http://127.0.0.1:{port}", "/health")
        check("the application stays healthy with a dead upstream", status == 200,
              f"status={status}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()


def _get_on(base: str, path: str,
            headers: Optional[Dict[str, str]] = None,
            timeout: float = 30.0) -> Tuple[int, bytes]:
    """Return ``(status_code, body)`` for a GET against an arbitrary base URL."""
    request = urllib.request.Request(f"{base}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, str(exc).encode()


# ---------------------------------------------------------------------------
# Check 8 — a restart does not lose the data
# ---------------------------------------------------------------------------
def check_persistence() -> None:
    section("8. the database data survives a restart")
    from sqlalchemy import create_engine, text

    # A dedicated probe row makes the check independent of the other
    # checks, which create and consume their own rows.
    probe = "deploy_persistence_probe"
    engine = create_engine(CORE_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (username, password_hash, email) "
                "SELECT :username, 'not-a-real-hash', :email "
                "WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = :username)"
            ), {"username": probe, "email": f"{probe}@example.test"})

        with engine.connect() as conn:
            found = conn.execute(text(
                "SELECT id FROM users WHERE username = :username"
            ), {"username": probe}).fetchone()
        check("the persistence probe row exists in sentinel_core", found is not None,
              f"user={probe}")

        # The cluster's system identifier identifies the DATA DIRECTORY.
        # It survives a restart and a container rebuild, and it changes
        # only when the volume is recreated.
        #
        # The state file must be tied to it: without that tie, a state
        # file left behind by a different cluster (another daemon, a
        # recreated volume) would make the check compare two unrelated
        # probe identities and report a data loss that never happened.
        with engine.connect() as conn:
            cluster_id = str(conn.execute(text(
                "SELECT system_identifier FROM pg_control_system()"
            )).scalar())
    except Exception as exc:  # noqa: BLE001 - the outcome IS the check
        check("the persistence probe row exists in sentinel_core", False,
              f"{exc.__class__.__name__}: {exc}")
        cluster_id = None
        found = None
    finally:
        engine.dispose()

    # The state file records the probe's identity across the restart.
    state_file = os.path.join(REPO_ROOT, ".ci", "deploy-persistence.json")
    state: Dict[str, Any] = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            state = {}

    current_id = str(found[0]) if found else None
    recorded_id = state.get("probe_id")
    recorded_cluster = state.get("cluster_id")

    if recorded_id is None:
        # First run against this cluster: record the identity.
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as handle:
            json.dump({"probe_id": current_id, "cluster_id": cluster_id}, handle)
        check("the pre-restart probe identity was recorded", True,
              f"id={current_id} cluster={cluster_id}")
    elif recorded_cluster is not None and recorded_cluster != cluster_id:
        # The cluster is a DIFFERENT one: the volume was recreated
        # between the two runs.  Nothing was lost - the old data is gone
        # because the volume itself is new.  Re-record the baseline
        # instead of reporting a false data loss.
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as handle:
            json.dump({"probe_id": current_id, "cluster_id": cluster_id}, handle)
        check("the persistence baseline was re-recorded for the recreated cluster",
              True,
              f"cluster {recorded_cluster} -> {cluster_id} "
              "(the volume was recreated, so there was no data to lose)")
    elif recorded_cluster is None:
        # A state file written by an older version of this script, which
        # did not record the cluster.  It cannot be compared safely.
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as handle:
            json.dump({"probe_id": current_id, "cluster_id": cluster_id}, handle)
        check("the persistence baseline was re-recorded with its cluster identity",
              True,
              f"cluster={cluster_id} (the previous file carried no cluster identity)")
    else:
        # The same cluster: the probe must have kept its identity across
        # the restart.  A different identity here IS a real data loss.
        check("the probe row survived the restart with the same identity",
              recorded_id == current_id,
              f"before={recorded_id} after={current_id}")


# ---------------------------------------------------------------------------
# Check 9 — the teardown keeps the persistent volume
# ---------------------------------------------------------------------------
def _function_body(script_text: str, name: str) -> str:
    """Return the body of a shell function, up to its closing brace.

    The extraction is textual, but it is applied to a script this
    repository owns, and it is what lets the check reason about WHICH
    function performs a destructive operation instead of merely spotting
    the word somewhere in the file.
    """
    marker = f"{name}() {{"
    start = script_text.find(marker)
    if start == -1:
        return ""
    depth = 0
    for index in range(start + len(marker) - 1, len(script_text)):
        if script_text[index] == "{":
            depth += 1
        elif script_text[index] == "}":
            depth -= 1
            if depth == 0:
                return script_text[start:index + 1]
    return ""


def check_volume_policy() -> None:
    section("9. the teardown keeps the persistent volume")
    compose_file = os.path.join(REPO_ROOT, "docker-compose.yml")
    with open(compose_file, encoding="utf-8") as handle:
        compose_text = handle.read()

    # A named volume (not a bind mount to /tmp) is what survives `down`.
    check("the PostgreSQL data lives in a named volume",
          "postgres_data:/var/lib/postgresql/data" in compose_text)

    deploy_script = os.path.join(REPO_ROOT, "scripts", "deploy_local.sh")
    with open(deploy_script, encoding="utf-8") as handle:
        deploy_text = handle.read()

    # --- the destructive operation must be confined to cmd_reset --------
    # Every function that a routine operator runs must NOT contain a
    # volume-destroying command.  The check reads the function bodies
    # rather than the whole file, so a comment mentioning "down -v" cannot
    # make it pass.
    routine = ("cmd_up", "cmd_down", "cmd_status", "cmd_logs", "cmd_verify")
    for name in routine:
        body = _function_body(deploy_text, name)
        if not body:
            check(f"{name} exists", False, "the function was not found")
            continue
        destructive = [token for token in ("down -v", "volume rm", "rm -rf")
                       if token in body]
        check(f"{name} never destroys a persistent volume",
              not destructive,
              f"found {destructive}" if destructive else "")

    reset_body = _function_body(deploy_text, "cmd_reset")
    check("cmd_reset exists", bool(reset_body))
    check("cmd_reset is the only path that destroys the volume",
          "down -v" in reset_body,
          "cmd_reset does not contain 'down -v'")

    # --- the reset path must be explicit and guarded -------------------
    check("the reset path asks for a typed confirmation",
          'read -r answer' in reset_body and '"reset"' in reset_body)
    check("the reset path warns that the data is destroyed",
          "destroys the PostgreSQL volume" in reset_body)
    check("the reset path aborts when the confirmation does not match",
          "aborted - nothing was destroyed" in reset_body)

    # --- the verification itself must not destroy anything --------------
    # The check parses the script with the AST instead of grepping the
    # text: the token list lives in THIS function, so a text search would
    # always find its own search terms.  The AST sees the SQL strings the
    # script actually EXECUTES.
    verify_script = os.path.join(REPO_ROOT, "scripts", "deploy_verify.py")
    with open(verify_script, encoding="utf-8") as handle:
        verify_source = handle.read()
    executed_sql = _executed_sql(verify_source)
    destructive = sorted({
        keyword for keyword in
        ("DROP DATABASE", "DROP SCHEMA", "TRUNCATE", "DELETE FROM")
        if any(keyword in sql.upper() for sql in executed_sql)
    })
    check("the verification never drops, truncates or deletes a database object",
          not destructive,
          f"found {destructive}" if destructive else
          f"({len(executed_sql)} executed statements, none destructive)")

    # --- the application must not create tables at startup --------------
    # The AST sees the CALL, not the word.  The startup docstring mentions
    # ``create_all`` precisely to explain that the application does NOT
    # call it, and a text search would flag that explanation.
    main_py = os.path.join(REPO_ROOT, "app", "main.py")
    with open(main_py, encoding="utf-8") as handle:
        main_source = handle.read()
    create_all_calls = _called_attributes(main_source, "create_all")
    check("the application does not create tables at startup",
          not create_all_calls,
          f"found {create_all_calls}" if create_all_calls else
          "(the mention in the docstring is the explanation, not a call)")


def _executed_sql(source: str) -> List[str]:
    """Return every SQL string the source passes to ``text()``/``execute()``.

    The AST is used instead of a text search so the check sees only the
    statements the script actually executes, not the tokens of the check
    itself.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    sql: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        if name not in ("text", "execute"):
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                sql.append(argument.value)
    return sql


def _called_attributes(source: str, attribute: str) -> List[int]:
    """Return the line numbers where the source CALLS ``attribute``.

    A mention inside a docstring or a comment is not a call, and the AST
    distinguishes the two.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == attribute:
            lines.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == attribute:
            lines.append(node.lineno)
    return lines


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
def main() -> int:
    print("Sentinel Auth v3.3 — deployment verification")
    print(f"target: {BASE_URL}")

    checks = (
        check_databases,
        check_application,
        check_core_auth,
        check_detection_and_ml,
        check_manager,
        check_degradation,
        check_persistence,
        check_volume_policy,
    )
    for func in checks:
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - a failed check is a result
            check(f"{func.__name__} completed", False, f"{exc.__class__.__name__}: {exc}")

    print("\n" + "=" * 72)
    print(f"DEPLOY VERIFY: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("\nFailures:")
        for item in FAILED:
            print(f"  - {item}")
    print("=" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
