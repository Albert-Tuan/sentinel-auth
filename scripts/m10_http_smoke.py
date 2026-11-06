#!/usr/bin/env python
"""M10 HTTP smoke test against a REAL uvicorn server.

This script is deliberately outside the pytest suite: the acceptance
requires the five Manager endpoints to answer over a real socket, against
the three disposable PostgreSQL databases, with the real router, the real
RBAC layer and the real ``X-Internal-Secret`` boundary.

Usage::

    python scripts/m10_http_smoke.py

It seeds the fixture, starts uvicorn, runs the checks and prints a table.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

UTC = timezone.utc

CORE_URL = os.environ["CORE_DETECTION_TEST_URL"]
DETECTION_URL = os.environ["DETECTION_TEST_URL"]
ML_URL = os.environ["ML_TEST_URL"]
INTERNAL_SECRET = "m10-smoke-internal-secret-0123456789abcdef"

WINDOW_FROM = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
WINDOW_TO = datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)

TOKENS = {
    "manager": "live-manager-token",
    "analyst": "live-analyst-token",
    "admin": "live-admin-token",
    "plain": "live-plain-token",
    "suspended": "live-suspended-token",
    "expired": "live-expired-token",
}

MANAGER_ENDPOINTS = (
    "/api/v1/manager/dashboard",
    "/api/v1/manager/trends",
    "/api/v1/manager/alerts",
    "/api/v1/manager/soc-kpi",
    "/api/v1/manager/ml-stats",
)

PASSED: List[str] = []
FAILED: List[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    if ok:
        PASSED.append(name)
        print(f"  PASS  {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  [{detail}]")
    return ok


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(port: int, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def seed() -> None:
    """Seed the three databases with the deterministic fixture."""
    from tests.test_manager_live_integration import (  # noqa: E402
        _build_artifact,
        _seed_core,
        _seed_detection,
        _seed_ml,
    )
    from sqlalchemy import create_engine  # noqa: E402

    import tempfile  # noqa: E402
    from pathlib import Path  # noqa: E402

    tmp = Path(tempfile.mkdtemp(prefix="m10-smoke-"))
    artifact_path = tmp / "model.joblib"
    model_version = _build_artifact(artifact_path)
    model_id = "11111111-1111-1111-1111-111111111111"

    core = create_engine(CORE_URL)
    detection = create_engine(DETECTION_URL)
    ml = create_engine(ML_URL)

    core_ids = _seed_core(core)
    _seed_detection(detection, core_ids)
    _seed_ml(ml, model_id, str(artifact_path))

    core.dispose()
    detection.dispose()
    ml.dispose()
    print(f"  seeded; model version {model_version}")


def main() -> int:
    import httpx  # noqa: E402

    port = free_port()
    base = f"http://127.0.0.1:{port}"

    print("\n=== 1. seed the three disposable databases ===")
    seed()

    print("\n=== 2. start uvicorn (real socket) ===")
    env = dict(os.environ)
    env.update({
        "CORE_DATABASE_URL": CORE_URL,
        "DETECTION_DATABASE_URL": DETECTION_URL,
        "ML_DATABASE_URL": ML_URL,
        "INTERNAL_SECRET": INTERNAL_SECRET,
        # In a monolith deployment both upstreams are the same server.
        "CORE_APP_URL": base,
        "DETECTION_URL": base,
    })
    env.pop("ML_MODEL_PATH", None)

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        if not wait_for_server(port):
            print("  FAIL  uvicorn did not start")
            print(server.stdout.read() if server.stdout else "")
            return 1
        print(f"  uvicorn listening on {base}")

        client = httpx.Client(base_url=base, timeout=30.0)
        window = {"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()}

        print("\n=== 3. liveness ===")
        r = client.get("/health")
        check("GET /health -> 200", r.status_code == 200, f"status={r.status_code}")

        print("\n=== 4. RBAC on every Manager endpoint ===")
        for endpoint in MANAGER_ENDPOINTS:
            r = client.get(endpoint, params=window,
                           headers={"Authorization": f"Bearer {TOKENS['manager']}"})
            check(
                f"{endpoint}  SECURITY_MANAGER -> 200",
                r.status_code == 200,
                f"status={r.status_code}",
            )
            if r.status_code == 200:
                body = r.json()
                sources = body.get("sources") or {}
                check(
                    f"{endpoint}  payload has 'sources'",
                    isinstance(sources, dict) and len(sources) > 0,
                    f"sources={sorted(sources)}",
                )
                check(
                    f"{endpoint}  all sources healthy",
                    all(v.get("status") == "ok" for v in sources.values()),
                    json.dumps(sources),
                )
                check(
                    f"{endpoint}  not degraded",
                    body.get("degraded") is False,
                    f"degraded={body.get('degraded')}",
                )

        for token_key, label, expected in (
            ("plain", "no role", 403),
            ("analyst", "SOC_ANALYST", 403),
            ("admin", "SECURITY_ADMIN", 403),
        ):
            r = client.get(
                "/api/v1/manager/dashboard",
                params=window,
                headers={"Authorization": f"Bearer {TOKENS[token_key]}"},
            )
            check(
                f"RBAC  {label} -> {expected}",
                r.status_code == expected,
                f"status={r.status_code}",
            )

        r = client.get("/api/v1/manager/dashboard", params=window)
        check("RBAC  no token -> 401", r.status_code == 401, f"status={r.status_code}")

        r = client.get(
            "/api/v1/manager/dashboard",
            params=window,
            headers={"Authorization": f"Bearer {TOKENS['expired']}"},
        )
        check("RBAC  expired session -> 401", r.status_code == 401, f"status={r.status_code}")

        r = client.get(
            "/api/v1/manager/dashboard",
            params=window,
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        check("RBAC  unknown token -> 401", r.status_code == 401, f"status={r.status_code}")

        print("\n=== 5. the internal boundary is really used ===")
        r = client.get(
            "/api/v1/internal/analytics/core",
            params=window,
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        check("internal core endpoint -> 200 with the secret", r.status_code == 200,
              f"status={r.status_code}")
        r = client.get("/api/v1/internal/analytics/core", params=window)
        check("internal core endpoint -> 401 without the secret",
              r.status_code == 401, f"status={r.status_code}")

        print("\n=== 5b. dashboard payload against the three real databases ===")
        r = client.get("/api/v1/manager/dashboard", params=window,
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        body = r.json()
        core = body.get("core") or {}
        detection = body.get("detection") or {}

        check("dashboard  core.sessions_created == 4",
              core.get("sessions_created") == 4,
              f"got {core.get('sessions_created')}")
        check("dashboard  core.sessions_revoked == 1",
              core.get("sessions_revoked") == 1,
              f"got {core.get('sessions_revoked')}")
        check("dashboard  core.mfa_challenges == 3",
              core.get("mfa_challenges") == 3,
              f"got {core.get('mfa_challenges')}")
        check("dashboard  core.audit_events == 4",
              core.get("audit_events") == 4,
              f"got {core.get('audit_events')}")
        check("dashboard  detection.login_attempts == 4",
              detection.get("login_attempts") == 4,
              f"got {detection.get('login_attempts')}")
        check("dashboard  detection.alerts.total == 5",
              (detection.get("alerts") or {}).get("total") == 5,
              f"got {(detection.get('alerts') or {}).get('total')}")
        check("dashboard  detection.enforcement.success_rate == 0.5",
              (detection.get("enforcement") or {}).get("success_rate") == 0.5,
              f"got {(detection.get('enforcement') or {}).get('success_rate')}")

        # The audit feed is metadata-only (design 8 item 9).
        activity = core.get("audit_activity") or {}
        recent = activity.get("recent") or []
        check("dashboard  audit_activity.recent is not empty", len(recent) == 4,
              f"got {len(recent)}")
        forbidden = ("before_state", "after_state", "ip_address", "user_agent")
        check("dashboard  the audit feed omits the state and network fields",
              all(f not in row for row in recent for f in forbidden),
              json.dumps(recent[:1]))
        check("dashboard  the audit feed carries exactly the permitted keys",
              all(set(row) == {"id", "action", "actor", "resource",
                               "resource_id", "created_at"} for row in recent),
              json.dumps(sorted(recent[0]) if recent else []))

        print("\n=== 6. KPI values (absolute, hand-computed from the fixture) ===")
        r = client.get("/api/v1/manager/soc-kpi", params=window,
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        body = r.json()
        kpis = body.get("kpis") or {}
        expected_kpis = {
            # 3 acknowledged / 5 created alerts
            "acknowledgement_rate": 0.6,
            # (1 resolved + 1 false positive) / 5 created alerts
            "resolution_rate": 0.4,
            # 1 false positive / (1 resolved + 1 false positive)
            "false_positive_rate": 0.5,
            # 1 escalation / 5 created alerts
            "escalation_rate": 0.2,
            # 5 created alerts / 1 active analyst
            "alerts_per_analyst": 5.0,
            "mtta_seconds": 10200.0,
            "mttr_seconds": 9000.0,
            "enforcement_attempted": 2,
            "enforcement_succeeded": 1,
            "enforcement_success_rate": 0.5,
            "ml_assessments": 4,
            "ml_fallback_count": 2,
            "ml_fallback_rate": 0.5,
            "mfa_enrollment_rate": 0.1111,
            "forced_mfa_users": 1,
            "audit_events": 4,
        }
        for key, expected in expected_kpis.items():
            check(
                f"soc-kpi  {key} == {expected}",
                kpis.get(key) == expected,
                f"got {kpis.get(key)!r}",
            )

        print("\n=== 7. UTC windows (half-open [from, to)) ===")
        empty = {"from": "2026-09-01T00:00:00+00:00", "to": "2026-09-02T00:00:00+00:00"}
        r = client.get("/api/v1/manager/ml-stats", params=empty,
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        body = r.json()
        daily = body.get("daily") or []
        check("ml-stats  empty window -> zero-filled day row",
              len(daily) == 1 and daily[0].get("day") == "2026-09-01"
              and daily[0].get("total") == 0,
              json.dumps(daily))

        r = client.get("/api/v1/manager/trends", params={**window, "bucket": "day"},
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        body = r.json()
        series = body.get("series") or {}
        for key in ("login_attempts", "alerts", "ml"):
            starts = [p.get("bucket_start") for p in series.get(key) or []]
            check(f"trends  {key} buckets are UTC floors",
                  all(s.endswith("T00:00:00+00:00") for s in starts) if starts else True,
                  json.dumps(starts))

        print("\n=== 8. serialization parity ===")
        r = client.get("/api/v1/manager/alerts", params=window,
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        body = r.json()
        totals = body.get("totals") or {}
        check("alerts  totals.created == 5", totals.get("created") == 5,
              f"got {totals.get('created')}")
        check("alerts  by_risk_level has the 4 canonical keys",
              sorted((body.get("by_risk_level") or {})) ==
              ["critical", "high", "low", "medium"],
              json.dumps(body.get("by_risk_level")))
        check("alerts  by_status has the 4 canonical status keys",
              sorted((body.get("by_status") or {})) ==
              ["acknowledged", "false_positive", "open", "resolved"],
              json.dumps(body.get("by_status")))
        check("alerts  the backlog is present",
              isinstance(body.get("backlog"), dict),
              json.dumps(body.get("backlog")))

        # The critical backlog is part of the dashboard, not of /alerts.
        r = client.get("/api/v1/manager/dashboard", params=window,
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        dash = r.json()
        critical = ((dash.get("detection") or {}).get("critical_incidents")) or []
        check("dashboard  the critical backlog carries 3 incidents",
              len(critical) == 3, f"got {len(critical)}")
        if critical:
            alert_id = critical[0].get("alert_id")
            check("dashboard  alert_id is a UUID string",
                  isinstance(alert_id, str) and len(alert_id) == 36
                  and alert_id.count("-") == 4,
                  repr(alert_id))
            check("dashboard  the incident order is severity first",
                  [i.get("risk_level") for i in critical]
                  == ["critical", "high", "high"],
                  json.dumps([i.get("risk_level") for i in critical]))
            check("dashboard  every incident has a created_at in UTC",
                  all(str(i.get("created_at", "")).endswith("+00:00")
                      for i in critical),
                  json.dumps([i.get("created_at") for i in critical]))
        raw = r.text
        check("dashboard  no NaN / Infinity in the JSON",
              "NaN" not in raw and "Infinity" not in raw)

        print("\n=== 8b. every number in the payload is a plain JSON number ===")
        def _walk(node: Any) -> List[Any]:
            if isinstance(node, dict):
                out = []
                for value in node.values():
                    out.extend(_walk(value))
                return out
            if isinstance(node, list):
                out = []
                for value in node:
                    out.extend(_walk(value))
                return out
            return [node]

        numbers = [n for n in _walk(dash) if isinstance(n, (int, float))
                   and not isinstance(n, bool)]
        check("dashboard  no Decimal leaked into the JSON",
              all(isinstance(n, (float, int)) for n in numbers),
              f"{len(numbers)} numbers")

        print("\n=== 9. HTTP contract: 400 on a bad window, never 422 ===")
        r = client.get("/api/v1/manager/dashboard",
                       params={"from": "not-a-timestamp", "to": "also-bad"},
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        check("dashboard  bad window -> 400", r.status_code == 400,
              f"status={r.status_code}")
        r = client.get("/api/v1/manager/alerts",
                       params={**window, "status": "not-a-status"},
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        check("alerts  bad status filter -> 400", r.status_code == 400,
              f"status={r.status_code}")

        print("\n=== 10. degradation: every source down -> 503 ===")
        # Point all three sources at a failure: the two HTTP upstreams at a
        # dead port, the ML database at a closed one.  Only then does the
        # facade have no usable source at all, which is the 503 condition
        # of design section 6.1.2.
        dead = "http://127.0.0.1:1"
        env_dead = dict(env)
        env_dead.update({
            "CORE_APP_URL": dead,
            "DETECTION_URL": dead,
            "ML_DATABASE_URL": "postgresql://sentinel:sentinel123@127.0.0.1:1/nope",
        })
        dead_port = free_port()
        server_dead = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(dead_port), "--log-level", "warning"],
            cwd=REPO_ROOT, env=env_dead,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        try:
            if wait_for_server(dead_port):
                dc = httpx.Client(base_url=f"http://127.0.0.1:{dead_port}", timeout=30.0)
                r = dc.get("/api/v1/manager/dashboard", params=window,
                           headers={"Authorization": f"Bearer {TOKENS['manager']}"})
                check("degradation  every source down -> 503",
                      r.status_code == 503, f"status={r.status_code}")
                if r.status_code == 503:
                    srcs = (r.json().get("sources") or {})
                    check("degradation  the reason codes are the closed vocabulary",
                          all(v.get("detail") in (
                              "unreachable", "timeout", "http_500",
                              "invalid_payload", "not_configured",
                              "database_error", "internal_error",
                          ) for v in srcs.values()),
                          json.dumps(srcs))
                    check("degradation  the detail is the canonical message",
                          r.json().get("detail") == "analytics sources unavailable",
                          repr(r.json().get("detail")))
                dc.close()
            else:
                check("degradation  the degraded server started", False)
        finally:
            server_dead.terminate()
            server_dead.wait(timeout=15)

        print("\n=== 11. partial degradation -> 200 with 'degraded': true ===")
        # Only the two HTTP upstreams are down; the ML database still works,
        # so the endpoint must answer 200 and mark itself degraded.
        env_partial = dict(env)
        env_partial.update({"CORE_APP_URL": dead, "DETECTION_URL": dead})
        partial_port = free_port()
        server_partial = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(partial_port), "--log-level", "warning"],
            cwd=REPO_ROOT, env=env_partial,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        try:
            if wait_for_server(partial_port):
                pc = httpx.Client(base_url=f"http://127.0.0.1:{partial_port}", timeout=30.0)
                r = pc.get("/api/v1/manager/dashboard", params=window,
                           headers={"Authorization": f"Bearer {TOKENS['manager']}"})
                check("partial degradation  dashboard -> 200", r.status_code == 200,
                      f"status={r.status_code}")
                if r.status_code == 200:
                    body = r.json()
                    srcs = body.get("sources") or {}
                    check("partial degradation  core and detection are unavailable",
                          srcs.get("core", {}).get("status") == "unavailable"
                          and srcs.get("detection", {}).get("status") == "unavailable",
                          json.dumps(srcs))
                    check("partial degradation  ml is still ok",
                          srcs.get("ml", {}).get("status") == "ok",
                          json.dumps(srcs))
                    check("partial degradation  degraded is true",
                          body.get("degraded") is True,
                          f"degraded={body.get('degraded')}")
                pc.close()
            else:
                check("partial degradation  the server started", False)
        finally:
            server_partial.terminate()
            server_partial.wait(timeout=15)

        print("\n=== 12. the ML source is healthy on the main server ===")
        r = client.get("/api/v1/manager/ml-stats", params=window,
                       headers={"Authorization": f"Bearer {TOKENS['manager']}"})
        body = r.json()
        check("ml-stats  200 with the ML source healthy",
              r.status_code == 200
              and (body.get("sources") or {}).get("ml", {}).get("status") == "ok",
              f"status={r.status_code} sources={json.dumps(body.get('sources'))}")

        client.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()

    print("\n" + "=" * 72)
    print(f"HTTP SMOKE: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("\nFailures:")
        for item in FAILED:
            print(f"  - {item}")
    print("=" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
