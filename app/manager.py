"""
Security Manager analytics facade.

Implements the five public Manager endpoints of Sentinel Auth v3.3:

    GET /api/v1/manager/dashboard
    GET /api/v1/manager/trends
    GET /api/v1/manager/alerts
    GET /api/v1/manager/soc-kpi
    GET /api/v1/manager/ml-stats

Design document (normative): ``docs/M9-MANAGER-ANALYTICS-DESIGN.md``.

Bounded contexts
----------------
The Manager role is cross-service: the data it reports on lives in three
physically separate databases.  The facade therefore aggregates across the
*service* boundaries instead of across the databases:

* **ML** is owned by this context.  It is read **directly** through
  ``get_ml_db`` - the same dependency ``app/ml.py`` uses.  The read is
  read-only: it never writes, never scores and never touches the inference
  path.
* **Core** and **Detection** are owned by other contexts.  They are reached
  over HTTP with the ``X-Internal-Secret`` header through
  ``app/manager_client.py``.

This module therefore never imports ``get_core_db`` or ``get_detection_db``,
and never imports the Core- or Detection-owned ORM models.
``tests/test_manager_analytics.py`` guards that statically.

Degradation
-----------
Every endpoint answers with the same envelope.  A source that fails makes
its section ``null`` and sets ``degraded: true``; the endpoint only answers
**503** when *every* source it consumes has failed.  The reason code is
always one of the closed vocabulary of design section 6.1.1 - never a raw
exception, URL or upstream body.

KPI semantics
-------------
All KPI populations are alerts **created** inside the half-open window
``[from, to)``.  A rate over an empty population is ``null``, never ``0`` -
that distinction is the difference between "nothing happened" and "nothing
was measured", and the design requires it to be preserved.

Response models are declared **locally** in this module, following
``app/ml.py`` and ``app/internal_actions.py``, so the shared
``app/schemas.py`` stays untouched.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.authz import AuthContext, require_roles
from app.db import get_ml_db
from app.manager_client import (
    REASON_DATABASE_ERROR,
    REASON_INTERNAL_ERROR,
    REASON_INVALID_PAYLOAD,
    REASON_UNREACHABLE,
    SOURCE_CORE,
    SOURCE_DETECTION,
    SOURCE_ML,
    fetch_core_analytics,
    fetch_detection_analytics,
)
from app.models import FeatureStatistic, InferenceLog, ModelVersion
from app.time_utils import as_utc, utc_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["manager"])


def _serialize_utc(value: datetime) -> str:
    """Serialise a UTC datetime with an explicit ``+00:00`` offset.

    Pydantic v2 renders a UTC datetime as ``...Z``; design section 7.0
    requires the ``+00:00`` offset, so the format is pinned here rather
    than left to the library default.
    """
    return as_utc(value).isoformat()


#: A timezone-aware UTC datetime that always serialises with ``+00:00``.
UtcDatetime = Annotated[
    datetime, PlainSerializer(_serialize_utc, return_type=str, when_used="json")
]


# =============================================================================
# Canonical vocabularies (design section 3.2, reference document R2)
# =============================================================================

ALERT_STATUSES: Tuple[str, ...] = ("open", "acknowledged", "resolved", "false_positive")
RISK_LEVELS: Tuple[str, ...] = ("low", "medium", "high", "critical")
LOGIN_OUTCOMES: Tuple[str, ...] = (
    "success", "failure", "mfa_required", "mfa_success",
    "mfa_failed", "blocked", "locked", "rate_limited",
)
DETECTION_DECISIONS: Tuple[str, ...] = ("allow", "challenge", "block")
ML_INFERENCE_STATUSES: Tuple[str, ...] = ("ready", "degraded", "error")
ML_REASON_CODES: Tuple[str, ...] = (
    "unusual_hour", "high_fail_count", "new_ip", "new_device",
    "behavioral_deviation", "multiple_factors",
)

#: Bucket granularities.
BUCKETS: Tuple[str, ...] = ("hour", "day")

#: The ``auto`` bucket resolves from the window length - design section 3.2
#: rule 5.  It is the default, and it is also accepted explicitly.
BUCKET_AUTO = "auto"
BUCKETS_AND_AUTO: Tuple[str, ...] = ("hour", "day", BUCKET_AUTO)

#: Maximum window length.
MAX_WINDOW_DAYS = 366

#: A window longer than this resolves ``bucket=auto`` to ``day``.
AUTO_BUCKET_HOURS = 72

#: Maximum bucket count per granularity.
MAX_BUCKETS = {"hour": 400, "day": 366}

#: ``bucket=hour`` is only allowed for windows up to this length.
MAX_HOUR_WINDOW_DAYS = 31

#: Default window per endpoint, in hours.
DEFAULT_WINDOW_HOURS = {
    "dashboard": 24,
    "trends": 14 * 24,
    "alerts": 30 * 24,
    "soc-kpi": 30 * 24,
    "ml-stats": 30 * 24,
}

#: The sections each endpoint needs from the Detection payload.  A payload that
#: is missing one of them - or that carries it with the wrong container type -
#: is ``invalid_payload`` (design section 6.1.1).
_DETECTION_REQUIRED = {
    "dashboard": ("login_attempts", "alerts", "risk_assessments",
                  "enforcement", "analysts", "critical_incidents"),
    "trends": ("series",),
    "alerts": ("alerts",),
    "soc-kpi": ("alerts", "analysts", "enforcement", "risk_assessments"),
}

#: Sections each endpoint needs from the Core payload.
_CORE_REQUIRED = {
    "dashboard": ("users", "sessions", "mfa", "audit", "audit_activity"),
    "soc-kpi": ("users", "audit"),
}

#: The container type each required section must have.  A section that is
#: present but is not an object cannot be reshaped - reading it would raise
#: an ``AttributeError``, which would become a 500.  Such a payload is
#: rejected as ``invalid_payload`` instead (design sections 6.1.1 / 6.1.2:
#: "no 500" under any upstream failure).
_DETECTION_SECTION_TYPES = {
    "login_attempts": dict,
    "alerts": dict,
    "risk_assessments": dict,
    "enforcement": dict,
    "analysts": dict,
    "critical_incidents": list,
    "series": list,
}

_CORE_SECTION_TYPES = {
    "users": dict,
    "sessions": dict,
    "mfa": dict,
    "audit": dict,
    "audit_activity": dict,
    "series": list,
}


# =============================================================================
# Response models (design section 7.0)
# =============================================================================

class ManagerModel(BaseModel):
    """Base for every Manager response model.

    ``from_attributes=False`` because the models are built from plain dicts
    (the facade never touches a Core or Detection ORM object) and
    ``extra="ignore"`` so a forward-compatible upstream field cannot break
    the facade.
    """

    model_config = ConfigDict(from_attributes=False, extra="ignore")


class SourceStatus(ManagerModel):
    """Availability of one analytics source."""

    status: str  # "ok" | "unavailable"
    detail: Optional[str] = None  # a closed reason code, or None


class AnalyticsWindow(ManagerModel):
    """The effective window actually used, echoed back to the caller."""

    from_: UtcDatetime = Field(alias="from")
    to: UtcDatetime


class ManagerEnvelope(ManagerModel):
    """The envelope shared by every Manager response."""

    generated_at: UtcDatetime
    window: AnalyticsWindow
    degraded: bool
    sources: Dict[str, SourceStatus]


class CriticalIncidentSubject(ManagerModel):
    username: Optional[str] = None
    user_id: Optional[str] = None


class CriticalIncident(ManagerModel):
    alert_id: str
    risk_level: str
    status: str
    created_at: UtcDatetime
    subject: Optional[CriticalIncidentSubject] = None
    detection_reason: Optional[str] = None
    combined_score: Optional[float] = None
    assigned_to: Optional[str] = None
    age_hours: Optional[float] = None


class ActivePolicy(ManagerModel):
    active_version: Optional[str] = None
    active_policy_id: Optional[str] = None


class AuditActivityRow(ManagerModel):
    """One audit row.

    Deliberately carries no ``before_state`` / ``after_state`` /
    ``ip_address`` / ``user_agent`` - design section 3.3.
    """

    id: str
    action: str
    actor: Optional[str] = None
    resource: Optional[str] = None
    resource_id: Optional[str] = None
    created_at: UtcDatetime


class AuditActivity(ManagerModel):
    by_action: Dict[str, int]
    by_actor_type: Dict[str, int]
    recent: List[AuditActivityRow]


class DashboardCore(ManagerModel):
    total_users: int
    users_by_status: Dict[str, int]
    users_with_mfa_required: int
    users_under_forced_mfa: int
    new_users: int
    users_with_failed_logins: int
    active_sessions: int
    sessions_created: int
    sessions_revoked: int
    mfa_challenges: int
    mfa_completed: int
    mfa_failed: int
    audit_events: int
    audit_activity: Optional[AuditActivity] = None


class DashboardDetectionAlerts(ManagerModel):
    total: int
    open: int
    acknowledged: int
    resolved: int
    false_positive: int
    critical_open: int


class EnforcementStats(ManagerModel):
    """Enforcement attempt / success counts and the derived rate."""

    attempted: int
    succeeded: int
    success_rate: Optional[float] = None


class MlFallbackStats(ManagerModel):
    """The ML fallback summary over the assessment population."""

    assessments: int
    fallback: int
    fallback_rate: Optional[float] = None


class DashboardDetection(ManagerModel):
    login_attempts: int
    by_outcome: Dict[str, int]
    by_risk_level: Dict[str, int]
    by_decision: Dict[str, int]
    avg_combined_score: Optional[float] = None
    alerts: DashboardDetectionAlerts
    critical_incidents: List[CriticalIncident] = Field(default_factory=list)
    enforcement: Optional[EnforcementStats] = None
    ml_fallback: Optional[MlFallbackStats] = None
    policy: Optional[ActivePolicy] = None


class MlDailyPoint(ManagerModel):
    """One ML day bucket - the public names are the shortened view names."""

    day: str
    total: int
    anomalies: int
    successful: int
    errors: int
    degraded: int
    avg_processing_ms: Optional[float] = None
    avg_anomaly_score: Optional[float] = None


class DashboardMl(ManagerModel):
    active_model_version: Optional[str] = None
    model_status: str
    inferences: int
    anomalies: int
    anomaly_rate: Optional[float] = None
    avg_processing_ms: Optional[float] = None
    daily: List[MlDailyPoint] = Field(default_factory=list)


class ManagerDashboardResponse(ManagerEnvelope):
    core: Optional[DashboardCore] = None
    detection: Optional[DashboardDetection] = None
    ml: Optional[DashboardMl] = None


class ManagerTrendPoint(ManagerModel):
    bucket_start: UtcDatetime
    total: int
    by_outcome: Dict[str, int]
    by_risk_level: Dict[str, int]
    avg_combined_score: Optional[float] = None


class ManagerTrendAlertsPoint(ManagerModel):
    bucket_start: UtcDatetime
    total: int
    by_status: Dict[str, int]


class ManagerTrendMlPoint(ManagerModel):
    bucket_start: UtcDatetime
    total: int
    anomalies: int
    successful: int
    errors: int
    degraded: int
    avg_processing_ms: Optional[float] = None
    avg_anomaly_score: Optional[float] = None


class ManagerTrendSeries(ManagerModel):
    login_attempts: Optional[List[ManagerTrendPoint]] = None
    alerts: Optional[List[ManagerTrendAlertsPoint]] = None
    ml: Optional[List[ManagerTrendMlPoint]] = None


class ManagerTrendsResponse(ManagerEnvelope):
    bucket: str
    series: ManagerTrendSeries


class AlertTotals(ManagerModel):
    created: int
    open: int
    acknowledged: int
    resolved: int
    false_positive: int


class AlertBacklog(ManagerModel):
    open_count: int
    oldest_open_age_hours: Optional[float] = None
    unassigned: int
    escalated: int


class ManagerAlertsResponse(ManagerEnvelope):
    totals: AlertTotals
    by_status: Dict[str, int]
    by_risk_level: Dict[str, int]
    by_rule: List[Dict[str, Any]] = Field(default_factory=list)
    by_ml_reason: List[Dict[str, Any]] = Field(default_factory=list)
    backlog: AlertBacklog
    false_positive_rate: Optional[float] = None
    mtta_seconds: Optional[float] = None
    mttr_seconds: Optional[float] = None
    acknowledged_count: int
    resolved_count: int


class ManagerSocKpis(ManagerModel):
    """Every KPI is nullable.

    A KPI over an empty population is ``null``; a KPI whose source is down is
    also ``null`` - design sections 5 and 6.1.
    """

    mtta_seconds: Optional[float] = None
    mttr_seconds: Optional[float] = None
    acknowledgement_rate: Optional[float] = None
    resolution_rate: Optional[float] = None
    false_positive_rate: Optional[float] = None
    escalation_rate: Optional[float] = None
    alerts_per_analyst: Optional[float] = None
    enforcement_attempted: Optional[int] = None
    enforcement_succeeded: Optional[int] = None
    enforcement_success_rate: Optional[float] = None
    ml_assessments: Optional[int] = None
    ml_fallback_count: Optional[int] = None
    ml_fallback_rate: Optional[float] = None
    mfa_enrollment_rate: Optional[float] = None
    forced_mfa_users: Optional[int] = None
    audit_events: Optional[int] = None


class ManagerSocKpiResponse(ManagerEnvelope):
    kpis: ManagerSocKpis


class MlModelInfo(ManagerModel):
    active_version: Optional[str] = None
    status: Optional[str] = None
    is_production: bool = False
    algorithm: Optional[str] = None
    deployed_at: Optional[UtcDatetime] = None
    trained_by: Optional[str] = None


class MlVersionInfo(ManagerModel):
    version: str
    status: str
    is_production: bool
    training_date: Optional[UtcDatetime] = None
    inferences: int = 0


class MlInferenceStats(ManagerModel):
    total: int
    anomalies: int
    anomaly_rate: Optional[float] = None
    avg_normalized_score: Optional[float] = None
    avg_processing_ms: Optional[float] = None
    p95_processing_ms: Optional[float] = None
    errors: int = 0
    degraded: int = 0


class MlFeaturePoint(ManagerModel):
    feature_name: str
    count: int
    mean: Optional[float] = None
    std: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p95: Optional[float] = None
    anomaly_rate: Optional[float] = None
    timestamp: Optional[UtcDatetime] = None


class ManagerMlStatsResponse(ManagerEnvelope):
    model: Optional[MlModelInfo] = None
    versions: List[MlVersionInfo] = Field(default_factory=list)
    inference: MlInferenceStats
    by_status: Dict[str, int]
    reason_codes: List[Dict[str, Any]] = Field(default_factory=list)
    daily: List[MlDailyPoint] = Field(default_factory=list)
    features: List[MlFeaturePoint] = Field(default_factory=list)


# =============================================================================
# Window / bucket handling (design sections 3.2 and 5.3)
# =============================================================================

def get_optional_ml_db():
    """Yield the ML session, or ``None`` when the context is unavailable.

    ``get_ml_db`` raises when the ML database URL cannot be resolved (for
    example when only the legacy single-database URL is configured).  That
    raise happens during dependency resolution, *before* the route body
    runs, so it would become a 500 for the caller - which design section
    6.1.2 forbids.

    The ML read is a **source**, not a precondition: an unavailable ML
    context is the ``database_error`` source failure, exactly like a failed
    query.  Yielding ``None`` lets the facade treat it that way.

    The endpoints that do not consume ML at all (``/alerts`` and
    ``/soc-kpi``) therefore never open an ML session, and the endpoints
    that do consume it degrade instead of failing.
    """
    generator = None
    try:
        generator = get_ml_db()
        session = next(generator)
    except Exception as exc:  # noqa: BLE001 - a missing context is a source failure
        logger.warning(
            "ML context unavailable for manager analytics: %s",
            exc.__class__.__name__,
        )
        if generator is not None:
            generator.close()
        yield None
        return

    try:
        yield session
    finally:
        # Closing the upstream generator runs its own cleanup - ``get_ml_db``
        # closes the session in its ``finally`` block.
        generator.close()


class WindowSpec:
    """The effective window and bucket of one request."""

    __slots__ = ("start", "end", "bucket")

    def __init__(self, start: datetime, end: datetime, bucket: str):
        self.start = start
        self.end = end
        self.bucket = bucket


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _floor_bucket(ts: datetime, bucket: str) -> datetime:
    """Floor a UTC instant to the start of its bucket (design section 5.3)."""
    if bucket == "hour":
        return ts.replace(minute=0, second=0, microsecond=0)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_step(bucket: str) -> timedelta:
    return timedelta(hours=1) if bucket == "hour" else timedelta(days=1)


def _bucket_count(start: datetime, end: datetime, bucket: str) -> int:
    """Number of buckets in ``[from, to)`` (design section 5.3)."""
    first = _floor_bucket(start, bucket)
    step = _bucket_step(bucket)
    count = 0
    cursor = first
    while cursor < end:
        count += 1
        cursor += step
    return count


def bucket_starts(start: datetime, end: datetime, bucket: str) -> List[datetime]:
    """The full list of bucket starts - the zero-fill scaffolding (5.3).

    ``from`` is floored, so the first bucket may start before ``from``; the
    label stays aligned to the wall clock while the SQL predicate still
    excludes data before ``from``.
    """
    step = _bucket_step(bucket)
    cursor = _floor_bucket(start, bucket)
    out: List[datetime] = []
    while cursor < end:
        out.append(cursor)
        cursor += step
    return out


def resolve_window(
    *,
    from_: Optional[datetime],
    to: Optional[datetime],
    bucket: Optional[str],
    default_hours: int,
) -> WindowSpec:
    """Validate the query parameters and resolve the effective window.

    Implements design section 3.2.  Every violation is a **400**, raised
    before any upstream call is made.
    """
    end = as_utc(to) if to is not None else utc_now()
    start = as_utc(from_) if from_ is not None else end - timedelta(hours=default_hours)

    if start >= end:
        raise _bad_request("'from' must be strictly earlier than 'to'")

    span = end - start
    if span > timedelta(days=MAX_WINDOW_DAYS):
        raise _bad_request(f"window must not exceed {MAX_WINDOW_DAYS} days")

    if bucket is not None and bucket not in BUCKETS_AND_AUTO:
        raise _bad_request("'bucket' must be one of: hour, day, auto")

    # ``bucket=auto`` is resolved from the window length (design section 3.2
    # rule 5): ``day`` when the window exceeds 72 h, ``hour`` otherwise.
    # An omitted bucket resolves the same way.
    if bucket is None or bucket == BUCKET_AUTO:
        resolved = "day" if span > timedelta(hours=AUTO_BUCKET_HOURS) else "hour"
    else:
        resolved = bucket

    if resolved == "hour" and span > timedelta(days=MAX_HOUR_WINDOW_DAYS):
        raise _bad_request(
            f"bucket=hour requires a window of at most {MAX_HOUR_WINDOW_DAYS} days"
        )

    if _bucket_count(start, end, resolved) > MAX_BUCKETS[resolved]:
        raise _bad_request(
            f"window produces more than {MAX_BUCKETS[resolved]} {resolved} buckets"
        )

    return WindowSpec(start=start, end=end, bucket=resolved)


def validate_filter(name: str, value: Optional[str], vocabulary: Sequence[str]) -> Optional[str]:
    """Validate an optional vocabulary filter (design section 3.2 rule 7)."""
    if value is None:
        return None
    if value not in vocabulary:
        raise _bad_request(f"'{name}' must be one of: {', '.join(vocabulary)}")
    return value


def _parse_window_param(name: str, value: Optional[str]) -> Optional[datetime]:
    """Parse a window parameter, or raise a 400.

    FastAPI validates a ``datetime`` query parameter itself and answers
    **422** when the value is unparseable.  Design section 6.1.2 allows
    exactly five response shapes - 200, 400, 401, 403, 503 - and a malformed
    window is a **400** ("invalid window / bucket / filter").  The parameter
    is therefore taken as a raw string and parsed here, so the endpoint
    answers 400 like every other invalid input.

    A naive timestamp is treated as UTC, matching the documented
    ``as_utc`` contract (design section 3.2 rule 6).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _bad_request(
            f"'{name}' must be an ISO-8601 datetime, got {text!r}"
        )
    return as_utc(parsed)


