"""Canonical ML contract and real-artifact inference tests."""
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from functools import partial

import joblib
import anyio
import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler

from app import ml
from app.models import FeatureStatistic, InferenceLog, ModelVersion


FEATURES = {
    "hour_of_day": 14,
    "fail_count_24h": 2,
    "ip_change_rate_7d": 0.25,
    "new_device": True,
    "average_login_interval_seconds": 3600,
    "deviation_score": 0.3,
}
SECRET_HEADER = {"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"}


class ApiClient:
    def __init__(self, app):
        self.app = app

    async def _request(self, method, path, **kwargs):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    def post(self, path, **kwargs):
        return anyio.run(partial(self._request, "POST", path, **kwargs))

    def get(self, path, **kwargs):
        return anyio.run(partial(self._request, "GET", path, **kwargs))


@pytest.fixture(scope="session")
def artifact(tmp_path_factory):
    rng = np.random.default_rng(42)
    training = rng.uniform(size=(200, 6))
    training[:, 0] *= 23
    training[:, 1] *= 8
    training[:, 4] *= 10_000
    model = IsolationForest(contamination="auto", random_state=42).fit(training)
    oriented = -model.decision_function(training)
    scaler = MinMaxScaler(clip=True).fit(oriented.reshape(-1, 1))
    path = tmp_path_factory.mktemp("ml-artifact") / "model.joblib"
    joblib.dump({
        "model": model,
        "score_scaler": scaler,
        "features": list(ml.FEATURE_FIELDS),
        "version": "test-isolation-forest",
    }, path)
    return path


@pytest.fixture()
def client(db, artifact, monkeypatch):
    monkeypatch.setenv("ML_MODEL_PATH", str(artifact))
    ml.reset_runtime()
    app = FastAPI()
    app.include_router(ml.router)
    app.dependency_overrides = {ml.get_ml_db: lambda: db}
    yield ApiClient(app)
    ml.reset_runtime()


def payload(features=None):
    return {"request_id": str(uuid4()), "features": features or FEATURES}


class ImmediateRequest:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    async def body(self):
        return self._body


def complete_without_event_loop(coroutine):
    with pytest.raises(StopIteration) as completed:
        coroutine.send(None)
    return completed.value.value


def score_without_event_loop(db, request):
    return complete_without_event_loop(
        ml.score(ImmediateRequest(request), SECRET_HEADER["X-Internal-Secret"], db)
    )


def test_score_requires_internal_secret(client):
    assert client.post("/api/v1/internal/ml/score", json=payload()).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"features": FEATURES},
        {"request_id": str(uuid4()), "features": {}},
        {"request_id": str(uuid4()), "features": {k: v for k, v in FEATURES.items() if k != "new_device"}},
        payload({**FEATURES, "unknown": 1}),
        payload({**FEATURES, "hour_of_day": 24}),
        payload({**FEATURES, "fail_count_24h": -1}),
        payload({**FEATURES, "ip_change_rate_7d": 1.1}),
        payload({**FEATURES, "new_device": 1}),
        payload({**FEATURES, "average_login_interval_seconds": -1}),
        payload({**FEATURES, "deviation_score": -0.1}),
    ],
)
def test_invalid_contract_returns_400(client, body):
    assert client.post("/api/v1/internal/ml/score", json=body, headers=SECRET_HEADER).status_code == 400


def test_valid_request_runs_real_artifact_and_logs(client, db):
    request = payload()
    response = client.post("/api/v1/internal/ml/score", json=request, headers=SECRET_HEADER)
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == request["request_id"]
    assert 0.0 <= body["normalized_anomaly_score"] <= 1.0
    assert isinstance(body["is_anomaly"], bool)
    assert body["model_version"] == "test-isolation-forest"
    assert body["model_status"] == "ready"
    assert set(body["reason_codes"]) <= set(ml.REASON_CODES)

    log = db.query(InferenceLog).filter_by(request_id=UUID(request["request_id"])).one()
    assert log.features == FEATURES
    assert log.model_version_id is None
    assert log.model_version_used == "test-isolation-forest"
    assert log.model_status == "ready"
    assert log.processing_time_ms >= 0


def test_environment_path_inference_log_has_no_registry_id(db, artifact, monkeypatch):
    monkeypatch.setenv("ML_MODEL_PATH", str(artifact))
    ml.reset_runtime()
    request = payload()

    response = score_without_event_loop(db, request)

    assert response.model_version == "test-isolation-forest"
    log = db.query(InferenceLog).filter_by(request_id=UUID(request["request_id"])).one()
    assert log.model_version_id is None
    assert log.model_version_used == "test-isolation-forest"


