"""状态机：每个阶段失败后重试、重复触发同一阶段、幂等、重新分析。"""
import pytest
from sqlalchemy import func, select

from app.analysis.llm import LLMError
from app.models import AnalysisRun, Finding, Lesson, Segment, Sentence
from app.pipeline import media, stages
from app.pipeline.media import PermanentError
from app.pipeline.stages import run_stage

from .conftest import TRANSCRIPT, FakeLLM, auth, finding, make_lesson

RAW = [{"speaker": "SPEAKER_00" if sp == "teacher" else "SPEAKER_01", "start_ms": a, "end_ms": b, "text": t}
       for sp, a, b, t in TRANSCRIPT]


def count(db, model, lesson_id):
    return db.scalar(select(func.count()).select_from(model).where(model.lesson_id == lesson_id))


@pytest.fixture()
def pipeline(monkeypatch):
    """把外部依赖（FFmpeg、语音转写、课件文件、大模型）换成可控的假实现。"""
    state = {"media": lambda *a: (70000, RAW), "pages": lambda key: [], "llm": None}
    monkeypatch.setattr(media, "process_media", lambda *a: state["media"](*a))
    monkeypatch.setattr(media, "load_slide_pages", lambda key: state["pages"](key))

    def get_llm():
        if state["llm"] is None:
            raise LLMError("model API unavailable")
        return state["llm"]
    monkeypatch.setattr(stages, "get_llm", get_llm)
    return state


def good_output():
    return {"findings": [finding(evidence=[{"segment_id": "S002", "quote": "So what does this limit equal?"}])]}


def queued(db, users):
    lesson = make_lesson(db, users["t1"])
    lesson.queued_at = lesson.created_at
    db.commit()
    return lesson


def test_happy_path_walks_through_all_states(db, users, pipeline):
    lesson = queued(db, users)
    assert run_stage(db, lesson.id, "transcribing", False) == "done"
    assert lesson.status == "segmenting" and lesson.duration_ms == 70000
    assert count(db, Sentence, lesson.id) == len(RAW)

    assert run_stage(db, lesson.id, "segmenting", False) == "done"     # 没有模型也能切分，只是没有标题
    assert lesson.status == "analyzing" and count(db, Segment, lesson.id) >= 1

    pipeline["llm"] = FakeLLM(good_output())
    assert run_stage(db, lesson.id, "analyzing", False) == "done"
    assert lesson.status == "ready" and count(db, Finding, lesson.id) == 1
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.lesson_id == lesson.id))
    assert run.model == "fake-model" and run.prompt_version and run.raw_output and run.stats["findings_passed"] == 1


def test_stage_not_run_until_lesson_is_started(db, users, pipeline):
    lesson = make_lesson(db, users["t1"])            # 还没点开始
    assert run_stage(db, lesson.id, "transcribing", False) == "skipped"
    assert lesson.status == "uploaded"


@pytest.mark.parametrize("stage", ["transcribing", "segmenting", "analyzing"])
def test_each_stage_fails_then_retries_from_that_stage(db, users, pipeline, client, dispatched, stage):
    lesson = queued(db, users)
    pipeline["llm"] = FakeLLM({"titles": []}, good_output())    # 切分阶段先要一次标题

    def boom(*a):
        raise RuntimeError("temporary outage")
    broken = {"transcribing": ("media", boom), "segmenting": ("pages", boom),
              "analyzing": ("llm", FakeLLM(LLMError("rate limited"), LLMError("rate limited")))}[stage]
    original = pipeline[broken[0]]

    for s in stages.STAGES:
        if s == stage:
            break
        assert run_stage(db, lesson.id, s, False) == "done"
    sentences_before = count(db, Sentence, lesson.id)

    pipeline[broken[0]] = broken[1]
    assert run_stage(db, lesson.id, stage, final_attempt=False) == "retry"      # 自动重试期间状态不变
    assert lesson.status == stage
    assert run_stage(db, lesson.id, stage, final_attempt=True) == "failed"      # 重试用尽
    db.refresh(lesson)
    assert lesson.status == "failed" and lesson.error["stage"] == stage and lesson.error["reason"]

    # 失败状态下任务不会再执行
    assert run_stage(db, lesson.id, stage, False) == "skipped"

    # 手动重试：回到出错的那个阶段，前面阶段的结果保留
    pipeline[broken[0]] = original
    r = client.post(f"/api/lessons/{lesson.id}/retry", headers=auth(users["t1"]))
    assert r.status_code == 200 and dispatched == [(lesson.id, stage)]
    db.refresh(lesson)
    assert lesson.status == stage and lesson.error is None
    if stage != "transcribing":
        assert count(db, Sentence, lesson.id) == sentences_before
    assert run_stage(db, lesson.id, stage, False) == "done"
    assert lesson.status == stages.NEXT[stage]


