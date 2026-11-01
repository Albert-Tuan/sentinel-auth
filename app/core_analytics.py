"""Core-owned internal analytics provider.

Implements ``GET /api/v1/internal/analytics/core`` - the aggregate endpoint the
Security-Manager facade (``app/manager.py``) calls over HTTP.

Ownership
---------
This module is owned by the **Core context**.  It reads only from
``sentinel_core`` (via :func:`app.db.get_core_db`) and never imports the
Detection or ML session dependencies.  The Manager facade owns no SQL for
these facts: it forwards ``from`` / ``to`` / ``bucket`` verbatim and maps the
payload it gets back.

Normative source
----------------
``docs/M9-MANAGER-ANALYTICS-DESIGN.md`` sections 4.0 (shared contract rules),
4.2 (this endpoint), 5.1 (population rules) and 5.3 (bucket algorithm), plus
``docs/M9-MANAGER-ANALYTICS-REFERENCE.md`` section R1 (the SQL sketches this
module implements - R1.9 for protective actions, R1.10 for the audit activity
review).

The behavioural rules that are easy to get wrong, and that this module
implements deliberately:

* **Point-in-time vs window-scoped.**  ``users.total``, ``users.by_status``,
  ``users.mfa_required``, ``users.forced_mfa``, ``users.with_failed_logins``
  and ``sessions.active`` describe the **current** state of the system and
  ignore the window entirely.  ``users.new_in_window``,
  ``sessions.created_in_window``, ``sessions.revoked_in_window``, ``mfa.*``,
  ``audit.*``, ``audit_activity.*``, ``protective_actions.*`` and every series
  counter are **window-scoped** over ``[from, to)`` (design 5.1 rule 13).
* **Half-open windows.**  Every window predicate is ``[from, to)`` and every
  timestamp is timezone-aware UTC (design 4.0).  An event exactly at ``to`` is
  excluded; one exactly at ``from`` is included.
* **The audit feed is deliberately narrow.**  ``audit_activity.recent``
  exposes ``id``, ``action``, ``actor``, ``resource``, ``resource_id`` and
  ``created_at`` only.  It never exposes ``before_state``, ``after_state``,
  ``ip_address`` or ``user_agent`` - those stay on the ``SECURITY_ADMIN`` audit
  page, so this endpoint does not become a second, less-guarded copy of it
  (design 3.3, 8 item 9).
* **``actor`` is resolved to a username.**  Core owns ``users``, so the
  provider resolves ``actor_id`` to ``users.username``.  A system action has
  no ``actor_id``, so the literal ``actor_type`` (``system``) is returned
  instead (design 4.2, reference R1.10).
* **Zero-filled buckets.**  The series carries every bucket of the window,
  even the empty ones, with UTC-floored labels (design 5.3).

Cross-database parity
---------------------
The production database is PostgreSQL; the unit-test suite runs on SQLite.
Both must produce identical numbers (design 5.2), so this module never uses a
PostgreSQL-only SQL construct for anything that is counted:

* the bucketing expression is dialect-specific (PostgreSQL ``date_trunc`` with
  an explicit ``AT TIME ZONE 'UTC'``, SQLite ``strftime``) but both are
  normalised to the *same* UTC bucket grid, which is computed here in Python;
* the ``protective_action:<ACTION>`` prefix is split in Python, so the
  ``split_part`` of reference R1.9 and the Python equivalent agree on both
  backends.

The endpoint is read-only: it never writes to the database and never touches
the authentication, IAM, session-expiry or token code paths.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session as OrmSession

from app.db import get_core_db
from app.internal_auth import verify_internal_secret
from app.models import AuditLog, MfaTransaction, Session, User
from app.time_utils import as_utc, utc_now

router = APIRouter(prefix="/api/v1/internal", tags=["core-internal"])


# =============================================================================
# Canonical vocabularies
# =============================================================================

#: The canonical user statuses (design R2 / ``app/schemas.py::UserStatus``).
USER_STATUSES: Tuple[str, ...] = ("active", "suspended", "locked")

#: The canonical MFA transaction statuses (design R2).
MFA_STATUSES: Tuple[str, ...] = ("pending", "completed", "expired", "failed")

#: The canonical audit actor types (design R2).
ACTOR_TYPES: Tuple[str, ...] = ("user", "system")

#: The prefix of the audit actions that describe a protective action
#: (design 4.2 / reference R1.9).
PROTECTIVE_ACTION_PREFIX = "protective_action:"

#: The canonical protective actions (``app/schemas.py::SecurityAction``).
PROTECTIVE_ACTIONS: Tuple[str, ...] = (
    "REQUIRE_MFA",
    "REVOKE_SESSIONS",
    "LOCK_USER",
    "FORCE_LOGOUT",
)

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

#: The default window when neither ``from`` nor ``to`` is supplied (24 h).
DEFAULT_WINDOW_HOURS = 24

#: The maximum number of rows in the audit activity feed (design 3.3, 4.2).
MAX_RECENT_AUDIT_ROWS = 10


# =============================================================================
# Small helpers
# =============================================================================

def _bad_request(detail: str) -> HTTPException:
    """A 400 with the design's error shape (design 4.0 / 6.1.2)."""
    return HTTPException(status_code=400, detail=detail)


