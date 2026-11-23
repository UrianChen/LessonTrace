import json
import os
from datetime import date

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-0123"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import queue, storage
from app.db import Base
from app.main import app
from app.models import Lesson, Sentence, User
from app.security import create_token, hash_password


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    app_db._engine = engine
    app_db._Session = sessionmaker(engine, expire_on_commit=False)
    session = app_db.SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def dispatched(monkeypatch):
    """记录被放进队列的阶段任务，不真的连 Redis。"""
    calls = []
    monkeypatch.setattr(queue, "dispatch", lambda lesson_id, stage: calls.append((lesson_id, stage)))
    return calls


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    objects = {}
    monkeypatch.setattr(storage, "presign_put", lambda key, expires=0: f"http://localhost/bucket/{key}?sig=put")
    monkeypatch.setattr(storage, "presign_get", lambda key, expires=None, filename=None: f"http://localhost/bucket/{key}?sig=get")
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, ctype: objects.__setitem__(key, data))
    monkeypatch.setattr(storage, "get_bytes", lambda key: objects[key])
    monkeypatch.setattr(storage, "size_of", lambda key: len(objects[key]) if key in objects else None)

    def delete_prefix(prefix):
        for k in [k for k in objects if k.startswith(prefix)]:
            del objects[k]
    monkeypatch.setattr(storage, "delete_prefix", delete_prefix)
    return objects


@pytest.fixture()
def users(db):
    out = {}
    for username, role in [("t1", "teacher"), ("t2", "teacher"), ("center", "center"), ("admin", "admin")]:
        u = User(username=username, password_hash=hash_password("password-1"), name=username.upper(), role=role)
        db.add(u)
        out[username] = u
    db.commit()
    return out


@pytest.fixture()
def client(db):
    return TestClient(app)


def auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


# 一节很短的课：老师讲两段，中间有一次师生问答
TRANSCRIPT = [
    ("teacher", 0, 4000, "Good morning everyone, today we are going to talk about limits."),
    ("teacher", 4200, 9000, "A limit describes the value a function approaches as the input approaches some point."),
    ("teacher", 9500, 15000, "Let us look at the function sine x over x near zero."),
    ("teacher", 15500, 21000, "If we plug in smaller and smaller values, the ratio gets closer and closer to one."),
    ("teacher", 21500, 31000, "We can see that in the table on this slide, where each row is a smaller value of x."),
    ("teacher", 34000, 37000, "So what does this limit equal?"),
    ("teacher", 37200, 39000, "Right, it equals one."),
    ("teacher", 39500, 47000, "Now let us move on to one sided limits, which approach from the left or from the right."),
    ("student", 48000, 52000, "Is the left limit always the same as the right limit?"),
    ("teacher", 52500, 60000, "Good question, no, they can be different, and then the two sided limit does not exist."),
    ("teacher", 60500, 70000, "For example the step function jumps at zero, so the left limit is zero and the right limit is one."),
]


def make_lesson(db, teacher: User, status="uploaded", with_transcript=False) -> Lesson:
    lesson = Lesson(teacher_id=teacher.id, title="Limits", taught_on=date(2026, 11, 2), status=status,
                    video_key="x", slides_key=None)
    db.add(lesson)
    db.flush()
    lesson.video_key = f"lessons/{lesson.id}/video.mp4"
    if with_transcript:
        for i, (sp, a, b, text) in enumerate(TRANSCRIPT):
            db.add(Sentence(lesson_id=lesson.id, idx=i, start_ms=a, end_ms=b, speaker=sp, text=text))
    db.commit()
    return lesson


class FakeLLM:
    """按顺序返回预设输出的假模型。outputs 里可以放字符串、dict 或异常。"""
    model = "fake-model"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append(user)
        if not self.outputs:
            raise AssertionError("FakeLLM ran out of outputs")
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, str) else json.dumps(out)


def finding(dimension="Questioning and interaction", observation="The teacher answered the question right away.",
            suggestion="Pause for a few seconds after asking.", evidence=None):
    return {"dimension": dimension, "observation": observation, "suggestion": suggestion,
            "evidence": evidence if evidence is not None else [
                {"segment_id": "S001", "quote": "So what does this limit equal?"}]}
