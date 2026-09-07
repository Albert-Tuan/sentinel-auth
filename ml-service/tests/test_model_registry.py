import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.model_registry import (
    ActiveModel,
    Calibration,
    FeatureSchemaMismatch,
    ModelRegistry,
    FEATURE_NAMES,
    feature_vector_digest,
    reason_codes,
    sha256_file,
)
from app.schemas import LoginFeatures


class FakeIsolationForest:
    def score_samples(self, rows: list[list[float]]) -> list[float]:
        assert rows == [[2.0, 7.0, 0.7, 1.0, 300.0, 0.9]]
        return [-0.8]


def risky_features() -> LoginFeatures:
    return LoginFeatures(
        hour_of_day=2,
        fail_count_24h=7,
        ip_change_rate_7d=0.7,
        new_device=True,
        average_login_interval_seconds=300,
        deviation_score=0.9,
    )


def test_registry_uses_persisted_calibration_and_heuristic_evidence() -> None:
    registry = ModelRegistry(Path("unused"))
    registry._active = ActiveModel(  # noqa: SLF001 - inject a verified fake artifact at the unit boundary.
        version="test-model",
        feature_schema_version=1,
        artifact_digest="b" * 64,
        calibration=Calibration(lower_bound=0.2, upper_bound=1.0, anomaly_threshold=0.7),
        estimator=FakeIsolationForest(),
    )

    result = registry.score(feature_schema_version=1, features=risky_features())

    assert result.anomaly_score == pytest.approx(0.75)
    assert result.is_anomaly is True
    assert result.reason_codes == [
        "NEW_DEVICE",
        "HIGH_RECENT_FAILURE_COUNT",
        "HIGH_IP_CHANGE_RATE",
        "UNUSUAL_LOGIN_HOUR",
        "HIGH_BEHAVIOURAL_DEVIATION",
    ]


def test_registry_rejects_feature_schema_drift() -> None:
    registry = ModelRegistry(Path("unused"))
    registry._active = ActiveModel(  # noqa: SLF001
        version="test-model",
        feature_schema_version=1,
        artifact_digest="b" * 64,
        calibration=Calibration(lower_bound=0.2, upper_bound=1.0, anomaly_threshold=0.7),
        estimator=FakeIsolationForest(),
    )

    with pytest.raises(FeatureSchemaMismatch):
        registry.score(feature_schema_version=2, features=risky_features())


def test_calibration_rejects_invalid_bounds() -> None:
    with pytest.raises(Exception, match="upper_bound"):
        Calibration.from_manifest(
            {
                "method": "PERCENTILE_LINEAR_V1",
                "lower_bound": 0.5,
                "upper_bound": 0.5,
                "anomaly_threshold": 0.8,
            }
        )


def test_registry_loads_only_an_approved_checksum_verified_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = tmp_path / "reviewed-model.joblib"
    artifact.write_bytes(b"reviewed immutable artifact")
    (tmp_path / "active-model.json").write_text(
        json.dumps(
            {
                "version": "reviewed-v1",
                "status": "ACTIVE",
                "feature_schema_version": 1,
                "feature_names": list(FEATURE_NAMES),
                "artifact": {"file": artifact.name, "sha256": sha256_file(artifact)},
                "calibration": {
                    "method": "PERCENTILE_LINEAR_V1",
                    "lower_bound": 0.2,
                    "upper_bound": 1.0,
                    "anomaly_threshold": 0.7,
                },
                "promotion": {"decision": "APPROVED", "approved_at": "2026-09-07T00:00:00Z"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "joblib", SimpleNamespace(load=lambda _: FakeIsolationForest()))

    registry = ModelRegistry(tmp_path)
    assert registry.reload() is True
    assert registry.score(feature_schema_version=1, features=risky_features()).model_version == "reviewed-v1"

    artifact.write_bytes(b"tampered")
    assert registry.reload() is False
    assert registry.status()[1] == "Model artifact SHA-256 verification failed"


def test_reason_codes_do_not_claim_model_causality() -> None:
    assert reason_codes(
        LoginFeatures(
            hour_of_day=12,
            fail_count_24h=0,
            ip_change_rate_7d=0,
            new_device=False,
            average_login_interval_seconds=3600,
            deviation_score=0.1,
        )
    ) == ["NO_HEURISTIC_TRIGGER"]


def test_feature_vector_digest_is_deterministic_and_does_not_expose_values() -> None:
    digest = feature_vector_digest(feature_schema_version=1, features=risky_features())
    assert digest == feature_vector_digest(feature_schema_version=1, features=risky_features())
    assert len(digest) == 64
    assert digest != feature_vector_digest(
        feature_schema_version=1,
        features=risky_features().model_copy(update={"deviation_score": 0.8}),
    )