def _iso(value: datetime) -> str:
    """ISO-8601 UTC representation of an instant."""
    return as_utc(value).isoformat()


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
    start = (
        as_utc(from_)
        if from_ is not None
        else end - timedelta(hours=DEFAULT_WINDOW_HOURS)
    )

    if start >= end:
        raise _bad_request("'from' must be strictly earlier than 'to'")

    span = end - start
    if span > timedelta(days=MAX_WINDOW_DAYS):
        raise _bad_request(f"window must not exceed {MAX_WINDOW_DAYS} days")

    if bucket is not None and bucket not in BUCKETS + (BUCKET_AUTO,):
        raise _bad_request(
            f"'bucket' must be one of: {', '.join(BUCKETS + (BUCKET_AUTO,))}"
        )

    # ``bucket=auto`` is resolved from the window length (design 3.2 rule 5):
    # ``day`` when the window exceeds 72 h, ``hour`` otherwise.  An omitted
    # bucket resolves the same way.
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
    model,
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
    stmt = select(*columns).select_from(model).where(*conditions)
    row = db.execute(stmt).one()
    return {
        value: int(row[index] or 0)
        for index, value in enumerate(vocabulary)
    }


def _grouped_counts(
    db: OrmSession,
    model,
    column,
    conditions: Sequence[Any],
) -> Dict[str, int]:
    """Count rows grouped by ``column`` over the matching population."""
    stmt = (
        select(column, func.count())
        .select_from(model)
        .where(*conditions)
        .group_by(column)
    )
    out: Dict[str, int] = {}
    for value, count in db.execute(stmt).all():
        if value is None:
            continue
        out[str(value)] = int(count)
    return out


# =============================================================================
# Section builders
# =============================================================================

def _users_section(db: OrmSession, start: datetime, end: datetime) -> Dict[str, Any]:
    """The ``users`` block (design 4.2).

    Every field except ``new_in_window`` is **point-in-time**: it describes the
    current state of the account base and ignores the window (design 5.1
    rule 13).
    """
    total = int(db.execute(
        select(func.count()).select_from(User)
    ).scalar_one())

    by_status = _conditional_counts(db, User, User.status, USER_STATUSES, [])

    mfa_required = int(db.execute(
        select(func.count()).select_from(User).where(User.admin_mfa_required.is_(True))
    ).scalar_one())

    forced_mfa = int(db.execute(
        select(func.count()).select_from(User).where(User.detection_mfa_once.is_(True))
    ).scalar_one())

    # ``with_failed_logins`` is a point-in-time flag on the account, not a
    # window count - a user who failed three times last month still counts.
    with_failed_logins = int(db.execute(
        select(func.count()).select_from(User).where(User.failed_login_count > 0)
    ).scalar_one())

    # ``new_in_window`` is the one window-scoped field of the block.
    new_in_window = int(db.execute(
        select(func.count()).select_from(User).where(
            User.created_at >= start, User.created_at < end
        )
    ).scalar_one())

    return {
        "total": total,
        "by_status": by_status,
        "mfa_required": mfa_required,
        "forced_mfa": forced_mfa,
        "new_in_window": new_in_window,
        "with_failed_logins": with_failed_logins,
    }