def test_permanent_error_fails_without_retry(db, users, pipeline):
    lesson = queued(db, users)

    def too_long(*a):
        raise PermanentError("recording is longer than the 2 hour limit")
    pipeline["media"] = too_long
    assert run_stage(db, lesson.id, "transcribing", final_attempt=False) == "failed"
    assert lesson.error == {"stage": "transcribing", "reason": "recording is longer than the 2 hour limit"}


def test_repeated_trigger_of_same_stage_is_idempotent(db, users, pipeline):
    lesson = queued(db, users)
    assert run_stage(db, lesson.id, "transcribing", False) == "done"
    # 同一阶段的任务又被投递一次：状态已前进，直接跳过
    assert run_stage(db, lesson.id, "transcribing", False) == "skipped"
    assert count(db, Sentence, lesson.id) == len(RAW)

    # 阶段在写完产物、更新状态之前崩了再重跑：先清旧产物，不会出现重复数据
    lesson.status = "transcribing"
    db.commit()
    assert run_stage(db, lesson.id, "transcribing", False) == "done"
    assert count(db, Sentence, lesson.id) == len(RAW)

    assert run_stage(db, lesson.id, "segmenting", False) == "done"
    n = count(db, Segment, lesson.id)
    lesson.status = "segmenting"
    db.commit()
    assert run_stage(db, lesson.id, "segmenting", False) == "done"
    assert count(db, Segment, lesson.id) == n

    pipeline["llm"] = FakeLLM(good_output(), good_output())
    assert run_stage(db, lesson.id, "analyzing", False) == "done"
    lesson.status = "analyzing"
    db.commit()
    assert run_stage(db, lesson.id, "analyzing", False) == "done"
    assert count(db, Finding, lesson.id) == 1


def test_retry_only_allowed_when_failed(db, users, client, dispatched):
    lesson = make_lesson(db, users["t1"], status="ready")
    assert client.post(f"/api/lessons/{lesson.id}/retry", headers=auth(users["t1"])).status_code == 409
    assert dispatched == []


def test_admin_can_retry_a_failed_lesson(db, users, client, dispatched):
    lesson = make_lesson(db, users["t1"], status="failed")
    lesson.error = {"stage": "analyzing", "reason": "x"}
    db.commit()
    assert client.post(f"/api/lessons/{lesson.id}/retry", headers=auth(users["admin"])).status_code == 200
    assert dispatched == [(lesson.id, "analyzing")]


def test_reanalysis_keeps_reviewed_findings_and_replaces_drafts(db, users, pipeline, client, dispatched):
    lesson = queued(db, users)
    two = {"findings": [
        finding(evidence=[{"segment_id": "S002", "quote": "So what does this limit equal?"}]),
        finding(dimension="Clarity of explanation", observation="A table of values was used.",
                suggestion="Ask students to predict the next row.",
                evidence=[{"segment_id": "S001", "quote": "the ratio gets closer and closer to one"}]),
    ]}
    pipeline["llm"] = FakeLLM({"titles": []}, two)
    for s in stages.STAGES:
        assert run_stage(db, lesson.id, s, False) == "done"
    first, second = db.scalars(select(Finding).where(Finding.lesson_id == lesson.id).order_by(Finding.id)).all()

    h = auth(users["t1"])
    assert client.patch(f"/api/findings/{first.id}", json={"action": "accept"}, headers=h).status_code == 200
    r = client.post(f"/api/lessons/{lesson.id}/reanalyze", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "analyzing"
    assert dispatched == [(lesson.id, "analyzing")]

    new = finding(dimension="Clarity of explanation", observation="The step function example was concrete.",
                  suggestion="Sketch it on the board.",
                  evidence=[{"segment_id": "S002", "quote": "Right, it equals one."}])
    pipeline["llm"] = FakeLLM({"findings": [two["findings"][0], new]})
    db.expire_all()      # 接口用的是另一个会话
    assert run_stage(db, lesson.id, "analyzing", False) == "done"
    db.expire_all()
    rows = db.scalars(select(Finding).where(Finding.lesson_id == lesson.id).order_by(Finding.id)).all()
    # 已采纳的保留；旧草稿被替换；与已采纳条目重复的新草稿不再出现
    assert [(f.status, f.observation) for f in rows] == [
        ("accepted", first.observation), ("draft", "The step function example was concrete.")]
    assert db.get(Lesson, lesson.id).status == "ready"