class WindowQuery:
    """The raw window / bucket / filter parameters of one request.

    Parsed by the ``parse_*_query`` dependencies so that an unparseable
    datetime becomes a 400 instead of FastAPI's default 422.
    """

    __slots__ = ("from_", "to", "bucket", "status", "risk_level")

    def __init__(
        self,
        from_: Optional[datetime] = None,
        to: Optional[datetime] = None,
        bucket: Optional[str] = None,
        status: Optional[str] = None,
        risk_level: Optional[str] = None,
    ):
        self.from_ = from_
        self.to = to
        self.bucket = bucket
        self.status = status
        self.risk_level = risk_level


async def parse_window_query(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
) -> WindowQuery:
    """Parse ``from`` / ``to`` for the endpoints that accept only a window.

    Registered as a route dependency so it runs **before** FastAPI validates
    the route's own parameters - a dependency is resolved first, so the 400
    it raises wins over the framework's 422.
    """
    return WindowQuery(
        from_=_parse_window_param("from", from_),
        to=_parse_window_param("to", to),
    )


async def parse_trends_query(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    bucket: Optional[str] = Query(None),
) -> WindowQuery:
    """Parse the parameters of ``/trends`` - a window plus ``bucket``."""
    return WindowQuery(
        from_=_parse_window_param("from", from_),
        to=_parse_window_param("to", to),
        bucket=bucket,
    )


