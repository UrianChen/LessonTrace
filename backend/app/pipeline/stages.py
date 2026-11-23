"""三个处理阶段和状态机（设计方案第 6 节）。

一阶段一任务；阶段开始先清掉本阶段旧产物再重算（幂等）；
产物写入数据库后才更新状态。模块之间只通过数据库记录交接。
"""
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..analysis import runner
from ..analysis.llm import LLMConfigError, LLMError, get_llm
from ..analysis.validator import Seg, SegSentence
from ..config import load_dimensions
from ..models import (AnalysisRun, Finding, FindingEvidence, Lesson, Metric, Segment,
                      Sentence, Slide)
from . import media
from .media import PermanentError
from .metrics import compute_metrics, summary_for_model
from .segmenter import code_for, segment
from .slides import align_slides
from .speakers import label_speakers

STAGES = ("transcribing", "segmenting", "analyzing")
NEXT = {"transcribing": "segmenting", "segmenting": "analyzing", "analyzing": "ready"}


# ---------- 读取 ----------

def get_sentences(db: Session, lesson_id: int) -> list[Sentence]:
    return list(db.scalars(select(Sentence).where(Sentence.lesson_id == lesson_id).order_by(Sentence.idx)))


def get_segments(db: Session, lesson_id: int) -> list[Segment]:
    return list(db.scalars(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.start_ms)))


def get_slides(db: Session, lesson_id: int) -> list[Slide]:
    return list(db.scalars(select(Slide).where(Slide.lesson_id == lesson_id).order_by(Slide.page_no)))


def load_segs(db: Session, lesson_id: int) -> list[Seg]:
    """把片段表和句子表拼成校验/分析用的结构。片段文本始终取自当前的句子。"""
    sentences = get_sentences(db, lesson_id)
    pages = {s.id: s.page_no for s in get_slides(db, lesson_id)}
    out = []
    for g in get_segments(db, lesson_id):
        out.append(Seg(
            code=g.code, start_ms=g.start_ms, end_ms=g.end_ms, db_id=g.id, page_no=pages.get(g.slide_id),
            sentences=[SegSentence(s.idx, s.start_ms, s.end_ms, s.speaker, s.text)
                       for s in sentences[g.sentence_from:g.sentence_to + 1]],
        ))
    return out


# ---------- 阶段 1：转写 ----------

def transcribe_stage(db: Session, lesson: Lesson):
    db.execute(delete(Sentence).where(Sentence.lesson_id == lesson.id))
    duration_ms, raw = media.process_media(lesson.id, lesson.video_key, lesson.slides_key)
    raw = [s for s in raw if s.get("text", "").strip()]
    if not raw:
        raise PermanentError("no speech was recognised in the recording")
    raw.sort(key=lambda s: s["start_ms"])
    for i, s in enumerate(label_speakers(raw)):
        db.add(Sentence(lesson_id=lesson.id, idx=i, start_ms=int(s["start_ms"]), end_ms=int(s["end_ms"]),
                        speaker=s["speaker"], text=s["text"].strip()))
    lesson.duration_ms = duration_ms


# ---------- 阶段 2：对齐、切分、统计 ----------

def store_metrics(db: Session, lesson_id: int):
    db.execute(delete(Metric).where(Metric.lesson_id == lesson_id))
    segs = get_segments(db, lesson_id)
    for key, value, gi in compute_metrics(get_sentences(db, lesson_id), segs, get_slides(db, lesson_id)):
        db.add(Metric(lesson_id=lesson_id, key=key, value=value,
                      segment_id=segs[gi].id if gi is not None else None))


def segment_stage(db: Session, lesson: Lesson):
    # 片段是后面一切的基础，重算时依赖它的条目一并清掉
    db.execute(delete(Finding).where(Finding.lesson_id == lesson.id))
    db.execute(delete(Metric).where(Metric.lesson_id == lesson.id))
    db.execute(delete(Segment).where(Segment.lesson_id == lesson.id))
    db.execute(delete(Slide).where(Slide.lesson_id == lesson.id))

    sentences = get_sentences(db, lesson.id)
    pages = media.load_slide_pages(lesson.slides_key)
    spans = align_slides(pages, sentences)
    slides = []
    for i, text in enumerate(pages):
        sl = Slide(lesson_id=lesson.id, page_no=i + 1, text=text,
                   start_ms=spans[i][0] if spans[i] else None, end_ms=spans[i][1] if spans[i] else None)
        db.add(sl)
        slides.append(sl)
    db.flush()

    for i, p in enumerate(segment(sentences, spans)):
        db.add(Segment(lesson_id=lesson.id, code=code_for(i), start_ms=p.start_ms, end_ms=p.end_ms,
                       slide_id=slides[p.page_idx].id if p.page_idx is not None else None,
                       sentence_from=p.first, sentence_to=p.last))
    db.flush()

    # 标题由大模型生成，只用于界面展示；模型不可用不影响本阶段
    try:
        titles = runner.generate_titles(get_llm(), load_segs(db, lesson.id))
    except LLMError:
        titles = {}
    for g in get_segments(db, lesson.id):
        g.title = titles.get(g.code, "")
    db.flush()
    store_metrics(db, lesson.id)


