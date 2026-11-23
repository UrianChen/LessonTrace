"""数据模型（设计方案第 5 节）。

约定：所有时间用毫秒整数；findings 没有任何分数字段；
证据的时间永远从 segments 查，不存模型给的时间。
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Json = JSON().with_variant(JSONB, "postgresql")
PK = BigInteger().with_variant(Integer, "sqlite")


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))  # teacher / center / admin
    dept: Mapped[str] = mapped_column(String(128), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    taught_on: Mapped[date] = mapped_column(Date)
    video_key: Mapped[str | None] = mapped_column(String(300))
    slides_key: Mapped[str | None] = mapped_column(String(300))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="uploaded", index=True)
    error: Mapped[dict | None] = mapped_column(Json)  # {"stage": ..., "reason": ...}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    teacher: Mapped[User] = relationship()


class Sentence(Base):
    __tablename__ = "sentences"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(16))  # teacher / student / unknown
    text: Mapped[str] = mapped_column(Text)


class Slide(Base):
    __tablename__ = "slides"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    start_ms: Mapped[int | None] = mapped_column(Integer)  # 未对齐时为空
    end_ms: Mapped[int | None] = mapped_column(Integer)


class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(8))  # S012，模型引用的 ID
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    slide_id: Mapped[int | None] = mapped_column(ForeignKey("slides.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), default="")
    sentence_from: Mapped[int] = mapped_column(Integer)  # 句子 idx，闭区间
    sentence_to: Mapped[int] = mapped_column(Integer)


class Metric(Base):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict | list | float | int | None] = mapped_column(Json)
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(32))
    raw_output: Mapped[list | dict | None] = mapped_column(Json)
    stats: Mapped[dict | None] = mapped_column(Json)
    status: Mapped[str] = mapped_column(String(16))  # ok / failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"))
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    dimension: Mapped[str] = mapped_column(String(100))
    observation: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/accepted/edited/rejected
    source: Mapped[str] = mapped_column(String(16), default="model")  # model / teacher

    evidence: Mapped[list["FindingEvidence"]] = relationship(
        cascade="all, delete-orphan", order_by="FindingEvidence.id", passive_deletes=True
    )


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"))
    quote: Mapped[str] = mapped_column(Text)


class ReviewAction(Base):
    """老师的每次操作，只增不改。"""
    __tablename__ = "review_actions"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16))
    before: Mapped[dict | None] = mapped_column(Json)
    after: Mapped[dict | None] = mapped_column(Json)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(Json)  # 生成时的快照
    pdf_key: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 空 = 未提交

    lesson: Mapped[Lesson] = relationship()


class AuditLog(Base):
    """只增不改。删除课程后日志仍保留，所以 target 不设外键。"""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(32))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
