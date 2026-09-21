"""Pydantic request/response models matching docs/api-contract.yml."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    username: str | None = Field(default=None, min_length=1, max_length=254)
    email: str | None = Field(default=None, max_length=254)
    password: str = Field(min_length=1)
    device_fingerprint: str | None = Field(default=None, max_length=512)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and (value.count("@") != 1 or value.startswith("@") or value.endswith("@")):
            raise ValueError("Invalid email")
        return value

    @model_validator(mode="after")
    def exactly_one_identifier(self) -> "LoginRequest":
        if (self.username is None) == (self.email is None):
            raise ValueError("Exactly one of username or email is required")
        return self


class RegisterRequest(StrictModel):
    username: str = Field(min_length=1, max_length=254)
    email: str = Field(max_length=254)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if value.count("@") != 1 or value.startswith("@") or value.endswith("@"):
            raise ValueError("Invalid email")
        return value


class MfaVerification(StrictModel):
    pre_auth_token: str = Field(min_length=1)
    challenge_response: str = Field(pattern=r"^[0-9]{4}$")


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=1)


class SessionIssued(StrictModel):
    decision: Literal["ALLOW"] = "ALLOW"
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


class MfaRequired(StrictModel):
    decision: Literal["MFA_REQUIRED"] = "MFA_REQUIRED"
    pre_auth_token: str
    expires_in: int
    otp_expires_in: Literal[60] = 60


class Denied(StrictModel):
    decision: Literal["DENY"] = "DENY"
    message: Literal["Authentication could not be completed."] = "Authentication could not be completed."


class UserProfile(StrictModel):
    id: UUID
    username: str
    email: str
    status: Literal["ACTIVE", "LOCKED"]
    roles: list[Literal["USER", "SECURITY_ADMIN", "SOC_ANALYST", "SECURITY_MANAGER"]]
    admin_mfa_required: bool


class SessionSummary(StrictModel):
    id: UUID
    source_ip: str
    device_id: str | None
    user_agent: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class SessionList(StrictModel):
    items: list[SessionSummary]


class Problem(StrictModel):
    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
