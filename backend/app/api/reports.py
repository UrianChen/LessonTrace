from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import storage
from ..config import load_dimensions
from ..db import get_db
from ..models import Finding, Lesson, Report, User, now
from ..pipeline import stages
from ..report_pdf import render_pdf
from ..security import audit, require
from .lessons import lesson_metrics, own_lesson
from .review import finding_out

router = APIRouter()

HEADER_NOTE = "Reviewed and confirmed by the teacher"
KEPT = ("accepted", "edited")


class ReportIn(BaseModel):
    reflection: str = ""


def report_out(r: Report, with_content: bool = True) -> dict:
    out = {"id": r.id, "lesson_id": r.lesson_id, "version": r.version, "created_at": r.created_at.isoformat(),
           "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
           "title": r.content["lesson"]["title"], "taught_on": r.content["lesson"]["taught_on"],
           "teacher": r.content["lesson"]["teacher"], "has_pdf": bool(r.pdf_key)}
    if with_content:
        out["content"] = r.content
    return out


def _visible_report(db: Session, user: User, report_id: int) -> Report:
    """老师看自己的；中心只能看已提交的。"""
    r = db.get(Report, report_id)
    if r is not None:
        if user.role == "teacher" and r.lesson.teacher_id == user.id:
            return r
        if user.role == "center" and r.submitted_at is not None:
            return r
    raise HTTPException(404, "report not found")


@router.post("/lessons/{lesson_id}/report", status_code=201)
def generate_report(lesson_id: int, body: ReportIn, request: Request, user: User = Depends(require("teacher")),
                    db: Session = Depends(get_db)):
    lesson = own_lesson(db, user, lesson_id)
    if lesson.status not in ("ready", "confirmed"):
        raise HTTPException(409, "A report can be generated once processing has finished")
    findings = list(db.scalars(select(Finding).where(Finding.lesson_id == lesson.id).order_by(Finding.id)))
    # 还有未处理的条目时不能生成报告，避免未经确认的内容进入报告
    pending = sum(1 for f in findings if f.status == "draft")
    if pending:
        raise HTTPException(409, f"{pending} findings still need to be reviewed")

    segs = {s.db_id: s for s in stages.load_segs(db, lesson.id)}
    kept = [finding_out(f, segs) for f in findings if f.status in KEPT]
    dims = []
    for d in load_dimensions():
        dims.append({"name": d["name"], "name_zh": d.get("name_zh", d["name"]),
                     "findings": [{k: f[k] for k in ("observation", "suggestion", "source", "evidence")}
                                  for f in kept if f["dimension"] == d["name"]]})
    m = lesson_metrics(db, lesson.id)["lesson"]
    version = (db.scalar(select(func.max(Report.version)).where(Report.lesson_id == lesson.id)) or 0) + 1
    # 条目和证据复制进快照，之后再改条目不影响已生成的报告
    content = {
        "header_note": HEADER_NOTE, "version": version, "generated_at": now().isoformat(),
        "lesson": {"title": lesson.title, "taught_on": lesson.taught_on.isoformat(), "teacher": user.name,
                   "dept": user.dept, "duration_ms": lesson.duration_ms},
        "metrics": m, "dimensions": dims, "reflection": body.reflection.strip(),
    }
    report = Report(lesson_id=lesson.id, version=version, content=content)
    db.add(report)
    db.flush()
    key = f"{storage.lesson_prefix(lesson.id)}reports/report-v{version}.pdf"
    storage.put_bytes(key, render_pdf(content), "application/pdf")
    report.pdf_key = key
    lesson.status = "confirmed"
    audit(db, request, user.id, "generate_report", "report", report.id)
    db.commit()
    return report_out(report)


@router.get("/reports")
def list_reports(user: User = Depends(require("teacher", "center")), db: Session = Depends(get_db)):
    q = select(Report).join(Lesson).order_by(Report.id.desc())
    if user.role == "teacher":
        q = q.where(Lesson.teacher_id == user.id)
    else:
        q = q.where(Report.submitted_at.is_not(None))
    return [report_out(r, with_content=False) for r in db.scalars(q)]


@router.get("/reports/{report_id}")
def get_report(report_id: int, request: Request, user: User = Depends(require("teacher", "center")),
               db: Session = Depends(get_db)):
    r = _visible_report(db, user, report_id)
    audit(db, request, user.id, "view_report", "report", r.id)
    db.commit()
    return report_out(r)


@router.get("/reports/{report_id}/pdf")
def report_pdf(report_id: int, request: Request, user: User = Depends(require("teacher", "center")),
               db: Session = Depends(get_db)):
    """PDF 下载地址，短期有效。"""
    r = _visible_report(db, user, report_id)
    if not r.pdf_key:
        raise HTTPException(404, "pdf not found")
    audit(db, request, user.id, "download_report", "report", r.id)
    db.commit()
    return {"url": storage.presign_get(r.pdf_key, expires=300, filename=f"lessontrace-report-{r.id}.pdf")}


@router.post("/reports/{report_id}/submit")
def submit_report(report_id: int, request: Request, user: User = Depends(require("teacher")),
                  db: Session = Depends(get_db)):
    """生成后默认只有老师自己可见，提交后中心才能看到。"""
    r = db.get(Report, report_id)
    if r is None or r.lesson.teacher_id != user.id:
        raise HTTPException(404, "report not found")
    if r.submitted_at is None:
        r.submitted_at = now()
        audit(db, request, user.id, "submit_report", "report", r.id)
        db.commit()
    return report_out(r)
