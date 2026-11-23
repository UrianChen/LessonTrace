import os
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import queue, storage
from ..config import MAX_VIDEO_BYTES
from ..db import get_db
from ..models import AnalysisRun, Finding, Lesson, Metric, Report, Sentence, User, now
from ..pipeline import stages
from ..security import audit, check_media_token, create_media_token, current_user, require

router = APIRouter()

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
SLIDES_EXT = {".pdf", ".pptx"}
PROCESSING = ("transcribing", "segmenting", "analyzing")


def own_lesson(db: Session, user: User, lesson_id: int) -> Lesson:
    """老师只能访问自己的课。别人的课和不存在的课返回同样的 404。"""
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or user.role != "teacher" or lesson.teacher_id != user.id:
        raise HTTPException(404, "lesson not found")
    return lesson


def queue_position(db: Session, lesson: Lesson) -> int | None:
    """排在前面的课有几节（单机单 GPU，任务排队执行）。"""
    if lesson.queued_at is None or lesson.status not in ("uploaded", *PROCESSING):
        return None
    return db.scalar(select(func.count()).select_from(Lesson).where(
        Lesson.queued_at < lesson.queued_at, Lesson.status.in_(("uploaded", *PROCESSING)))) or 0


def lesson_out(db: Session, lesson: Lesson, detail: bool = False) -> dict:
    out = {
        "id": lesson.id, "title": lesson.title, "taught_on": lesson.taught_on.isoformat(),
        "status": lesson.status, "error": lesson.error, "duration_ms": lesson.duration_ms,
        "has_slides": bool(lesson.slides_key), "created_at": lesson.created_at.isoformat(),
        "started": lesson.queued_at is not None,
    }
    if detail:
        out["queue_position"] = queue_position(db, lesson)
        if lesson.status in ("ready", "confirmed"):
            rows = dict(db.execute(select(Finding.status, func.count()).where(
                Finding.lesson_id == lesson.id).group_by(Finding.status)).all())
            total = sum(rows.values())
            out["progress"] = {"total": total, "processed": total - rows.get("draft", 0)}
            run = db.scalar(select(AnalysisRun).where(AnalysisRun.lesson_id == lesson.id, AnalysisRun.status == "ok")
                            .order_by(AnalysisRun.id.desc()))
            out["skipped_dimensions"] = (run.stats or {}).get("skipped_dimensions", {}) if run else {}
            rep = db.scalar(select(Report).where(Report.lesson_id == lesson.id).order_by(Report.version.desc()))
            out["latest_report_id"] = rep.id if rep else None
    return out


class LessonIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    taught_on: date
    video_filename: str
    video_size: int = Field(gt=0)
    slides_filename: str | None = None


@router.get("/lessons")
def list_lessons(user: User = Depends(require("teacher", "admin")), db: Session = Depends(get_db)):
    if user.role == "admin":
        # 管理员只看任务状态，用于重试失败的任务；看不到课程名称和内容
        rows = db.scalars(select(Lesson).order_by(Lesson.id.desc()).limit(200))
        return [{"id": l.id, "teacher": l.teacher.name, "status": l.status, "error": l.error,
                 "created_at": l.created_at.isoformat()} for l in rows]
    rows = db.scalars(select(Lesson).where(Lesson.teacher_id == user.id).order_by(Lesson.id.desc()))
    return [lesson_out(db, l, detail=True) for l in rows]


@router.post("/lessons", status_code=201)
def create_lesson(body: LessonIn, request: Request, user: User = Depends(require("teacher")),
                  db: Session = Depends(get_db)):
    vext = os.path.splitext(body.video_filename)[1].lower()
    if vext not in VIDEO_EXT:
        raise HTTPException(422, f"Unsupported video format. Use one of: {', '.join(sorted(VIDEO_EXT))}")
    if body.video_size > MAX_VIDEO_BYTES:
        raise HTTPException(422, "The recording must be 4 GB or smaller")
    sext = None
    if body.slides_filename:
        sext = os.path.splitext(body.slides_filename)[1].lower()
        if sext not in SLIDES_EXT:
            raise HTTPException(422, "Slides must be a PDF or PPTX file")
    lesson = Lesson(teacher_id=user.id, title=body.title.strip(), taught_on=body.taught_on, status="uploaded")
    db.add(lesson)
    db.flush()
    prefix = storage.lesson_prefix(lesson.id)
    lesson.video_key = f"{prefix}video{vext}"
    lesson.slides_key = f"{prefix}slides{sext}" if sext else None
    audit(db, request, user.id, "create_lesson", "lesson", lesson.id)
    db.commit()
    return {
        "lesson": lesson_out(db, lesson),
        "upload": {"video_url": storage.presign_put(lesson.video_key),
                   "slides_url": storage.presign_put(lesson.slides_key) if lesson.slides_key else None},
    }


