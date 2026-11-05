"""Detection-owned internal analytics provider.

Implements ``GET /api/v1/internal/analytics/detection`` - the aggregate
endpoint the Security-Manager facade (``app/manager.py``) calls over HTTP.

Ownership
---------
This module is owned by the **Detection context**.  It reads only from
``sentinel_detection`` (via :func:`app.db.get_detection_db`) and never
imports the Core or ML session dependencies.  The Manager facade owns no SQL
for these facts: it forwards ``from`` / ``to`` / ``bucket`` / ``status`` /
``risk_level`` verbatim and maps the payload it gets back.

Normative source
----------------
``docs/M9-MANAGER-ANALYTICS-DESIGN.md`` sections 4.0 (shared contract rules),
4.1 (this endpoint), 5.1 (population rules) and 5.3 (bucket algorithm), plus
``docs/M9-MANAGER-ANALYTICS-REFERENCE.md`` section R1 (the SQL sketches this
module implements).

The behavioural rules that are easy to get wrong, and that this module
implements deliberately:

* **Event-based vs current-status acknowledgement.**  ``alerts.acknowledged_count``
  counts alerts with at least one ``acknowledged`` *timeline event* (created
  before ``to``); ``alerts.by_status.acknowledged`` counts alerts whose
  *current* status is ``acknowledged``.  They are different numbers on the same
  fixture and must stay that way (design 4.1 / 5.1 rule 6).
* **MTTA population.**  For every alert created inside the window that has an
  ``acknowledged`` event before ``to``: the *earliest* such event, minus the
  alert's ``created_at``.  An alert acknowledged only *after* ``to``
  contributes nothing at all - not to MTTA and not to the acknowledgement
  count (design 5.1 rules 2 and 3).
* **MTTR population.**  Alerts created in the window whose *current* status is
  ``resolved`` **and** whose ``resolved_at`` falls inside ``[from, to)``.
  Both window predicates are required, and false positives are excluded
  entirely (design 5.1 rule 4, reference R1.2).
* **Structured breakdowns.**  ``by_rule`` / ``by_ml_reason`` read the structured
  ``alerts.detection_scores`` payload (``rule_hits[].rule_name`` and
  ``ml_reason_codes[]``), never the free-text ``detection_reason`` whose
  cardinality is unbounded (design 3.5).  A malformed payload is *skipped*,
  never raised.
* **Critical incidents are a backlog.**  ``critical_incidents`` is the current
  open/acknowledged high+critical backlog: top 10, severity first then oldest
  first.  The reporting window and the ``status`` / ``risk_level`` filters do
  **not** filter it (design 4.0, 8 item 8, reference R1.8).  For the same
  reason ``alerts.critical_open`` is a current-backlog count and is not
  window-scoped either (design 4.1 field notes).
* **Half-open windows.**  Every window predicate is ``[from, to)`` and every
  timestamp is timezone-aware UTC (design 4.0).
* **Zero-filled buckets.**  The series carries every bucket of the window, even
  the empty ones, with UTC-floored labels (design 5.3).

Cross-database parity
---------------------
The production database is PostgreSQL; the unit-test suite runs on SQLite.
Both must produce identical numbers (design 5.2), so this module never uses a
PostgreSQL-only SQL construct for anything that is counted:

* the bucketing expression is dialect-specific (PostgreSQL ``date_trunc`` with
  an explicit ``AT TIME ZONE 'UTC'``, SQLite ``strftime``) but both are
  normalised to the *same* UTC bucket grid, which is computed here in Python;
* the JSON payloads (``detection_scores``, ``detection_logs.details``) are
  read and interpreted in Python, so a JSONB boolean and a SQLite JSON boolean
  are counted identically;
* the MTTA / MTTR durations are computed in Python from the two timestamps, so
  the arithmetic is identical on both backends.

The endpoint is read-only: it never writes to the database and never touches
the Detection scoring pipeline or the SOC lifecycle.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session as OrmSession

from app.db import get_detection_db
from app.internal_auth import verify_internal_secret
from app.models import (
    Alert,
    AlertTimeline,
    DetectionLog,
    LoginAttempt,
    Policy,
    RiskAssessment,
    SocAnalyst,
)
from app.time_utils import as_utc, utc_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/internal", tags=["detection-internal"])


# =============================================================================
# Vocabularies (design reference R2)
# =============================================================================

#: The four canonical alert statuses - source of truth is the CHECK
#: constraint ``chk_alerts_status`` (``app/alerts.py::ALERT_STATUSES``).
ALERT_STATUSES: Tuple[str, ...] = ("open", "acknowledged", "resolved", "false_positive")

#: The canonical risk levels - ``chk_alerts_risk_level`` /
#: ``chk_login_attempts_risk_level`` (``app/alerts.py::RISK_LEVELS``).
RISK_LEVELS: Tuple[str, ...] = ("low", "medium", "high", "critical")

#: The canonical login outcomes - ``chk_login_attempts_outcome``.
LOGIN_OUTCOMES: Tuple[str, ...] = (
    "success", "failure", "mfa_required", "mfa_success",
    "mfa_failed", "blocked", "locked", "rate_limited",
)

#: The canonical detection decisions - the inline CHECK on
#: ``login_attempts.detection_decision``.
DETECTION_DECISIONS: Tuple[str, ...] = ("allow", "challenge", "block")

#: Bucket granularities (design 3.2).
BUCKETS: Tuple[str, ...] = ("hour", "day")

#: ``bucket=auto`` resolves from the window length (design 3.2 rule 5).
BUCKET_AUTO = "auto"

#: Maximum window and bucket counts (design 3.2 rules 2-4).
MAX_WINDOW_DAYS = 366
MAX_HOUR_WINDOW_DAYS = 31
MAX_BUCKETS = {"hour": 400, "day": 366}

#: ``bucket=auto`` becomes ``day`` when the window is longer than this.
AUTO_BUCKET_HOURS = 72

#: The risk levels that make an alert an incident (design 3.3).
INCIDENT_RISK_LEVELS: Tuple[str, ...] = ("high", "critical")

#: The statuses that keep an alert in the incident backlog (design 3.3).
INCIDENT_STATUSES: Tuple[str, ...] = ("open", "acknowledged")

#: The maximum number of incidents returned (design 3.3).
MAX_CRITICAL_INCIDENTS = 10

#: The maximum number of rows in a top-N breakdown (design 3.5).
MAX_BREAKDOWN_ROWS = 20


# =============================================================================
# Small helpers
# =============================================================================

def _bad_request(detail: str) -> HTTPException:
    """A 400 with the design's error shape (design 4.0 / 6.1.2)."""
    return HTTPException(status_code=400, detail=detail)


