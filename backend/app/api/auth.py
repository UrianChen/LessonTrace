from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import audit, create_token, current_user, verify_password

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role, "dept": u.dept, "active": u.active}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    ok = user is not None and user.active and verify_password(body.password, user.password_hash)
    # 失败的尝试也记录；用户名不存在时 user_id 为空，尝试的用户名记在 target_id
    audit(db, request, user.id if user else None, "login" if ok else "login_failed", "user", body.username.strip()[:64])
    db.commit()
    if not ok:
        raise HTTPException(401, "Wrong username or password, or the account is disabled")
    return {"token": create_token(user), "user": user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