@router.post("/lessons/{lesson_id}/start")
def start_lesson(lesson_id: int, user: User = Depends(require("teacher")), db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    if lesson.status != "uploaded" or lesson.queued_at is not None:
        raise HTTPException(409, "Processing has already started")
    size = storage.size_of(lesson.video_key)
    if size is None:
        raise HTTPException(409, "The recording has not finished uploading")
    if size > MAX_VIDEO_BYTES:
        raise HTTPException(422, "The recording must be 4 GB or smaller")
    if lesson.slides_key and storage.size_of(lesson.slides_key) is None:
        raise HTTPException(409, "The slides have not finished uploading")
    lesson.queued_at = now()
    db.commit()
    _dispatch(db, lesson, "transcribing", revert=lambda: setattr(lesson, "queued_at", None))
    return lesson_out(db, lesson, detail=True)


def _dispatch(db: Session, lesson: Lesson, stage: str, revert):
    try:
        queue.dispatch(lesson.id, stage)
    except Exception:
        revert()
        db.commit()
        raise HTTPException(503, "The task queue is unavailable. Try again shortly.")


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: int, user: User = Depends(require("teacher")), db: Session = Depends(get_db)):
    return lesson_out(db, own_lesson(db, user, lesson_id), detail=True)


@router.post("/lessons/{lesson_id}/retry")
def retry_lesson(lesson_id: int, request: Request, user: User = Depends(require("teacher", "admin")),
                 db: Session = Depends(get_db)):
    """从失败的阶段重新开始，前面阶段的结果保留。老师或管理员都可以点。"""
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or (user.role == "teacher" and lesson.teacher_id != user.id):
        raise HTTPException(404, "lesson not found")
    if lesson.status != "failed" or not lesson.error:
        raise HTTPException(409, "Only a failed lesson can be retried")
    error = lesson.error
    stage = error["stage"]
    lesson.status, lesson.error, lesson.queued_at = stage, None, now()
    audit(db, request, user.id, "retry_lesson", "lesson", lesson.id)
    db.commit()

    def revert():
        lesson.status, lesson.error = "failed", error
    _dispatch(db, lesson, stage, revert)
    return {"id": lesson.id, "status": lesson.status}


@router.post("/lessons/{lesson_id}/reanalyze")
def reanalyze(lesson_id: int, request: Request, user: User = Depends(require("teacher")),
              db: Session = Depends(get_db)):
    """老师修正文字稿后重新分析：待审阅 → 分析与校验中。已处理的条目保留，只替换草稿。"""
    lesson = own_lesson(db, user, lesson_id)
    if lesson.status != "ready":
        raise HTTPException(409, "Only a lesson that is ready for review can be re-analyzed")
    stages.store_metrics(db, lesson.id)   # 说话人或文字改过，统计跟着重算
    lesson.status, lesson.queued_at = "analyzing", now()
    audit(db, request, user.id, "reanalyze_lesson", "lesson", lesson.id)
    db.commit()
    _dispatch(db, lesson, "analyzing", revert=lambda: setattr(lesson, "status", "ready"))
    return lesson_out(db, lesson, detail=True)


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, request: Request, user: User = Depends(require("teacher")),
                  db: Session = Depends(get_db)):
    """删除课程：级联删除全部记录和对象存储里的文件。"""
    lesson = own_lesson(db, user, lesson_id)
    storage.delete_prefix(storage.lesson_prefix(lesson.id))
    db.execute(delete(Lesson).where(Lesson.id == lesson.id))
    audit(db, request, user.id, "delete_lesson", "lesson", lesson_id)
    db.commit()
    return Response(status_code=204)


