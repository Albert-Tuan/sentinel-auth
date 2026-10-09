"""Timezone-safe timestamp utilities.

Policy: all application timestamps representing real instants are
timezone-aware UTC (datetime with tzinfo=timezone.utc).

PostgreSQL TIMESTAMPTZ columns store instants correctly regardless of
session timezone when Python values are timezone-aware UTC.
PostgreSQL interprets naive values in its session timezone, which caused
TIME-01: a naive datetime created at "09:31 UTC" was stored as "09:31 +07"
by a session in Asia/Ho_Chi_Minh, making OTPs appear ~7 hours expired.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC instant as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC.

    - Already aware: returned as-is (tzinfo preserved; UTC conversion would
      be a semantic change so we leave other zones untouched).
    - Naive: treated as UTC — the numeric values are preserved and the UTC
      tzinfo is attached.  This is safe ONLY for values that are contractually
      known to have been created as UTC by the application (e.g. legacy SQLite
      rows persisted by SQLAlchemy DateTime defaults that never set timezone).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
