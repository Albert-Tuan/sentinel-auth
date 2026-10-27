"""Parity checks for Detection's six canonical runtime features."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.detection import build_features
from app.models import LoginAttempt


def attempt(user_id, timestamp, *, outcome="success", ip="10.0.0.1", device="known",
            fingerprint=None):
    return LoginAttempt(
        event_id=uuid4(),
        user_id=user_id,
        username_attempted="parity-user",
        outcome=outcome,
        ip_address=ip,
        user_agent=device,
        device_fingerprint=fingerprint,
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


# =============================================================================
# Fingerprint-first device novelty (P1-3)
# =============================================================================

FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def test_fingerprint_wins_over_user_agent_when_both_are_present(db):
    """A KNOWN fingerprint beats an UNKNOWN User-Agent.

    This is the core of the fingerprint-first semantics: the fingerprint is
    the authoritative device identity, and the User-Agent is only a fallback
    for events that carry no fingerprint at all.
    """
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="brand-new-ua", fingerprint=FP_A)
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=5), device="old-ua", fingerprint=FP_A),
        current,
    )

    assert build_features(db, current)["new_device"] is False


def test_unseen_fingerprint_with_known_user_agent_is_new(db):
    """A KNOWN User-Agent does NOT rescue an UNSEEN fingerprint."""
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="known-ua", fingerprint=FP_B)
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=5), device="known-ua", fingerprint=FP_A),
        current,
    )

    assert build_features(db, current)["new_device"] is True


def test_two_devices_with_the_same_user_agent_are_distinguished_by_fingerprint(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="same-ua", fingerprint=FP_B)
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=5), device="same-ua", fingerprint=FP_A),
        current,
    )

    assert build_features(db, current)["new_device"] is True


def test_user_agent_proxy_is_used_when_no_fingerprint_is_available(db):
    """An event without a fingerprint falls back to the User-Agent proxy."""
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="known-ua", fingerprint=None)
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=5), device="known-ua", fingerprint=None),
        current,
    )

    assert build_features(db, current)["new_device"] is False


def test_fingerprint_history_uses_the_30_day_window(db):
    """A fingerprint older than 30 days no longer counts as known."""
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="ua", fingerprint=FP_A)
    commit(
        db,
        attempt(
            user_id,
            now - timedelta(days=30, microseconds=1),
            device="ua",
            fingerprint=FP_A,
        ),
        current,
    )

    assert build_features(db, current)["new_device"] is True


def test_fingerprint_30d_lower_boundary_is_inclusive(db):
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="ua", fingerprint=FP_A)
    commit(
        db,
        attempt(user_id, now - timedelta(days=30), device="ua", fingerprint=FP_A),
        current,
    )

    assert build_features(db, current)["new_device"] is False


def test_current_event_is_excluded_from_the_fingerprint_history(db):
    """The event being scored must not make itself 'known'."""
    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="ua", fingerprint=FP_A)
    commit(db, current)

    assert build_features(db, current)["new_device"] is True


def test_no_device_signal_at_all_is_not_new(db):
    now = datetime(2026, 2, 1, 12)
    current = attempt(uuid4(), now, device=None, fingerprint=None)
    commit(db, current)

    assert build_features(db, current)["new_device"] is False


# =============================================================================
# Device-signal provenance is logging metadata, NOT an ML feature
# =============================================================================

def test_device_signal_source_reports_fingerprint(db):
    from app.detection import DEVICE_SIGNAL_FINGERPRINT, device_signal_source

    attempt_row = attempt(uuid4(), datetime(2026, 2, 1, 12), fingerprint=FP_A)
    assert device_signal_source(attempt_row) == DEVICE_SIGNAL_FINGERPRINT


def test_device_signal_source_reports_user_agent_proxy(db):
    from app.detection import DEVICE_SIGNAL_USER_AGENT_PROXY, device_signal_source

    attempt_row = attempt(uuid4(), datetime(2026, 2, 1, 12), fingerprint=None)
    assert device_signal_source(attempt_row) == DEVICE_SIGNAL_USER_AGENT_PROXY


def test_device_signal_source_reports_unavailable(db):
    from app.detection import DEVICE_SIGNAL_UNAVAILABLE, device_signal_source

    attempt_row = attempt(uuid4(), datetime(2026, 2, 1, 12), device=None, fingerprint=None)
    assert device_signal_source(attempt_row) == DEVICE_SIGNAL_UNAVAILABLE


def test_device_signal_source_is_never_part_of_the_feature_vector(db):
    """``device_signal_source`` must not leak into the 6-feature vector."""
    now = datetime(2026, 2, 1, 12)
    current = attempt(uuid4(), now, device="ua", fingerprint=FP_A)
    commit(db, current)

    features = build_features(db, current)
    assert "device_signal_source" not in features
    assert len(features) == 6


# =============================================================================
# Detection <-> ML contract parity
# =============================================================================

CANONICAL_FEATURES = (
    "hour_of_day",
    "fail_count_24h",
    "ip_change_rate_7d",
    "new_device",
    "average_login_interval_seconds",
    "deviation_score",
)


def test_feature_vector_has_exactly_the_six_canonical_features(db):
    now = datetime(2026, 2, 1, 12)
    current = attempt(uuid4(), now)
    commit(db, current)

    features = build_features(db, current)
    assert set(features) == set(CANONICAL_FEATURES)
    assert len(features) == 6


def test_ml_feature_order_matches_the_canonical_order():
    from app.ml import FEATURE_FIELDS

    assert tuple(FEATURE_FIELDS) == CANONICAL_FEATURES


def test_allowed_feature_fields_match_the_ml_contract():
    from app.ml import FEATURE_FIELDS
    from app.schemas import ALLOWED_FEATURE_FIELDS

    assert set(ALLOWED_FEATURE_FIELDS) == set(FEATURE_FIELDS)


def test_ml_login_features_model_exposes_exactly_the_six_fields():
    from app.ml import FEATURE_FIELDS, LoginFeatures

    assert set(LoginFeatures.model_fields) == set(FEATURE_FIELDS)


def test_feature_vector_satisfies_the_ml_request_contract(db):
    """A Detection feature vector must be accepted by the ML request model."""
    from app.ml import LoginFeatures

    now = datetime(2026, 2, 1, 12)
    user_id = uuid4()
    current = attempt(user_id, now, device="ua", fingerprint=FP_A)
    commit(
        db,
        attempt(user_id, now - timedelta(minutes=10), outcome="failure"),
        attempt(user_id, now - timedelta(minutes=5)),
        current,
    )

    features = build_features(db, current)
    # Pydantic validates the ranges; a TypeError would mean a wrong type.
    validated = LoginFeatures(**features)
    assert validated.hour_of_day == 12
    assert validated.new_device is True


def test_detection_sends_the_features_in_the_canonical_order(db):
    """The order of the keys in the vector must match the ML contract."""
    from app.ml import FEATURE_FIELDS

    now = datetime(2026, 2, 1, 12)
    current = attempt(uuid4(), now)
    commit(db, current)

    features = build_features(db, current)
    assert tuple(features.keys()) == CANONICAL_FEATURES
    assert tuple(features.keys()) == tuple(FEATURE_FIELDS)


def test_ml_artifact_feature_order_is_validated():
    """An artifact whose feature order differs is rejected at load time."""
    import joblib
    import numpy as np
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from pathlib import Path
    import tempfile

    from app.ml import FEATURE_FIELDS, IsolationForestRuntime

    model = IsolationForest(n_estimators=5, random_state=0).fit(
        np.zeros((4, len(FEATURE_FIELDS)))
    )
    scaler = StandardScaler().fit(np.zeros((4, 1)))

    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.joblib"
        joblib.dump(
            {
                "model": model,
                "score_scaler": scaler,
                "features": list(FEATURE_FIELDS),
                "version": "test",
            },
            good,
        )
        # The canonical order loads fine.
        IsolationForestRuntime.load(good)

        bad = Path(tmp) / "bad.joblib"
        reversed_features = list(reversed(FEATURE_FIELDS))
        joblib.dump(
            {
                "model": model,
                "score_scaler": scaler,
                "features": reversed_features,
                "version": "test",
            },
            bad,
        )
        with pytest.raises(ValueError, match="feature order"):
            IsolationForestRuntime.load(bad)
