"""Contract-level authentication tests, portable to SQLite and isolated PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.passwords import hash_password
from app.core.settings import Settings
from app.core.tokens import decode_jwt, issue_jwt, token_verifier
from app.main import create_app
from app.models import (
    IpRateLimit,
    LoginAttempt,
    LoginOutcome,
    MfaChallenge,
    MfaChallengeStatus,
    OutboxEvent,
    PreAuthStatus,
    PreAuthTransaction,
    Role,
    RoleCode,
    Session as AuthSession,
    User,
    UserRole,
    UserStatus,
)
from app.models.base import utc_now
from app.services.authentication import AuthenticationService, MfaVerificationError, SessionIssuedResult
from app.services.rate_limit import RedisAuthenticationRateLimiter


class TestRateLimiter:
    __test__ = False

    def __init__(self) -> None:
        self.allowed = True
        self.limit: int | None = None
        self.scope_limits: dict[str, int] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.ip_counts: dict[tuple[str, str], int] = {}
        self.account_counts: dict[tuple[str, str], int] = {}

    def allow(self, *, scope: str, source_ip: str, account_identifier: str) -> bool:
        self.calls.append((scope, source_ip, account_identifier))
        if not self.allowed:
            return False
        limit = self.scope_limits.get(scope, self.limit)
        if limit is None:
            return True
        ip_key = (scope, source_ip)
        account_key = (scope, account_identifier)
        self.ip_counts[ip_key] = self.ip_counts.get(ip_key, 0) + 1
        self.account_counts[account_key] = self.account_counts.get(account_key, 0) + 1
        return self.ip_counts[ip_key] <= limit and self.account_counts[account_key] <= limit


@dataclass
class TestMailer:
    __test__ = False

    deliveries: list[tuple[str, str]] = field(default_factory=list)
    fail: bool = False

    def send_email_otp(self, *, recipient: str, code: str) -> None:
        self.deliveries.append((recipient, code))
        if self.fail:
            raise RuntimeError("SMTP unavailable")


@dataclass
class AuthHarness:
    client: TestClient
    app: FastAPI
    factory: sessionmaker[Session]
    settings: Settings
    mailer: TestMailer
    limiter: TestRateLimiter


def _settings() -> Settings:
    return Settings(
        app_env="development",
        service_name="core-app",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_secret="local-test-jwt-secret-that-is-not-production",
        jwt_algorithm="HS256",
        jwt_issuer="sentinel-auth-core",
        jwt_audience="sentinel-auth-browser",
        access_token_ttl_minutes=15,
        refresh_token_ttl_days=7,
        smtp_host="mailpit",
        smtp_port=1025,
        smtp_from="no-reply@sentinel-auth.local",
        initial_security_admin_username=None,
        initial_security_admin_email=None,
        initial_security_admin_password=None,
    )


@pytest.fixture
def auth_harness(database_engine) -> AuthHarness:
    factory = sessionmaker(bind=database_engine, autoflush=False, expire_on_commit=False)
    with factory() as session, session.begin():
        session.add_all([Role(code=role_code) for role_code in RoleCode])
    settings = _settings()
    mailer = TestMailer()
    limiter = TestRateLimiter()
    app = create_app(settings=settings, session_factory=factory, mailer=mailer, rate_limiter=limiter)
    return AuthHarness(TestClient(app), app, factory, settings, mailer, limiter)


def _headers() -> dict[str, str]:
    return {"X-Correlation-ID": str(uuid4())}


def _create_user(
    harness: AuthHarness,
    *,
    username: str,
    password: str = "correct-password",
    roles: tuple[RoleCode, ...] = (RoleCode.USER,),
    status: UserStatus = UserStatus.ACTIVE,
    admin_mfa_required: bool = False,
    detection_mfa_once: bool = False,
) -> User:
    with harness.factory() as session, session.begin():
        role_ids = {role.code: role.id for role in session.scalars(select(Role))}
        user = User(
            username=username,
            email=f"{username}@example.test",
            password_hash=hash_password(password),
            status=status,
            admin_mfa_required=admin_mfa_required,
            detection_mfa_once=detection_mfa_once,
        )
        session.add(user)
        session.flush()
        session.add_all([UserRole(user_id=user.id, role_id=role_ids[role_code]) for role_code in roles])
        user_id = user.id
    with harness.factory() as session:
        return session.get(User, user_id)


def _login(harness: AuthHarness, username: str, password: str = "correct-password"):
    return harness.client.post(
        "/api/v1/auth/login",
        headers=_headers(),
        json={"username": username, "password": password},
    )


def _wrong_otp(code: str) -> str:
    return "0000" if code != "0000" else "0001"


def _counts(harness: AuthHarness) -> tuple[int, int, int]:
    with harness.factory() as session:
        return (
            session.scalar(select(func.count()).select_from(LoginAttempt)) or 0,
            session.scalar(select(func.count()).select_from(OutboxEvent)) or 0,
            session.scalar(select(func.count()).select_from(AuthSession)) or 0,
        )


def test_register_hashes_password_and_assigns_user_role(auth_harness: AuthHarness) -> None:
    password = "not-persisted-in-plaintext"
    response = auth_harness.client.post(
        "/api/v1/auth/register",
        headers=_headers(),
        json={"username": "registered", "email": "registered@example.test", "password": password},
    )

    assert response.status_code == 201
    assert response.json()["roles"] == ["USER"]
    assert "password_hash" not in response.json()
    with auth_harness.factory() as session:
        user = session.scalar(select(User).where(User.username == "registered"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != password
        assert password not in user.password_hash


def test_login_success_creates_session_attempt_and_immutable_outbox(auth_harness: AuthHarness) -> None:
    _create_user(auth_harness, username="login-user", roles=(RoleCode.USER, RoleCode.SOC_ANALYST))

    response = _login(auth_harness, "login-user")

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    attempts, events, sessions = _counts(auth_harness)
    assert (attempts, events, sessions) == (1, 1, 1)
    with auth_harness.factory() as session:
        attempt = session.scalar(select(LoginAttempt))
        event = session.scalar(select(OutboxEvent))
        persisted_session = session.scalar(select(AuthSession))
        assert attempt.outcome == LoginOutcome.ALLOW
        assert attempt.mfa_completed is True
        assert event.login_attempt_id == attempt.id
        assert event.event_type == "auth.login-attempt.v1"
        assert event.payload["outcome"] == "ALLOW"
        assert "correct-password" not in str(event.payload)
        assert body["access_token"] not in str(event.payload)
        assert persisted_session.refresh_token_hash == token_verifier(body["refresh_token"])
        assert persisted_session.refresh_token_hash != body["refresh_token"]


def test_login_failures_are_generic_recorded_and_never_create_session(auth_harness: AuthHarness) -> None:
    _create_user(auth_harness, username="known")

    wrong_password = _login(auth_harness, "known", "wrong-password")
    nonexistent = _login(auth_harness, "not-known", "wrong-password")

    assert wrong_password.status_code == nonexistent.status_code == 200
    assert wrong_password.json() == nonexistent.json() == {
        "decision": "DENY",
        "message": "Authentication could not be completed.",
    }
    attempts, events, sessions = _counts(auth_harness)
    assert (attempts, events, sessions) == (2, 2, 0)
    with auth_harness.factory() as session:
        assert {attempt.outcome for attempt in session.scalars(select(LoginAttempt))} == {LoginOutcome.DENY}


@pytest.mark.parametrize("status", [UserStatus.LOCKED, UserStatus.DELETED])
def test_locked_or_deleted_account_is_denied_and_records_no_session(
    auth_harness: AuthHarness,
    status: UserStatus,
) -> None:
    _create_user(auth_harness, username=f"{status.lower()}-user", status=status)

    response = _login(auth_harness, f"{status.lower()}-user")

    assert response.status_code == 200
    assert response.json()["decision"] == "DENY"
    assert _counts(auth_harness) == (1, 1, 0)


def test_access_tokens_authenticate_multi_role_identity_and_reject_invalid_forms(auth_harness: AuthHarness) -> None:
    user = _create_user(
        auth_harness,
        username="multi-role",
        roles=(RoleCode.USER, RoleCode.SECURITY_ADMIN, RoleCode.SOC_ANALYST),
    )
    issued_response = auth_harness.client.post(
        "/api/v1/auth/login",
        headers=_headers(),
        json={"email": "multi-role@example.test", "password": "correct-password"},
    )
    assert issued_response.status_code == 200
    issued = issued_response.json()
    access_token = issued["access_token"]
    claims = decode_jwt(access_token, settings=auth_harness.settings, expected_type="access")
    assert {"sub", "iat", "exp", "roles", "jti", "sid"}.issubset(claims)
    assert set(claims["roles"]) == {"USER", "SECURITY_ADMIN", "SOC_ANALYST"}

    profile = auth_harness.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert profile.status_code == 200
    assert profile.json()["roles"] == ["SECURITY_ADMIN", "SOC_ANALYST", "USER"]

    with auth_harness.factory() as session:
        persisted_session = session.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        expired, _, _ = issue_jwt(
            settings=auth_harness.settings,
            subject=user.id,
            session_id=persisted_session.id,
            roles=["USER"],
            token_type="access",
            expires_in=timedelta(seconds=-1),
            token_version=persisted_session.token_version,
            token_id=UUID(persisted_session.access_jti),
        )
        expired_refresh, _, _ = issue_jwt(
            settings=auth_harness.settings,
            subject=user.id,
            session_id=persisted_session.id,
            roles=["USER"],
            token_type="refresh",
            expires_in=timedelta(seconds=-1),
            token_version=persisted_session.token_version,
        )

    for token in ("malformed", f"{access_token}x", expired, issued["refresh_token"]):
        response = auth_harness.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/problem+json")
    assert auth_harness.client.post(
        "/api/v1/auth/refresh", headers=_headers(), json={"refresh_token": expired_refresh}
    ).status_code == 401


def test_refresh_rotates_tokens_and_rejects_replay_or_access_token(auth_harness: AuthHarness) -> None:
    _create_user(auth_harness, username="refresh-user")
    initial = _login(auth_harness, "refresh-user").json()

    rotated = auth_harness.client.post(
        "/api/v1/auth/refresh", headers=_headers(), json={"refresh_token": initial["refresh_token"]}
    )

    assert rotated.status_code == 200
    new_tokens = rotated.json()
    assert new_tokens["refresh_token"] != initial["refresh_token"]
    assert auth_harness.client.post(
        "/api/v1/auth/refresh", headers=_headers(), json={"refresh_token": initial["refresh_token"]}
    ).status_code == 401
    assert auth_harness.client.post(
        "/api/v1/auth/refresh", headers=_headers(), json={"refresh_token": initial["access_token"]}
    ).status_code == 401
    assert auth_harness.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {initial['access_token']}"}
    ).status_code == 401
    assert auth_harness.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {new_tokens['access_token']}"}
    ).status_code == 200


def test_logout_and_owned_session_revoke_invalidate_access_and_refresh(auth_harness: AuthHarness) -> None:
    user = _create_user(auth_harness, username="session-owner")
    another = _create_user(auth_harness, username="other-owner")
    current = _login(auth_harness, "session-owner").json()
    other = _login(auth_harness, "other-owner").json()
    access_headers = {"Authorization": f"Bearer {current['access_token']}", **_headers()}

    listed = auth_harness.client.get("/api/v1/users/me/sessions", headers=access_headers)
    assert listed.status_code == 200
    current_session_id = listed.json()["items"][0]["id"]
    with auth_harness.factory() as session:
        other_session = session.scalar(select(AuthSession).where(AuthSession.user_id == another.id))
    assert auth_harness.client.delete(
        f"/api/v1/sessions/{other_session.id}", headers=access_headers
    ).status_code == 403
    assert auth_harness.client.delete(
        f"/api/v1/sessions/{uuid4()}", headers=access_headers
    ).status_code == 404
    assert auth_harness.client.delete(f"/api/v1/sessions/{current_session_id}", headers=access_headers).status_code == 204
    assert auth_harness.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {current['access_token']}"}
    ).status_code == 401
    assert auth_harness.client.post(
        "/api/v1/auth/refresh", headers=_headers(), json={"refresh_token": current["refresh_token"]}
    ).status_code == 401
    assert auth_harness.client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {other['access_token']}", **_headers()},
    ).status_code == 204


def test_mfa_requires_pre_auth_then_issues_one_session_and_consumes_challenge(auth_harness: AuthHarness) -> None:
    _create_user(auth_harness, username="mfa-user", admin_mfa_required=True)

    required = _login(auth_harness, "mfa-user")

    assert required.status_code == 200
    body = required.json()
    assert body["decision"] == "MFA_REQUIRED"
    assert body["expires_in"] == 300
    assert body["otp_expires_in"] == 60
    assert "access_token" not in body
    assert _counts(auth_harness) == (1, 1, 0)
    assert len(auth_harness.mailer.deliveries) == 1
    assert auth_harness.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {body['pre_auth_token']}"}
    ).status_code == 401
    code = auth_harness.mailer.deliveries[-1][1]
    wrong = "0000" if code != "0000" else "0001"
    wrong_response = auth_harness.client.post(
        "/api/v1/auth/mfa/verify",
        headers=_headers(),
        json={"pre_auth_token": body["pre_auth_token"], "challenge_response": wrong},
    )
    assert wrong_response.status_code == 401
    completed = auth_harness.client.post(
        "/api/v1/auth/mfa/verify",
        headers=_headers(),
        json={"pre_auth_token": body["pre_auth_token"], "challenge_response": code},
    )
    assert completed.status_code == 200
    assert completed.json()["decision"] == "ALLOW"
    assert _counts(auth_harness) == (1, 1, 1)
    assert auth_harness.client.post(
        "/api/v1/auth/mfa/verify",
        headers=_headers(),
        json={"pre_auth_token": body["pre_auth_token"], "challenge_response": code},
    ).status_code == 401
    with auth_harness.factory() as session:
        pre_auth = session.scalar(select(PreAuthTransaction))
        challenge = session.scalar(select(MfaChallenge))
        attempt = session.scalar(select(LoginAttempt))
        assert pre_auth.status == PreAuthStatus.VERIFIED
        assert pre_auth.token_hash == token_verifier(body["pre_auth_token"])
        assert pre_auth.token_hash != body["pre_auth_token"]
        assert challenge.status == MfaChallengeStatus.VERIFIED
        assert challenge.fail_count == 1
        assert code not in challenge.code_hash
        assert attempt.mfa_completed is False


def test_mfa_expiry_max_attempts_mail_failure_and_supersession_are_safe(auth_harness: AuthHarness) -> None:
    user = _create_user(auth_harness, username="mfa-edge", admin_mfa_required=True, detection_mfa_once=True)
    first = _login(auth_harness, "mfa-edge").json()
    first_code = auth_harness.mailer.deliveries[-1][1]
    second = _login(auth_harness, "mfa-edge").json()
    second_code = auth_harness.mailer.deliveries[-1][1]
    assert auth_harness.client.post(
        "/api/v1/auth/mfa/verify",
        headers=_headers(),
        json={"pre_auth_token": first["pre_auth_token"], "challenge_response": first_code},
    ).status_code == 401
    with auth_harness.factory() as session, session.begin():
        challenge = session.scalar(
            select(MfaChallenge).join(PreAuthTransaction).where(PreAuthTransaction.token_hash == token_verifier(second["pre_auth_token"]))
        )
        challenge.expires_at = utc_now() - timedelta(seconds=1)
    assert auth_harness.client.post(
        "/api/v1/auth/mfa/verify",
        headers=_headers(),
        json={"pre_auth_token": second["pre_auth_token"], "challenge_response": second_code},
    ).status_code == 401

    fresh = _login(auth_harness, "mfa-edge").json()
    wrong = "0000" if auth_harness.mailer.deliveries[-1][1] != "0000" else "0001"
    for _ in range(3):
        assert auth_harness.client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": fresh["pre_auth_token"], "challenge_response": wrong},
        ).status_code == 401
    with auth_harness.factory() as session:
        latest_challenge = session.scalar(select(MfaChallenge).order_by(MfaChallenge.created_at.desc()))
        assert latest_challenge.status == MfaChallengeStatus.LOCKED

    auth_harness.mailer.fail = True
    failed_delivery = _login(auth_harness, "mfa-edge")
    assert failed_delivery.status_code == 200
    assert failed_delivery.json()["decision"] == "MFA_REQUIRED"
    attempts, events, sessions = _counts(auth_harness)
    assert attempts == events
    assert sessions == 0
    with auth_harness.factory() as session:
        assert session.get(User, user.id).detection_mfa_once is True


def test_rate_limit_is_pre_decision_and_creates_no_attempt_or_event(auth_harness: AuthHarness) -> None:
    _create_user(auth_harness, username="limited-user")
    auth_harness.limiter.allowed = False

    response = _login(auth_harness, "limited-user")

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert _counts(auth_harness) == (0, 0, 0)


def test_enforced_ip_rate_limit_is_pre_decision_and_creates_no_attempt_or_event(auth_harness: AuthHarness) -> None:
    _create_user(auth_harness, username="enforced-ip-user")
    with auth_harness.factory() as session, session.begin():
        session.add(
            IpRateLimit(
                source_ip="0.0.0.0",
                reason="test enforcement",
                enforced_until=utc_now() + timedelta(minutes=15),
            )
        )

    response = _login(auth_harness, "enforced-ip-user")

    assert response.status_code == 429
    assert _counts(auth_harness) == (0, 0, 0)


def test_mfa_rate_limit_accumulates_across_pre_auth_tokens_for_one_user(auth_harness: AuthHarness) -> None:
    user = _create_user(auth_harness, username="mfa-rate-one-user", admin_mfa_required=True)
    auth_harness.limiter.scope_limits["mfa"] = 2
    challenges = [_login(auth_harness, "mfa-rate-one-user").json() for _ in range(3)]

    responses = [
        auth_harness.client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={
                "pre_auth_token": challenge["pre_auth_token"],
                "challenge_response": _wrong_otp(auth_harness.mailer.deliveries[index][1]),
            },
        )
        for index, challenge in enumerate(challenges)
    ]

    assert [response.status_code for response in responses] == [401, 401, 429]
    mfa_calls = [call for call in auth_harness.limiter.calls if call[0] == "mfa"]
    assert [call[2] for call in mfa_calls] == [f"user:{user.id}"] * 3
    assert auth_harness.limiter.account_counts[("mfa", f"user:{user.id}")] == 3


def test_mfa_rate_limit_separates_accounts_but_shares_ip_policy(auth_harness: AuthHarness) -> None:
    first_user = _create_user(auth_harness, username="mfa-rate-first", admin_mfa_required=True)
    second_user = _create_user(auth_harness, username="mfa-rate-second", admin_mfa_required=True)
    auth_harness.limiter.scope_limits["mfa"] = 3
    first_challenge = _login(auth_harness, "mfa-rate-first").json()
    second_challenge = _login(auth_harness, "mfa-rate-second").json()
    first_wrong = _wrong_otp(auth_harness.mailer.deliveries[-2][1])
    second_wrong = _wrong_otp(auth_harness.mailer.deliveries[-1][1])

    responses = [
        auth_harness.client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": first_challenge["pre_auth_token"], "challenge_response": first_wrong},
        ),
        auth_harness.client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": second_challenge["pre_auth_token"], "challenge_response": second_wrong},
        ),
        auth_harness.client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": first_challenge["pre_auth_token"], "challenge_response": first_wrong},
        ),
        auth_harness.client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": second_challenge["pre_auth_token"], "challenge_response": second_wrong},
        ),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 429]
    assert auth_harness.limiter.account_counts[("mfa", f"user:{first_user.id}")] == 2
    assert auth_harness.limiter.account_counts[("mfa", f"user:{second_user.id}")] == 2
    assert auth_harness.limiter.ip_counts[("mfa", "0.0.0.0")] == 4


def test_mfa_rate_limit_accumulates_one_user_across_source_ips(auth_harness: AuthHarness) -> None:
    user = _create_user(auth_harness, username="mfa-rate-multi-ip", admin_mfa_required=True)
    auth_harness.limiter.scope_limits["mfa"] = 2
    with (
        TestClient(auth_harness.app, client=("198.51.100.10", 50000)) as first_ip_client,
        TestClient(auth_harness.app, client=("198.51.100.11", 50001)) as second_ip_client,
    ):
        first_challenge = first_ip_client.post(
            "/api/v1/auth/login",
            headers=_headers(),
            json={"username": "mfa-rate-multi-ip", "password": "correct-password"},
        ).json()
        first_wrong = _wrong_otp(auth_harness.mailer.deliveries[-1][1])
        first_response = first_ip_client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": first_challenge["pre_auth_token"], "challenge_response": first_wrong},
        )

        second_challenge = second_ip_client.post(
            "/api/v1/auth/login",
            headers=_headers(),
            json={"username": "mfa-rate-multi-ip", "password": "correct-password"},
        ).json()
        second_wrong = _wrong_otp(auth_harness.mailer.deliveries[-1][1])
        second_response = second_ip_client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": second_challenge["pre_auth_token"], "challenge_response": second_wrong},
        )

        third_challenge = first_ip_client.post(
            "/api/v1/auth/login",
            headers=_headers(),
            json={"username": "mfa-rate-multi-ip", "password": "correct-password"},
        ).json()
        third_response = first_ip_client.post(
            "/api/v1/auth/mfa/verify",
            headers=_headers(),
            json={"pre_auth_token": third_challenge["pre_auth_token"], "challenge_response": first_wrong},
        )

    assert [first_response.status_code, second_response.status_code, third_response.status_code] == [401, 401, 429]
    assert auth_harness.limiter.account_counts[("mfa", f"user:{user.id}")] == 3
    assert auth_harness.limiter.ip_counts[("mfa", "198.51.100.10")] == 2
    assert auth_harness.limiter.ip_counts[("mfa", "198.51.100.11")] == 1


def test_deleted_user_and_revoked_session_are_rejected_after_token_issuance(auth_harness: AuthHarness) -> None:
    user = _create_user(auth_harness, username="state-change")
    issued = _login(auth_harness, "state-change").json()
    with auth_harness.factory() as session, session.begin():
        persisted_user = session.get(User, user.id)
        persisted_user.status = UserStatus.DELETED
        persisted_user.deleted_at = utc_now()

    assert auth_harness.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {issued['access_token']}"}
    ).status_code == 401


def test_expired_session_rejects_access_and_refresh(auth_harness: AuthHarness) -> None:
    user = _create_user(auth_harness, username="expired-session")
    issued = _login(auth_harness, "expired-session").json()
    with auth_harness.factory() as session, session.begin():
        persisted_session = session.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        persisted_session.expires_at = utc_now() - timedelta(seconds=1)

    assert auth_harness.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {issued['access_token']}"}
    ).status_code == 401
    assert auth_harness.client.post(
        "/api/v1/auth/refresh", headers=_headers(), json={"refresh_token": issued["refresh_token"]}
    ).status_code == 401


def test_expired_pre_auth_token_is_rejected_and_closed(auth_harness: AuthHarness) -> None:
    _create_user(auth_harness, username="expired-pre-auth", admin_mfa_required=True)
    required = _login(auth_harness, "expired-pre-auth").json()
    code = auth_harness.mailer.deliveries[-1][1]
    with auth_harness.factory() as session, session.begin():
        pre_auth = session.scalar(select(PreAuthTransaction).where(PreAuthTransaction.token_hash == token_verifier(required["pre_auth_token"])))
        pre_auth.expires_at = utc_now() - timedelta(seconds=1)

    assert auth_harness.client.post(
        "/api/v1/auth/mfa/verify",
        headers=_headers(),
        json={"pre_auth_token": required["pre_auth_token"], "challenge_response": code},
    ).status_code == 401
    with auth_harness.factory() as session:
        pre_auth = session.scalar(select(PreAuthTransaction).where(PreAuthTransaction.token_hash == token_verifier(required["pre_auth_token"])))
        assert pre_auth.status == PreAuthStatus.EXPIRED


def test_detection_mfa_once_is_consumed_only_after_successful_verification(auth_harness: AuthHarness) -> None:
    user = _create_user(auth_harness, username="one-time-mfa", detection_mfa_once=True)
    required = _login(auth_harness, "one-time-mfa").json()
    code = auth_harness.mailer.deliveries[-1][1]
    assert auth_harness.client.post(
        "/api/v1/auth/mfa/verify",
        headers=_headers(),
        json={"pre_auth_token": required["pre_auth_token"], "challenge_response": code},
    ).status_code == 200
    with auth_harness.factory() as session:
        assert session.get(User, user.id).detection_mfa_once is False


def test_concurrent_mfa_verification_creates_exactly_one_session_on_postgresql(auth_harness: AuthHarness, database_engine) -> None:
    if database_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock verification")
    _create_user(auth_harness, username="concurrent-mfa", admin_mfa_required=True)
    required = _login(auth_harness, "concurrent-mfa").json()
    code = auth_harness.mailer.deliveries[-1][1]
    barrier = Barrier(2)

    def verify_once() -> bool:
        with auth_harness.factory() as session:
            service = AuthenticationService(session=session, settings=auth_harness.settings, mailer=auth_harness.mailer)
            try:
                barrier.wait(timeout=5)
                result = service.verify_mfa(
                    pre_auth_token=required["pre_auth_token"],
                    challenge_response=code,
                    source_ip="0.0.0.0",
                    user_agent="pytest",
                )
                return isinstance(result, SessionIssuedResult)
            except MfaVerificationError:
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: verify_once(), range(2)))
    assert results.count(True) == 1
    assert _counts(auth_harness) == (1, 1, 1)


@pytest.mark.skipif(
    os.getenv("CORE_APP_REDIS_INTEGRATION") != "1",
    reason="Set CORE_APP_REDIS_INTEGRATION=1 to run against local Redis",
)
def test_redis_rate_limiter_enforces_both_identifier_and_ip() -> None:
    settings = _settings().__class__(
        **{
            **_settings().__dict__,
            "redis_url": os.getenv("CORE_APP_REDIS_URL", "redis://localhost:6379/0"),
            "auth_rate_limit_requests": 2,
            "auth_rate_limit_window_seconds": 60,
        }
    )
    limiter = RedisAuthenticationRateLimiter(settings)
    account = str(uuid4())
    assert limiter.allow(scope="pytest-account", source_ip="198.51.100.10", account_identifier=account)
    assert limiter.allow(scope="pytest-account", source_ip="198.51.100.11", account_identifier=account)
    assert not limiter.allow(scope="pytest-account", source_ip="198.51.100.12", account_identifier=account)
    assert limiter.allow(scope="pytest-ip", source_ip="198.51.100.20", account_identifier=str(uuid4()))
    assert limiter.allow(scope="pytest-ip", source_ip="198.51.100.20", account_identifier=str(uuid4()))
    assert not limiter.allow(scope="pytest-ip", source_ip="198.51.100.20", account_identifier=str(uuid4()))