# ---------- 阶段 3：分析、校验 ----------

def analyze_stage(db: Session, lesson: Lesson):
    # 只替换未处理的草稿；已采纳、修改、删除过的和老师自己写的都保留
    db.execute(delete(Finding).where(Finding.lesson_id == lesson.id, Finding.status == "draft",
                                     Finding.source == "model"))
    db.flush()
    segs = load_segs(db, lesson.id)
    by_page: dict[int, list[str]] = {}
    for g in segs:
        if g.page_no:
            by_page.setdefault(g.page_no, []).append(g.code)
    slides = [{"page_no": s.page_no, "text": s.text,
               "segments": by_page.get(s.page_no, []) if s.start_ms is not None else []}
              for s in get_slides(db, lesson.id)]
    rows = db.execute(select(Metric.key, Metric.value, Metric.segment_id).where(Metric.lesson_id == lesson.id)).all()
    metrics = summary_for_model([(k, v, sid) for k, v, sid in rows])

    llm = get_llm()
    try:
        result = runner.run_analysis(llm, segs, slides, metrics, load_dimensions())
    except LLMError as e:
        _record_failed_run(lesson.id, llm.model, str(e))
        raise

    run = AnalysisRun(lesson_id=lesson.id, model=result.model, prompt_version=result.prompt_version,
                      raw_output=result.raw_output, stats=result.stats, status="ok")
    db.add(run)
    db.flush()

    seg_ids = {g.code: g.db_id for g in segs}
    kept = set()
    for f in db.scalars(select(Finding).where(Finding.lesson_id == lesson.id, Finding.status != "rejected")):
        kept.add((f.dimension, frozenset(e.segment_id for e in f.evidence)))
    for f in result.findings:
        ids = [seg_ids[e["segment_id"]] for e in f["evidence"]]
        if (f["dimension"], frozenset(ids)) in kept:
            continue  # 与老师已保留的条目重复
        db.add(Finding(run_id=run.id, lesson_id=lesson.id, dimension=f["dimension"],
                       observation=f["observation"], suggestion=f["suggestion"], status="draft", source="model",
                       evidence=[FindingEvidence(segment_id=i, quote=e["quote"])
                                 for i, e in zip(ids, f["evidence"])]))


def _record_failed_run(lesson_id: int, model: str, error: str):
    """失败的调用也留痕。用独立会话提交，不受阶段回滚影响。"""
    from ..analysis.prompts import PROMPT_VERSION
    from ..db import SessionLocal
    s = SessionLocal()
    try:
        s.add(AnalysisRun(lesson_id=lesson_id, model=model, prompt_version=PROMPT_VERSION,
                          raw_output={"error": error}, stats=None, status="failed"))
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


STAGE_FUNCS = {"transcribing": transcribe_stage, "segmenting": segment_stage, "analyzing": analyze_stage}


# ---------- 状态机 ----------

def mark_failed(db: Session, lesson_id: int, stage: str, reason: str):
    lesson = db.get(Lesson, lesson_id)
    if lesson is not None and lesson.status == stage:
        lesson.status = "failed"
        lesson.error = {"stage": stage, "reason": reason[:1000]}
        db.commit()


def run_stage(db: Session, lesson_id: int, stage: str, final_attempt: bool) -> str:
    """执行一个阶段。返回 done / skipped / retry / failed。

    状态不是本阶段时什么都不做，所以重复触发同一阶段是安全的。
    """
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        return "skipped"
    if stage == "transcribing" and lesson.status == "uploaded" and lesson.queued_at is not None:
        lesson.status = "transcribing"   # 任务被取出执行
        db.commit()
    if lesson.status != stage:
        return "skipped"
    try:
        STAGE_FUNCS[stage](db, lesson)
        lesson.status = NEXT[stage]
        lesson.error = None
        db.commit()
        return "done"
    except SoftTimeLimitExceeded:
        db.rollback()
        mark_failed(db, lesson_id, stage, "stage timed out")
        return "failed"
    except (PermanentError, LLMConfigError) as e:
        db.rollback()
        mark_failed(db, lesson_id, stage, str(e))
        return "failed"
    except Exception as e:
        db.rollback()
        if final_attempt:
            mark_failed(db, lesson_id, stage, f"{type(e).__name__}: {e}")
            return "failed"
        return "retry"
