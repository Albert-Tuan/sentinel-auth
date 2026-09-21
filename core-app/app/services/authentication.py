"""Transactional core authentication flows; routers only map their results to HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import secrets
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import selectinload

from app.core.passwords import hash_password, verify_password
from app.core.settings import Settings
from app.core.tokens import (
    TokenValidationError,
    context_digest,
    decode_jwt,
    generate_opaque_token,
    issue_jwt,
    token_verifier,
)
from app.models import (
    IpRateLimit,
    LoginAttempt,
    LoginOutcome,
    MfaChallenge,
    MfaChallengeStatus,
    OutboxEvent,
    OutboxStatus,
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
from app.services.mailer import MfaMailer


_GENERIC_DENIED_MESSAGE = "Authentication could not be completed."


class AuthenticationError(ValueError):
    """Base class for errors deliberately safe to map to public auth failures."""


class RegistrationConflictError(AuthenticationError):
    pass


class AuthenticationRequiredError(AuthenticationError):
    pass


class SessionNotFoundError(AuthenticationError):
    pass


class SessionOwnershipError(AuthenticationError):
    pass


class MfaVerificationError(AuthenticationError):
    pass


class RateLimitedError(AuthenticationError):
    pass


@dataclass(frozen=True)
class UserProfileData:
    id: UUID
    username: str
    email: str
    status: str
    roles: list[str]
    admin_mfa_required: bool


@dataclass(frozen=True)
class SessionIssuedResult:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class MfaRequiredResult:
    pre_auth_token: str
    expires_in: int
    otp_expires_in: int


@dataclass(frozen=True)
class DeniedResult:
    message: str = _GENERIC_DENIED_MESSAGE


@dataclass(frozen=True)
class AuthenticatedIdentity:
    user: User
    session: AuthSession
    roles: list[str]


class AuthenticationService:
    """Owns database transaction boundaries for public authentication flows."""

    def __init__(self, session: DbSession, settings: Settings, mailer: MfaMailer) -> None:
        self._session = session
        self._settings = settings
        self._mailer = mailer

    def register(self, *, username: str, email: str, password: str) -> UserProfileData:
        normalized_username = username.strip()
        normalized_email = email.strip().casefold()
        with self._session.begin():
            existing = self._session.scalar(
                select(User.id).where(
                    or_(
                        func.lower(User.username) == normalized_username.casefold(),
                        func.lower(User.email) == normalized_email,
                    )
                )
            )
            if existing is not None:
                raise RegistrationConflictError("Account already exists")

            user_role = self._session.scalar(select(Role).where(Role.code == RoleCode.USER))
            if user_role is None:
                raise RuntimeError("The seeded USER role is missing")

            user = User(
                username=normalized_username,
                email=normalized_email,
                password_hash=hash_password(password),
                status=UserStatus.ACTIVE,
            )
            self._session.add(user)
            self._session.flush()
            self._session.add(UserRole(user_id=user.id, role_id=user_role.id))
            profile = self._profile_from_user(user, [RoleCode.USER])
        return profile

    def login(
        self,
        *,
        username: str | None,
        email: str | None,
        password: str,
        source_ip: str,
        user_agent: str | None,
        device_fingerprint: str | None,
        correlation_id: UUID,
    ) -> SessionIssuedResult | MfaRequiredResult | DeniedResult:
        otp_delivery: tuple[str, str] | None = None
        result: SessionIssuedResult | MfaRequiredResult | DeniedResult
        with self._session.begin():
            if self.source_ip_is_enforced(source_ip):
                raise RateLimitedError("Source IP is currently rate limited")
            user = self._find_user(username=username, email=email, lock=True)
            device_hash = self._digest_optional(device_fingerprint)
            if user is None or user.status != UserStatus.ACTIVE:
                self._record_login_attempt(
                    user=user,
                    correlation_id=correlation_id,
                    outcome=LoginOutcome.DENY,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    device_hash=device_hash,
                    mfa_completed=False,
                )
                result = DeniedResult()
            elif not verify_password(user.password_hash, password):
                self._record_login_attempt(
                    user=user,
                    correlation_id=correlation_id,
                    outcome=LoginOutcome.DENY,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    device_hash=device_hash,
                    mfa_completed=False,
                )
                result = DeniedResult()
            elif user.admin_mfa_required or user.detection_mfa_once:
                attempt = self._record_login_attempt(
                    user=user,
                    correlation_id=correlation_id,
                    outcome=LoginOutcome.MFA_REQUIRED,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    device_hash=device_hash,
                    mfa_completed=False,
                )
                raw_token, code = self._create_mfa_challenge(
                    user=user,
                    login_attempt=attempt,
                    source_ip=source_ip,
                    device_hash=device_hash,
                )
                result = MfaRequiredResult(
                    pre_auth_token=raw_token,
                    expires_in=self._settings.pre_auth_ttl_seconds,
                    otp_expires_in=self._settings.mfa_otp_ttl_seconds,
                )
                otp_delivery = (user.email, code)
            else:
                self._record_login_attempt(
                    user=user,
                    correlation_id=correlation_id,
                    outcome=LoginOutcome.ALLOW,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    device_hash=device_hash,
                    mfa_completed=True,
                )
                result = self._create_session_tokens(
                    user=user,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    device_hash=device_hash,
                )

        # The transaction above is committed before SMTP. A delivery failure must
        # never roll back the immutable attempt/challenge nor issue a JWT.
        if otp_delivery is not None:
            try:
                self._mailer.send_email_otp(recipient=otp_delivery[0], code=otp_delivery[1])
            except Exception:
                pass
        return result

    def verify_mfa(
        self,
        *,
        pre_auth_token: str,
        challenge_response: str,
        source_ip: str,
        user_agent: str | None,
    ) -> SessionIssuedResult:
        failure = False
        issued: SessionIssuedResult | None = None
        with self._session.begin():
            pre_auth = self._session.scalar(
                select(PreAuthTransaction)
                .where(PreAuthTransaction.token_hash == token_verifier(pre_auth_token))
                .with_for_update()
            )
            if pre_auth is None:
                failure = True
            else:
                user = self._session.scalar(select(User).where(User.id == pre_auth.user_id).with_for_update())
                challenge = self._session.scalar(
                    select(MfaChallenge)
                    .where(MfaChallenge.pre_auth_transaction_id == pre_auth.id)
                    .with_for_update()
                )
                now = utc_now()
                if (
                    user is None
                    or user.status != UserStatus.ACTIVE
                    or pre_auth.status != PreAuthStatus.ACTIVE
                    or _is_expired(pre_auth.expires_at, now)
                    or pre_auth.bound_ip_hash != self._digest(source_ip)
                    or challenge is None
                ):
                    if pre_auth.status == PreAuthStatus.ACTIVE and _is_expired(pre_auth.expires_at, now):
                        pre_auth.status = PreAuthStatus.EXPIRED
                    failure = True
                elif challenge.status != MfaChallengeStatus.ACTIVE or _is_expired(challenge.expires_at, now):
                    if challenge.status == MfaChallengeStatus.ACTIVE and _is_expired(challenge.expires_at, now):
                        challenge.status = MfaChallengeStatus.EXPIRED
                    failure = True
                elif not verify_password(challenge.code_hash, challenge_response):
                    challenge.fail_count += 1
                    if challenge.fail_count >= self._settings.mfa_max_attempts:
                        challenge.status = MfaChallengeStatus.LOCKED
                        pre_auth.status = PreAuthStatus.INVALIDATED
                        pre_auth.invalidated_at = now
                        pre_auth.invalidated_reason = "MFA_MAX_ATTEMPTS"
                    failure = True
                else:
                    challenge.status = MfaChallengeStatus.VERIFIED
                    challenge.verified_at = now
                    pre_auth.status = PreAuthStatus.VERIFIED
                    pre_auth.verified_at = now
                    if user.detection_mfa_once:
                        user.detection_mfa_once = False
                    issued = self._create_session_tokens(
                        user=user,
                        source_ip=source_ip,
                        user_agent=user_agent,
                        device_hash=pre_auth.bound_device_hash,
                    )

        if failure or issued is None:
            raise MfaVerificationError("MFA verification failed")
        return issued

    def mfa_rate_limit_account_identifier(self, *, pre_auth_token: str) -> str:
        """Resolve a stable, non-sensitive MFA rate-limit subject.

        The raw pre-auth credential is intentionally never used as a Redis
        account key. A transaction may already have been invalidated or
        consumed, but it still resolves to its owner so attempts across tokens
        issued for one account accumulate under one account limit. Token
        validity and consumption remain exclusively the responsibility of
        :meth:`verify_mfa`.
        """

        verifier = token_verifier(pre_auth_token)
        # Finish this read transaction before the router makes the Redis call;
        # verify_mfa then starts its own locking transaction without changing
        # pre-auth state merely for rate-limit resolution.
        with self._session.begin():
            user_id = self._session.scalar(
                select(PreAuthTransaction.user_id).where(PreAuthTransaction.token_hash == verifier)
            )
        if user_id is not None:
            return f"user:{user_id}"

        # No account can be resolved for an unknown credential. Retain a
        # verifier-only fallback to throttle repeated invalid credentials while
        # never placing the raw token in Redis, logs, or the database.
        return f"unknown-pre-auth:{verifier}"

    def refresh(self, *, refresh_token: str) -> SessionIssuedResult:
        claims = decode_jwt(refresh_token, settings=self._settings, expected_type="refresh")
        session_id, subject_id = _claim_uuids(claims)
        with self._session.begin():
            auth_session = self._session.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
            user = self._session.scalar(select(User).where(User.id == subject_id).with_for_update())
            now = utc_now()
            if (
                auth_session is None
                or user is None
                or auth_session.user_id != user.id
                or user.status != UserStatus.ACTIVE
                or auth_session.revoked_at is not None
                or _is_expired(auth_session.expires_at, now)
                or auth_session.token_version != claims.get("token_version")
                or not secrets.compare_digest(auth_session.refresh_token_hash, token_verifier(refresh_token))
            ):
                raise AuthenticationRequiredError("Refresh token is not active")

            auth_session.token_version += 1
            roles = self._role_codes(user.id)
            access_id = uuid4()
            access_token, _, _ = issue_jwt(
                settings=self._settings,
                subject=user.id,
                session_id=auth_session.id,
                roles=roles,
                token_type="access",
                expires_in=timedelta(minutes=self._settings.access_token_ttl_minutes),
                token_version=auth_session.token_version,
                token_id=access_id,
            )
            remaining_refresh_ttl = _as_utc(auth_session.expires_at) - now
            refresh_token_new, _, _ = issue_jwt(
                settings=self._settings,
                subject=user.id,
                session_id=auth_session.id,
                roles=roles,
                token_type="refresh",
                expires_in=remaining_refresh_ttl,
                token_version=auth_session.token_version,
            )
            auth_session.access_jti = str(access_id)
            auth_session.refresh_token_hash = token_verifier(refresh_token_new)
            issued = SessionIssuedResult(
                access_token=access_token,
                refresh_token=refresh_token_new,
                expires_in=self._settings.access_token_ttl_minutes * 60,
            )
        return issued

    def current_identity(self, *, access_token: str) -> AuthenticatedIdentity:
        claims = decode_jwt(access_token, settings=self._settings, expected_type="access")
        session_id, subject_id = _claim_uuids(claims)
        auth_session = self._session.scalar(select(AuthSession).where(AuthSession.id == session_id))
        user = self._session.scalar(select(User).where(User.id == subject_id))
        now = utc_now()
        if (
            auth_session is None
            or user is None
            or auth_session.user_id != user.id
            or user.status != UserStatus.ACTIVE
            or auth_session.revoked_at is not None
            or _is_expired(auth_session.expires_at, now)
            or auth_session.access_jti != claims.get("jti")
            or auth_session.token_version != claims.get("token_version")
        ):
            raise AuthenticationRequiredError("Access token is not active")
        return AuthenticatedIdentity(user=user, session=auth_session, roles=self._role_codes(user.id))

    def profile(self, identity: AuthenticatedIdentity) -> UserProfileData:
        return self._profile_from_user(identity.user, identity.roles)

    def list_sessions(self, identity: AuthenticatedIdentity) -> list[AuthSession]:
        return list(
            self._session.scalars(
                select(AuthSession).where(AuthSession.user_id == identity.user.id).order_by(AuthSession.created_at.desc())
            )
        )

    def revoke_current_session(self, identity: AuthenticatedIdentity) -> None:
        session_id = identity.session.id
        user_id = identity.user.id
        self._session.rollback()
        with self._session.begin():
            auth_session = self._session.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
            if auth_session is None or auth_session.user_id != user_id:
                raise AuthenticationRequiredError("Session is not active")
            if auth_session.revoked_at is None:
                auth_session.revoked_at = utc_now()

    def revoke_owned_session(self, identity: AuthenticatedIdentity, target_session_id: UUID) -> None:
        user_id = identity.user.id
        self._session.rollback()
        with self._session.begin():
            target = self._session.scalar(select(AuthSession).where(AuthSession.id == target_session_id).with_for_update())
            if target is None:
                raise SessionNotFoundError("Session was not found")
            if target.user_id != user_id:
                raise SessionOwnershipError("Session is not owned by current user")
            if target.revoked_at is None:
                target.revoked_at = utc_now()

    def source_ip_is_enforced(self, source_ip: str) -> bool:
        return self._session.scalar(
            select(IpRateLimit.id).where(
                IpRateLimit.source_ip == source_ip,
                IpRateLimit.enforced_until > utc_now(),
            )
        ) is not None

    def _find_user(self, *, username: str | None, email: str | None, lock: bool) -> User | None:
        identifier_clause = (
            func.lower(User.username) == username.strip().casefold()
            if username is not None
            else func.lower(User.email) == email.strip().casefold()
        )
        statement = select(User).where(identifier_clause)
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def _create_mfa_challenge(
        self,
        *,
        user: User,
        login_attempt: LoginAttempt,
        source_ip: str,
        device_hash: str | None,
    ) -> tuple[str, str]:
        now = utc_now()
        existing_pre_auth = list(
            self._session.scalars(
                select(PreAuthTransaction)
                .where(PreAuthTransaction.user_id == user.id, PreAuthTransaction.status == PreAuthStatus.ACTIVE)
                .with_for_update()
            )
        )
        for transaction in existing_pre_auth:
            transaction.status = PreAuthStatus.INVALIDATED
            transaction.invalidated_at = now
            transaction.invalidated_reason = "SUPERSEDED_BY_NEW_LOGIN"
        if existing_pre_auth:
            self._session.execute(
                select(MfaChallenge)
                .where(
                    MfaChallenge.user_id == user.id,
                    MfaChallenge.status == MfaChallengeStatus.ACTIVE,
                )
                .with_for_update()
            )
            for challenge in self._session.scalars(
                select(MfaChallenge).where(
                    MfaChallenge.user_id == user.id,
                    MfaChallenge.status == MfaChallengeStatus.ACTIVE,
                )
            ):
                challenge.status = MfaChallengeStatus.INVALIDATED
                challenge.invalidated_at = now
                challenge.invalidated_reason = "SUPERSEDED_BY_NEW_LOGIN"
            self._session.flush()

        raw_token = generate_opaque_token()
        code = f"{secrets.randbelow(10_000):04d}"
        pre_auth = PreAuthTransaction(
            user_id=user.id,
            login_attempt_id=login_attempt.id,
            token_hash=token_verifier(raw_token),
            status=PreAuthStatus.ACTIVE,
            expires_at=now + timedelta(seconds=self._settings.pre_auth_ttl_seconds),
            bound_ip_hash=self._digest(source_ip),
            bound_device_hash=device_hash,
        )
        self._session.add(pre_auth)
        self._session.flush()
        self._session.add(
            MfaChallenge(
                user_id=user.id,
                pre_auth_transaction_id=pre_auth.id,
                code_hash=hash_password(code),
                status=MfaChallengeStatus.ACTIVE,
                expires_at=now + timedelta(seconds=self._settings.mfa_otp_ttl_seconds),
                fail_count=0,
            )
        )
        return raw_token, code

    def _create_session_tokens(
        self,
        *,
        user: User,
        source_ip: str,
        user_agent: str | None,
        device_hash: str | None,
    ) -> SessionIssuedResult:
        now = utc_now()
        roles = self._role_codes(user.id)
        session_id = uuid4()
        session_expires_at = now + timedelta(days=self._settings.refresh_token_ttl_days)
        access_id = uuid4()
        access_token, _, _ = issue_jwt(
            settings=self._settings,
            subject=user.id,
            session_id=session_id,
            roles=roles,
            token_type="access",
            expires_in=timedelta(minutes=self._settings.access_token_ttl_minutes),
            token_version=1,
            token_id=access_id,
        )
        refresh_token, _, _ = issue_jwt(
            settings=self._settings,
            subject=user.id,
            session_id=session_id,
            roles=roles,
            token_type="refresh",
            expires_in=timedelta(days=self._settings.refresh_token_ttl_days),
            token_version=1,
        )
        self._session.add(
            AuthSession(
                id=session_id,
                user_id=user.id,
                access_jti=str(access_id),
                refresh_token_hash=token_verifier(refresh_token),
                source_ip=source_ip,
                device_id=device_hash,
                user_agent=user_agent,
                expires_at=session_expires_at,
                token_version=1,
            )
        )
        return SessionIssuedResult(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.access_token_ttl_minutes * 60,
        )

    def _record_login_attempt(
        self,
        *,
        user: User | None,
        correlation_id: UUID,
        outcome: LoginOutcome,
        source_ip: str,
        user_agent: str | None,
        device_hash: str | None,
        mfa_completed: bool,
    ) -> LoginAttempt:
        occurred_at = utc_now()
        attempt = LoginAttempt(
            user_id=user.id if user is not None else None,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            outcome=outcome,
            source_ip=source_ip,
            device_fingerprint_hash=device_hash,
            user_agent=user_agent,
            policy_version=self._settings.auth_policy_version,
            mfa_completed=mfa_completed,
        )
        self._session.add(attempt)
        self._session.flush()
        payload = {
            "login_attempt_id": str(attempt.id),
            "user_id": str(user.id) if user is not None else None,
            "occurred_at": occurred_at.isoformat(),
            "outcome": str(outcome),
            "source_ip": source_ip,
            "device_fingerprint_hash": device_hash,
            "user_agent": user_agent,
            "region_code": None,
            "policy_version": self._settings.auth_policy_version,
            "mfa_completed": mfa_completed,
        }
        checksum = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self._session.add(
            OutboxEvent(
                login_attempt_id=attempt.id,
                event_type="auth.login-attempt.v1",
                schema_version=1,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
                producer="core-app",
                payload=payload,
                payload_checksum=checksum,
                status=OutboxStatus.PENDING,
                publish_attempts=0,
            )
        )
        return attempt

    def _role_codes(self, user_id: UUID) -> list[str]:
        return [
            str(role_code)
            for role_code in self._session.scalars(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
                .order_by(Role.code)
            )
        ]

    def _profile_from_user(self, user: User, roles: list[str] | list[RoleCode]) -> UserProfileData:
        return UserProfileData(
            id=user.id,
            username=user.username,
            email=user.email,
            status=str(user.status),
            roles=[str(role) for role in roles],
            admin_mfa_required=user.admin_mfa_required,
        )

    def _digest(self, value: str) -> str:
        return context_digest(value, self._settings)

    def _digest_optional(self, value: str | None) -> str | None:
        return self._digest(value) if value else None


def _claim_uuids(claims: dict[str, object]) -> tuple[UUID, UUID]:
    try:
        return UUID(str(claims["sid"])), UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenValidationError("JWT subject or session is invalid") from exc


def _is_expired(value: datetime, now: datetime) -> bool:
    return _as_utc(value) <= now


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
