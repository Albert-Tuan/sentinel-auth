"""Tests for the ML Service scoring endpoint (UC-DE-03)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml import ANOMALY_THRESHOLD, FEATURE_FIELDS, HeuristicAnomalyModel

client = TestClient(app)
SECRET = {"X-Internal-Secret": "changeme-in-production"}


def test_score_requires_internal_secret():
    response = client.post(
        "/api/v1/internal/ml/score", json={"features": {"hour_of_day": 2}}
    )
    assert response.status_code == 401


def test_score_returns_canonical_response_shape():
    """Field name is fixed by the ML team contract: normalized_anomaly_score."""
    response = client.post(
        "/api/v1/internal/ml/score",
        json={"features": {"hour_of_day": 2, "fail_count_24h": 5}},
        headers=SECRET,
    )
    assert response.status_code == 200
    body = response.json()
    assert "normalized_anomaly_score" in body
    assert 0.0 <= body["normalized_anomaly_score"] <= 1.0
    assert isinstance(body["is_anomaly"], bool)
    assert body["is_anomaly"] == (body["normalized_anomaly_score"] >= ANOMALY_THRESHOLD)
    assert body["model_status"] == "ready"
    assert body["model_version"]
    assert isinstance(body["reason_codes"], list)


def test_high_failure_count_scores_anomalous():
    response = client.post(
        "/api/v1/internal/ml/score",
        json={"features": {"fail_count_24h": 6}},
        headers=SECRET,
    )
    body = response.json()
    assert body["is_anomaly"] is True
    assert "high_fail_count" in body["reason_codes"]


def test_normal_login_scores_low():
    response = client.post(
        "/api/v1/internal/ml/score",
        json={
            "features": {
                "hour_of_day": 10,
                "fail_count_24h": 0,
                "ip_change_rate_7d": 0.1,
                "new_device": False,
                "average_login_interval_seconds": 3600,
                "deviation_score": 0.1,
            }
        },
        headers=SECRET,
    )
    body = response.json()
    assert body["normalized_anomaly_score"] < 0.25
    assert body["is_anomaly"] is False


def test_empty_features_are_accepted():
    """Missing features must not 500 - the engine degrades gracefully."""
    response = client.post(
        "/api/v1/internal/ml/score", json={"features": {}}, headers=SECRET
    )
    assert response.status_code == 200


def test_invalid_feature_type_is_rejected():
    response = client.post(
        "/api/v1/internal/ml/score",
        json={"features": {"hour_of_day": 99}},
        headers=SECRET,
    )
    assert response.status_code == 422


def test_feature_contract_publishes_exactly_six_features():
    """Rules may only reference these 6 fields (DECISIONS section 1.4)."""
    response = client.get("/api/v1/internal/ml/features")
    assert response.status_code == 200
    body = response.json()
    assert body["features"] == list(FEATURE_FIELDS)
    assert len(body["features"]) == 6
    assert body["response_field"] == "normalized_anomaly_score"


def test_health_reports_model_version():
    response = client.get("/api/v1/internal/ml/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["anomaly_threshold"] == ANOMALY_THRESHOLD


def test_model_score_always_within_unit_range():
    model = HeuristicAnomalyModel()
    for hour in range(24):
        for failures in (0, 1, 3, 5, 20):
            score, _ = model.predict({"hour_of_day": hour, "fail_count_24h": failures})
            assert 0.0 <= score <= 1.0
