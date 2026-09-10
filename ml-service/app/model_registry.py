"""Verified, immutable model loading and deterministic inference helpers."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from app.schemas import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, LoginFeatures

LOGGER = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """No verified active model can be used for inference."""


class FeatureSchemaMismatch(ValueError):
    """The active model and request do not have the same feature contract."""


@dataclass(frozen=True)
class Calibration:
    """Persisted percentile-derived mapping from raw Isolation Forest score to 0..1."""

    lower_bound: float
    upper_bound: float
    anomaly_threshold: float

    @classmethod
    def from_manifest(cls, value: Mapping[str, Any]) -> "Calibration":
        if value.get("method") != "PERCENTILE_LINEAR_V1":
            raise ModelUnavailable("Unsupported or missing calibration method")
        calibration = cls(
            lower_bound=float(value["lower_bound"]),
            upper_bound=float(value["upper_bound"]),
            anomaly_threshold=float(value["anomaly_threshold"]),
        )
        if not 0 <= calibration.anomaly_threshold <= 1:
            raise ModelUnavailable("Calibration anomaly_threshold must be in [0, 1]")
        if calibration.upper_bound <= calibration.lower_bound:
            raise ModelUnavailable("Calibration upper_bound must exceed lower_bound")
        return calibration

    def normalize(self, raw_score: float) -> float:
        score = (raw_score - self.lower_bound) / (self.upper_bound - self.lower_bound)
        return max(0.0, min(1.0, score))


@dataclass(frozen=True)
class ActiveModel:
    version: str
    feature_schema_version: int
    artifact_digest: str
    calibration: Calibration
    estimator: Any


@dataclass(frozen=True)
class InferenceResult:
    anomaly_score: float
    is_anomaly: bool
    model_version: str
    artifact_digest: str
    reason_codes: list[str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_vector_digest(*, feature_schema_version: int, features: LoginFeatures) -> str:
    """Correlate inference safely without retaining the underlying feature values."""

    canonical = json.dumps(
        {
            "feature_schema_version": feature_schema_version,
            "feature_names": list(FEATURE_NAMES),
            "feature_values": features.as_vector(),
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ModelRegistry:
    """Loads only a reviewed ``ACTIVE`` manifest from an ML-owned directory.

    The directory represents the local implementation of the model registry.
    A production artifact store may provide the same immutable manifest and
    digest contract; inference must never fetch a mutable ``latest`` artifact.
    """

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._lock = RLock()
        self._active: ActiveModel | None = None
        self._last_error: str | None = "Active model has not been loaded"

    def reload(self) -> bool:
        try:
            candidate = self._load_active()
        except (OSError, ValueError, KeyError, ModelUnavailable) as error:
            with self._lock:
                self._active = None
                self._last_error = str(error)
            LOGGER.warning("ml_model_unavailable", extra={"reason": str(error)})
            return False

        with self._lock:
            self._active = candidate
            self._last_error = None
        LOGGER.info(
            "ml_model_loaded",
            extra={"model_version": candidate.version, "artifact_digest": candidate.artifact_digest},
        )
        return True

    def status(self) -> tuple[bool, str | None]:
        with self._lock:
            return self._active is not None, self._last_error

    def score(self, *, feature_schema_version: int, features: LoginFeatures) -> InferenceResult:
        with self._lock:
            active = self._active
        if active is None:
            raise ModelUnavailable("No verified ACTIVE model is loaded")
        if feature_schema_version != active.feature_schema_version:
            raise FeatureSchemaMismatch(
                f"Request schema v{feature_schema_version} is incompatible with active "
                f"model schema v{active.feature_schema_version}"
            )

        # IsolationForest.score_samples: a lower value is more anomalous.
        try:
            raw_score = -float(active.estimator.score_samples([features.as_vector()])[0])
        except (AttributeError, TypeError, ValueError) as error:
            raise ModelUnavailable("Active model failed to score the feature vector") from error

        anomaly_score = active.calibration.normalize(raw_score)
        return InferenceResult(
            anomaly_score=anomaly_score,
            is_anomaly=anomaly_score >= active.calibration.anomaly_threshold,
            model_version=active.version,
            artifact_digest=active.artifact_digest,
            reason_codes=reason_codes(features),
        )

    def _load_active(self) -> ActiveModel:
        manifest_path = self._model_dir / "active-model.json"
        if not manifest_path.is_file():
            raise ModelUnavailable(f"Active model manifest is missing: {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "ACTIVE":
            raise ModelUnavailable("Model manifest is not ACTIVE")
        promotion = manifest.get("promotion", {})
        if promotion.get("decision") != "APPROVED" or not promotion.get("approved_at"):
            raise ModelUnavailable("ACTIVE model is missing approved promotion evidence")
        if manifest.get("feature_names") != list(FEATURE_NAMES):
            raise ModelUnavailable("Artifact feature order does not match feature schema v1")
        if int(manifest.get("feature_schema_version", -1)) != FEATURE_SCHEMA_VERSION:
            raise ModelUnavailable("Unsupported feature schema version in model manifest")

        artifact = manifest.get("artifact", {})
        artifact_name = artifact.get("file")
        expected_digest = artifact.get("sha256")
        if not isinstance(artifact_name, str) or not isinstance(expected_digest, str):
            raise ModelUnavailable("Model artifact metadata is incomplete")
        artifact_path = (self._model_dir / artifact_name).resolve()
        model_dir = self._model_dir.resolve()
        if artifact_path.parent != model_dir or not artifact_path.is_file():
            raise ModelUnavailable("Artifact is outside the model registry or does not exist")
        if sha256_file(artifact_path) != expected_digest:
            raise ModelUnavailable("Model artifact SHA-256 verification failed")

        try:
            import joblib
        except ImportError as error:  # Allows static checks where optional ML deps are absent.
            raise ModelUnavailable("ML runtime dependency joblib is not installed") from error
        try:
            estimator = joblib.load(artifact_path)
        except Exception as error:  # Corrupt or incompatible serialized artifacts are unavailable, never trusted.
            raise ModelUnavailable("Model artifact could not be deserialized safely") from error
        if not callable(getattr(estimator, "score_samples", None)):
            raise ModelUnavailable("Artifact does not expose score_samples")

        return ActiveModel(
            version=str(manifest["version"]),
            feature_schema_version=int(manifest["feature_schema_version"]),
            artifact_digest=expected_digest,
            calibration=Calibration.from_manifest(manifest["calibration"]),
            estimator=estimator,
        )


def reason_codes(features: LoginFeatures) -> list[str]:
    """Heuristic evidence, explicitly not a causal explanation of the model."""

    codes: list[str] = []
    if features.new_device:
        codes.append("NEW_DEVICE")
    if features.fail_count_24h >= 5:
        codes.append("HIGH_RECENT_FAILURE_COUNT")
    if features.ip_change_rate_7d >= 0.5:
        codes.append("HIGH_IP_CHANGE_RATE")
    if features.hour_of_day <= 4:
        codes.append("UNUSUAL_LOGIN_HOUR")
    if features.deviation_score >= 0.7:
        codes.append("HIGH_BEHAVIOURAL_DEVIATION")
    return codes or ["NO_HEURISTIC_TRIGGER"]
