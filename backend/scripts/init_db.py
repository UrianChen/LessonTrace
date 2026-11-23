"""初始化：建表、建存储桶，为三种角色各创建一个账号。可重复执行。

    python -m scripts.init_db

口令取自 .env 的 INIT_TEACHER_PASSWORD / INIT_CENTER_PASSWORD / INIT_ADMIN_PASSWORD；
没填就随机生成并打印一次（只在账号被创建的那一次）。
"""
import secrets
import time

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import storage
from app.config import get_settings
from app.db import Base, SessionLocal, get_engine
from app.models import User
from app.security import hash_password

ACCOUNTS = [
    ("teacher", "teacher", "Sample Teacher", "Mathematics", "init_teacher_password"),
    ("center", "center", "Teaching Center", "Teaching Center", "init_center_password"),
    ("admin", "admin", "Administrator", "", "init_admin_password"),
]


def main():
    engine = get_engine()
    for attempt in range(30):
        try:
            Base.metadata.create_all(engine)
            break
        except OperationalError:
            if attempt == 29:
                raise
            time.sleep(2)
    for attempt in range(30):
        try:
            storage.ensure_bucket()
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(2)

    s = get_settings()
    db = SessionLocal()
    try:
        for username, role, name, dept, field in ACCOUNTS:
            if db.scalar(select(User).where(User.username == username)):
                continue
            password = getattr(s, field)
            generated = not password
            if generated:
                password = secrets.token_urlsafe(12)
            db.add(User(username=username, password_hash=hash_password(password), name=name, role=role, dept=dept))
            db.commit()
            if generated:
                print(f"[init] created account '{username}' with generated password: {password}", flush=True)
            else:
                print(f"[init] created account '{username}' (password from .env)", flush=True)
    finally:
        db.close()
    print("[init] database and storage are ready", flush=True)


if __name__ == "__main__":
    main()