def _sessions_section(db: OrmSession, start: datetime, end: datetime) -> Dict[str, Any]:
    """The ``sessions`` block (design 4.2).

    ``active`` is point-in-time (``revoked_at IS NULL AND expires_at > now()``);
    the two ``_in_window`` counters are window-scoped.
    """
    now = utc_now()

    active = int(db.execute(
        select(func.count()).select_from(Session).where(
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    ).scalar_one())

    created_in_window = int(db.execute(
        select(func.count()).select_from(Session).where(
            Session.created_at >= start, Session.created_at < end
        )
    ).scalar_one())

    revoked_in_window = int(db.execute(
        select(func.count()).select_from(Session).where(
            Session.revoked_at >= start, Session.revoked_at < end
        )
    ).scalar_one())

    return {
        "active": active,
        "created_in_window": created_in_window,
        "revoked_in_window": revoked_in_window,
    }


def _mfa_section(db: OrmSession, start: datetime, end: datetime) -> Dict[str, Any]:
    """The ``mfa`` block (design 4.2).

    The window anchor is ``mfa_transactions.created_at``; ``challenges`` is the
    number of transactions created in the window, and the three status counts
    break that population down.
    """
    conditions = [
        MfaTransaction.created_at >= start,
        MfaTransaction.created_at < end,
    ]

    challenges = int(db.execute(
        select(func.count()).select_from(MfaTransaction).where(*conditions)
    ).scalar_one())

    by_status = _conditional_counts(
        db, MfaTransaction, MfaTransaction.status, MFA_STATUSES, conditions
    )

    return {
        "challenges": challenges,
        "completed": by_status.get("completed", 0),
        "failed": by_status.get("failed", 0),
        "expired": by_status.get("expired", 0),
    }


def _audit_conditions(start: datetime, end: datetime) -> List[Any]:
    """The window predicate of the audit trail (half-open ``[from, to)``)."""
    return [AuditLog.created_at >= start, AuditLog.created_at < end]


def _audit_section(
    db: OrmSession,
    start: datetime,
    end: datetime,
    by_action: Dict[str, int],
) -> Dict[str, Any]:
    """The compact ``audit`` block (design 4.2).

    ``by_action`` is the same count as ``audit_activity.by_action`` - Core
    computes it once and returns it in both places (design 4.2 field notes).
    The breakdown is therefore passed in rather than recomputed.
    """
    total = int(db.execute(
        select(func.count()).select_from(AuditLog).where(
            *_audit_conditions(start, end)
        )
    ).scalar_one())

    return {"total": total, "by_action": by_action}


def _audit_activity_section(
    db: OrmSession,
    start: datetime,
    end: datetime,
    by_action: Dict[str, int],
) -> Dict[str, Any]:
    """The ``audit_activity`` review block (design 3.3 / 4.2, reference R1.10).

    The breakdown and the feed share one ``WHERE`` clause, so they always
    describe the same window.  The feed deliberately selects **no**
    ``before_state``, ``after_state``, ``ip_address`` or ``user_agent``
    column.
    """
    conditions = _audit_conditions(start, end)

    # ``actor_type`` has a **closed** vocabulary (``chk_audit_logs_actor_type``),
    # so the breakdown carries the full canonical key set, zero-filled - the
    # UI never has to handle a missing key (design 3.3).  ``by_action`` on
    # the other hand is open (``protective_action:<ACTION>``), so it stays
    # sparse.
    by_actor_type = _conditional_counts(
        db, AuditLog, AuditLog.actor_type, ACTOR_TYPES, conditions
    )

    # The feed resolves the actor to a username.  The join is a LEFT JOIN
    # because ``actor_id`` is nullable and ``ON DELETE SET NULL``.
    rows = db.execute(
        select(
            AuditLog.id,
            AuditLog.action,
            AuditLog.actor_type,
            AuditLog.resource,
            AuditLog.resource_id,
            AuditLog.created_at,
            User.username,
        )
        .select_from(AuditLog)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc())
        .limit(MAX_RECENT_AUDIT_ROWS)
    ).all()

    recent: List[Dict[str, Any]] = []
    for (
        row_id, action, actor_type, resource, resource_id, created_at, username
    ) in rows:
        recent.append({
            "id": str(row_id),
            "action": action,
            # A system action has no ``actor_id``, so it falls back to the
            # literal actor type (reference R1.10).
            "actor": username if username is not None else actor_type,
            "resource": resource,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "created_at": _iso(created_at),
        })

    return {
        "by_action": by_action,
        "by_actor_type": by_actor_type,
        "recent": recent,
    }


def _protective_actions_section(
    db: OrmSession,
    start: datetime,
    end: datetime,
) -> Dict[str, Any]:
    """The ``protective_actions`` block (design 4.2, reference R1.9).

    A protective action is an audit row whose action starts with
    ``protective_action:``; the suffix after the ``:`` is the action name.
    The prefix is split in Python so the PostgreSQL ``split_part`` of
    reference R1.9 and this implementation agree on both backends.
    """
    conditions = _audit_conditions(start, end)

    rows = db.execute(
        select(AuditLog.action)
        .select_from(AuditLog)
        .where(*conditions, AuditLog.action.like(f"{PROTECTIVE_ACTION_PREFIX}%"))
    ).all()

    by_action: Dict[str, int] = {}
    for (action,) in rows:
        if not isinstance(action, str):
            continue
        name = action[len(PROTECTIVE_ACTION_PREFIX):]
        if not name:
            # A bare ``protective_action:`` carries no action name and is
            # skipped rather than reported under an empty key.
            continue
        by_action[name] = by_action.get(name, 0) + 1

    return {
        "total": sum(by_action.values()),
        "by_action": by_action,
    }


# =============================================================================
# The series
# =============================================================================

