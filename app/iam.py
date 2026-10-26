"""Core IAM endpoints owned by the Security Administrator.

The router intentionally covers account read, role assignment, account lock/
unlock, persistent MFA toggling and audit-log read. Account create/edit and
Detection policy administration remain outside this Core IAM milestone.

The shared entrypoint must include this router at `/api/v1/admin`; that
registration is intentionally left to the `app/main.py` owner.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_

from app.authz import AuthContext, require_roles
from app.db import get_db
from app.models import AuditLog, Role, Session, User, UserRole
from app.schemas import (
    AuditLogItem,
    AuditLogList,
    MfaToggleRequest,
    RoleAssignRequest,
    UserItem,
    UserList,
    UserRole as UserRoleEnum,
    UserStatus,
)
from app.time_utils import utc_now

router = APIRouter(prefix="/api/v1/admin", tags=["iam-admin"])

_SPECIAL_ROLES = {"SECURITY_ADMIN", "SOC_ANALYST", "SECURITY_MANAGER"}


def _audit(
    db,
    *,
    ctx: AuthContext,
    action: str,
    resource: str,
    resource_id=None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    reason: Optional[str] = None,
    request: Optional[Request] = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=ctx.user.id,
            actor_type="user",
            action=action,
            resource=resource,
            resource_id=resource_id,
            before_state=before_state,
            after_state=after_state,
            change_reason=reason,
            ip_address=(request.client.host if request and request.client else None),
            user_agent=request.headers.get("User-Agent") if request else None,
        )
    )


def _roles(db, user_id) -> list[str]:
    return [row[0] for row in db.query(UserRole.role_id).filter(UserRole.user_id == user_id).all()]


def _user_item(db, user: User) -> UserItem:
    return UserItem(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        admin_mfa_required=user.admin_mfa_required,
        roles=sorted(_roles(db, user.id)),
        last_login_at=user.last_login_at,
        failed_login_count=user.failed_login_count,
        locked_at=user.locked_at,
        created_at=user.created_at,
    )


def _revoke_sessions(db, user_id) -> int:
    return int(
        db.query(Session)
        .filter(Session.user_id == user_id, Session.revoked_at.is_(None))
        .update({Session.revoked_at: utc_now()}, synchronize_session=False)
        or 0
    )


def _guard_last_active_admin(db, target: User, role_id: str) -> None:
    if role_id != "SECURITY_ADMIN" or target.status != "active":
        return
    count = (
        db.query(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .filter(UserRole.role_id == "SECURITY_ADMIN", User.status == "active")
        .count()
    )
    if count <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove or lock the last active SECURITY_ADMIN",
        )


@router.get("/users", response_model=UserList)
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    role: Optional[UserRoleEnum] = None,
    account_status: Optional[UserStatus] = Query(None, alias="status"),
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_db),
) -> UserList:
    query = db.query(User)
    if role is not None:
        query = query.join(UserRole, UserRole.user_id == User.id).filter(UserRole.role_id == role.value)
    if account_status is not None:
        query = query.filter(User.status == account_status.value)
    total = query.distinct().count()
    users = (
        query.distinct()
        .order_by(User.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return UserList(users=[_user_item(db, user) for user in users], total=total, page=page, limit=limit)


@router.post("/users/{user_id}/roles", response_model=UserItem)
async def assign_role(
    user_id: UUID,
    body: RoleAssignRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_db),
) -> UserItem:
    role_id = body.role.value
    if role_id not in {"USER", *_SPECIAL_ROLES}:
        raise HTTPException(status_code=422, detail="Unsupported role")
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if db.query(Role).filter(Role.id == role_id).first() is None:
        raise HTTPException(status_code=422, detail="Role is not configured")
    before = _roles(db, target.id)
    if role_id not in before:
        db.add(UserRole(user_id=target.id, role_id=role_id, assigned_by=ctx.user.id))
        revoked = _revoke_sessions(db, target.id)
        after = sorted([*before, role_id])
        _audit(
            db,
            ctx=ctx,
            action="assign_role",
            resource="user_role",
            resource_id=target.id,
            before_state={"roles": sorted(before)},
            after_state={"roles": after, "sessions_revoked": revoked},
            request=request,
        )
        db.commit()
    return _user_item(db, target)


@router.delete("/users/{user_id}/roles/{role_id}", response_model=UserItem)
async def revoke_role(
    user_id: UUID,
    role_id: str,
    request: Request,
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_db),
) -> UserItem:
    if role_id == "USER":
        raise HTTPException(status_code=422, detail="The USER base role cannot be removed")
    if role_id not in _SPECIAL_ROLES:
        raise HTTPException(status_code=422, detail="Unsupported role")
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    assignment = db.query(UserRole).filter(UserRole.user_id == target.id, UserRole.role_id == role_id).first()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Role assignment not found")
    _guard_last_active_admin(db, target, role_id)
    before = _roles(db, target.id)
    db.delete(assignment)
    revoked = _revoke_sessions(db, target.id)
    _audit(
        db,
        ctx=ctx,
        action="revoke_role",
        resource="user_role",
        resource_id=target.id,
        before_state={"roles": sorted(before)},
        after_state={"roles": sorted(set(before) - {role_id}), "sessions_revoked": revoked},
        request=request,
    )
    db.commit()
    return _user_item(db, target)


@router.post("/users/{user_id}/lock", response_model=UserItem)
async def lock_user(
    user_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_db),
) -> UserItem:
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.status != "locked":
        _guard_last_active_admin(db, target, "SECURITY_ADMIN")
        before = {"status": target.status, "locked_at": target.locked_at.isoformat() if target.locked_at else None}
        target.status = "locked"
        target.locked_at = utc_now()
        revoked = _revoke_sessions(db, target.id)
        _audit(
            db,
            ctx=ctx,
            action="lock_user",
            resource="user",
            resource_id=target.id,
            before_state=before,
            after_state={"status": target.status, "sessions_revoked": revoked},
            request=request,
        )
        db.commit()
    return _user_item(db, target)


@router.delete("/users/{user_id}/lock", response_model=UserItem)
async def unlock_user(
    user_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_db),
) -> UserItem:
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    before = {"status": target.status, "locked_at": target.locked_at.isoformat() if target.locked_at else None}
    target.status = "active"
    target.locked_at = None
    _audit(
        db,
        ctx=ctx,
        action="unlock_user",
        resource="user",
        resource_id=target.id,
        before_state=before,
        after_state={"status": "active"},
        request=request,
    )
    db.commit()
    return _user_item(db, target)


@router.put("/users/{user_id}/mfa", response_model=UserItem)
async def toggle_mfa(
    user_id: UUID,
    body: MfaToggleRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_db),
) -> UserItem:
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    before = {"admin_mfa_required": target.admin_mfa_required}
    target.admin_mfa_required = body.mfa_required
    revoked = _revoke_sessions(db, target.id)
    _audit(
        db,
        ctx=ctx,
        action="toggle_mfa",
        resource="user",
        resource_id=target.id,
        before_state=before,
        after_state={
            "admin_mfa_required": target.admin_mfa_required,
            "sessions_revoked": revoked,
        },
        request=request,
    )
    db.commit()
    return _user_item(db, target)


@router.get("/audit-logs", response_model=AuditLogList)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    actor: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    from_time: Optional[datetime] = Query(None, alias="from"),
    to_time: Optional[datetime] = Query(None, alias="to"),
    ctx: AuthContext = Depends(require_roles("SECURITY_ADMIN")),
    db=Depends(get_db),
) -> AuditLogList:
    query = db.query(AuditLog)
    if actor:
        actor_user = db.query(User.id).filter(User.username == actor).first()
        actor_id = actor_user[0] if actor_user else None
        query = query.filter(
            or_(
                AuditLog.actor_id == actor_id if actor_id else False,
                AuditLog.actor_type == actor,
            )
        )
    if action:
        query = query.filter(AuditLog.action == action)
    if resource:
        query = query.filter(AuditLog.resource == resource)
    if from_time:
        query = query.filter(AuditLog.created_at >= from_time)
    if to_time:
        query = query.filter(AuditLog.created_at <= to_time)
    total = query.count()
    rows = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    result = []
    for row in rows:
        actor_value = row.actor_type
        if row.actor_id:
            actor_user = db.query(User).filter(User.id == row.actor_id).first()
            actor_value = actor_user.username if actor_user else str(row.actor_id)
        result.append(
            AuditLogItem(
                id=row.id,
                request_id=row.request_id,
                actor=actor_value,
                action=row.action,
                resource=row.resource,
                resource_id=row.resource_id,
                before_state=row.before_state,
                after_state=row.after_state,
                change_reason=row.change_reason,
                ip_address=str(row.ip_address) if row.ip_address else None,
                user_agent=row.user_agent,
                created_at=row.created_at,
            )
        )
    return AuditLogList(logs=result, total=total, page=page, limit=limit)