async def parse_alerts_query(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    risk_level: Optional[str] = Query(None),
) -> WindowQuery:
    """Parse the parameters of ``/alerts`` - a window plus the two filters."""
    return WindowQuery(
        from_=_parse_window_param("from", from_),
        to=_parse_window_param("to", to),
        status=status_,
        risk_level=risk_level,
    )


def _iso(value: datetime) -> str:
    """ISO-8601 UTC representation used for the upstream query string."""
    return as_utc(value).isoformat()


# =============================================================================
# Small conversion helpers
# =============================================================================

def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _round_rate(value: Optional[float]) -> Optional[float]:
    """Rates are rounded to 4 decimals (design section 5)."""
    if value is None:
        return None
    return round(value, 4)


def _round_seconds(value: Any) -> Optional[float]:
    """Seconds are rounded to 1 decimal (design section 5)."""
    number = _as_float(value)
    if number is None:
        return None
    return round(number, 1)


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """A rate over an empty population is ``null``, never ``0``."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return _round_rate(numerator / denominator)


def _as_dict(value: Any) -> Dict[str, Any]:
    """Coerce an upstream value to a dict; anything else becomes empty.

    A nested breakdown that arrives with the wrong type cannot be read.
    Treating it as an empty breakdown is both safe and semantically right:
    an unreadable breakdown is an absent breakdown, and the counts it would
    have carried are unknown rather than present (design sections 5 and 6.1).
    """
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    """Coerce an upstream value to a list; anything else becomes empty."""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _breakdown_rows(value: Any) -> List[Dict[str, Any]]:
    """Normalise a top-N breakdown the upstream supplied.

    The breakdown is a list of ``{"rule": ..., "count": ...}`` or
    ``{"code": ..., "count": ...}`` rows.  The **key name is preserved** -
    the public contract distinguishes the two vocabularies by their key
    (design section 3.5), so a row is never renamed.

    A row that is not an object, or that carries no usable name and count,
    is skipped - never raised (design section 3.5: "A rule or code that
    cannot be read is skipped, never raised").
    """
    rows: List[Dict[str, Any]] = []
    for raw in _as_list(value):
        if not isinstance(raw, dict):
            continue
        count = raw.get("count")
        if count is None:
            continue
        if "rule" in raw and raw["rule"] is not None:
            rows.append({"rule": str(raw["rule"]), "count": _as_int(count)})
        elif "code" in raw and raw["code"] is not None:
            rows.append({"code": str(raw["code"]), "count": _as_int(count)})
    return rows


def _zero_filled(keys: Sequence[str], counts: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Zero-fill a breakdown so the UI never has to handle missing keys."""
    out = {key: 0 for key in keys}
    for key, value in _as_dict(counts).items():
        out[str(key)] = _as_int(value)
    return out


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an upstream timestamp into timezone-aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return as_utc(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return as_utc(parsed)


def _top_counts(counts: Dict[str, int], key: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Top-N descending, ties broken by name for deterministic output."""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{key: name, "count": count} for name, count in ordered]


# =============================================================================
# The ML source - a direct, read-only aggregate over sentinel_ml
# =============================================================================

def _dialect_name(db: OrmSession) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:  # noqa: BLE001 - a missing bind is an internal error
        return ""


def _bucket_expression(db: OrmSession, bucket: str):
    """The SQL expression that floors ``created_at`` to a UTC bucket.

    **PostgreSQL**: ``date_trunc`` on a ``TIMESTAMPTZ`` truncates in the
    *session* timezone, and this codebase does not pin the session timezone
    (``app/db.py`` builds the engine without a ``connect_args`` timezone).
    The explicit ``AT TIME ZONE 'UTC'`` converts to a naive UTC timestamp
    first, so the truncation is timezone-independent - design section 6.4.

    **SQLite**: there is no ``AT TIME ZONE`` and the stored value is the
    naive UTC wall clock, so ``strftime`` over the same column produces the
    identical bucket.

    Both backends therefore agree on the bucket boundary (design section
    7.0.1).
    """
    dialect = _dialect_name(db)
    if dialect == "postgresql":
        part = "hour" if bucket == "hour" else "day"
        return func.date_trunc(part, InferenceLog.created_at.op("AT TIME ZONE")("UTC"))
    fmt = "%Y-%m-%d %H:00:00" if bucket == "hour" else "%Y-%m-%d"
    return func.strftime(fmt, InferenceLog.created_at)


def _bucket_key(value: Any, bucket: str) -> str:
    """Normalise a bucket expression result into an ISO key."""
    if isinstance(value, datetime):
        moment = as_utc(value)
        if bucket == "hour":
            return moment.strftime("%Y-%m-%dT%H:00:00+00:00")
        return moment.strftime("%Y-%m-%dT00:00:00+00:00")
    text = str(value)
    if bucket == "hour":
        # "2026-10-31 23:00:00" -> "2026-10-31T23:00:00+00:00"
        return f"{text.replace(' ', 'T')}+00:00"
    # "2026-10-31" -> "2026-10-31T00:00:00+00:00"
    return f"{text}T00:00:00+00:00"


def _bucket_label(moment: datetime, bucket: str) -> str:
    if bucket == "hour":
        return moment.strftime("%Y-%m-%dT%H:00:00+00:00")
    return moment.strftime("%Y-%m-%dT00:00:00+00:00")


def _ml_bucket_rows(db: OrmSession, window: WindowSpec, bucket: str) -> Dict[str, Dict[str, Any]]:
    """The ML buckets over the window, keyed by the ISO bucket start.

    One implementation serves both ``/ml-stats.daily`` and the ``/trends``
    ML series, so the two endpoints cannot disagree about a day (design
    section 7.1).
    """
    expr = _bucket_expression(db, bucket)
    rows = db.execute(
        select(
            expr.label("bucket"),
            func.count().label("total"),
            func.count().filter(InferenceLog.is_anomaly.is_(True)).label("anomalies"),
            func.count().filter(InferenceLog.model_status == "ready").label("successful"),
            func.count().filter(InferenceLog.model_status == "error").label("errors"),
            func.count().filter(InferenceLog.model_status == "degraded").label("degraded"),
            func.avg(InferenceLog.processing_time_ms).label("avg_processing_ms"),
            func.avg(InferenceLog.normalized_score).label("avg_anomaly_score"),
        )
        .where(
            InferenceLog.created_at >= window.start,
            InferenceLog.created_at < window.end,
        )
        .group_by(expr)
        .order_by(expr)
    ).all()

    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        out[_bucket_key(row.bucket, bucket)] = {
            "total": _as_int(row.total),
            "anomalies": _as_int(row.anomalies),
            "successful": _as_int(row.successful),
            "errors": _as_int(row.errors),
            "degraded": _as_int(row.degraded),
            "avg_processing_ms": _round_seconds(row.avg_processing_ms),
            "avg_anomaly_score": _round_rate(_as_float(row.avg_anomaly_score)),
        }
    return out


def _empty_bucket() -> Dict[str, Any]:
    return {
        "total": 0, "anomalies": 0, "successful": 0, "errors": 0,
        "degraded": 0, "avg_processing_ms": None, "avg_anomaly_score": None,
    }


def _ml_daily_points(db: OrmSession, window: WindowSpec) -> List[MlDailyPoint]:
    """The ML daily buckets, zero-filled, in chronological order.

    The explicit UTC grouping is used rather than the ``local_ml_stats``
    view, because the view truncates in the session timezone (design
    section 6.4).  The window filter is applied here so that this list and
    the ``/trends`` ML series agree for any given day (design 7.1).
    """
    counts = _ml_bucket_rows(db, window, "day")
    points: List[MlDailyPoint] = []
    for start in bucket_starts(window.start, window.end, "day"):
        base = counts.get(_bucket_label(start, "day"), _empty_bucket())
        points.append(MlDailyPoint(day=start.date().isoformat(), **base))
    return points


def _ml_series_points(db: OrmSession, window: WindowSpec) -> List[ManagerTrendMlPoint]:
    """The ML bucketed series, zero-filled, in chronological order."""
    counts = _ml_bucket_rows(db, window, window.bucket)
    points: List[ManagerTrendMlPoint] = []
    for start in bucket_starts(window.start, window.end, window.bucket):
        base = counts.get(_bucket_label(start, window.bucket), _empty_bucket())
        points.append(ManagerTrendMlPoint(bucket_start=start, **base))
    return points


def _ml_inference_stats(db: OrmSession, window: WindowSpec) -> MlInferenceStats:
    """The window-scoped inference aggregate."""
    row = db.execute(
        select(
            func.count().label("total"),
            func.count().filter(InferenceLog.is_anomaly.is_(True)).label("anomalies"),
            func.avg(InferenceLog.normalized_score).label("avg_normalized_score"),
            func.avg(InferenceLog.processing_time_ms).label("avg_processing_ms"),
            func.count().filter(InferenceLog.model_status == "error").label("errors"),
            func.count().filter(InferenceLog.model_status == "degraded").label("degraded"),
        )
        .where(
            InferenceLog.created_at >= window.start,
            InferenceLog.created_at < window.end,
        )
    ).one()

    total = _as_int(row.total)
    anomalies = _as_int(row.anomalies)
    return MlInferenceStats(
        total=total,
        anomalies=anomalies,
        anomaly_rate=_safe_ratio(anomalies, total),
        avg_normalized_score=_round_rate(_as_float(row.avg_normalized_score)),
        avg_processing_ms=_round_seconds(row.avg_processing_ms),
        p95_processing_ms=_ml_p95_processing_ms(db, window),
        errors=_as_int(row.errors),
        degraded=_as_int(row.degraded),
    )


def _ml_p95_processing_ms(db: OrmSession, window: WindowSpec) -> Optional[float]:
    """The 95th percentile of ``processing_time_ms`` over the window.

    Computed in Python over the window's rows so PostgreSQL and SQLite
    produce the identical number (design section 7.0.1).
    """
    values = sorted(
        float(value) for (value,) in db.execute(
            select(InferenceLog.processing_time_ms).where(
                InferenceLog.created_at >= window.start,
                InferenceLog.created_at < window.end,
                InferenceLog.processing_time_ms.isnot(None),
            )
        ).all()
        if value is not None
    )
    if not values:
        return None
    rank = max(1, math.ceil(0.95 * len(values)))
    return _round_seconds(values[rank - 1])


def _ml_by_status(db: OrmSession, window: WindowSpec) -> Dict[str, int]:
    rows = db.execute(
        select(InferenceLog.model_status, func.count())
        .where(
            InferenceLog.created_at >= window.start,
            InferenceLog.created_at < window.end,
        )
        .group_by(InferenceLog.model_status)
    ).all()
    counts = {str(status_value): _as_int(count) for status_value, count in rows}
    return _zero_filled(ML_INFERENCE_STATUSES, counts)


def _ml_reason_codes(db: OrmSession, window: WindowSpec) -> List[Dict[str, Any]]:
    """Top 20 ML reason codes over the window.

    ``reason_codes`` is a JSON array; the rows are read and counted in
    Python so PostgreSQL and SQLite produce identical numbers.  A code
    outside the canonical vocabulary is skipped, never raised.
    """
    rows = db.execute(
        select(InferenceLog.reason_codes).where(
            InferenceLog.created_at >= window.start,
            InferenceLog.created_at < window.end,
        )
    ).all()

    counts: Dict[str, int] = {}
    for (payload,) in rows:
        if not isinstance(payload, (list, tuple)):
            continue
        for code in payload:
            name = str(code)
            if name not in ML_REASON_CODES:
                continue
            counts[name] = counts.get(name, 0) + 1

    return _top_counts(counts, key="code")


def _ml_versions(db: OrmSession, window: WindowSpec) -> List[MlVersionInfo]:
    """Every registry row, with the window inference count per version.

    The count uses the registry foreign key when it is present, and falls
    back to the ``model_version_used`` string for inferences scored from an
    environment-provided artifact (those rows carry no registry id).  The
    two counts are added, never mixed, so an inference is counted exactly
    once per version.
    """
    window_filter = (
        (InferenceLog.created_at >= window.start)
        & (InferenceLog.created_at < window.end)
    )
    by_id = dict(
        db.execute(
            select(InferenceLog.model_version_id, func.count())
            .where(InferenceLog.model_version_id.isnot(None), window_filter)
            .group_by(InferenceLog.model_version_id)
        ).all()
    )
    by_used = dict(
        db.execute(
            select(InferenceLog.model_version_used, func.count())
            .where(
                InferenceLog.model_version_id.is_(None),
                InferenceLog.model_version_used.isnot(None),
                window_filter,
            )
            .group_by(InferenceLog.model_version_used)
        ).all()
    )

    rows = db.execute(
        select(
            ModelVersion.id,
            ModelVersion.version,
            ModelVersion.status,
            ModelVersion.is_production,
            ModelVersion.training_date,
        ).order_by(ModelVersion.version)
    ).all()

    out: List[MlVersionInfo] = []
    for row in rows:
        inferences = _as_int(by_id.get(row.id)) + _as_int(by_used.get(row.version))
        out.append(
            MlVersionInfo(
                version=str(row.version),
                status=str(row.status),
                is_production=bool(row.is_production),
                training_date=as_utc(row.training_date) if row.training_date else None,
                inferences=inferences,
            )
        )
    return out


def _ml_active_model(db: OrmSession) -> Optional[MlModelInfo]:
    """The production registry row.

    The same selection ``app/ml.py::resolve_model_source`` makes
    (``status = 'active' AND is_production``).  ``null`` when no production
    model is registered.
    """
    row = db.execute(
        select(
            ModelVersion.version,
            ModelVersion.status,
            ModelVersion.is_production,
            ModelVersion.algorithm,
            ModelVersion.deployed_at,
            ModelVersion.trained_by,
        )
        .where(
            ModelVersion.status == "active",
            ModelVersion.is_production.is_(True),
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    return MlModelInfo(
        active_version=str(row.version),
        status=str(row.status),
        is_production=bool(row.is_production),
        algorithm=_as_str(row.algorithm),
        deployed_at=as_utc(row.deployed_at) if row.deployed_at else None,
        trained_by=_as_str(row.trained_by),
    )


def _ml_features(db: OrmSession) -> List[MlFeaturePoint]:
    """The latest row per ``feature_name`` from ``feature_statistics``.

    Latest = max ``timestamp`` per ``feature_name``, ties broken by max
    ``id``.
    """
    ranked = select(
        FeatureStatistic.feature_name.label("feature_name"),
        FeatureStatistic.timestamp.label("timestamp"),
        FeatureStatistic.count.label("count"),
        FeatureStatistic.mean.label("mean"),
        FeatureStatistic.std.label("std"),
        FeatureStatistic.min.label("min"),
        FeatureStatistic.max.label("max"),
        FeatureStatistic.p25.label("p25"),
        FeatureStatistic.p50.label("p50"),
        FeatureStatistic.p75.label("p75"),
        FeatureStatistic.p95.label("p95"),
        FeatureStatistic.anomaly_rate.label("anomaly_rate"),
        func.row_number().over(
            partition_by=FeatureStatistic.feature_name,
            order_by=(FeatureStatistic.timestamp.desc(), FeatureStatistic.id.desc()),
        ).label("rn"),
    ).subquery()

    rows = db.execute(
        select(ranked)
        .where(ranked.c.rn == 1)
        .order_by(ranked.c.feature_name)
    ).all()

    return [
        MlFeaturePoint(
            feature_name=str(row.feature_name),
            count=_as_int(row.count),
            mean=_round_rate(_as_float(row.mean)),
            std=_round_rate(_as_float(row.std)),
            min=_as_float(row.min),
            max=_as_float(row.max),
            p25=_as_float(row.p25),
            p50=_as_float(row.p50),
            p75=_as_float(row.p75),
            p95=_as_float(row.p95),
            anomaly_rate=_round_rate(_as_float(row.anomaly_rate)),
            timestamp=as_utc(row.timestamp) if row.timestamp else None,
        )
        for row in rows
    ]


def _ml_runtime_status(db: OrmSession) -> Tuple[Optional[str], str]:
    """The ML **runtime** status and the loaded artifact version.

    ``get_ml_runtime`` returns an ``IsolationForestRuntime`` object and has
    no status field: the status is the *outcome* of the call - ``ready``
    when the artifact loads, ``error`` when it does not.  ``degraded``
    belongs to ``inference_logs.model_status`` and never appears here
    (design section 3.3).
    """
    try:
        from app.ml import get_ml_runtime

        runtime = get_ml_runtime(db)
    except Exception as exc:  # noqa: BLE001 - a missing artifact must not 500
        logger.info(
            "ML artifact unavailable for manager analytics: %s",
            exc.__class__.__name__,
        )
        return None, "error"
    return (_as_str(getattr(runtime, "version", None)), "ready")


# =============================================================================
# Detection payload -> public shapes
# =============================================================================

def _detection_alerts_block(payload: Dict[str, Any]) -> DashboardDetectionAlerts:
    alerts = _as_dict(payload.get("alerts"))
    by_status = _as_dict(alerts.get("by_status"))
    return DashboardDetectionAlerts(
        total=_as_int(alerts.get("created")),
        open=_as_int(by_status.get("open")),
        acknowledged=_as_int(by_status.get("acknowledged")),
        resolved=_as_int(by_status.get("resolved")),
        false_positive=_as_int(by_status.get("false_positive")),
        critical_open=_as_int(alerts.get("critical_open")),
    )


def _enforcement_block(payload: Dict[str, Any]) -> Optional[EnforcementStats]:
    """The enforcement summary.

    The upstream sends ``attempted``, ``succeeded`` and ``success_rate``.
    The counts are integers and the rate is a number - a PostgreSQL
    ``Numeric`` column arrives as a ``Decimal``, which would serialise as a
    **string** inside a free-form dict, so every value is converted here
    (design section 7.0.1).

    ``success_rate`` is derived from the two counts rather than taken from
    the upstream, so it follows the same rule as every other rate in the
    facade: ``null`` over an empty population, never ``0``.
    """
    raw = _as_dict(payload.get("enforcement"))
    if not raw:
        return None
    attempted = _as_int(raw.get("attempted"))
    succeeded = _as_int(raw.get("succeeded"))
    return EnforcementStats(
        attempted=attempted,
        succeeded=succeeded,
        success_rate=_safe_ratio(succeeded, attempted),
    )


def _critical_incidents(payload: Dict[str, Any]) -> List[CriticalIncident]:
    out: List[CriticalIncident] = []
    for raw in _as_list(payload.get("critical_incidents")):
        if not isinstance(raw, dict):
            continue
        subject_raw = raw.get("subject")
        subject = None
        if isinstance(subject_raw, dict):
            subject = CriticalIncidentSubject(
                username=_as_str(subject_raw.get("username")),
                user_id=_as_str(subject_raw.get("user_id")),
            )
        out.append(
            CriticalIncident(
                alert_id=str(raw.get("alert_id")),
                risk_level=str(raw.get("risk_level")),
                status=str(raw.get("status")),
                created_at=_parse_dt(raw.get("created_at")) or utc_now(),
                subject=subject,
                detection_reason=_as_str(raw.get("detection_reason")),
                combined_score=_round_rate(_as_float(raw.get("combined_score"))),
                assigned_to=_as_str(raw.get("assigned_to")),
                age_hours=_round_seconds(raw.get("age_hours")),
            )
        )
    return out


def _dashboard_detection(payload: Dict[str, Any]) -> DashboardDetection:
    login = _as_dict(payload.get("login_attempts"))
    assessments = _as_dict(payload.get("risk_assessments"))
    total = _as_int(assessments.get("total"))
    ml_success = _as_int(assessments.get("ml_success"))

    policy_raw = payload.get("policy")
    policy = None
    if isinstance(policy_raw, dict):
        policy = ActivePolicy(
            active_version=_as_str(policy_raw.get("active_version")),
            active_policy_id=_as_str(policy_raw.get("active_policy_id")),
        )

    return DashboardDetection(
        login_attempts=_as_int(login.get("total")),
        by_outcome=_zero_filled(LOGIN_OUTCOMES, login.get("by_outcome")),
        by_risk_level=_zero_filled(RISK_LEVELS, login.get("by_risk_level")),
        by_decision=_zero_filled(DETECTION_DECISIONS, login.get("by_decision")),
        avg_combined_score=_round_rate(_as_float(login.get("avg_combined_score"))),
        alerts=_detection_alerts_block(payload),
        critical_incidents=_critical_incidents(payload),
        enforcement=_enforcement_block(payload),
        ml_fallback=MlFallbackStats(
            assessments=total,
            fallback=max(0, total - ml_success),
            fallback_rate=_round_rate(_as_float(assessments.get("fallback_rate"))),
        ),
        policy=policy,
    )


def _detection_trend_series(
    payload: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split the flat internal series into the two public arrays (3.4)."""
    login_attempts: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []
    for raw in _as_list(payload.get("series")):
        if not isinstance(raw, dict):
            continue
        bucket = _parse_dt(raw.get("bucket_start"))
        if bucket is None:
            continue
        login_attempts.append({
            "bucket_start": bucket,
            "total": _as_int(raw.get("login_attempts")),
            "by_outcome": _zero_filled(LOGIN_OUTCOMES, raw.get("by_outcome")),
            "by_risk_level": _zero_filled(RISK_LEVELS, raw.get("by_risk_level")),
            "avg_combined_score": _round_rate(_as_float(raw.get("avg_combined_score"))),
        })
        alerts.append({
            "bucket_start": bucket,
            "total": _as_int(raw.get("alerts_created")),
            "by_status": _zero_filled(ALERT_STATUSES, raw.get("alerts_by_status")),
        })
    return login_attempts, alerts


# =============================================================================
# Core payload -> public shapes
# =============================================================================

def _audit_activity(payload: Dict[str, Any]) -> Optional[AuditActivity]:
    raw = _as_dict(payload.get("audit_activity"))
    if not raw:
        return None
    recent: List[AuditActivityRow] = []
    for row in _as_list(raw.get("recent")):
        if not isinstance(row, dict):
            continue
        recent.append(
            AuditActivityRow(
                id=str(row.get("id")),
                action=str(row.get("action")),
                actor=_as_str(row.get("actor")),
                resource=_as_str(row.get("resource")),
                resource_id=_as_str(row.get("resource_id")),
                created_at=_parse_dt(row.get("created_at")) or utc_now(),
            )
        )
    return AuditActivity(
        by_action={str(k): _as_int(v) for k, v in _as_dict(raw.get("by_action")).items()},
        by_actor_type={
            str(k): _as_int(v) for k, v in _as_dict(raw.get("by_actor_type")).items()
        },
        recent=recent,
    )


def _dashboard_core(payload: Dict[str, Any]) -> DashboardCore:
    users = _as_dict(payload.get("users"))
    sessions = _as_dict(payload.get("sessions"))
    mfa = _as_dict(payload.get("mfa"))
    audit = _as_dict(payload.get("audit"))
    return DashboardCore(
        total_users=_as_int(users.get("total")),
        users_by_status={str(k): _as_int(v) for k, v in _as_dict(users.get("by_status")).items()},
        users_with_mfa_required=_as_int(users.get("mfa_required")),
        users_under_forced_mfa=_as_int(users.get("forced_mfa")),
        new_users=_as_int(users.get("new_in_window")),
        users_with_failed_logins=_as_int(users.get("with_failed_logins")),
        active_sessions=_as_int(sessions.get("active")),
        sessions_created=_as_int(sessions.get("created_in_window")),
        sessions_revoked=_as_int(sessions.get("revoked_in_window")),
        mfa_challenges=_as_int(mfa.get("challenges")),
        mfa_completed=_as_int(mfa.get("completed")),
        mfa_failed=_as_int(mfa.get("failed")),
        audit_events=_as_int(audit.get("total")),
        audit_activity=_audit_activity(payload),
    )


# =============================================================================
# KPI assembly (design sections 4.3 and 5)
# =============================================================================

def _detection_kpis(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Every KPI group that Detection supplies."""
    alerts = _as_dict(payload.get("alerts"))
    analysts = _as_dict(payload.get("analysts"))
    enforcement = _as_dict(payload.get("enforcement"))
    assessments = _as_dict(payload.get("risk_assessments"))

    created = _as_int(alerts.get("created"))
    acknowledged_count = _as_int(alerts.get("acknowledged_count"))
    resolved_count = _as_int(alerts.get("resolved_count"))
    false_positive_count = _as_int(alerts.get("false_positive_count"))
    escalated_count = _as_int(alerts.get("escalated_count"))
    active_analysts = _as_int(analysts.get("active"))

    enforcement_attempted = _as_int(enforcement.get("attempted"))
    enforcement_succeeded = _as_int(enforcement.get("succeeded"))

    assessments_total = _as_int(assessments.get("total"))
    ml_success = _as_int(assessments.get("ml_success"))

    return {
        "mtta_seconds": _round_seconds(alerts.get("mtta_seconds")),
        "mttr_seconds": _round_seconds(alerts.get("mttr_seconds")),
        "acknowledgement_rate": _safe_ratio(acknowledged_count, created),
        "resolution_rate": _safe_ratio(resolved_count + false_positive_count, created),
        "false_positive_rate": _safe_ratio(
            false_positive_count, resolved_count + false_positive_count
        ),
        "escalation_rate": _safe_ratio(escalated_count, created),
        "alerts_per_analyst": _safe_ratio(created, active_analysts),
        "enforcement_attempted": enforcement_attempted,
        "enforcement_succeeded": enforcement_succeeded,
        "enforcement_success_rate": _safe_ratio(enforcement_succeeded, enforcement_attempted),
        "ml_assessments": assessments_total,
        "ml_fallback_count": max(0, assessments_total - ml_success),
        "ml_fallback_rate": _round_rate(_as_float(assessments.get("fallback_rate"))),
    }


def _core_kpis(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Every KPI group that Core supplies."""
    users = _as_dict(payload.get("users"))
    audit = _as_dict(payload.get("audit"))
    return {
        "mfa_enrollment_rate": _safe_ratio(
            _as_int(users.get("mfa_required")), _as_int(users.get("total"))
        ),
        "forced_mfa_users": _as_int(users.get("forced_mfa")),
        "audit_events": _as_int(audit.get("total")),
    }


# =============================================================================
# Source orchestration
# =============================================================================

class _SourceOutcome:
    """The outcome of one source: its payload or its reason code."""

    __slots__ = ("payload", "reason")

    def __init__(self, payload: Optional[Dict[str, Any]], reason: Optional[str]):
        self.payload = payload
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.reason is None and self.payload is not None


def _validate_payload(
    payload: Optional[Dict[str, Any]],
    required: Sequence[str],
    section_types: Optional[Dict[str, type]] = None,
) -> Optional[str]:
    """Return a reason code when the payload is unusable, else ``None``.

    A malformed or incomplete upstream body is a source failure
    (``invalid_payload``), never a 500 for the caller (design 6.1.1).

    A required section must be **present** and must have the **container
    type** the reshaping code expects.  A section that is present but is,
    say, a string where an object is required cannot be reshaped: reading it
    would raise ``AttributeError`` and become a 500.  Rejecting it here
    keeps the "no 500" guarantee of design section 6.1.2.
    """
    if not isinstance(payload, dict):
        return REASON_INVALID_PAYLOAD
    for key in required:
        if key not in payload:
            return REASON_INVALID_PAYLOAD
        if section_types is not None:
            expected = section_types.get(key)
            if expected is not None and payload[key] is not None:
                if not isinstance(payload[key], expected):
                    return REASON_INVALID_PAYLOAD
    return None


async def _fetch_http_sources(
    window: WindowSpec,
    *,
    need_core: bool,
    need_detection: bool,
    status_filter: Optional[str] = None,
    risk_level_filter: Optional[str] = None,
) -> Dict[str, _SourceOutcome]:
    """Fetch the HTTP sources concurrently (design section 6.2)."""
    tasks: List[Tuple[str, Any]] = []
    if need_detection:
        tasks.append((
            SOURCE_DETECTION,
            fetch_detection_analytics(
                from_=_iso(window.start),
                to=_iso(window.end),
                bucket=window.bucket,
                status=status_filter,
                risk_level=risk_level_filter,
            ),
        ))
    if need_core:
        tasks.append((
            SOURCE_CORE,
            fetch_core_analytics(
                from_=_iso(window.start),
                to=_iso(window.end),
                bucket=window.bucket,
            ),
        ))

    outcomes: Dict[str, _SourceOutcome] = {}
    if not tasks:
        return outcomes

    gathered = await asyncio.gather(
        *(coro for _name, coro in tasks), return_exceptions=True
    )
    for (name, _coro), result in zip(tasks, gathered):
        if isinstance(result, BaseException):
            # A client bug would raise; treat it as an unavailable source
            # rather than letting it become a 500 for the caller.
            logger.exception("manager internal fetch raised")
            outcomes[name] = _SourceOutcome(None, REASON_INTERNAL_ERROR)
            continue
        outcomes[name] = _SourceOutcome(
            result.payload if result.ok else None,
            None if result.ok else (result.reason or REASON_UNREACHABLE),
        )
    return outcomes


def _read_ml_source(db: OrmSession, window: WindowSpec) -> Dict[str, Any]:
    """The ML read - a direct, read-only aggregate over ``sentinel_ml``."""
    return {
        "daily": _ml_daily_points(db, window),
        "series": _ml_series_points(db, window),
        "stats": _ml_inference_stats(db, window),
        "by_status": _ml_by_status(db, window),
        "reason_codes": _ml_reason_codes(db, window),
        "versions": _ml_versions(db, window),
        "model": _ml_active_model(db),
        "features": _ml_features(db),
        "runtime": _ml_runtime_status(db),
    }


def _ml_source_failure(exc: BaseException) -> str:
    """Map an ML read failure to a closed reason code."""
    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(exc, SQLAlchemyError):
        return REASON_DATABASE_ERROR
    return REASON_INTERNAL_ERROR


def _statuses_from_outcomes(
    outcomes: Dict[str, _SourceOutcome],
    required: Dict[str, Sequence[str]],
    section_types: Optional[Dict[str, Dict[str, type]]] = None,
) -> Tuple[Dict[str, SourceStatus], Dict[str, _SourceOutcome]]:
    """Build the public ``sources`` map and the usable payloads.

    A payload that is missing a section the endpoint needs - or that
    carries it with the wrong container type - is an ``invalid_payload``
    source failure, not a 500 (design section 6.1.1).  The second return
    value holds only the sources whose payload passed validation, so a
    degraded source never contributes a section.
    """
    statuses: Dict[str, SourceStatus] = {}
    usable: Dict[str, _SourceOutcome] = {}
    for name, outcome in outcomes.items():
        reason = outcome.reason
        if outcome.ok:
            reason = _validate_payload(
                outcome.payload,
                required.get(name, ()),
                (section_types or {}).get(name),
            )
        if reason is None:
            statuses[name] = SourceStatus(status="ok", detail=None)
            usable[name] = outcome
        else:
            statuses[name] = SourceStatus(status="unavailable", detail=reason)
    return statuses, usable


def _all_failed(statuses: Dict[str, SourceStatus]) -> bool:
    """True when every consumed source is unavailable (design section 6.1)."""
    return bool(statuses) and all(
        item.status == "unavailable" for item in statuses.values()
    )


def _unavailable_response(statuses: Dict[str, SourceStatus]) -> JSONResponse:
    """The 503 body of design section 6.1.2.

    ``{"detail": "analytics sources unavailable", "sources": {...}}`` - the
    one Manager response that is not the endpoint's response model.
    """
    return JSONResponse(
        status_code=503,
        content={
            "detail": "analytics sources unavailable",
            "sources": {
                name: {"status": item.status, "detail": item.detail}
                for name, item in statuses.items()
            },
        },
    )


def _window_model(window: WindowSpec) -> AnalyticsWindow:
    return AnalyticsWindow(**{"from": window.start, "to": window.end})


async def _gather_sources(
    window: WindowSpec,
    db: Optional[OrmSession],
    *,
    need_core: bool,
    need_detection: bool,
    need_ml: bool,
    status_filter: Optional[str] = None,
    risk_level_filter: Optional[str] = None,
) -> Tuple[Dict[str, _SourceOutcome], Optional[Dict[str, Any]], Optional[str]]:
    """Fetch every needed source concurrently.

    The ML read is a direct database access, so it runs in a worker thread
    while the HTTP fetches are in flight - a slow source does not serialise
    the others (design section 6.2).
    """
    http_task = asyncio.create_task(
        _fetch_http_sources(
            window,
            need_core=need_core,
            need_detection=need_detection,
            status_filter=status_filter,
            risk_level_filter=risk_level_filter,
        )
    )

    ml_task = None
    ml_reason = None
    if need_ml:
        if db is None:
            # The ML context could not be resolved at all.  That is the
            # ``database_error`` source failure, not a 500.
            ml_reason = REASON_DATABASE_ERROR
        else:
            ml_task = asyncio.create_task(
                asyncio.to_thread(_read_ml_source, db, window)
            )

    http_outcomes = await http_task

    ml_payload = None
    if ml_task is not None:
        try:
            ml_payload = await ml_task
        except Exception as exc:  # noqa: BLE001 - never surface a 500
            ml_reason = _ml_source_failure(exc)
            logger.warning(
                "manager ML source unavailable: %s (%s)",
                ml_reason, exc.__class__.__name__,
            )

    return http_outcomes, ml_payload, ml_reason


# =============================================================================
# Routes
# =============================================================================

#: The 503 body of design section 6.1.2.  It is the one Manager response
#: that is not the endpoint's response model, so it is declared explicitly
#: for OpenAPI accuracy.
_SOURCES_UNAVAILABLE_RESPONSE = {
    "description": "Every analytics source consumed by the endpoint failed.",
    "content": {
        "application/json": {
            "example": {
                "detail": "analytics sources unavailable",
                "sources": {
                    "detection": {"status": "unavailable", "detail": "timeout"},
                },
            },
        },
    },
}

#: The other three non-200 shapes of design section 6.1.2.  They are
#: declared explicitly so the OpenAPI document matches the five-shape
#: contract the design mandates.
_BAD_REQUEST_RESPONSE = {
    "description": "Invalid window, bucket or filter.",
    "content": {"application/json": {"example": {"detail": "'from' must be strictly earlier than 'to'"}}},
}
_UNAUTHORIZED_RESPONSE = {
    "description": "No or invalid bearer token.",
    "content": {"application/json": {"example": {"detail": "Missing Authorization header"}}},
}
_FORBIDDEN_RESPONSE = {
    "description": "Authenticated but not a SECURITY_MANAGER.",
    "content": {"application/json": {"example": {"detail": "Insufficient permissions"}}},
}

#: Every Manager endpoint answers with exactly these five shapes.
_MANAGER_RESPONSES = {
    400: _BAD_REQUEST_RESPONSE,
    401: _UNAUTHORIZED_RESPONSE,
    403: _FORBIDDEN_RESPONSE,
    503: _SOURCES_UNAVAILABLE_RESPONSE,
}


@router.get("/manager/dashboard", response_model=ManagerDashboardResponse, responses=_MANAGER_RESPONSES)
async def manager_dashboard(
    ctx: AuthContext = Depends(require_roles("SECURITY_MANAGER")),
    query: WindowQuery = Depends(parse_window_query),
    db: Optional[OrmSession] = Depends(get_optional_ml_db),
):
    """Security overview snapshot.  Default window: the last 24 hours."""
    window = resolve_window(
        from_=query.from_, to=query.to, bucket=None,
        default_hours=DEFAULT_WINDOW_HOURS["dashboard"],
    )

    http_outcomes, ml_payload, ml_reason = await _gather_sources(
        window, db, need_core=True, need_detection=True, need_ml=True
    )

    statuses, usable = _statuses_from_outcomes(http_outcomes, {
        SOURCE_DETECTION: _DETECTION_REQUIRED["dashboard"],
        SOURCE_CORE: _CORE_REQUIRED["dashboard"],
    }, {
        SOURCE_DETECTION: _DETECTION_SECTION_TYPES,
        SOURCE_CORE: _CORE_SECTION_TYPES,
    })
    # The ML source is ``ok`` only when its payload actually arrived.
    statuses[SOURCE_ML] = (
        SourceStatus(status="ok", detail=None)
        if ml_reason is None and ml_payload is not None
        else SourceStatus(status="unavailable", detail=ml_reason or REASON_INTERNAL_ERROR)
    )

    if _all_failed(statuses):
        return _unavailable_response(statuses)

    degraded = any(item.status == "unavailable" for item in statuses.values())

    core_block = None
    core_outcome = usable.get(SOURCE_CORE)
    if core_outcome is not None:
        core_block = _dashboard_core(core_outcome.payload)

    detection_block = None
    detection_outcome = usable.get(SOURCE_DETECTION)
    if detection_outcome is not None:
        detection_block = _dashboard_detection(detection_outcome.payload)

    ml_block = None
    if ml_payload is not None:
        version, runtime_status = ml_payload["runtime"]
        stats = ml_payload["stats"]
        ml_block = DashboardMl(
            active_model_version=version,
            model_status=runtime_status,
            inferences=stats.total,
            anomalies=stats.anomalies,
            anomaly_rate=stats.anomaly_rate,
            avg_processing_ms=stats.avg_processing_ms,
            daily=list(ml_payload.get("daily") or []),
        )

    return ManagerDashboardResponse(
        generated_at=utc_now(),
        window=_window_model(window),
        degraded=degraded,
        sources=statuses,
        core=core_block,
        detection=detection_block,
        ml=ml_block,
    )


@router.get("/manager/trends", response_model=ManagerTrendsResponse, responses=_MANAGER_RESPONSES)
async def manager_trends(
    ctx: AuthContext = Depends(require_roles("SECURITY_MANAGER")),
    query: WindowQuery = Depends(parse_trends_query),
    db: Optional[OrmSession] = Depends(get_optional_ml_db),
):
    """Risk trends.  Default window: the last 14 days, ``bucket=auto``."""
    window = resolve_window(
        from_=query.from_, to=query.to, bucket=query.bucket,
        default_hours=DEFAULT_WINDOW_HOURS["trends"],
    )

    http_outcomes, ml_payload, ml_reason = await _gather_sources(
        window, db, need_core=False, need_detection=True, need_ml=True
    )

    statuses, usable = _statuses_from_outcomes(http_outcomes, {
        SOURCE_DETECTION: _DETECTION_REQUIRED["trends"],
    }, {
        SOURCE_DETECTION: _DETECTION_SECTION_TYPES,
    })
    # The ML source is ``ok`` only when its payload actually arrived.
    statuses[SOURCE_ML] = (
        SourceStatus(status="ok", detail=None)
        if ml_reason is None and ml_payload is not None
        else SourceStatus(status="unavailable", detail=ml_reason or REASON_INTERNAL_ERROR)
    )

    if _all_failed(statuses):
        return _unavailable_response(statuses)

    degraded = any(item.status == "unavailable" for item in statuses.values())

    login_attempts = None
    alerts = None
    detection_outcome = usable.get(SOURCE_DETECTION)
    if detection_outcome is not None:
        raw_login, raw_alerts = _detection_trend_series(detection_outcome.payload)
        login_attempts = [ManagerTrendPoint(**point) for point in raw_login]
        alerts = [ManagerTrendAlertsPoint(**point) for point in raw_alerts]

    ml_series = None
    if ml_payload is not None:
        ml_series = list(ml_payload.get("series") or [])

    return ManagerTrendsResponse(
        generated_at=utc_now(),
        window=_window_model(window),
        degraded=degraded,
        sources=statuses,
        bucket=window.bucket,
        series=ManagerTrendSeries(
            login_attempts=login_attempts,
            alerts=alerts,
            ml=ml_series,
        ),
    )


@router.get("/manager/alerts", response_model=ManagerAlertsResponse, responses=_MANAGER_RESPONSES)
async def manager_alerts(
    ctx: AuthContext = Depends(require_roles("SECURITY_MANAGER")),
    query: WindowQuery = Depends(parse_alerts_query),
):
    """Alert statistics.  Default window: the last 30 days.

    ``status`` and ``risk_level`` select the alert population; an unknown
    value is a 400, not an empty result.
    """
    status_filter = validate_filter("status", query.status, ALERT_STATUSES)
    risk_level_filter = validate_filter("risk_level", query.risk_level, RISK_LEVELS)

    window = resolve_window(
        from_=query.from_, to=query.to, bucket=None,
        default_hours=DEFAULT_WINDOW_HOURS["alerts"],
    )

    http_outcomes, _ml_payload, _ml_reason = await _gather_sources(
        window, None, need_core=False, need_detection=True, need_ml=False,
        status_filter=status_filter, risk_level_filter=risk_level_filter,
    )

    statuses, usable = _statuses_from_outcomes(http_outcomes, {
        SOURCE_DETECTION: _DETECTION_REQUIRED["alerts"],
    }, {
        SOURCE_DETECTION: _DETECTION_SECTION_TYPES,
    })

    # ``/alerts`` consumes a single source: any failure is a 503.
    if _all_failed(statuses):
        return _unavailable_response(statuses)

    degraded = any(item.status == "unavailable" for item in statuses.values())

    detection_outcome = usable.get(SOURCE_DETECTION)
    payload = detection_outcome.payload if detection_outcome is not None else {}
    alerts = _as_dict(payload.get("alerts"))
    by_status = _as_dict(alerts.get("by_status"))

    created = _as_int(alerts.get("created"))
    resolved_count = _as_int(alerts.get("resolved_count"))
    false_positive_count = _as_int(alerts.get("false_positive_count"))

    return ManagerAlertsResponse(
        generated_at=utc_now(),
        window=_window_model(window),
        degraded=degraded,
        sources=statuses,
        totals=AlertTotals(
            created=created,
            open=_as_int(by_status.get("open")),
            acknowledged=_as_int(by_status.get("acknowledged")),
            resolved=_as_int(by_status.get("resolved")),
            false_positive=_as_int(by_status.get("false_positive")),
        ),
        by_status=_zero_filled(ALERT_STATUSES, by_status),
        by_risk_level=_zero_filled(RISK_LEVELS, alerts.get("by_risk_level")),
        by_rule=_breakdown_rows(alerts.get("by_rule")),
        by_ml_reason=_breakdown_rows(alerts.get("by_ml_reason")),
        backlog=AlertBacklog(
            open_count=_as_int(by_status.get("open")),
            oldest_open_age_hours=_round_seconds(alerts.get("oldest_open_age_hours")),
            unassigned=_as_int(alerts.get("unassigned_open")),
            escalated=_as_int(alerts.get("escalated_count")),
        ),
        false_positive_rate=_safe_ratio(
            false_positive_count, resolved_count + false_positive_count
        ),
        mtta_seconds=_round_seconds(alerts.get("mtta_seconds")),
        mttr_seconds=_round_seconds(alerts.get("mttr_seconds")),
        acknowledged_count=_as_int(alerts.get("acknowledged_count")),
        resolved_count=resolved_count,
    )


@router.get("/manager/soc-kpi", response_model=ManagerSocKpiResponse, responses=_MANAGER_RESPONSES)
async def manager_soc_kpi(
    ctx: AuthContext = Depends(require_roles("SECURITY_MANAGER")),
    query: WindowQuery = Depends(parse_window_query),
):
    """SOC effectiveness KPIs.  Default window: the last 30 days."""
    window = resolve_window(
        from_=query.from_, to=query.to, bucket=None,
        default_hours=DEFAULT_WINDOW_HOURS["soc-kpi"],
    )

    http_outcomes, _ml_payload, _ml_reason = await _gather_sources(
        window, None, need_core=True, need_detection=True, need_ml=False
    )

    statuses, usable = _statuses_from_outcomes(http_outcomes, {
        SOURCE_DETECTION: _DETECTION_REQUIRED["soc-kpi"],
        SOURCE_CORE: _CORE_REQUIRED["soc-kpi"],
    }, {
        SOURCE_DETECTION: _DETECTION_SECTION_TYPES,
        SOURCE_CORE: _CORE_SECTION_TYPES,
    })

    if _all_failed(statuses):
        return _unavailable_response(statuses)

    degraded = any(item.status == "unavailable" for item in statuses.values())

    kpis: Dict[str, Any] = {}
    detection_outcome = usable.get(SOURCE_DETECTION)
    if detection_outcome is not None:
        kpis.update(_detection_kpis(detection_outcome.payload))
    core_outcome = usable.get(SOURCE_CORE)
    if core_outcome is not None:
        kpis.update(_core_kpis(core_outcome.payload))

    return ManagerSocKpiResponse(
        generated_at=utc_now(),
        window=_window_model(window),
        degraded=degraded,
        sources=statuses,
        kpis=ManagerSocKpis(**kpis),
    )


@router.get("/manager/ml-stats", response_model=ManagerMlStatsResponse, responses=_MANAGER_RESPONSES)
async def manager_ml_stats(
    ctx: AuthContext = Depends(require_roles("SECURITY_MANAGER")),
    query: WindowQuery = Depends(parse_window_query),
    db: Optional[OrmSession] = Depends(get_optional_ml_db),
):
    """ML model and inference analytics.  Default window: the last 30 days."""
    window = resolve_window(
        from_=query.from_, to=query.to, bucket=None,
        default_hours=DEFAULT_WINDOW_HOURS["ml-stats"],
    )

    http_outcomes, ml_payload, ml_reason = await _gather_sources(
        window, db, need_core=False, need_detection=False, need_ml=True
    )

    statuses, usable = _statuses_from_outcomes(http_outcomes, {})
    # The ML source is ``ok`` only when its payload actually arrived.
    statuses[SOURCE_ML] = (
        SourceStatus(status="ok", detail=None)
        if ml_reason is None and ml_payload is not None
        else SourceStatus(status="unavailable", detail=ml_reason or REASON_INTERNAL_ERROR)
    )

    # ``/ml-stats`` consumes a single source: any failure is a 503.
    if _all_failed(statuses):
        return _unavailable_response(statuses)

    degraded = any(item.status == "unavailable" for item in statuses.values())

    stats = ml_payload["stats"]
    return ManagerMlStatsResponse(
        generated_at=utc_now(),
        window=_window_model(window),
        degraded=degraded,
        sources=statuses,
        model=ml_payload.get("model"),
        versions=list(ml_payload.get("versions") or []),
        inference=stats,
        by_status=ml_payload.get("by_status") or {},
        reason_codes=list(ml_payload.get("reason_codes") or []),
        daily=list(ml_payload.get("daily") or []),
        features=list(ml_payload.get("features") or []),
    )
