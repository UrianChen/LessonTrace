from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, User
from ..security import audit, hash_password, require
from .auth import user_out

router = APIRouter()


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=64)
    role: str = Field(pattern="^(teacher|center|admin)$")
    dept: str = Field(default="", max_length=128)


class UserPatch(BaseModel):
    active: bool


@router.get("/users")
def list_users(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def add_user(body: UserIn, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "That username is already taken")
    u = User(username=body.username, password_hash=hash_password(body.password), name=body.name.strip(),
             role=body.role, dept=body.dept.strip())
    db.add(u)
    db.flush()
    audit(db, request, user.id, "create_user", "user", u.id)
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, request: Request, user: User = Depends(require("admin")),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "user not found")
    if u.id == user.id and not body.active:
        raise HTTPException(409, "You cannot disable your own account")
    u.active = body.active
    audit(db, request, user.id, "enable_user" if body.active else "disable_user", "user", u.id)
    db.commit()
    return user_out(u)


@router.get("/audit-logs")
def audit_logs(user_id: int | None = None, since: datetime | None = None, until: datetime | None = None,
               page: int = 1, size: int = 50, user: User = Depends(require("admin")),
               db: Session = Depends(get_db)):
    """登录和访问日志，可按用户和时间筛选。"""
    size = max(1, min(size, 200))
    q = select(AuditLog)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if since is not None:
        q = q.where(AuditLog.at >= since)
    if until is not None:
        q = q.where(AuditLog.at <= until)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.id.desc()).offset((max(page, 1) - 1) * size).limit(size))
    names = {u.id: u.name for u in db.scalars(select(User))}
    return {"total": total, "items": [
        {"id": a.id, "user_id": a.user_id, "user": names.get(a.user_id), "action": a.action,
         "target_type": a.target_type, "target_id": a.target_id, "ip": a.ip, "at": a.at.isoformat()} for a in rows]}
