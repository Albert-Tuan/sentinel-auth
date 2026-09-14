from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth_router import router as auth_router
from app.api.auth_router import problem_response
from app.core.settings import Settings
from app.services.authentication import AuthenticationRequiredError
from app.services.mailer import MfaMailer
from app.services.rate_limit import AuthenticationRateLimiter


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    mailer: MfaMailer | None = None,
    rate_limiter: AuthenticationRateLimiter | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Sentinel Auth Core",
        version="0.1.0",
        description="Core authentication endpoints defined in docs/api-contract.yml.",
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.mailer = mailer
    app.state.rate_limiter = rate_limiter

    @app.exception_handler(RequestValidationError)
    async def request_validation_problem(_: Request, __: RequestValidationError) -> JSONResponse:
        return problem_response(422, "Request validation failed")

    @app.exception_handler(AuthenticationRequiredError)
    async def authentication_problem(_: Request, __: AuthenticationRequiredError) -> JSONResponse:
        return problem_response(401, "Authentication required")

    app.include_router(auth_router)

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "core-app"}

    return app


app = create_app()
