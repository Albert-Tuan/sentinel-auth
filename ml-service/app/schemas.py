"""The executable form of the versioned inference contract."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


FEATURE_SCHEMA_VERSION = 1
FEATURE_NAMES = (
    "hour_of_day",
    "fail_count_24h",
    "ip_change_rate_7d",
    "new_device",
    "average_login_interval_seconds",
    "deviation_score",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginFeatures(StrictModel):
    """Feature schema v1 owned by detection-engine and consumed by ML."""

    hour_of_day: Annotated[int, Field(ge=0, le=23)]
    fail_count_24h: Annotated[int, Field(ge=0)]
    ip_change_rate_7d: Annotated[float, Field(ge=0, le=1)]
    new_device: bool
    average_login_interval_seconds: Annotated[float, Field(ge=0)]
    deviation_score: Annotated[float, Field(ge=0, le=1)]

    def as_vector(self) -> list[float]:
        """Return the artifact's stable feature order; never rely on dict order."""

        return [
            float(self.hour_of_day),
            float(self.fail_count_24h),
            float(self.ip_change_rate_7d),
            float(self.new_device),
            float(self.average_login_interval_seconds),
            float(self.deviation_score),
        ]


class ScoreRequest(StrictModel):
    login_attempt_id: UUID
    feature_schema_version: Literal[FEATURE_SCHEMA_VERSION]
    features: LoginFeatures


class ScoreResponse(StrictModel):
    """A nullable score is intentional when the dependency is degraded."""

    inference_id: UUID
    login_attempt_id: UUID
    status: Literal["SCORED", "DEGRADED"]
    feature_schema_version: int
    anomaly_score: float | None
    is_anomaly: bool | None
    model_version: str | None
    model_artifact_digest: str | None
    reason_codes: list[str]


class Problem(StrictModel):
    type: str
    title: str
    status: int
    detail: str | None = None
