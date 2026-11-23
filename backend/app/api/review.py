from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.validator import Seg, locate_quote, quote_matches
from ..config import load_dimensions
from ..db import get_db
from ..models import Finding, FindingEvidence, ReviewAction, User
from ..pipeline import stages
from ..security import current_user, require
from .lessons import own_lesson

router = APIRouter()


class EvidenceIn(BaseModel):
    segment_id: str
    quote: str = Field(min_length=1)


class FindingIn(BaseModel):
    dimension: str
    observation: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    evidence: list[EvidenceIn] = Field(min_length=1)


class FindingPatch(BaseModel):
    action: Literal["accept", "reject", "edit"]
    observation: str | None = Field(default=None, min_length=1)
    suggestion: str | None = Field(default=None, min_length=1)
    evidence: list[EvidenceIn] | None = Field(default=None, min_length=1)


def finding_out(f: Finding, segs_by_id: dict[int, Seg]) -> dict:
    """时间是服务端从片段表查出的，前端用它控制播放器。"""
    evidence = []
    for e in f.evidence:
        seg = segs_by_id[e.segment_id]
        qs, qe = locate_quote(e.quote, seg)
        evidence.append({"segment_id": seg.code, "quote": e.quote, "start_ms": seg.start_ms, "end_ms": seg.end_ms,
                         "quote_start_ms": qs, "quote_end_ms": qe})
    return {"id": f.id, "dimension": f.dimension, "observation": f.observation, "suggestion": f.suggestion,
            "status": f.status, "source": f.source, "evidence": evidence}


def _snapshot(f: Finding, segs_by_id: dict[int, Seg]) -> dict:
    return {"observation": f.observation, "suggestion": f.suggestion, "status": f.status,
            "evidence": [{"segment_id": segs_by_id[e.segment_id].code, "quote": e.quote} for e in f.evidence]}


def _check_evidence(items: list[EvidenceIn], segs: list[Seg]) -> list[FindingEvidence]:
    """老师写的条目同样要有证据：片段必须存在，引文必须出自该片段。"""
    by_code = {s.code: s for s in segs}
    out = []
    for ev in items:
        seg = by_code.get(ev.segment_id.strip().upper())
        if seg is None:
            raise HTTPException(422, f"Segment {ev.segment_id} does not exist")
        if not quote_matches(ev.quote, seg.text):
            raise HTTPException(422, f"The quote was not found in the transcript of segment {seg.code}")
        out.append(FindingEvidence(segment_id=seg.db_id, quote=ev.quote.strip()))
    return out


def _dimension_names() -> list[str]:
    return [d["name"] for d in load_dimensions()]


@router.get("/dimensions")
def dimensions(user: User = Depends(current_user)):
    return [{"name": d["name"], "name_zh": d.get("name_zh", d["name"]),
             "definition": " ".join(d["definition"].split())} for d in load_dimensions()]


@router.get("/lessons/{lesson_id}/findings")
def list_findings(lesson_id: int, user: User = Depends(require("teacher")), db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    segs = {s.db_id: s for s in stages.load_segs(db, lesson.id)}
    rows = db.scalars(select(Finding).where(Finding.lesson_id == lesson.id).order_by(Finding.id))
    return [finding_out(f, segs) for f in rows]


@router.post("/lessons/{lesson_id}/findings", status_code=201)
def add_finding(lesson_id: int, body: FindingIn, user: User = Depends(require("teacher")),
                db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    if lesson.status not in ("ready", "confirmed"):
        raise HTTPException(409, "Findings can be reviewed once processing has finished")
    if body.dimension not in _dimension_names():
        raise HTTPException(422, "Unknown dimension")
    segs = stages.load_segs(db, lesson.id)
    f = Finding(lesson_id=lesson.id, dimension=body.dimension, observation=body.observation.strip(),
                suggestion=body.suggestion.strip(), status="accepted", source="teacher",
                evidence=_check_evidence(body.evidence, segs))
    db.add(f)
    db.flush()
    by_id = {s.db_id: s for s in segs}
    db.add(ReviewAction(finding_id=f.id, user_id=user.id, action="create", before=None, after=_snapshot(f, by_id)))
    db.commit()
    return finding_out(f, by_id)


@router.patch("/findings/{finding_id}")
def patch_finding(finding_id: int, body: FindingPatch, user: User = Depends(require("teacher")),
                  db: Session = Depends(get_db)):
    f = db.get(Finding, finding_id)
    if f is None:
        raise HTTPException(404, "finding not found")
    lesson = own_lesson(db, user, f.lesson_id)
    if lesson.status not in ("ready", "confirmed"):
        raise HTTPException(409, "Findings can be reviewed once processing has finished")
    segs = stages.load_segs(db, lesson.id)
    by_id = {s.db_id: s for s in segs}
    before = _snapshot(f, by_id)   # 原文保留在 review_actions.before

    if body.action == "accept":
        f.status = "accepted"
    elif body.action == "reject":
        f.status = "rejected"
    else:
        if body.observation is not None:
            f.observation = body.observation.strip()
        if body.suggestion is not None:
            f.suggestion = body.suggestion.strip()
        if body.evidence is not None:
            f.evidence = _check_evidence(body.evidence, segs)
        f.status = "edited"
    db.flush()
    db.add(ReviewAction(finding_id=f.id, user_id=user.id, action=body.action, before=before,
                        after=_snapshot(f, by_id)))
    db.commit()
    return finding_out(f, by_id)
