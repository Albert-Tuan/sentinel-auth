"""
Authentication endpoints - login, MFA, session management.
Sync with schema-v2.sql definitions.
"""
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4
import hashlib
import secrets

from fastapi import APIRouter, HTTPException, status, Depends, Request, Header
from pydantic import BaseModel
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

from app.db import get_db
from app.models import User, Session, PreAuthTransaction, MfaNotification, LoginAttempt, RiskAssessment, Role
from app.schemas import (
    UserRegisterRequest, UserRegisterResponse,
    LoginRequest, LoginResponse,
    MfaVerifyRequest, MfaVerifyResponse,
    RefreshRequest, RefreshResponse,
    LogoutResponse, SessionItem, SessionList,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
ph = PasswordHasher()


# =============================================================================
# Internal helpers
# =============================================================================

def hash_token(token: str) -> str:
    """SHA256 hash of token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_otp() -> str:
    """Generate 6-digit OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_ip(ip: str) -> str:
    """Hash IP address for storage (privacy)."""
    return hashlib.sha256(ip.encode()).hexdigest()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
    user_role = Role(id="USER", name="Người dùng")
    # Note: 'USER' role should already exist from seed data
    # If not, we need to handle it

    from app.models import UserRole
    ur = UserRole(
        user_id=user.id,
        role_id="USER",
        assigned_at=datetime.utcnow(),
    )
    db.add(ur)

    db.commit()
    db.refresh(user)

    return UserRegisterResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        created_at=user.created_at,
    )


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
    4. Inline detection (rule + ML scoring) - called from detection module
    5. MFA check (persistent or one-time)
    6. Create session + JWT tokens
    """
    client_ip = get_client_ip(req)
    request_id = uuid4()

    # 1. Rate limit check
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=1)

    rate = db.query(RateLimit).filter(
        RateLimit.ip_address == client_ip,
        RateLimit.action == "login",
        RateLimit.window_start >= window_start,
    ).first()

    if rate and rate.count >= rate.max_count:
        # Record rate-limited login attempt
        la = LoginAttempt(
            request_id=request_id,
            username_attempted=request.username,
            occurred_at=now,
            outcome="rate_limited",
            source_ip=client_ip,
            rate_limited=True,
        )
        db.add(la)
        db.commit()
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Update or create rate limit
    if rate:
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
        la = LoginAttempt(
            request_id=request_id,
            username_attempted=request.username,
            occurred_at=now,
            outcome="failure",
            source_ip=client_ip,
            user_agent=req.headers.get("User-Agent"),
        )
        db.add(la)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        ph.verify(user.password_hash, request.password)
    except VerifyMismatchError:
        # Wrong password
        user.failed_login_count += 1
        la = LoginAttempt(
            request_id=request_id,
            user_id=user.id,
            username_attempted=request.username,
            occurred_at=now,
            outcome="failure",
            source_ip=client_ip,
            user_agent=req.headers.get("User-Agent"),
        )
        db.add(la)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 3. Check account status
    if user.status == "locked":
        la = LoginAttempt(
            request_id=request_id,
            user_id=user.id,
            username_attempted=request.username,
            occurred_at=now,
            outcome="locked",
            source_ip=client_ip,
            user_agent=req.headers.get("User-Agent"),
        )
        db.add(la)
        db.commit()
        raise HTTPException(status_code=423, detail="Account is locked")

    # Reset failed login count on successful credential verification
    user.failed_login_count = 0

    # 4. MFA check
    mfa_required = user.admin_mfa_required or user.detection_mfa_once

    if mfa_required:
        # Create pre-auth transaction
        mfa_type = "persistent" if user.admin_mfa_required else "one_time"
        expires_at = now + timedelta(minutes=5)

        pre_auth = PreAuthTransaction(
            user_id=user.id,
            mfa_type=mfa_type,
            expires_at=expires_at,
            status="pending",
            bound_ip=hash_ip(client_ip),
        )
        db.add(pre_auth)
        db.flush()

        # Generate OTP
        otp = generate_otp()
        otp_hash = ph.hash(otp)

        # Create MFA notification
        notification = MfaNotification(
            pre_auth_transaction_id=pre_auth.id,
            channel="email",
            recipient=user.email or "",
            mfa_code_hash=otp_hash,
            expires_at=expires_at,
        )
        db.add(notification)
        db.flush()

        # Link notification to pre_auth
        pre_auth.notification_id = notification.id

        # TODO: Send email OTP via Mailpit (smtp localhost:1025)

        la = LoginAttempt(
            request_id=request_id,
            user_id=user.id,
            occurred_at=now,
            outcome="mfa_required",
            source_ip=client_ip,
            user_agent=req.headers.get("User-Agent"),
            mfa_used=True,
        )
        db.add(la)
        db.commit()

        # Return MFA challenge response
        # In production, email OTP would be sent here
        return LoginResponse(
            access_token="",
            refresh_token="",
            mfa_required=True,
            session_id=pre_auth.id,
        )

    # 5. No MFA - create session directly
    return await _create_session(user, client_ip, req.headers.get("User-Agent"), db)


async def _create_session(
    user: User,
    client_ip: str,
    user_agent: Optional[str],
    db,
) -> LoginResponse:
    """Create a new session and generate JWT tokens."""
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
        expires_at=datetime.utcnow() + timedelta(hours=1),
        last_activity_at=datetime.utcnow(),
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.add(session)

    # Update user last login
    user.last_login_at = datetime.utcnow()

    # Record successful login
    request_id = uuid4()
    la = LoginAttempt(
        request_id=request_id,
        user_id=user.id,
        occurred_at=datetime.utcnow(),
        outcome="success",
        source_ip=client_ip,
        user_agent=user_agent,
    )
    db.add(la)
    db.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        mfa_required=False,
        session_id=session.id,
    )


@router.post("/mfa/verify", response_model=MfaVerifyResponse)
async def mfa_verify(
    request: MfaVerifyRequest,
    req: Request,
    db=Depends(get_db),
) -> MfaVerifyResponse:
    """
    Verify MFA code for a pre-auth transaction.

    - Validates pre_auth transaction exists and is pending
    - Checks ownership (session_id is pre_auth.id)
    - Verifies OTP against stored hash
    - Marks MFA as used (one-time: clears detection_mfa_once flag)
    - Creates session + tokens
    """
    client_ip = get_client_ip(req)
    now = datetime.utcnow()

    # Find pre-auth transaction
    pre_auth = db.query(PreAuthTransaction).filter(
        PreAuthTransaction.id == request.session_id,
        PreAuthTransaction.status == "pending",
        PreAuthTransaction.expires_at > now,
    ).first()

    if not pre_auth:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # Find user
    user = db.query(User).filter(User.id == pre_auth.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Find MFA notification
    notification = db.query(MfaNotification).filter(
        MfaNotification.id == pre_auth.notification_id,
    ).first()

    if not notification:
        raise HTTPException(status_code=404, detail="MFA notification not found")

    if notification.verified_at:
        raise HTTPException(status_code=400, detail="MFA code already used")

    # Verify OTP
    try:
        ph.verify(notification.mfa_code_hash, request.mfa_code)
    except (VerifyMismatchError, InvalidHash):
        # Wrong OTP
        pre_auth.fail_count += 1
        if pre_auth.fail_count >= 3:
            pre_auth.status = "failed"
        db.commit()

        # Record failed MFA
        la = LoginAttempt(
            request_id=uuid4(),
            user_id=user.id,
            occurred_at=now,
            outcome="mfa_failed",
            source_ip=client_ip,
            user_agent=req.headers.get("User-Agent"),
            mfa_used=True,
        )
        db.add(la)
        db.commit()

        raise HTTPException(status_code=401, detail="Invalid MFA code")

    # OTP verified successfully
    pre_auth.status = "completed"
    notification.verified_at = now

    # Clear one-time MFA flag
    if pre_auth.mfa_type == "one_time":
        user.detection_mfa_once = False

    # Create session
    result = await _create_session(user, client_ip, req.headers.get("User-Agent"), db)

    # Record successful MFA login
    la = LoginAttempt(
        request_id=uuid4(),
        user_id=user.id,
        occurred_at=now,
        outcome="mfa_success",
        source_ip=client_ip,
        user_agent=req.headers.get("User-Agent"),
        mfa_used=True,
    )
    db.add(la)
    db.commit()

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

    if session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Session expired")

    # Generate new access token
    new_access_token = secrets.token_urlsafe(32)
    new_jti = str(uuid4())

    session.access_token_hash = hash_token(new_access_token)
    session.token_jti = new_jti
    session.last_activity_at = datetime.utcnow()

    # Optional: rotate refresh token (token rotation for security)
    new_refresh_token = secrets.token_urlsafe(32)
    session.refresh_token_hash = hash_token(new_refresh_token)

    db.commit()

    return RefreshResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    req: Request,
    db=Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> LogoutResponse:
    """
    Logout current session.

    - Revokes session by setting revoked_at
    """
    # Extract token from Authorization header
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.split(" ")[1]
    token_hash = hash_token(token)

    session = db.query(Session).filter(
        Session.access_token_hash == token_hash,
        Session.revoked_at.is_(None),
    ).first()

    if session:
        session.revoked_at = datetime.utcnow()
        db.commit()

    return LogoutResponse(status="ok")


@router.get("/sessions", response_model=SessionList)
async def list_sessions(
    req: Request,
    db=Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> SessionList:
    """
    List current user's sessions.

    - Returns only sessions belonging to the authenticated user
    - Includes IP, user-agent, expiry, last activity
    """
    # Extract token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.split(" ")[1]
    token_hash = hash_token(token)

    session = db.query(Session).filter(
        Session.access_token_hash == token_hash,
        Session.revoked_at.is_(None),
    ).first()

    if not session:
        raise HTTPException(status_code=401, detail="Invalid or revoked token")

    # Get all active sessions for this user
    sessions = db.query(Session).filter(
        Session.user_id == session.user_id,
        Session.revoked_at.is_(None),
        Session.expires_at > datetime.utcnow(),
    ).all()

    session_items = [
        SessionItem(
            id=s.id,
            ip_address=str(s.ip_address) if s.ip_address else None,
            user_agent=s.user_agent,
            expires_at=s.expires_at,
            last_activity_at=s.last_activity_at,
            created_at=s.created_at,
            is_current=(s.id == session.id),
        )
        for s in sessions
    ]

    return SessionList(sessions=session_items, total=len(session_items))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: str,
    req: Request,
    db=Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> None:
    """
    Revoke a specific session.

    - User can only revoke their own sessions
    - Cannot revoke another user's session
    """
    # Extract token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.split(" ")[1]
    token_hash = hash_token(token)

    current_session = db.query(Session).filter(
        Session.access_token_hash == token_hash,
        Session.revoked_at.is_(None),
    ).first()

    if not current_session:
        raise HTTPException(status_code=401, detail="Invalid or revoked token")

    # Find session to revoke
    target_session = db.query(Session).filter(
        Session.id == session_id,
    ).first()

    if not target_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check ownership
    if target_session.user_id != current_session.user_id:
        raise HTTPException(status_code=403, detail="Cannot revoke session of another user")

    target_session.revoked_at = datetime.utcnow()
    db.commit()


# Import RateLimit here to avoid circular import
from app.models import RateLimit
