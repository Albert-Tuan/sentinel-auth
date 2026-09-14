from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model_registry import InferenceResult, ModelUnavailable


class UnavailableRegistry:
    def reload(self) -> bool:
        return False

    def status(self) -> tuple[bool, str | None]:
        return False, "No verified ACTIVE model is loaded"

    def score(self, **_: object) -> InferenceResult:
        raise ModelUnavailable("No verified ACTIVE model is loaded")


def test_health_is_degraded_and_readiness_is_unavailable_without_model() -> None:
    app = create_app(
        settings=Settings(Path("models"), "test-workload-token", "test"),
        registry=UnavailableRegistry(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        health = client.get("/health")
        readiness = client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {
        "status": "degraded",
        "service": "ml-service",
        "model_loaded": False,
    }
    assert readiness.status_code == 503
    assert readiness.headers["content-type"].startswith("application/problem+json")
