"""Private, versioned ML inference API; it deliberately owns no authentication data."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings
from app.model_registry import (
    FeatureSchemaMismatch,
    ModelRegistry,
    ModelUnavailable,
    feature_vector_digest,
)
from app.schemas import FEATURE_SCHEMA_VERSION, Problem, ScoreRequest, ScoreResponse

LOGGER = logging.getLogger(__name__)


def problem_response(*, status_code: int, title: str, detail: str, type_name: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content=Problem(
            type=f"urn:sentinel-auth:ml:{type_name}",
            title=title,
            status=status_code,
            detail=detail,
        ).model_dump(),
    )


def create_app(*, settings: Settings | None = None, registry: ModelRegistry | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    registry = registry or ModelRegistry(settings.model_dir)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.registry.reload()
        yield

    app = FastAPI(
        title="Sentinel Auth ML",
        version="1.0.0",
        description="Private versioned anomaly inference. It never reads core-app or detection-engine data stores.",
        lifespan=lifespan,
    )
    app.state.registry = registry

    @app.exception_handler(RequestValidationError)
    async def validation_problem(_: Request, error: RequestValidationError) -> JSONResponse:
        return problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid inference request",
            detail=str(error.errors()),
            type_name="invalid-request",
        )

    def require_ml_score_scope(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        """Compose adapter; production ingress replaces this with mTLS/JWT scope validation."""

        expected = f"Bearer {settings.internal_dev_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid workload identity with ml.score scope is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, object]:
        loaded, _ = app.state.registry.status()
        return {
            "status": "ok" if loaded else "degraded",
            "service": "ml-service",
            "model_loaded": loaded,
        }

    @app.get("/ready", tags=["operations"], response_model=None)
    def ready() -> dict[str, object] | JSONResponse:
        loaded, error = app.state.registry.status()
        if not loaded:
            return problem_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                title="Model unavailable",
                detail=error or "No verified ACTIVE model is loaded",
                type_name="model-unavailable",
            )
        return {"status": "ok", "service": "ml-service", "model_loaded": True}

    @app.post(
        "/internal/v1/ml/score",
        response_model=ScoreResponse,
        responses={
            401: {"model": Problem},
            422: {"model": Problem},
            503: {"model": Problem},
        },
        tags=["ml"],
    )
    def score(
        payload: ScoreRequest,
        correlation_id: Annotated[UUID, Header(alias="X-Correlation-ID")],
        _: None = Depends(require_ml_score_scope),
    ) -> ScoreResponse | JSONResponse:
        inference_id = uuid4()
        try:
            result = app.state.registry.score(
                feature_schema_version=payload.feature_schema_version,
                features=payload.features,
            )
        except FeatureSchemaMismatch as error:
            return problem_response(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Unsupported feature schema",
                detail=str(error),
                type_name="feature-schema-mismatch",
            )
        except ModelUnavailable as error:
            return problem_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                title="Model unavailable",
                detail=str(error),
                type_name="model-unavailable",
            )

        LOGGER.info(
            "ml_inference_scored",
            extra={
                "inference_id": str(inference_id),
                "correlation_id": str(correlation_id),
                "login_attempt_id": str(payload.login_attempt_id),
                "model_version": result.model_version,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "input_digest": feature_vector_digest(
                    feature_schema_version=payload.feature_schema_version,
                    features=payload.features,
                ),
                "anomaly_score": result.anomaly_score,
            },
        )
        return ScoreResponse(
            inference_id=inference_id,
            login_attempt_id=payload.login_attempt_id,
            status="SCORED",
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            anomaly_score=result.anomaly_score,
            is_anomaly=result.is_anomaly,
            model_version=result.model_version,
            model_artifact_digest=result.artifact_digest,
            reason_codes=result.reason_codes,
        )

    return app


app = create_app()
