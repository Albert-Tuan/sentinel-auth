from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model_registry import InferenceResult


LOGIN_ATTEMPT_ID = "6a9f8de8-9e0b-48d2-9e1d-b735a2287011"
CORRELATION_ID = "96cb09f9-14fe-4ec9-8a90-b381d5734933"


class ReadyRegistry:
    def __init__(self) -> None:
        self.requests: list[tuple[int, list[float]]] = []

    def reload(self) -> bool:
        return True

    def status(self) -> tuple[bool, str | None]:
        return True, None

    def score(self, *, feature_schema_version: int, features: object) -> InferenceResult:
        self.requests.append((feature_schema_version, features.as_vector()))  # type: ignore[attr-defined]
        return InferenceResult(
            anomaly_score=0.91,
            is_anomaly=True,
            model_version="iforest-2026-09-07",
            artifact_digest="a" * 64,
            reason_codes=["NEW_DEVICE", "HIGH_RECENT_FAILURE_COUNT"],
        )


def client_for(registry: ReadyRegistry) -> TestClient:
    app = create_app(
        settings=Settings(Path("models"), "test-workload-token", "test"),
        registry=registry,  # type: ignore[arg-type]
    )
    return TestClient(app)


def score_payload() -> dict[str, object]:
    return {
        "login_attempt_id": LOGIN_ATTEMPT_ID,
        "feature_schema_version": 1,
        "features": {
            "hour_of_day": 2,
            "fail_count_24h": 7,
            "ip_change_rate_7d": 0.7,
            "new_device": True,
            "average_login_interval_seconds": 300.0,
            "deviation_score": 0.9,
        },
    }


def headers(*, token: str = "test-workload-token") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Correlation-ID": CORRELATION_ID,
    }


def test_score_returns_versioned_metadata_and_stable_feature_order() -> None:
    registry = ReadyRegistry()
    with client_for(registry) as client:
        response = client.post("/internal/v1/ml/score", json=score_payload(), headers=headers())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SCORED"
    assert body["login_attempt_id"] == LOGIN_ATTEMPT_ID
    assert UUID(body["inference_id"])
    assert body["model_version"] == "iforest-2026-09-07"
    assert body["anomaly_score"] == 0.91
    assert registry.requests == [(1, [2.0, 7.0, 0.7, 1.0, 300.0, 0.9])]


def test_score_requires_workload_identity() -> None:
    with client_for(ReadyRegistry()) as client:
        response = client.post("/internal/v1/ml/score", json=score_payload(), headers=headers(token="wrong"))

    assert response.status_code == 401


def test_score_rejects_unknown_feature_and_missing_correlation_id() -> None:
    payload = score_payload()
    payload["features"]["raw_ip_address"] = "203.0.113.8"  # type: ignore[index]
    with client_for(ReadyRegistry()) as client:
        response = client.post("/internal/v1/ml/score", json=payload, headers={"Authorization": "Bearer test-workload-token"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
