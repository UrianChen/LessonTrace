from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_Session = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(get_settings().db_url, pool_pre_ping=True)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def SessionLocal():
    get_engine()
    return _Session()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
