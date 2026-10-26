"""
Authentication endpoints - login, MFA, session management.
Mirrors infra/postgres/schema-core-v3.3.sql.
"""
import hashlib
import ipaddress
import asyncio
import logging
import os
import secrets
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

from app.time_utils import utc_now, as_utc
from uuid import UUID, uuid4

import httpx
from app.client_ip import get_client_ip
from fastapi import APIRouter, HTTPException, status, Depends, Request, Header
from pydantic import BaseModel
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

from app.authz import hash_token, get_current_auth_context, AuthContext
from app.db import get_db
from app.models import (
    IpAddress,
    AuditLog,
    MfaNotification,
    MfaTransaction,
    RateLimit,
    RiskAssessment,
    Role,
    Session,
    User,
)
from app.schemas import (
    UserRegisterRequest, UserRegisterResponse,
    LoginRequest, LoginResponse,
    MfaVerifyRequest, MfaVerifyResponse,
    RefreshRequest, RefreshResponse,
    LogoutResponse, SessionItem, SessionList,
    UserItem,
)

from app.internal_auth import (
    InternalAuthConfigurationError,
    get_internal_secret,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
ph = PasswordHasher()

LOGIN_EVENT_TIMEOUT = float(os.getenv("LOGIN_EVENT_TIMEOUT", "3"))
RUN_LOGIN_EVENT_DELIVERY = os.getenv("RUN_LOGIN_EVENT_DELIVERY", "1")


@dataclass(frozen=True)
class LoginEvent:
    """Core-owned event payload sent to Detection over HTTP.

    This deliberately is not a SQLAlchemy model: ``login_attempts`` belongs
    to the Detection database and Core must not persist it locally.
    """

    event_id: UUID
    request_id: UUID
    user_id: Optional[UUID]
    username_attempted: str
    outcome: str
    mfa_used: bool
    ip_address: Optional[str]
    user_agent: Optional[str]
    timestamp: datetime


def _audit(
    db,
    *,
    action: str,
    resource: str,
    resource_id=None,
    actor_id=None,
    actor_type: str = "system",
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    change_reason: Optional[str] = None,
    request_id=None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuditLog:
    """Queue an immutable audit record in the Core database transaction."""
    row = AuditLog(
        request_id=request_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        resource=resource,
        resource_id=resource_id,
        before_state=before_state,
        after_state=after_state,
        change_reason=change_reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(row)
    return row


async def _send_login_event(attempt: Optional[LoginEvent]) -> bool:
    """Deliver one stable LoginEvent to Detection over the service boundary.

    Detection owns ``login_attempts``. Core only sends this HTTP event and never
    opens or writes the Detection database. Delivery is best-effort so a
    Detection outage cannot turn a valid credential check into an auth outage.
    """
    if attempt is None or RUN_LOGIN_EVENT_DELIVERY != "1" or not DETECTION_URL:
        return False
    payload = {
        "event_id": str(attempt.event_id),
        "user_id": str(attempt.user_id) if attempt.user_id else None,
        "username_attempted": attempt.username_attempted or "",
        "outcome": attempt.outcome,
        "mfa_used": bool(attempt.mfa_used),
        "ip_address": attempt.ip_address,
        "user_agent": attempt.user_agent,
        "timestamp": attempt.timestamp.isoformat(),
        "request_id": str(attempt.request_id) if attempt.request_id else None,
    }
    try:
        headers = {"X-Internal-Secret": get_internal_secret()}
    except InternalAuthConfigurationError:
        logger.warning("login event delivery skipped: internal secret is not configured")
        return False
    for delivery_attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=LOGIN_EVENT_TIMEOUT) as client:
                response = await client.post(
                    f"{DETECTION_URL}/api/v1/internal/login-events",
                    json=payload,
                    headers=headers,
                )
            if response.status_code < 500:
                if response.status_code >= 400:
                    logger.warning("login event rejected with HTTP %s", response.status_code)
                    return False
                return True
        except httpx.HTTPError as exc:
            logger.warning(
                "login event delivery failed (attempt %s): %s",
                delivery_attempt + 1,
                exc.__class__.__name__,
            )
        if delivery_attempt == 0:
            await asyncio.sleep(0)
    return False


def _smtp_config() -> tuple[str, int, str, float, bool]:
    host = os.getenv("MFA_SMTP_HOST", "localhost")
    port = int(os.getenv("MFA_SMTP_PORT", "1025"))
    sender = os.getenv("MFA_FROM_EMAIL", "no-reply@sentinel-auth.local")
    timeout = float(os.getenv("MFA_SMTP_TIMEOUT", "3"))
    starttls = os.getenv("MFA_SMTP_STARTTLS", "0") == "1"
    return host, port, sender, timeout, starttls


def _send_otp_email_sync(recipient: str, otp: str) -> None:
    """Send the OTP through the configured SMTP provider (Mailpit by default)."""
    host, port, sender, timeout, starttls = _smtp_config()
    message = EmailMessage()
    message["Subject"] = "Sentinel Auth verification code"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Your Sentinel Auth verification code is "
        f"{otp}. It expires in 5 minutes."
    )
    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        if starttls:
            smtp.starttls()
        smtp.send_message(message)


async def _send_otp_email(recipient: str, otp: str) -> None:
    if not recipient:
        raise ValueError("MFA email recipient is empty")
    await asyncio.to_thread(_send_otp_email_sync, recipient, otp)


# =============================================================================
# Internal helpers
# =============================================================================

def generate_otp() -> str:
    """Generate 6-digit OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def resolve_ip_address(db, client_ip: str) -> Optional[str]:
    """Return the ``ip_addresses.id`` for ``client_ip``, creating it on first sight.

    The SQL normalises IPs into ``ip_addresses`` and ``sessions`` only stores
    the FK, so every session insert must go through here. Returns ``None``
    for unknown/unusable values so the session is still created.
    """
    if not client_ip or client_ip == "unknown":
        return None
    try:
        row = db.query(IpAddress).filter(IpAddress.ip_address == client_ip).first()
    except Exception:  # noqa: BLE001 - IP tracking must not block login
        logger.warning("could not resolve ip_addresses row for %s", client_ip, exc_info=True)
        return None
    if row is None:
        row = IpAddress(ip_address=client_ip)
        db.add(row)
        db.flush()
    else:
        row.last_seen_at = utc_now()
    return row.id


def normalize_ip(value: str) -> str:
    """Canonicalise an IP address string to its standard textual form.

    Uses Python's ipaddress module so that equivalent IPv6 representations
    (e.g. ``2001:db8::1`` and ``2001:0db8:0:0:0:0:0:1``) compare equal.
    Raises ValueError for any input that is not a valid IPv4 or IPv6 address.
    """
    return str(ipaddress.ip_address(value))


def _login_event(
    *,
    request_id: UUID,
    username_attempted: str,
    outcome: str,
    timestamp: datetime,
    user_id: Optional[UUID] = None,
    mfa_used: bool = False,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> LoginEvent:
    """Build a stable event without touching Detection's database tables."""
    return LoginEvent(
        event_id=uuid4(),
        request_id=request_id,
        user_id=user_id,
        username_attempted=username_attempted,
        outcome=outcome,
        mfa_used=mfa_used,
        ip_address=ip_address,
        user_agent=user_agent,
        timestamp=timestamp,
    )


# =============================================================================
# Request/Response schemas
# =============================================================================

class RegisterRequest(BaseModel):
    username: str
    email: Optional[str] = None
    password: str


class RegisterResponse(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    created_at: datetime


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/register", response_model=UserRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(request: UserRegisterRequest, db=Depends(get_db)) -> UserRegisterResponse:
    """
    Register a new user account.

    - Validates username (3-50 chars, alphanumeric + underscore), email, password (>=8 chars)
    - Checks for duplicate username/email
    - Hashes password with Argon2id
    - Creates user with role 'USER'
    - Does NOT auto-assign special roles
    """
    # Validate username length
    if len(request.username) < 3 or len(request.username) > 50:
        raise HTTPException(status_code=422, detail="Username must be 3-50 characters")

    # Validate username characters
    if not all(c.isalnum() or c == "_" for c in request.username):
        raise HTTPException(status_code=422, detail="Username must be alphanumeric + underscore only")

    # Validate password length
    if len(request.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    # Validate email if provided
    if request.email:
        if "@" not in request.email or "(" in request.email or ")" in request.email:
            raise HTTPException(status_code=422, detail="Invalid email format")

    # Check for duplicate username
    existing = db.query(User).filter(User.username == request.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    # Check for duplicate email
    if request.email:
        existing_email = db.query(User).filter(User.email == request.email).first()
        if existing_email:
            raise HTTPException(status_code=409, detail="Email already exists")

    # Hash password
    password_hash = ph.hash(request.password)

    # Create user
    user = User(
        username=request.username,
        email=request.email.lower() if request.email else None,
        password_hash=password_hash,
        status="active",
        admin_mfa_required=False,
        detection_mfa_once=False,
    )
    db.add(user)
    db.flush()

    # Assign role 'USER'
    # The 'USER' role is seeded by infra/postgres/schema-core-v3.3.sql;
    # insert it here so registration still works against an empty database.
    from app.models import UserRole
    ur = UserRole(
        user_id=user.id,
        role_id="USER",
        assigned_at=utc_now(),
    )
    db.add(ur)

    _audit(
        db,
        action="register",
        resource="user",
        resource_id=user.id,
        actor_id=user.id,
        actor_type="user",
        after_state={
            "username": user.username,
            "email": user.email,
            "status": user.status,
            "roles": ["USER"],
        },
    )

    db.commit()
    db.refresh(user)

    return UserRegisterResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        created_at=user.created_at,
    )


#: Detection Engine is consulted synchronously before a token is issued.
#: Set to "" to disable the gate (e.g. local development, or when the
#: Detection Engine is not deployed).
DETECTION_URL = os.getenv("DETECTION_URL", "http://localhost:8001").rstrip("/")
#: Set to "0" to bypass the gate entirely (local dev, or Detection not deployed).
RUN_PRE_TOKEN_CHECK = os.getenv("RUN_PRE_TOKEN_CHECK", "1")
PRE_TOKEN_CHECK_TIMEOUT = 3.0
#: Only these risk levels hold the token back. Everything below the
#: threshold is served immediately so normal logins keep their latency.
GATED_RISK_LEVELS = {"high", "critical"}


async def _pre_token_risk(user, client_ip: str, user_agent: Optional[str]) -> Optional[str]:
    """Ask the Detection Engine to score this login before we issue a token.

    Returns the risk level (``high``/``critical``) when the login should be
    held back for MFA, or ``None`` to proceed.

    Fails **open**: any error, timeout or missing configuration returns
    ``None`` so a Detection outage cannot lock every user out of the system.
    That trade-off is deliberate - availability of the login path wins over
    a stricter gate, and the asynchronous callback still revokes the session
    afterwards if the verdict turns out to be risky.
    """
    if not DETECTION_URL or RUN_PRE_TOKEN_CHECK != "1":
        return None

    try:
        async with httpx.AsyncClient(timeout=PRE_TOKEN_CHECK_TIMEOUT) as client:
            response = await client.post(
                f"{DETECTION_URL}/api/v1/internal/pre-token-check",
                json={
                    "username": user.username,
                    "user_id": str(user.id),
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "timestamp": utc_now().isoformat(),
                },
                headers={"X-Internal-Secret": get_internal_secret()},
            )
    except Exception as exc:  # noqa: BLE001 - fail open by design
        logger.warning(
            "pre-token-check unavailable, proceeding unscored: %s",
            exc.__class__.__name__,
        )
        return None

    if response.status_code >= 400:
        logger.warning("pre-token-check returned HTTP %s, proceeding", response.status_code)
        return None

    try:
        body = response.json()
    except ValueError:
        logger.warning("pre-token-check returned a non-JSON body, proceeding")
        return None

    if body.get("degraded"):
        logger.info("pre-token-check degraded (%s), proceeding", body.get("reason"))
        return None

    level = body.get("risk_level")
    if body.get("require_mfa") and level in GATED_RISK_LEVELS:
        logger.info("holding token for %s: risk_level=%s", user.username, level)
        return level
    return None


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    req: Request,
    db=Depends(get_db),
) -> LoginResponse:
    """
    Authenticate user credentials.

    1. Rate limit check (5 requests/minute/IP)
    2. Verify credentials
    3. Check account status
    4. Risk gate: ask the Detection Engine whether to hold the token
    5. MFA check (persistent or one-time)
    6. Create session + tokens
    """
    client_ip = get_client_ip(req)
    request_id = uuid4()

    # 1. Rate limit check
    now = utc_now()
    window_start = now - timedelta(minutes=1)

    # ``rate_limits`` has a natural primary key ``(ip_address, action)``.
    # Reuse and reset the row when its window has elapsed; never attempt to
    # insert a second row for the same key.
    rate = db.query(RateLimit).filter(
        RateLimit.ip_address == client_ip,
        RateLimit.action == "login",
    ).with_for_update().first()

    if rate and as_utc(rate.window_start) >= window_start and rate.count >= rate.max_count:
        # Record rate-limited login attempt
        la = _login_event(
            request_id=request_id,
            username_attempted=request.username,
            timestamp=now,
            outcome="rate_limited",
            ip_address=client_ip,
        )
        db.commit()
        await _send_login_event(la)
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Update or create rate limit
    if rate:
        if as_utc(rate.window_start) < window_start:
            rate.window_start = now
            rate.count = 1
        else:
            rate.count += 1
    else:
        rate = RateLimit(
            ip_address=client_ip,
            action="login",
            count=1,
            max_count=5,
            window_start=now,
        )
        db.add(rate)

    # 2. Find user and verify password
    user = db.query(User).filter(User.username == request.username).first()

    if not user:
        # Generic error - don't reveal account existence
        la = _login_event(
            request_id=request_id,
            username_attempted=request.username,
            timestamp=now,
            outcome="failure",
            ip_address=client_ip,
            user_agent=req.headers.get("User-Agent"),
        )
        db.commit()
        await _send_login_event(la)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        ph.verify(user.password_hash, request.password)
    except VerifyMismatchError:
        # Wrong password
        user.failed_login_count += 1
        la = _login_event(
            request_id=request_id,
            user_id=user.id,
            username_attempted=request.username,
            timestamp=now,
            outcome="failure",
            ip_address=client_ip,
            user_agent=req.headers.get("User-Agent"),
        )
        db.commit()
        await _send_login_event(la)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 3. Check account status
    if user.status == "locked":
        la = _login_event(
            request_id=request_id,
            user_id=user.id,
            username_attempted=request.username,
            timestamp=now,
            outcome="locked",
            ip_address=client_ip,
            user_agent=req.headers.get("User-Agent"),
        )
        db.commit()
        await _send_login_event(la)
        raise HTTPException(status_code=423, detail="Account is locked")

    # Reset failed login count on successful credential verification
    user.failed_login_count = 0

    # 4. Risk gate (phương án C). Credentials are valid, but the Detection
    # Engine may still consider this login risky. In that case we demand a
    # fresh MFA before any token exists, which closes the window where a
    # stolen credential would otherwise be usable immediately. The async
    # callback also revokes the session later, so this is defence in depth.
    user_agent = req.headers.get("User-Agent")
    gated_level = await _pre_token_risk(user, client_ip, user_agent)
    if gated_level is not None:
        # Reuse the one-time MFA machinery: the challenge is issued, but
        # no session and therefore no token exists yet.
        user.detection_mfa_once = True

    # 5. MFA check
    mfa_required = user.admin_mfa_required or user.detection_mfa_once

    if mfa_required:
        # Create pre-auth transaction
        mfa_type = "persistent" if user.admin_mfa_required else "one_time"
        expires_at = now + timedelta(minutes=5)

        try:
            bound_ip = normalize_ip(client_ip) if client_ip and client_ip != "unknown" else None
        except ValueError:
            # ASGI test clients and some local adapters use a non-IP peer
            # label. Production proxy validation supplies a real IP; leave
            # the binding unset for an explicitly non-address peer.
            bound_ip = None

        mfa_txn = MfaTransaction(
            user_id=user.id,
            mfa_type=mfa_type,
            expires_at=expires_at,
            status="pending",
            bound_ip=bound_ip,
        )
        db.add(mfa_txn)
        db.flush()

        # Generate OTP
        otp = generate_otp()
        otp_hash = ph.hash(otp)

        # Create MFA notification
        notification = MfaNotification(
            mfa_transaction_id=mfa_txn.id,
            channel="email",
            recipient=user.email or "",
            mfa_code_hash=otp_hash,
            expires_at=expires_at,
        )
        db.add(notification)
        db.flush()

        # Link notification to mfa_txn
        mfa_txn.notification_id = notification.id

        try:
            await _send_otp_email(notification.recipient, otp)
            notification.delivered_at = utc_now()
        except Exception as exc:  # noqa: BLE001 - delivery status is persisted
            notification.failed_at = utc_now()
            notification.failure_reason = exc.__class__.__name__
            logger.warning("MFA email delivery failed: %s", exc.__class__.__name__)

        la = _login_event(
            request_id=request_id,
            user_id=user.id,
            username_attempted=request.username,
            timestamp=now,
            outcome="mfa_required",
            ip_address=client_ip,
            user_agent=req.headers.get("User-Agent"),
            mfa_used=True,
        )
        db.commit()
        await _send_login_event(la)

        # Return MFA challenge response
        # In production, email OTP would be sent here
        return LoginResponse(
            access_token="",
            refresh_token="",
            mfa_required=True,
            session_id=mfa_txn.id,
        )

    # 5. No MFA - create session directly
    result, login_event = await _create_session(
        user, client_ip, req.headers.get("User-Agent"), db
    )
    db.commit()
    await _send_login_event(login_event)
    return result


async def _create_session(
    user: User,
    client_ip: str,
    user_agent: Optional[str],
    db,
) -> tuple[LoginResponse, LoginEvent]:
    """Create a new session and generate tokens.

    Does NOT commit. Caller owns the transaction boundary and must call
    db.commit() after all related state changes are flushed.

    Returns (LoginResponse, LoginEvent) so caller can deliver the Detection
    event after the Core transaction commits.
    before the single commit.
    """
    now = utc_now()

    # Generate tokens
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    jti = str(uuid4())

    session = Session(
        user_id=user.id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        refresh_token_family=uuid4(),  # New family for this refresh cycle
        token_jti=jti,
        expires_at=now + timedelta(hours=1),
        last_activity_at=now,
        ip_address_id=resolve_ip_address(db, client_ip),
        user_agent=user_agent,
    )
    db.add(session)

    # Update user last login
    user.last_login_at = now

    # Build a Core-owned event. Detection persists the corresponding
    # ``login_attempts`` row after receiving it over HTTP.
    request_id = uuid4()
    la = _login_event(
        request_id=request_id,
        user_id=user.id,
        username_attempted=user.username,
        timestamp=now,
        outcome="success",
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.flush()  # Populate session.id before recording its audit resource.
    _audit(
        db,
        action="login_success",
        resource="session",
        resource_id=session.id,
        actor_id=user.id,
        actor_type="user",
        after_state={"user_id": str(user.id), "expires_at": session.expires_at.isoformat()},
        request_id=request_id,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.flush()  # Ensure all generated identifiers are available to caller.

    return (
        LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            mfa_required=False,
            session_id=session.id,
        ),
        la,
    )


@router.post("/mfa/verify", response_model=MfaVerifyResponse)
async def mfa_verify(
    request: MfaVerifyRequest,
    req: Request,
    db=Depends(get_db),
) -> MfaVerifyResponse:
    """
    Verify MFA code for a pre-auth transaction (P0-05: atomic OTP consumption).

    Uses SELECT ... FOR UPDATE to prevent concurrent OTP consumption.
    Only ONE request can succeed per MFA transaction.

    Concurrency semantics after lock acquisition:
    - status == 'pending'  → proceed with verification
    - status == 'completed' → 409 Conflict (already consumed)
    - status == 'failed'    → 409 Conflict
    - status == 'expired'  → 401 (expired)
    """
    client_ip = get_client_ip(req)
    now = utc_now()

    # ------------------------------------------------------------------
    # STEP 1: Lock the MFA transaction row with SELECT ... FOR UPDATE.
    # The losing concurrent request waits here until the winner commits
    # or rolls back, preventing double-consumption of the same OTP.
    # ------------------------------------------------------------------
    mfa_txn = (
        db.query(MfaTransaction)
        .filter(MfaTransaction.id == request.session_id)
        .with_for_update()
        .first()
    )

    if not mfa_txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if mfa_txn.mfa_type == "trusted_device":
        raise HTTPException(
            status_code=409,
            detail="Trusted-device approvals must be completed by the approving device",
        )

    # ------------------------------------------------------------------
    # STEP 2: Inspect state after acquiring the lock.
    # The row lock serializes concurrent requests so we can safely
    # distinguish "already consumed" from "pending".
    # ------------------------------------------------------------------
    if mfa_txn.status == "completed":
        raise HTTPException(status_code=409, detail="MFA transaction already completed")

    if mfa_txn.status == "failed":
        raise HTTPException(status_code=409, detail="MFA transaction failed")

    if mfa_txn.status == "expired":
        raise HTTPException(status_code=401, detail="MFA transaction expired")

    # Check expiry: if OTP has expired, mark expired and reject.
    if as_utc(mfa_txn.expires_at) <= now:
        mfa_txn.status = "expired"
        db.commit()
        raise HTTPException(status_code=401, detail="MFA code has expired")

    # ------------------------------------------------------------------
    # STEP 3: Load user and notification while holding the lock.
    # ------------------------------------------------------------------
    user = db.query(User).filter(User.id == mfa_txn.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    notification = (
        db.query(MfaNotification)
        .filter(MfaNotification.id == mfa_txn.notification_id)
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="MFA notification not found")

    if notification.verified_at is not None:
        raise HTTPException(status_code=409, detail="MFA code already used")

    # ------------------------------------------------------------------
    # STEP 4: Verify OTP — wrong attempts are also serialized by the row lock.
    # ------------------------------------------------------------------
    try:
        ph.verify(notification.mfa_code_hash, request.mfa_code)
    except (VerifyMismatchError, InvalidHash):
        # Wrong OTP: increment fail_count atomically while holding the lock.
        mfa_txn.fail_count += 1
        if mfa_txn.fail_count >= 3:
            mfa_txn.status = "failed"

        # Record failed MFA attempt
        la = _login_event(
            request_id=uuid4(),
            user_id=user.id,
            username_attempted=user.username,
            timestamp=now,
            outcome="mfa_failed",
            ip_address=client_ip,
            user_agent=req.headers.get("User-Agent"),
            mfa_used=True,
        )
        db.commit()
        await _send_login_event(la)

        raise HTTPException(status_code=401, detail="Invalid MFA code")

    # ------------------------------------------------------------------
    # STEP 5: OTP verified — IP binding check (P0-03, must remain intact).
    # ------------------------------------------------------------------
    if mfa_txn.bound_ip:
        if client_ip == "unknown":
            logger.warning(
                "MFA verify rejected: client IP is unknown"
            )
            raise HTTPException(
                status_code=403,
                detail="MFA verification is bound to the original IP address",
            )
        if normalize_ip(mfa_txn.bound_ip) != normalize_ip(client_ip):
            logger.warning(
                "MFA verify rejected: IP mismatch bound=%s got=%s",
                mfa_txn.bound_ip,
                client_ip,
            )
            raise HTTPException(
                status_code=403,
                detail="MFA verification is bound to the original IP address",
            )

    # ------------------------------------------------------------------
    # STEP 6: Mark transaction and notification as consumed.
    # ------------------------------------------------------------------
    mfa_txn.status = "completed"
    notification.verified_at = now

    # Clear one-time MFA flag if applicable
    if mfa_txn.mfa_type == "one_time":
        user.detection_mfa_once = False

    # ------------------------------------------------------------------
    # STEP 7: Create session and audit event atomically.
    # All of these commit together or none do.
    # ------------------------------------------------------------------
    result, _ = await _create_session(
        user, client_ip, req.headers.get("User-Agent"), db
    )

    la = _login_event(
        request_id=uuid4(),
        user_id=user.id,
        username_attempted=user.username,
        timestamp=now,
        outcome="mfa_success",
        ip_address=client_ip,
        user_agent=req.headers.get("User-Agent"),
        mfa_used=True,
    )
    db.commit()
    await _send_login_event(la)

    return MfaVerifyResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        session_id=result.session_id,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    request: RefreshRequest,
    db=Depends(get_db),
) -> RefreshResponse:
    """
    Refresh access token using refresh token.

    - Verifies refresh token hash exists and is not revoked
    - Optionally rotates refresh token
    - Issues new access token
    """
    refresh_hash = hash_token(request.refresh_token)

    session = db.query(Session).filter(
        Session.refresh_token_hash == refresh_hash,
        Session.revoked_at.is_(None),
    ).first()

    if not session:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if as_utc(session.expires_at) <= utc_now():
        raise HTTPException(status_code=401, detail="Session expired")

    # Generate new access token
    new_access_token = secrets.token_urlsafe(32)
    new_jti = str(uuid4())

    session.access_token_hash = hash_token(new_access_token)
    session.token_jti = new_jti
    session.last_activity_at = utc_now()

    # Optional: rotate refresh token (token rotation for security)
    new_refresh_token = secrets.token_urlsafe(32)
    session.refresh_token_hash = hash_token(new_refresh_token)

    _audit(
        db,
        action="refresh_session",
        resource="session",
        resource_id=session.id,
        actor_id=session.user_id,
        actor_type="user",
        after_state={"expires_at": session.expires_at.isoformat()},
    )

    db.commit()

    return RefreshResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
) -> LogoutResponse:
    """
    Logout current session.

    - Uses canonical get_current_auth_context() for authentication
    - Revokes ctx.session by setting revoked_at
    - Post-logout: same token → 401 on protected endpoints
    """
    if ctx.session:
        ctx.session.revoked_at = utc_now()
        _audit(
            db,
            action="logout",
            resource="session",
            resource_id=ctx.session.id,
            actor_id=ctx.user.id,
            actor_type="user",
            after_state={"revoked": True},
        )
        db.commit()

    return LogoutResponse(status="ok")


@router.post("/logout-all", response_model=LogoutResponse)
async def logout_all(
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
) -> LogoutResponse:
    """Revoke every active session belonging to the authenticated user."""
    now = utc_now()
    revoked = int(
        db.query(Session)
        .filter(Session.user_id == ctx.user.id, Session.revoked_at.is_(None))
        .update({Session.revoked_at: now}, synchronize_session=False)
        or 0
    )
    _audit(
        db,
        action="logout_all",
        resource="user",
        resource_id=ctx.user.id,
        actor_id=ctx.user.id,
        actor_type="user",
        after_state={"sessions_revoked": revoked},
    )
    db.commit()
    return LogoutResponse(status="ok")


@router.get("/me", response_model=UserItem)
async def get_my_account(
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
) -> UserItem:
    """Return the authenticated user's account projection and current roles."""
    return UserItem(
        id=ctx.user.id,
        username=ctx.user.username,
        email=ctx.user.email,
        full_name=ctx.user.full_name,
        status=ctx.user.status,
        admin_mfa_required=ctx.user.admin_mfa_required,
        roles=sorted(ctx.roles),
        last_login_at=ctx.user.last_login_at,
        failed_login_count=ctx.user.failed_login_count,
        locked_at=ctx.user.locked_at,
        created_at=ctx.user.created_at,
    )


@router.get("/sessions", response_model=SessionList)
async def list_sessions(
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
) -> SessionList:
    """
    List current user's sessions.

    - Uses canonical get_current_auth_context() for authentication
    - Returns only sessions belonging to the authenticated user
    - Includes IP, user-agent, expiry, last activity
    - is_current = session.id == ctx.session.id
    """
    # Get all active sessions for this user
    sessions = db.query(Session).filter(
        Session.user_id == ctx.user.id,
        Session.revoked_at.is_(None),
        Session.expires_at > utc_now(),
    ).all()

    session_items = [
        SessionItem(
            id=s.id,
            ip_address=(
                str(s.ip_address.ip_address) if s.ip_address and s.ip_address.ip_address else None
            ),
            user_agent=s.user_agent,
            expires_at=s.expires_at,
            last_activity_at=s.last_activity_at,
            created_at=s.created_at,
            is_current=(s.id == ctx.session.id),
        )
        for s in sessions
    ]

    return SessionList(sessions=session_items, total=len(session_items))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: UUID,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
) -> None:
    """
    Revoke a specific session.

    - Uses canonical get_current_auth_context() for authentication
    - User can only revoke their own sessions
    - Cannot revoke another user's session → 403
    """
    # Find session to revoke
    target_session = db.query(Session).filter(
        Session.id == session_id,
    ).first()

    if not target_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ownership: can only revoke own sessions
    if target_session.user_id != ctx.user.id:
        raise HTTPException(status_code=403, detail="Cannot revoke session of another user")

    target_session.revoked_at = utc_now()
    _audit(
        db,
        action="revoke_session",
        resource="session",
        resource_id=target_session.id,
        actor_id=ctx.user.id,
        actor_type="user",
        after_state={"revoked": True},
    )
    db.commit()


# Import RateLimit here to avoid circular import
from app.models import RateLimit
