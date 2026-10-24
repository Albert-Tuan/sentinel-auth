"""ML tests moved to test_ml_runtime.py with the canonical strict contract."""

from app.ml import FEATURE_FIELDS


def test_canonical_feature_order_is_stable():
    assert FEATURE_FIELDS == (
        "hour_of_day",
        "fail_count_24h",
        "ip_change_rate_7d",
        "new_device",
        "average_login_interval_seconds",
        "deviation_score",
    )