@router.get("/lessons/{lesson_id}/video")
def video_url(lesson_id: int, user: User = Depends(require("teacher")), db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    if lesson.status not in ("ready", "confirmed", "segmenting", "analyzing"):
        raise HTTPException(409, "The recording is still being processed")
    from ..config import get_settings
    return {"url": f"/api/lessons/{lesson.id}/hls/index.m3u8?token={create_media_token(lesson.id)}",
            "expires_in": get_settings().signed_url_ttl}


@router.get("/lessons/{lesson_id}/hls/index.m3u8")
def hls_playlist(lesson_id: int, token: str):
    """播放列表。每个分片换成对象存储的短期签名地址；播放器带不了登录令牌，所以用播放令牌。"""
    check_media_token(token, lesson_id)
    prefix = storage.lesson_prefix(lesson_id) + "hls/"
    try:
        text = storage.get_bytes(prefix + "index.m3u8").decode()
    except Exception:
        raise HTTPException(404, "playlist not found")
    lines = [storage.presign_get(prefix + ln.strip()) if ln.strip() and not ln.startswith("#") else ln
             for ln in text.splitlines()]
    return Response("\n".join(lines) + "\n", media_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-store"})


@router.get("/lessons/{lesson_id}/transcript")
def transcript(lesson_id: int, request: Request, user: User = Depends(require("teacher")),
               db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    audit(db, request, user.id, "view_lesson", "lesson", lesson.id)
    db.commit()
    return [{"id": s.id, "idx": s.idx, "start_ms": s.start_ms, "end_ms": s.end_ms,
             "speaker": s.speaker, "text": s.text} for s in stages.get_sentences(db, lesson.id)]


class SentencePatch(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    speaker: str | None = Field(default=None, pattern="^(teacher|student|unknown)$")


@router.patch("/sentences/{sentence_id}")
def patch_sentence(sentence_id: int, body: SentencePatch, user: User = Depends(require("teacher")),
                   db: Session = Depends(get_db)):
    s = db.get(Sentence, sentence_id)
    if s is None:
        raise HTTPException(404, "sentence not found")
    lesson = own_lesson(db, user, s.lesson_id)
    if lesson.status not in ("ready", "confirmed"):
        raise HTTPException(409, "The transcript can be corrected once processing has finished")
    if body.text is not None:
        s.text = body.text.strip()
    if body.speaker is not None:
        s.speaker = body.speaker
    db.flush()
    stages.store_metrics(db, lesson.id)
    db.commit()
    return {"id": s.id, "idx": s.idx, "start_ms": s.start_ms, "end_ms": s.end_ms, "speaker": s.speaker, "text": s.text}


@router.get("/lessons/{lesson_id}/segments")
def segments(lesson_id: int, user: User = Depends(require("teacher")), db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    pages = {s.id: s.page_no for s in stages.get_slides(db, lesson.id)}
    return [{"id": g.code, "start_ms": g.start_ms, "end_ms": g.end_ms, "title": g.title,
             "slide_page": pages.get(g.slide_id), "sentence_from": g.sentence_from, "sentence_to": g.sentence_to}
            for g in stages.get_segments(db, lesson.id)]


@router.get("/lessons/{lesson_id}/metrics")
def metrics(lesson_id: int, user: User = Depends(require("teacher")), db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    return lesson_metrics(db, lesson.id)


def lesson_metrics(db: Session, lesson_id: int) -> dict:
    codes = {g.id: g.code for g in stages.get_segments(db, lesson_id)}
    out = {"lesson": {}, "segments": {}, "note": "Student speech may be under-recorded: classroom audio mostly captures the teacher."}
    for m in db.scalars(select(Metric).where(Metric.lesson_id == lesson_id)):
        if m.segment_id is None:
            out["lesson"][m.key] = m.value
        else:
            out["segments"].setdefault(codes.get(m.segment_id, "?"), {})[m.key] = m.value
    return out
