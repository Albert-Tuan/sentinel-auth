"""Parity checks for Detection's six canonical runtime features."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.detection import build_features
from app.models import LoginAttempt


def attempt(user_id, timestamp, *, outcome="success", ip="10.0.0.1", device="known"):
    return LoginAttempt(
        event_id=uuid4(),
        user_id=user_id,
        username_attempted="parity-user",
        outcome=outcome,
        ip_address=ip,
        user_agent=device,
        timestamp=timestamp,
        status="pending",
    )


def commit(db, *rows):
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)


def test_all_six_features_use_only_strictly_earlier_history(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    history = [
        attempt(user_id, now - timedelta(minutes=10), outcome="failure"),
        attempt(user_id, now - timedelta(minutes=5), ip="10.0.0.2"),
    ]
    current = attempt(
        user_id,
        now,
        outcome="failure",
        ip="10.0.0.99",
        device="new",
    )
    commit(db, *history, current)

    assert build_features(db, current) == {
        "hour_of_day": 12,
        "fail_count_24h": 1,
        "ip_change_rate_7d": pytest.approx(1.0),
        "new_device": True,
        "average_login_interval_seconds": 300,
        "deviation_score": pytest.approx(0.0),
    }


def test_hour_of_day_is_utc():
    local_time = datetime(2026, 2, 1, 19, tzinfo=timezone(timedelta(hours=7)))
    current = attempt(None, local_time)

    assert build_features(None, current)["hour_of_day"] == 12


@pytest.mark.parametrize(
    ("current_ip", "expected_rate"),
    [
        ("10.0.0.2", 1 / 2),
        ("10.0.0.99", 1.0),
    ],
)
def test_old_and_new_ip(db, current_ip, expected_rate):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, ip=current_ip)
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=10)),
        attempt(user_id, now - timedelta(minutes=5), ip="10.0.0.2"),
        current,
    )

    features = build_features(db, current)
    assert features["ip_change_rate_7d"] == pytest.approx(expected_rate)


def test_current_ip_dominant_in_prior_history(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, ip="dominant")
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=15), ip="dominant"),
        attempt(user_id, now - timedelta(minutes=10), ip="other"),
        attempt(user_id, now - timedelta(minutes=5), ip="dominant"),
        current,
    )

    assert build_features(db, current)["ip_change_rate_7d"] == pytest.approx(1 / 3)


def test_no_prior_ip_history_has_zero_rate(db):
    now = datetime(2026, 2, 1, 12)
    current = attempt(uuid4(), now, ip="first")
    commit(db, current)

    assert build_features(db, current)["ip_change_rate_7d"] == 0.0


def test_24h_lower_boundary_is_inclusive_and_current_failure_is_exclusive(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    outside = timedelta(microseconds=1)
    current = attempt(user_id, now, outcome="failure")
    commit(
        db,
        attempt(user_id, now - timedelta(hours=24), outcome="failure"),
        attempt(user_id, now - timedelta(hours=24) - outside, outcome="failure"),
        current,
    )

    assert build_features(db, current)["fail_count_24h"] == 1


def test_7d_lower_boundary_is_inclusive_and_current_ip_is_exclusive(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    outside = timedelta(microseconds=1)
    current = attempt(user_id, now, ip="current")
    commit(
        db,
        attempt(user_id, now - timedelta(days=7), ip="at-7d"),
        attempt(user_id, now - timedelta(days=7) - outside, ip="before-7d"),
        current,
    )

    assert build_features(db, current)["ip_change_rate_7d"] == pytest.approx(1.0)


def test_30d_lower_boundary_is_inclusive(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    outside = timedelta(microseconds=1)
    current = attempt(user_id, now, device="at-30d")
    commit(
        db,
        attempt(user_id, now - timedelta(days=30), device="at-30d"),
        attempt(user_id, now - timedelta(days=30) - outside, device="before-30d"),
        current,
    )

    assert build_features(db, current)["new_device"] is False


@pytest.mark.parametrize(
    ("prior_device", "current_device", "expected"),
    [
        ("known", "known", False),
        ("known", "new", True),
    ],
)
def test_seen_and_unseen_user_agent(db, prior_device, current_device, expected):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device=current_device)
    commit(db, attempt(user_id, now - timedelta(minutes=5), device=prior_device), current)

    assert build_features(db, current)["new_device"] is expected


def test_no_prior_user_agent_history_is_new(db):
    now = datetime(2026, 2, 1, 12)
    current = attempt(uuid4(), now, device="first")
    commit(db, current)

    assert build_features(db, current)["new_device"] is True


def test_missing_current_user_agent_is_not_new(db):
    now = datetime(2026, 2, 1, 12)
    current = attempt(uuid4(), now, device=None)
    commit(db, current)

    assert build_features(db, current)["new_device"] is False


def test_device_older_than_30d_is_new(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="expired")
    commit(
        db,
        attempt(user_id, now - timedelta(days=30, microseconds=1), device="expired"),
        current,
    )

    assert build_features(db, current)["new_device"] is True


def test_interval_uses_only_ten_most_recent_prior_timestamps(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now)
    history = [attempt(user_id, now - timedelta(minutes=minutes)) for minutes in range(11, 0, -1)]
    commit(db, *history, current)

    features = build_features(db, current)
    assert features["average_login_interval_seconds"] == 60
    assert features["deviation_score"] == pytest.approx(0.0)


@pytest.mark.parametrize("prior_count", [0, 1])
def test_insufficient_interval_history_returns_zero(db, prior_count):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    history = [attempt(user_id, now - timedelta(minutes=1))] if prior_count else []
    current = attempt(user_id, now)
    commit(db, *history, current)

    features = build_features(db, current)
    assert features["average_login_interval_seconds"] == 0
    assert features["deviation_score"] == 0.0


def test_deviation_score_is_clamped_to_one(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now)
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=4)),
        attempt(user_id, now - timedelta(minutes=3)),
        current,
    )

    features = build_features(db, current)
    assert features["average_login_interval_seconds"] == 60
    assert features["deviation_score"] == 1.0
