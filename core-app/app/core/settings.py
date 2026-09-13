"""Environment-backed settings for the core-app foundation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


class SettingsError(ValueError):
    """A required runtime setting is absent or unsafe for the selected environment."""


@dataclass(frozen=True)
class Settings:
    app_env: str
    service_name: str
    database_url: str
    redis_url: str
    jwt_secret: str
    jwt_algorithm: str
    jwt_issuer: str
    jwt_audience: str
    access_token_ttl_minutes: int
    refresh_token_ttl_days: int
    smtp_host: str
    smtp_port: int
    smtp_from: str
    initial_security_admin_username: str | None
    initial_security_admin_email: str | None
    initial_security_admin_password: str | None
    pre_auth_ttl_seconds: int = 300
    mfa_otp_ttl_seconds: int = 60
    mfa_max_attempts: int = 3
    auth_rate_limit_requests: int = 5
    auth_rate_limit_window_seconds: int = 60
    smtp_timeout_seconds: int = 5
    auth_policy_version: str = "core-auth-v1"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            service_name=os.getenv("SERVICE_NAME", "core-app"),
            database_url=os.getenv("DATABASE_URL", ""),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            jwt_secret=os.getenv("JWT_SECRET", ""),
            jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
            jwt_issuer=os.getenv("JWT_ISSUER", "sentinel-auth-core"),
            jwt_audience=os.getenv("JWT_AUDIENCE", "sentinel-auth-browser"),
            access_token_ttl_minutes=_positive_int("ACCESS_TOKEN_TTL_MINUTES", 15),
            refresh_token_ttl_days=_positive_int("REFRESH_TOKEN_TTL_DAYS", 7),
            smtp_host=os.getenv("SMTP_HOST", "mailpit"),
            smtp_port=_positive_int("SMTP_PORT", 1025),
            smtp_from=os.getenv("SMTP_FROM", "no-reply@sentinel-auth.local"),
            initial_security_admin_username=_optional_env("INITIAL_SECURITY_ADMIN_USERNAME"),
            initial_security_admin_email=_optional_env("INITIAL_SECURITY_ADMIN_EMAIL"),
            initial_security_admin_password=_optional_env("INITIAL_SECURITY_ADMIN_PASSWORD"),
            pre_auth_ttl_seconds=_positive_int("PRE_AUTH_TTL_SECONDS", 300),
            mfa_otp_ttl_seconds=_positive_int("MFA_OTP_TTL_SECONDS", 60),
            mfa_max_attempts=_positive_int("MFA_MAX_ATTEMPTS", 3),
            auth_rate_limit_requests=_positive_int("AUTH_RATE_LIMIT_REQUESTS", 5),
            auth_rate_limit_window_seconds=_positive_int("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60),
            smtp_timeout_seconds=_positive_int("SMTP_TIMEOUT_SECONDS", 5),
            auth_policy_version=os.getenv("AUTH_POLICY_VERSION", "core-auth-v1"),
        )

    def validate_runtime_security(self) -> None:
        if not self.database_url:
            raise SettingsError("DATABASE_URL must be set")
        if not self.jwt_secret:
            raise SettingsError("JWT_SECRET must be set")
        if self.app_env != "development" and self.jwt_secret.startswith("local-"):
            raise SettingsError("A local JWT_SECRET is prohibited outside development")
        if self.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
            raise SettingsError("JWT_ALGORITHM must be an approved HMAC algorithm")
        if self.pre_auth_ttl_seconds > 300:
            raise SettingsError("PRE_AUTH_TTL_SECONDS must not exceed 300")
        if self.mfa_otp_ttl_seconds != 60:
            raise SettingsError("MFA_OTP_TTL_SECONDS must be 60 in v1")
        if self.mfa_max_attempts != 3:
            raise SettingsError("MFA_MAX_ATTEMPTS must be 3 in v1")

    def bootstrap_credentials(self) -> tuple[str, str, str]:
        values = (
            self.initial_security_admin_username,
            self.initial_security_admin_email,
            self.initial_security_admin_password,
        )
        if not all(values):
            raise SettingsError(
                "INITIAL_SECURITY_ADMIN_USERNAME, INITIAL_SECURITY_ADMIN_EMAIL and "
                "INITIAL_SECURITY_ADMIN_PASSWORD must be set when bootstrapping an empty database"
            )
        return values[0], values[1], values[2]


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    return value if value else None


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value <= 0:
        raise SettingsError(f"{name} must be positive")
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