def test_registry_model_path_overrides_environment(db, artifact, tmp_path, monkeypatch):
    monkeypatch.setenv("ML_MODEL_PATH", str(tmp_path / "fallback.joblib"))
    registered = ModelVersion(
        name="test", version="test-isolation-forest", model_path=str(artifact),
        status="active", is_production=True, config={},
    )
    db.add(registered)
    db.commit()
    assert ml.resolve_model_path(db) == artifact
    assert ml.get_ml_runtime(db).model_version_id == registered.id


def test_registered_inference_log_references_registry_row(db, artifact, monkeypatch):
    monkeypatch.delenv("ML_MODEL_PATH", raising=False)
    registered = ModelVersion(
        name="test", version="registry-entry", model_path=str(artifact),
        status="active", is_production=True, config={},
    )
    db.add(registered)
    db.commit()
    ml.reset_runtime()

    request = payload()
    response = score_without_event_loop(db, request)

    assert response.model_version == "test-isolation-forest"
    log = db.query(InferenceLog).filter_by(request_id=UUID(request["request_id"])).one()
    assert log.model_version_id == registered.id
    assert log.model_version_used == "test-isolation-forest"


def test_cached_runtime_refreshes_registry_id_for_same_path(db, artifact, monkeypatch):
    monkeypatch.setenv("ML_MODEL_PATH", str(artifact))
    ml.reset_runtime()
    runtime = ml.get_ml_runtime(db)
    assert runtime.model_version_id is None

    registered = ModelVersion(
        name="test", version="registry-entry", model_path=str(artifact),
        status="active", is_production=True, config={},
    )
    db.add(registered)
    db.commit()

    assert ml.get_ml_runtime(db) is runtime
    assert runtime.model_version_id == registered.id

    registered.status = "archived"
    db.commit()
    assert ml.get_ml_runtime(db) is runtime
    assert runtime.model_version_id is None


def test_missing_or_corrupt_artifact_fails_safely(db, tmp_path, monkeypatch):
    for path in (tmp_path / "missing.joblib", tmp_path / "corrupt.joblib"):
        if path.name == "corrupt.joblib":
            path.write_text("not a joblib artifact", encoding="utf-8")
        monkeypatch.setenv("ML_MODEL_PATH", str(path))
        ml.reset_runtime()
        assert complete_without_event_loop(ml.ml_health(db))["model_status"] == "error"
        request = payload()
        with pytest.raises(ml.HTTPException) as exc:
            score_without_event_loop(db, request)
        assert exc.value.status_code == 503
        log = db.query(InferenceLog).filter_by(request_id=UUID(request["request_id"])).one()
        assert log.model_status == "error"
        assert log.error_message


def test_normalization_preserves_score_order(artifact):
    runtime = ml.IsolationForestRuntime.load(artifact)
    normalized = runtime.normalize(np.array([-0.5, 0.0, 0.5]))
    assert np.all((0 <= normalized) & (normalized <= 1))
    assert np.all(np.diff(normalized) >= 0)


def test_feature_contract_publishes_exactly_six_features(client):
    body = client.get("/api/v1/internal/ml/features").json()
    assert body["features"] == list(ml.FEATURE_FIELDS)
    assert len(body["features"]) == 6


def test_health_and_reason_codes_use_canonical_values(client):
    health = client.get("/api/v1/internal/ml/health").json()
    assert health == {
        "status": "ok",
        "model_version": "test-isolation-forest",
        "model_status": "ready",
    }
    risky = {
        **FEATURES,
        "hour_of_day": 2,
        "fail_count_24h": 5,
        "ip_change_rate_7d": 0.75,
        "deviation_score": 0.8,
    }
    reasons = client.post(
        "/api/v1/internal/ml/score", json=payload(risky), headers=SECRET_HEADER,
    ).json()["reason_codes"]
    assert reasons == [
        "unusual_hour", "high_fail_count", "new_ip", "new_device",
        "behavioral_deviation", "multiple_factors",
    ]


def test_feature_statistics_are_batched_off_inference_path(client, db):
    assert client.post(
        "/api/v1/internal/ml/score", json=payload(), headers=SECRET_HEADER,
    ).status_code == 200
    assert ml.refresh_feature_statistics(db, datetime(2000, 1, 1, tzinfo=timezone.utc)) == 6
    statistics = db.query(FeatureStatistic).all()
    assert {item.feature_name for item in statistics} == set(ml.FEATURE_FIELDS)
    assert all(item.count == 1 for item in statistics)


def test_internal_secret_misconfiguration_stays_fail_closed(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_SECRET", "changeme-in-production")
    response = client.post("/api/v1/internal/ml/score", json=payload(), headers={
        "X-Internal-Secret": "changeme-in-production",
    })
    assert response.status_code == 503
