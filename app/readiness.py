"""Readiness probe - the dependency check behind ``GET /ready``.

Design
======

``/health`` is the **liveness** probe: it answers "is this process alive?"
and never consults a dependency.  A database that is down must not cause the
orchestrator to restart the process, because the process is fine.

``/ready`` is the **readiness** probe: it answers "can this process serve
traffic right now?".  It checks the *minimum* dependencies that must be up
for the monolith to accept and serve requests:

* the Core database - every authenticated request needs it;
* the Detection database - the SOC read/write path needs it;
* the ML database - the ML context needs it.

The probe is strictly read-only and cheap:

* it runs ``SELECT 1`` on each context (no table scan, no join, no write);
* it never creates, updates or deletes a row;
* it never loads the ML artifact and never runs an inference.

Missing ML artifact vs. missing database
-----------------------------------------

These are two *different* failures and the probe keeps them apart:

* a **missing ML artifact** is a normal, expected state.  The demo
  deployment ships a staged placeholder whose file does not exist, and the
  Detection Engine falls back to a rule-only score.  The service can serve
  requests, so the probe reports ``degraded`` and still answers ``200``.
* a **missing database** is a hard failure.  The service cannot serve the
  requests that need that context, so the probe answers ``503``.

A third case completes the picture: an **unverifiable** artifact state.
The registry query reads the ``model_versions`` table, so a transaction
holding a lock on it blocks the query indefinitely while ``SELECT 1`` keeps
answering.  When the registry could not be queried, the artifact state is
unknown - and readiness is **fail-closed**: the probe answers ``503``
rather than assuming the artifact is merely missing.

That distinction is what lets an orchestrator keep a working instance in
service while the model artifact is still being provisioned.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession
from starlette.concurrency import run_in_threadpool

from app import db

logger = logging.getLogger(__name__)

#: How long a single dependency check may take before it is reported as
#: unavailable.  The probe must answer fast: an orchestrator polls it
#: every few seconds, and a probe that blocks is worse than no probe.
PROBE_TIMEOUT_SECONDS = 2.0

#: The bounded contexts the readiness probe checks, in a stable order.
REQUIRED_CONTEXTS = (db.CORE, db.DETECTION, db.ML)

#: How long a successful probe result is reused, in seconds.
#:
#: The orchestrator polls readiness frequently (and the deployment
#: verification calls it several times in a row), while a database
#: round-trip is not free.  A short cache keeps the probe cheap without
#: making it stale enough to matter: a database that dies is noticed
#: within one cache window.
CACHE_TTL_SECONDS = 2.0

#: Cached probe result: ``(timestamp, payload)``.
_cache: Optional[tuple] = None


class _Deadline:
    """A monotonic deadline shared by every check in one probe run."""

    def __init__(self, budget: float = PROBE_TIMEOUT_SECONDS) -> None:
        self._expires_at = time.monotonic() + budget

    def remaining(self) -> float:
        return max(0.0, self._expires_at - time.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0.0


def _check_context(context: str, deadline: _Deadline) -> Dict[str, str]:
    """Probe ONE bounded context with a read-only ``SELECT 1``.

    Returns a per-context status dict.  The function never raises: a
    database that cannot be reached is a *reported* result, not an error
    that escapes the probe.

    The statement runs under a server-side ``statement_timeout`` so a
    database that accepts the connection but then stops answering is cut
    off instead of blocking the probe.  The connect timeout in
    ``app/db.py`` covers the other half of the failure: a host that never
    completes the handshake.
    """
    result: Dict[str, str] = {"status": "unavailable"}

    if deadline.expired():
        result["detail"] = "probe deadline exceeded"
        return result

    session: Optional[OrmSession] = None
    try:
        session = db.get_context_session(context)
        # ``SELECT 1`` is the cheapest statement that proves the server
        # answers.  It touches no table and writes nothing.
        #
        # The statement timeout is expressed in milliseconds and derived
        # from the remaining budget, so the probe as a whole stays inside
        # its deadline.
        budget_ms = max(1, int(deadline.remaining() * 1000))
        session.execute(text(f"SET LOCAL statement_timeout = {budget_ms}"))
        session.execute(text("SELECT 1")).scalar()
        result = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - the outcome IS the result
        result = {
            "status": "unavailable",
            "detail": exc.__class__.__name__,
        }
        logger.warning(
            "readiness probe: the %s database is unavailable (%s)",
            context,
            exc.__class__.__name__,
        )
    finally:
        if session is not None:
            # The probe may have been interrupted by the statement timeout,
            # which leaves the session in a failed transaction.  Rolling
            # back first returns the connection to the pool in a clean
            # state; ``close()`` alone would leave the transaction open
            # until the connection is garbage collected.
            try:
                session.rollback()
            except Exception:  # noqa: BLE001 - the probe never fails on cleanup
                pass
            session.close()

    return result


def _check_ml_artifact(deadline: _Deadline) -> Dict[str, str]:
    """Report the ML artifact state WITHOUT loading the model.

    The probe only asks the model *registry* whether an artifact is
    configured and whether the file exists.  It never deserialises the
    artifact, never runs an inference and never writes an inference log.

    The registry query is subject to the SAME deadline as the database
    checks, and it is bounded twice over:

    * the probe does not start the query at all when the deadline has
      already been spent by the database checks;
    * the query itself runs under a server-side ``statement_timeout``
      derived from the remaining budget.

    Both are necessary.  The registry query reads the ``model_versions``
    table, so a transaction holding an ``ACCESS EXCLUSIVE`` lock on it
    blocks the query indefinitely - the server simply queues the reader
    behind the writer.  ``SELECT 1`` keeps working in that situation, so
    the database check reports ``ok`` while the artifact check would hang
    forever.  Without the bound, ``/ready`` would never answer.

    The three outcomes are kept apart:

    * the artifact is **not configured** or its **file is missing** →
      ``degraded``.  The Detection Engine falls back to a rule-only score,
      so the service still serves traffic.
    * the registry could **not be queried** (timeout, unreachable
      database, a locked table) → ``unavailable``.  The artifact state
      could not be verified, and readiness is **fail-closed**: the probe
      must not claim the service is ready when it could not check a
      dependency it needs.
    * the deadline was already spent → ``unavailable`` as well, for the
      same reason.
    """
    if deadline.expired():
        return {
            "status": "unavailable",
            "detail": "probe deadline exceeded before the registry query",
        }

    session: Optional[OrmSession] = None
    try:
        from app.ml import resolve_model_source

        session = db.get_context_session(db.ML)

        # The registry query reads a real table, so it needs the same
        # server-side bound as the database checks.
        budget_ms = max(1, int(deadline.remaining() * 1000))
        session.execute(text(f"SET LOCAL statement_timeout = {budget_ms}"))

        path, _ = resolve_model_source(session)
        if path.exists():
            return {"status": "ready"}
        return {
            "status": "degraded",
            "detail": "the configured ML artifact file does not exist",
        }
    except FileNotFoundError:
        # No artifact is configured at all.  This is a normal, expected
        # state - the service falls back to a rule-only score.
        return {
            "status": "degraded",
            "detail": "no active ML artifact is configured",
        }
    except Exception as exc:  # noqa: BLE001 - the outcome IS the result
        # The registry could not be queried, so the artifact state is
        # UNKNOWN.  Reporting this as "the artifact is merely missing"
        # would be a lie that turns a broken dependency into a healthy
        # answer.
        logger.warning(
            "readiness probe: the ML registry could not be queried (%s)",
            exc.__class__.__name__,
        )
        return {
            "status": "unavailable",
            "detail": exc.__class__.__name__,
        }
    finally:
        if session is not None:
            try:
                session.rollback()
            except Exception:  # noqa: BLE001 - cleanup never fails the probe
                pass
            session.close()


def _probe() -> Dict:
    """Run one complete readiness probe and return its payload."""
    deadline = _Deadline()

    checks: Dict[str, Dict[str, str]] = {}
    for context in REQUIRED_CONTEXTS:
        checks[context] = _check_context(context, deadline)

    # The artifact state is only meaningful when the ML database answered.
    if checks.get(db.ML, {}).get("status") == "ok":
        checks["ml_artifact"] = _check_ml_artifact(deadline)
    else:
        checks["ml_artifact"] = {
            "status": "unknown",
            "detail": "the ML database is unavailable",
        }

    # The service is ready when every required context answered AND the
    # ML artifact state could be verified.
    #
    # The ML artifact participates in the decision in two ways:
    #
    # * a missing artifact (``degraded``) does NOT take the service out of
    #   service - the Detection Engine falls back to a rule-only score;
    # * an UNVERIFIED artifact state (``unavailable``) DOES take it out of
    #   service.  Readiness is fail-closed: when the registry could not be
    #   queried, the probe must not report the service as ready on the
    #   assumption that the artifact is merely missing.
    required_ok = all(
        checks[context]["status"] == "ok" for context in REQUIRED_CONTEXTS
    )
    artifact = checks.get("ml_artifact", {})
    artifact_verified = artifact.get("status") in ("ready", "degraded")
    degraded = any(
        entry["status"] == "degraded" for entry in checks.values()
    )

    ready = required_ok and artifact_verified

    payload: Dict = {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
    }
    if ready and degraded:
        payload["status"] = "ready"
        payload["degraded"] = True
    return payload


def readiness_payload() -> Dict:
    """Return the readiness payload, using the short-lived cache.

    The cache only holds *successful* probes.  A failing probe is never
    cached, so a recovery is reported immediately.
    """
    global _cache

    now = time.monotonic()
    if _cache is not None:
        cached_at, cached_payload = _cache
        if now - cached_at < CACHE_TTL_SECONDS and cached_payload["status"] == "ready":
            return cached_payload

    payload = _probe()
    if payload["status"] == "ready":
        _cache = (now, payload)
    else:
        _cache = None
    return payload


def reset_readiness_cache() -> None:
    """Drop the cached probe result.  Used by tests and by the deployment."""
    global _cache
    _cache = None


async def readiness_payload_async() -> Dict:
    """Return the readiness payload without blocking the event loop.

    The probe talks to PostgreSQL through the **synchronous** SQLAlchemy
    driver, so running it directly inside an ``async def`` endpoint holds
    the event loop for the whole probe.  When a database is unreachable the
    probe takes its full budget - two seconds - and during that time every
    OTHER request in the process (a login, the SOC alert list) is stalled,
    even though the process is perfectly healthy.

    The probe therefore runs in a worker thread.  The event loop keeps
    serving traffic while the thread waits for the database, and the
    endpoint answers exactly as before.
    """
    return await run_in_threadpool(readiness_payload)