def _series(
    db: OrmSession,
    start: datetime,
    end: datetime,
    bucket: str,
) -> List[Dict[str, Any]]:
    """The flat, zero-filled series (design 4.2 / 5.3).

    Every bucket of the window is present, even when it holds no data.  The
    three counters are the **bucketed counterparts** of three window-scoped
    aggregates, which is what the design's own example shows: the bucket
    carries ``logins: 88``, ``mfa_challenges: 20`` and ``audit_events: 45``
    while the aggregates carry ``sessions.created_in_window: 88``,
    ``mfa.challenges: 20`` and ``audit.total: 45``.

    * ``logins`` - the sessions created in the bucket, i.e. the successful
      logins that produced a session.  It is **not** the count of the
      ``login_success`` audit rows: an audit row is one of the
      ``audit_events`` of its bucket, so a login count derived from the audit
      trail could never exceed the audit-event count.  The failure volume
      lives in Detection ``login_attempts`` and is not part of this series
      (reference R2.4).
    * ``mfa_challenges`` - the MFA transactions created in the bucket.
    * ``audit_events`` - every audit row in the bucket.
    """
    dialect_name = db.get_bind().dialect.name

    login_label = _bucket_label(Session.created_at, bucket, dialect_name).label(
        "bucket_start"
    )
    login_rows = db.execute(
        select(login_label, func.count())
        .select_from(Session)
        .where(
            Session.created_at >= start,
            Session.created_at < end,
        )
        .group_by(login_label)
    ).all()

    mfa_label = _bucket_label(MfaTransaction.created_at, bucket, dialect_name).label(
        "bucket_start"
    )
    mfa_rows = db.execute(
        select(mfa_label, func.count())
        .select_from(MfaTransaction)
        .where(
            MfaTransaction.created_at >= start,
            MfaTransaction.created_at < end,
        )
        .group_by(mfa_label)
    ).all()

    audit_label = _bucket_label(AuditLog.created_at, bucket, dialect_name).label(
        "bucket_start"
    )
    audit_rows = db.execute(
        select(audit_label, func.count())
        .select_from(AuditLog)
        .where(AuditLog.created_at >= start, AuditLog.created_at < end)
        .group_by(audit_label)
    ).all()

    logins: Dict[datetime, int] = {}
    for label, count in login_rows:
        bucket_start = _label_to_bucket_start(label)
        if bucket_start is None:
            continue
        logins[bucket_start] = int(count)

    challenges: Dict[datetime, int] = {}
    for label, count in mfa_rows:
        bucket_start = _label_to_bucket_start(label)
        if bucket_start is None:
            continue
        challenges[bucket_start] = int(count)

    events: Dict[datetime, int] = {}
    for label, count in audit_rows:
        bucket_start = _label_to_bucket_start(label)
        if bucket_start is None:
            continue
        events[bucket_start] = int(count)

    series: List[Dict[str, Any]] = []
    for bucket_start in _bucket_starts(start, end, bucket):
        series.append({
            "bucket_start": _iso(bucket_start),
            "logins": logins.get(bucket_start, 0),
            "mfa_challenges": challenges.get(bucket_start, 0),
            "audit_events": events.get(bucket_start, 0),
        })
    return series


# =============================================================================
# The endpoint
# =============================================================================

@router.get("/analytics/core")
async def core_analytics(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    bucket: Optional[str] = Query(None),
    x_internal_secret: Optional[str] = Header(None),
    db: OrmSession = Depends(get_core_db),
) -> Dict[str, Any]:
    """The Core-owned analytics aggregate for the Manager facade.

    The window is half-open ``[from, to)`` and every timestamp is UTC.
    """
    verify_internal_secret(x_internal_secret)

    start, end, resolved_bucket = _resolve_window(
        _parse_dt_param("from", from_),
        _parse_dt_param("to", to),
        bucket,
    )

    # ``audit.by_action`` and ``audit_activity.by_action`` are the same
    # count, so Core computes the breakdown once and hands it to both
    # sections (design 4.2 field notes).
    audit_by_action = _grouped_counts(
        db, AuditLog, AuditLog.action, _audit_conditions(start, end)
    )

    return {
        "generated_at": _iso(utc_now()),
        "window": {"from": _iso(start), "to": _iso(end)},
        "bucket": resolved_bucket,
        "users": _users_section(db, start, end),
        "sessions": _sessions_section(db, start, end),
        "mfa": _mfa_section(db, start, end),
        "audit": _audit_section(db, start, end, audit_by_action),
        "audit_activity": _audit_activity_section(db, start, end, audit_by_action),
        "protective_actions": _protective_actions_section(db, start, end),
        "series": _series(db, start, end, resolved_bucket),
    }


__all__ = [
    "router",
    "USER_STATUSES",
    "MFA_STATUSES",
    "ACTOR_TYPES",
    "PROTECTIVE_ACTIONS",
]
