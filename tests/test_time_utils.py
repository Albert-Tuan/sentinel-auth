"""Unit tests for app/time_utils.py."""

from datetime import datetime, timezone, timedelta

import pytest

from app.time_utils import utc_now, as_utc


class TestUtcNow:
    def test_returns_aware_utc(self):
        """utc_now() returns a timezone-aware datetime with UTC tzinfo."""
        result = utc_now()
        assert result.tzinfo is not None, "utc_now() must return timezone-aware datetime"
        assert result.tzinfo == timezone.utc, "utc_now() must return UTC timezone"

    def test_is_recent(self):
        """utc_now() returns a value within the last 10 seconds."""
        now = utc_now()
        age = datetime.now(timezone.utc) - now
        assert timedelta(seconds=0) <= age <= timedelta(seconds=10)


class TestAsUtc:
    """Test as_utc() semantics.

    Contract:
    - Naive values are treated as UTC (numeric values preserved, tzinfo attached).
      This is safe ONLY for values the application contractually guarantees were
      created as UTC (e.g. legacy SQLite rows persisted by naive DateTime defaults).
    - Aware values are converted to UTC via astimezone(timezone.utc).
    """

    def test_naive_datetime_becomes_utc_aware(self):
        """Naive datetime → UTC-aware with same numeric values preserved."""
        naive = datetime(2026, 10, 9, 12, 0, 0)
        result = as_utc(naive)

        assert result.tzinfo is not None, "Result must be timezone-aware"
        assert result.tzinfo == timezone.utc, "Result must be UTC"
        assert result.year == 2026
        assert result.month == 10
        assert result.day == 9
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0

    def test_aware_utc_datetime_unchanged(self):
        """Already-UTC-aware datetime is returned as equivalent UTC-aware."""
        aware_utc = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
        result = as_utc(aware_utc)

        assert result.tzinfo == timezone.utc
        assert result == aware_utc

    def test_aware_non_utc_converted_to_utc(self):
        """Aware non-UTC datetime is converted to the equivalent UTC instant."""
        # 19:00 Asia/Ho_Chi_Minh (+07) = 12:00 UTC
        import zoneinfo
        asia_tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
        aware_plus07 = datetime(2026, 10, 9, 19, 0, 0, tzinfo=asia_tz)
        result = as_utc(aware_plus07)

        assert result.tzinfo == timezone.utc
        assert result.hour == 12
        assert result.minute == 0
        assert result == datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)

    def test_different_non_utc_zones_normalise_to_same_utc(self):
        """Two datetimes representing the same instant in different zones normalise
        to the same UTC value."""
        import zoneinfo

        # Asia/Ho_Chi_Minh = UTC+7; Asia/Dubai = UTC+4 (no DST in October).
        # Same instant: 22:00 Dubai = 01:00+1d Ho_Chi_Minh.
        tz_hcm = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
        tz_dubai = zoneinfo.ZoneInfo("Asia/Dubai")

        # 23:00 Dubai (+04:00) = 02:00+1d Ho_Chi_Minh (+07:00) = 19:00 UTC
        instant1 = datetime(2026, 10, 9, 23, 0, 0, tzinfo=tz_dubai)
        instant2 = datetime(2026, 10, 10, 2, 0, 0, tzinfo=tz_hcm)

        assert as_utc(instant1) == as_utc(instant2)
        assert as_utc(instant1).hour == 19
        assert as_utc(instant1).minute == 0
