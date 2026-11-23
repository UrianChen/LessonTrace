from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, User


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def _encode(payload: dict, ttl: timedelta) -> str:
    payload = {**payload, "exp": datetime.now(timezone.utc) + ttl}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")


def create_token(user: User) -> str:
    return _encode({"sub": str(user.id), "typ": "login"}, timedelta(hours=get_settings().jwt_ttl_hours))


def create_media_token(lesson_id: int) -> str:
    """播放用的短期令牌，只对一节课的播放列表有效。"""
    return _encode({"lesson": lesson_id, "typ": "media"}, timedelta(seconds=get_settings().signed_url_ttl))


def check_media_token(token: str, lesson_id: int):
    data = _decode(token)
    if data.get("typ") != "media" or data.get("lesson") != lesson_id:
        raise HTTPException(401, "invalid or expired token")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "not authenticated")
    data = _decode(auth[7:])
    if data.get("typ") != "login":
        raise HTTPException(401, "invalid or expired token")
    user = db.get(User, int(data["sub"]))
    if user is None or not user.active:
        raise HTTPException(401, "account is disabled")
    return user


def require(*roles: str):
    """按角色校验。校验做在服务端每个接口上，不依赖前端隐藏按钮。"""
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "not allowed for this role")
        return user
    return dep


def client_ip(request: Request) -> str | None:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


def audit(db: Session, request: Request, user_id: int | None, action: str,
          target_type: str | None = None, target_id=None):
    """写审计日志（只增不改）。调用方负责 commit。"""
    db.add(AuditLog(user_id=user_id, action=action, target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None, ip=client_ip(request)))