def _iso(value: datetime) -> str:
    """ISO-8601 UTC representation of an instant."""
    return as_utc(value).isoformat()


def _round(value: Optional[float], digits: int) -> Optional[float]:
    """Round to ``digits`` decimals; ``None`` stays ``None`` (never ``0``)."""
    if value is None:
        return None
    return round(float(value), digits)


def _mean(values: Sequence[float]) -> Optional[float]:
    """Arithmetic mean, or ``None`` over an empty population (design 5)."""
    if not values:
        return None
    return sum(values) / len(values)


def _as_float(value: Any) -> Optional[float]:
    """Coerce a DB numeric (``Decimal`` on PostgreSQL, ``float`` on SQLite)."""
    if value is None:
        return None
    return float(value)


def _is_true(value: Any) -> bool:
    """Interpret a JSON boolean that may arrive as ``true``, ``"true"`` or ``1``.

    PostgreSQL's ``details->>'enforced' = 'true'`` compares the *text* form of
    the JSON value, so both a JSON boolean and a JSON string ``"true"`` count
    as enforced.  The SQLite path sees the real Python boolean.  Normalising
    here keeps both backends on the same number (design 7.0.1).
    """
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() == "true"
    if isinstance(value, (int, float)):
        return value == 1
    return False


def _parse_dt_param(name: str, value: Optional[str]) -> Optional[datetime]:
    """Parse a window parameter, or raise a 400.

    The parameter is taken as a raw string so an unparseable timestamp answers
    **400** instead of FastAPI's default 422 (design 6.1.2).  A naive
    timestamp is treated as UTC (design 3.2 rule 6).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _bad_request(f"'{name}' must be an ISO-8601 datetime, got {text!r}")
    return as_utc(parsed)


def _floor_bucket(ts: datetime, bucket: str) -> datetime:
    """Floor a UTC instant to the start of its bucket (design 5.3)."""
    if bucket == "hour":
        return ts.replace(minute=0, second=0, microsecond=0)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_step(bucket: str) -> timedelta:
    return timedelta(hours=1) if bucket == "hour" else timedelta(days=1)


def _bucket_starts(start: datetime, end: datetime, bucket: str) -> List[datetime]:
    """The full list of bucket starts - the zero-fill scaffolding (design 5.3).

    ``start`` is floored, so the first bucket may begin before ``from``; the
    SQL predicate still excludes data before ``from``, but the label stays
    aligned to the wall clock.
    """
    step = _bucket_step(bucket)
    cursor = _floor_bucket(start, bucket)
    out: List[datetime] = []
    while cursor < end:
        out.append(cursor)
        cursor += step
    return out


def _resolve_window(
    from_: Optional[datetime],
    to: Optional[datetime],
    bucket: Optional[str],
) -> Tuple[datetime, datetime, str]:
    """Validate the window parameters (design 3.2).

    Every violation is a 400, raised before any query runs.
    """
    end = as_utc(to) if to is not None else utc_now()
    start = as_utc(from_) if from_ is not None else end - timedelta(hours=24)

    if start >= end:
        raise _bad_request("'from' must be strictly earlier than 'to'")

    span = end - start
    if span > timedelta(days=MAX_WINDOW_DAYS):
        raise _bad_request(f"window must not exceed {MAX_WINDOW_DAYS} days")

    if bucket is not None and bucket not in BUCKETS + (BUCKET_AUTO,):
        raise _bad_request(f"'bucket' must be one of: {', '.join(BUCKETS + (BUCKET_AUTO,))}")

    if bucket is None or bucket == BUCKET_AUTO:
        resolved = "day" if span > timedelta(hours=AUTO_BUCKET_HOURS) else "hour"
    else:
        resolved = bucket

    if resolved == "hour" and span > timedelta(days=MAX_HOUR_WINDOW_DAYS):
        raise _bad_request(
            f"bucket=hour requires a window of at most {MAX_HOUR_WINDOW_DAYS} days"
        )

    if len(_bucket_starts(start, end, resolved)) > MAX_BUCKETS[resolved]:
        raise _bad_request(
            f"window produces more than {MAX_BUCKETS[resolved]} {resolved} buckets"
        )

    return start, end, resolved


def _validate_filter(name: str, value: Optional[str], vocabulary: Sequence[str]) -> Optional[str]:
    """Validate an optional vocabulary filter (design 3.2 rule 7)."""
    if value is None:
        return None
    if value not in vocabulary:
        raise _bad_request(f"'{name}' must be one of: {', '.join(vocabulary)}")
    return value


# =============================================================================
# Bucket expressions
# =============================================================================

def _bucket_label(column, bucket: str, dialect_name: str):
    """A SQL expression grouping rows into UTC buckets.

    PostgreSQL truncates in the **session** timezone by default, which would
    shift a day boundary on a non-UTC server (design 6.4).  The explicit
    ``AT TIME ZONE 'UTC'`` makes the truncation UTC-based; SQLite's
    ``strftime`` works on the UTC wall clock that the application stores.
    """
    if dialect_name == "postgresql":
        return func.date_trunc(
            literal_column(f"'{bucket}'"),
            column.op("AT TIME ZONE")(literal_column("'UTC'")),
        )
    fmt = "%Y-%m-%d %H:00:00" if bucket == "hour" else "%Y-%m-%d 00:00:00"
    return func.strftime(literal_column(f"'{fmt}'"), column)


def _label_to_bucket_start(label: Any) -> Optional[datetime]:
    """Normalise a bucket label from either dialect to a UTC bucket start."""
    if label is None:
        return None
    if isinstance(label, datetime):
        return as_utc(label)
    text = str(label).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return as_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    try:
        return as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


# =============================================================================
# Aggregate helpers
# =============================================================================

def _conditional_counts(
    db: OrmSession,
    column,
    vocabulary: Sequence[str],
    conditions: Sequence[Any],
) -> Dict[str, int]:
    """Count rows per vocabulary value in a single pass, zero-filled."""
    columns = [
        func.coalesce(
            func.sum(case((column == value, 1), else_=0)), 0
        ).label(f"c_{index}")
        for index, value in enumerate(vocabulary)
    ]
    stmt = select(*columns).where(*conditions)
    row = db.execute(stmt).one()
    return {
        value: int(row[index] or 0)
        for index, value in enumerate(vocabulary)
    }


def _alert_conditions(
    start: datetime,
    end: datetime,
    status: Optional[str],
    risk_level: Optional[str],
) -> List[Any]:
    """The alert population: created in ``[from, to)`` plus the filters.

    The ``status`` / ``risk_level`` filters *select the alert population*
    (design 3.2): they are applied before every breakdown, so every
    window-scoped alert aggregate describes the same filtered population.
    """
    conditions: List[Any] = [
        Alert.created_at >= start,
        Alert.created_at < end,
    ]
    if status is not None:
        conditions.append(Alert.status == status)
    if risk_level is not None:
        conditions.append(Alert.risk_level == risk_level)
    return conditions


def _breakdown_rows(counter: Dict[str, int], key: str) -> List[Dict[str, Any]]:
    """Top-N breakdown rows: descending by count, ties broken by name.

    A name that cannot be read is skipped, never raised (design 3.5).
    """
    rows = [
        {key: name, "count": int(count)}
        for name, count in counter.items()
        if name
    ]
    rows.sort(key=lambda row: (-row["count"], row[key]))
    return rows[:MAX_BREAKDOWN_ROWS]


# =============================================================================
# Section builders
# =============================================================================

def _login_attempts_section(db: OrmSession, start: datetime, end: datetime) -> Dict[str, Any]:
    """The ``login_attempts`` block.

    The window predicate uses ``login_attempts.timestamp`` - **not**
    ``created_at`` (reference R1.5).
    """
    conditions = [LoginAttempt.timestamp >= start, LoginAttempt.timestamp < end]

    total = int(db.execute(
        select(func.count()).select_from(LoginAttempt).where(*conditions)
    ).scalar_one())

    by_outcome = _conditional_counts(db, LoginAttempt.outcome, LOGIN_OUTCOMES, conditions)
    by_risk_level = _conditional_counts(db, LoginAttempt.risk_level, RISK_LEVELS, conditions)
    by_decision = _conditional_counts(
        db, LoginAttempt.detection_decision, DETECTION_DECISIONS, conditions
    )

    # ``avg_combined_score`` needs the assessment of each attempt; the join is
    # 1:1 (``uq_risk_assessment_login``), so it cannot multiply rows.
    avg_combined = db.execute(
        select(func.avg(RiskAssessment.combined_score))
        .select_from(LoginAttempt)
        .outerjoin(RiskAssessment, RiskAssessment.login_attempt_id == LoginAttempt.id)
        .where(*conditions)
    ).scalar_one()

    return {
        "total": total,
        "by_outcome": by_outcome,
        "by_risk_level": by_risk_level,
        "by_decision": by_decision,
        "avg_combined_score": _round(_as_float(avg_combined), 4),
    }


def _risk_assessments_section(db: OrmSession, start: datetime, end: datetime) -> Dict[str, Any]:
    """The ``risk_assessments`` block.

    The window anchor is ``risk_assessments.created_at`` (design 5.1 rule 11).
    """
    conditions = [RiskAssessment.created_at >= start, RiskAssessment.created_at < end]

    total = int(db.execute(
        select(func.count()).select_from(RiskAssessment).where(*conditions)
    ).scalar_one())

    ml_success = int(db.execute(
        select(func.count()).select_from(RiskAssessment).where(
            *conditions, RiskAssessment.ml_status == "success"
        )
    ).scalar_one())
    ml_unavailable = int(db.execute(
        select(func.count()).select_from(RiskAssessment).where(
            *conditions, RiskAssessment.ml_status == "unavailable"
        )
    ).scalar_one())
    ml_error = int(db.execute(
        select(func.count()).select_from(RiskAssessment).where(
            *conditions, RiskAssessment.ml_status == "error"
        )
    ).scalar_one())

    # Fallback = every assessment whose ML did not succeed.  A NULL
    # ``ml_status`` counts as a fallback (design 5.1 rule 11), which is why the
    # numerator is ``total - ml_success`` rather than the two named buckets.
    fallback = max(0, total - ml_success)
    fallback_rate = None if total == 0 else round(fallback / total, 4)

    return {
        "total": total,
        "ml_success": ml_success,
        "ml_unavailable": ml_unavailable,
        "ml_error": ml_error,
        "fallback_rate": fallback_rate,
    }


def _alerts_section(
    db: OrmSession,
    start: datetime,
    end: datetime,
    status: Optional[str],
    risk_level: Optional[str],
) -> Dict[str, Any]:
    """The ``alerts`` block (design 4.1).

    Everything here is window-scoped over the filtered alert population, with
    one deliberate exception: ``critical_open`` is a **current-backlog** count,
    exactly like ``critical_incidents`` (design 4.1 field notes).
    """
    conditions = _alert_conditions(start, end, status, risk_level)

    created = int(db.execute(
        select(func.count()).select_from(Alert).where(*conditions)
    ).scalar_one())

    by_status = _conditional_counts(db, Alert.status, ALERT_STATUSES, conditions)
    by_risk_level = _conditional_counts(db, Alert.risk_level, RISK_LEVELS, conditions)

    # --- event-based acknowledgement ------------------------------------
    # For every alert of the population that has an ``acknowledged`` event
    # before ``to``: the earliest such event (design 5.1 rules 2 and 3).
    ack_rows = db.execute(
        select(Alert.created_at, func.min(AlertTimeline.created_at).label("ack_at"))
        .select_from(Alert)
        .join(AlertTimeline, AlertTimeline.alert_id == Alert.id)
        .where(
            *conditions,
            AlertTimeline.event_type == "acknowledged",
            AlertTimeline.created_at < end,
        )
        .group_by(Alert.id, Alert.created_at)
    ).all()

    mtta_durations: List[float] = []
    for created_at, ack_at in ack_rows:
        if ack_at is None:
            continue
        mtta_durations.append((as_utc(ack_at) - as_utc(created_at)).total_seconds())

    acknowledged_count = len(mtta_durations)

    # --- escalation (event-based) ----------------------------------------
    escalated_count = int(db.execute(
        select(func.count(func.distinct(Alert.id)))
        .select_from(Alert)
        .join(AlertTimeline, AlertTimeline.alert_id == Alert.id)
        .where(
            *conditions,
            AlertTimeline.event_type == "escalated",
            AlertTimeline.created_at < end,
        )
    ).scalar_one())

    # --- resolution (current status, resolution event inside the window) --
    mttr_rows = db.execute(
        select(Alert.created_at, Alert.resolved_at)
        .select_from(Alert)
        .where(
            *conditions,
            Alert.status == "resolved",
            Alert.resolved_at >= start,
            Alert.resolved_at < end,
        )
    ).all()

    mttr_durations: List[float] = []
    for created_at, resolved_at in mttr_rows:
        if resolved_at is None:
            continue
        mttr_durations.append((as_utc(resolved_at) - as_utc(created_at)).total_seconds())

    mttr_population = len(mttr_durations)

    # --- backlog ----------------------------------------------------------
    unassigned_open = int(db.execute(
        select(func.count()).select_from(Alert).where(
            *conditions,
            Alert.status == "open",
            Alert.assigned_to_id.is_(None),
        )
    ).scalar_one())

    # ``critical_open`` is a current-backlog count: it is NOT window-scoped
    # and NOT filtered, so it matches the critical incident backlog.
    critical_open = int(db.execute(
        select(func.count()).select_from(Alert).where(
            Alert.status == "open",
            Alert.risk_level == "critical",
        )
    ).scalar_one())

    oldest_open = db.execute(
        select(func.min(Alert.created_at)).select_from(Alert).where(
            *conditions, Alert.status == "open"
        )
    ).scalar_one()
    oldest_open_age_hours = None
    if oldest_open is not None:
        oldest_open_age_hours = _round(
            (utc_now() - as_utc(oldest_open)).total_seconds() / 3600.0, 1
        )

    # --- structured breakdowns -------------------------------------------
    by_rule = _rule_breakdown(db, conditions)
    by_ml_reason = _ml_reason_breakdown(db, conditions)

    return {
        "created": created,
        "by_status": by_status,
        "by_risk_level": by_risk_level,
        "by_rule": by_rule,
        "by_ml_reason": by_ml_reason,
        "acknowledged_count": acknowledged_count,
        "resolved_count": by_status.get("resolved", 0),
        "false_positive_count": by_status.get("false_positive", 0),
        "mttr_population": mttr_population,
        "escalated_count": escalated_count,
        "unassigned_open": unassigned_open,
        "critical_open": critical_open,
        "mtta_seconds": _round(_mean(mtta_durations), 1),
        "mttr_seconds": _round(_mean(mttr_durations), 1),
        "oldest_open_age_hours": oldest_open_age_hours,
    }


def _rule_breakdown(db: OrmSession, conditions: Sequence[Any]) -> List[Dict[str, Any]]:
    """``by_rule`` - the triggered rules of the structured score payload.

    The payload is read and interpreted in Python so that a malformed or
    missing ``detection_scores`` is skipped rather than raised, and so that
    PostgreSQL and SQLite produce identical numbers (design 3.5, 5.2).
    """
    rows = db.execute(
        select(Alert.detection_scores).select_from(Alert).where(*conditions)
    ).all()

    counter: Dict[str, int] = {}
    for (payload,) in rows:
        if not isinstance(payload, dict):
            continue
        hits = payload.get("rule_hits")
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            if not _is_true(hit.get("triggered")):
                continue
            name = hit.get("rule_name")
            if not isinstance(name, str) or not name:
                continue
            counter[name] = counter.get(name, 0) + 1

    return _breakdown_rows(counter, "rule")


def _ml_reason_breakdown(db: OrmSession, conditions: Sequence[Any]) -> List[Dict[str, Any]]:
    """``by_ml_reason`` - the ML reason codes of the structured payload."""
    rows = db.execute(
        select(Alert.detection_scores).select_from(Alert).where(*conditions)
    ).all()

    counter: Dict[str, int] = {}
    for (payload,) in rows:
        if not isinstance(payload, dict):
            continue
        codes = payload.get("ml_reason_codes")
        if not isinstance(codes, list):
            continue
        for code in codes:
            if not isinstance(code, str) or not code:
                continue
            counter[code] = counter.get(code, 0) + 1

    return _breakdown_rows(counter, "code")


def _analysts_section(db: OrmSession) -> Dict[str, Any]:
    """The ``analysts`` block - a point-in-time count (design 5.1 rule 9)."""
    active = int(db.execute(
        select(func.count()).select_from(SocAnalyst).where(SocAnalyst.is_active.is_(True))
    ).scalar_one())
    return {"active": active}


def _enforcement_section(db: OrmSession, start: datetime, end: datetime) -> Dict[str, Any]:
    """The ``enforcement`` block (design 5.1 rule 10).

    ``details->>'enforced' = 'true'`` is evaluated in Python because the JSON
    representation differs between JSONB (PostgreSQL) and JSON (SQLite);
    both are normalised to the same integer count (design 7.0.1).
    """
    rows = db.execute(
        select(DetectionLog.details)
        .select_from(DetectionLog)
        .where(
            DetectionLog.stage == "action_sent",
            DetectionLog.created_at >= start,
            DetectionLog.created_at < end,
        )
    ).all()

    attempted = len(rows)
    succeeded = 0
    for (details,) in rows:
        if isinstance(details, dict) and _is_true(details.get("enforced")):
            succeeded += 1

    success_rate = None if attempted == 0 else round(succeeded / attempted, 4)
    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "success_rate": success_rate,
    }


def _critical_incidents(db: OrmSession) -> List[Dict[str, Any]]:
    """The critical incident backlog (design 3.3 / 4.1, reference R1.8).

    This list is deliberately **not** window-scoped and **not** filtered by the
    ``status`` / ``risk_level`` query parameters: an open critical alert from
    three days ago is still an open critical alert.  It is capped at 10 and
    ordered by severity first, then oldest first.
    """
    rows = db.execute(
        select(
            Alert.id,
            Alert.risk_level,
            Alert.status,
            Alert.created_at,
            Alert.detection_reason,
            LoginAttempt.username_attempted,
            LoginAttempt.user_id,
            RiskAssessment.combined_score,
            SocAnalyst.display_name,
        )
        .select_from(Alert)
        .join(LoginAttempt, LoginAttempt.id == Alert.login_attempt_id)
        .outerjoin(
            RiskAssessment, RiskAssessment.login_attempt_id == Alert.login_attempt_id
        )
        .outerjoin(SocAnalyst, SocAnalyst.id == Alert.assigned_to_id)
        .where(
            Alert.risk_level.in_(INCIDENT_RISK_LEVELS),
            Alert.status.in_(INCIDENT_STATUSES),
        )
        .order_by(
            case((Alert.risk_level == "critical", 0), else_=1),
            Alert.created_at.asc(),
        )
        .limit(MAX_CRITICAL_INCIDENTS)
    ).all()

    now = utc_now()
    incidents: List[Dict[str, Any]] = []
    for row in rows:
        (
            alert_id, risk_level, status, created_at, detection_reason,
            username, user_id, combined_score, display_name,
        ) = row
        incidents.append({
            "alert_id": str(alert_id),
            "risk_level": risk_level,
            "status": status,
            "created_at": _iso(created_at),
            "subject": {
                "username": username,
                "user_id": str(user_id) if user_id is not None else None,
            },
            "detection_reason": detection_reason,
            "combined_score": _round(_as_float(combined_score), 4),
            "assigned_to": display_name,
            "age_hours": _round((now - as_utc(created_at)).total_seconds() / 3600.0, 1),
        })
    return incidents


def _policy_section(db: OrmSession) -> Dict[str, Any]:
    """The active detection policy - point-in-time, not window-scoped.

    ``policies`` lives in ``sentinel_detection``, so Detection owns this fact
    and the Manager facade never looks it up (design 4.1).
    """
    row = db.execute(
        select(Policy.version, Policy.id)
        .select_from(Policy)
        .where(Policy.is_active.is_(True))
        .limit(1)
    ).first()
    if row is None:
        return {"active_version": None, "active_policy_id": None}
    version, policy_id = row
    return {
        "active_version": version,
        "active_policy_id": str(policy_id),
    }


def _series(
    db: OrmSession,
    start: datetime,
    end: datetime,
    bucket: str,
    status: Optional[str],
    risk_level: Optional[str],
) -> List[Dict[str, Any]]:
    """The flat, zero-filled series (design 4.1 / 5.3).

    Every bucket of the window is present, even when it holds no data.  The
    alert-derived counters use the same filtered alert population as the
    ``alerts`` block.
    """
    dialect_name = db.get_bind().dialect.name
    grid = _bucket_starts(start, end, bucket)

    # --- login attempts per bucket ---------------------------------------
    attempt_label = _bucket_label(LoginAttempt.timestamp, bucket, dialect_name).label("bucket_start")
    attempt_rows = db.execute(
        select(
            attempt_label,
            func.count(),
            func.avg(RiskAssessment.combined_score),
        )
        .select_from(LoginAttempt)
        .outerjoin(RiskAssessment, RiskAssessment.login_attempt_id == LoginAttempt.id)
        .where(LoginAttempt.timestamp >= start, LoginAttempt.timestamp < end)
        .group_by(attempt_label)
    ).all()

    attempt_buckets: Dict[datetime, Dict[str, Any]] = {}
    for label, total, avg_combined in attempt_rows:
        bucket_start = _label_to_bucket_start(label)
        if bucket_start is None:
            continue
        attempt_buckets[bucket_start] = {
            "login_attempts": int(total),
            "avg_combined_score": _round(_as_float(avg_combined), 4),
        }

    # The per-outcome / per-risk breakdown is counted in one extra pass over
    # the same rows so that the counts are exact per bucket.
    outcome_label = _bucket_label(LoginAttempt.timestamp, bucket, dialect_name).label("bucket_start")
    outcome_rows = db.execute(
        select(outcome_label, LoginAttempt.outcome, func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.timestamp >= start, LoginAttempt.timestamp < end)
        .group_by(outcome_label, LoginAttempt.outcome)
    ).all()
    for label, outcome, count in outcome_rows:
        bucket_start = _label_to_bucket_start(label)
        if bucket_start is None or outcome is None:
            continue
        entry = attempt_buckets.setdefault(
            bucket_start,
            {"login_attempts": 0, "avg_combined_score": None},
        )
        entry.setdefault("by_outcome", {})
        entry["by_outcome"][str(outcome)] = int(count)

    risk_label = _bucket_label(LoginAttempt.timestamp, bucket, dialect_name).label("bucket_start")
    risk_rows = db.execute(
        select(risk_label, LoginAttempt.risk_level, func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.timestamp >= start, LoginAttempt.timestamp < end)
        .group_by(risk_label, LoginAttempt.risk_level)
    ).all()
    for label, level, count in risk_rows:
        bucket_start = _label_to_bucket_start(label)
        if bucket_start is None or level is None:
            continue
        entry = attempt_buckets.setdefault(
            bucket_start,
            {"login_attempts": 0, "avg_combined_score": None},
        )
        entry.setdefault("by_risk_level", {})
        entry["by_risk_level"][str(level)] = int(count)

    # --- alerts per bucket -------------------------------------------------
    alert_label = _bucket_label(Alert.created_at, bucket, dialect_name).label("bucket_start")
    alert_rows = db.execute(
        select(alert_label, Alert.status, func.count())
        .select_from(Alert)
        .where(*_alert_conditions(start, end, status, risk_level))
        .group_by(alert_label, Alert.status)
    ).all()
    alert_buckets: Dict[datetime, Dict[str, Any]] = {}
    for label, alert_status, count in alert_rows:
        bucket_start = _label_to_bucket_start(label)
        if bucket_start is None:
            continue
        entry = alert_buckets.setdefault(
            bucket_start, {"alerts_created": 0, "alerts_by_status": {}}
        )
        entry["alerts_created"] += int(count)
        if alert_status is not None:
            entry["alerts_by_status"][str(alert_status)] = (
                entry["alerts_by_status"].get(str(alert_status), 0) + int(count)
            )

    # --- assemble the zero-filled series -----------------------------------
    series: List[Dict[str, Any]] = []
    for bucket_start in grid:
        attempt = attempt_buckets.get(bucket_start, {})
        alert = alert_buckets.get(bucket_start, {})
        by_outcome = {value: 0 for value in LOGIN_OUTCOMES}
        for name, count in attempt.get("by_outcome", {}).items():
            if name in by_outcome:
                by_outcome[name] = int(count)
        by_risk_level = {value: 0 for value in RISK_LEVELS}
        for name, count in attempt.get("by_risk_level", {}).items():
            if name in by_risk_level:
                by_risk_level[name] = int(count)
        alerts_by_status = {value: 0 for value in ALERT_STATUSES}
        for name, count in alert.get("alerts_by_status", {}).items():
            if name in alerts_by_status:
                alerts_by_status[name] = int(count)

        series.append({
            "bucket_start": _iso(bucket_start),
            "login_attempts": int(attempt.get("login_attempts", 0)),
            "by_outcome": by_outcome,
            "by_risk_level": by_risk_level,
            "alerts_created": int(alert.get("alerts_created", 0)),
            "alerts_by_status": alerts_by_status,
            "avg_combined_score": attempt.get("avg_combined_score"),
        })
    return series


# =============================================================================
# The endpoint
# =============================================================================

@router.get("/analytics/detection")
async def detection_analytics(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    bucket: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    x_internal_secret: Optional[str] = Header(None),
    db: OrmSession = Depends(get_detection_db),
) -> Dict[str, Any]:
    """The Detection-owned analytics aggregate for the Manager facade.

    The window is half-open ``[from, to)`` and every timestamp is UTC.  The
    ``status`` / ``risk_level`` filters select the **alert population**; they
    never filter the critical incident backlog.
    """
    verify_internal_secret(x_internal_secret)

    start, end, resolved_bucket = _resolve_window(
        _parse_dt_param("from", from_),
        _parse_dt_param("to", to),
        bucket,
    )
    status_filter = _validate_filter("status", status, ALERT_STATUSES)
    risk_level_filter = _validate_filter("risk_level", risk_level, RISK_LEVELS)

    payload: Dict[str, Any] = {
        "generated_at": _iso(utc_now()),
        "window": {"from": _iso(start), "to": _iso(end)},
        "bucket": resolved_bucket,
        "login_attempts": _login_attempts_section(db, start, end),
        "risk_assessments": _risk_assessments_section(db, start, end),
        "alerts": _alerts_section(db, start, end, status_filter, risk_level_filter),
        "analysts": _analysts_section(db),
        "critical_incidents": _critical_incidents(db),
        "enforcement": _enforcement_section(db, start, end),
        "series": _series(db, start, end, resolved_bucket, status_filter, risk_level_filter),
        "policy": _policy_section(db),
    }
    return payload


__all__ = [
    "router",
    "ALERT_STATUSES",
    "RISK_LEVELS",
    "LOGIN_OUTCOMES",
    "DETECTION_DECISIONS",
]
