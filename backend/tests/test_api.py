"""权限、审阅流程、报告、账号与审计。"""
import pytest
from sqlalchemy import select

from app.models import AuditLog, Finding, FindingEvidence, Lesson, Report, ReviewAction, Segment
from app.pipeline import stages

from .conftest import TRANSCRIPT, auth, make_lesson


def ready_lesson(db, teacher, n_findings=2):
    """一节处理完、待审阅的课：1 个片段，若干草稿条目。"""
    lesson = make_lesson(db, teacher, status="ready", with_transcript=True)
    seg = Segment(lesson_id=lesson.id, code="S001", start_ms=0, end_ms=70000, sentence_from=0,
                  sentence_to=len(TRANSCRIPT) - 1, title="Limits")
    db.add(seg)
    db.flush()
    quotes = ["So what does this limit equal?", "Right, it equals one."]
    for i in range(n_findings):
        db.add(Finding(lesson_id=lesson.id, dimension="Questioning and interaction",
                       observation=f"Observation {i}", suggestion=f"Suggestion {i}", status="draft", source="model",
                       evidence=[FindingEvidence(segment_id=seg.id, quote=quotes[i % 2])]))
    stages.store_metrics(db, lesson.id)
    db.commit()
    return lesson


def finding_ids(db, lesson):
    return list(db.scalars(select(Finding.id).where(Finding.lesson_id == lesson.id).order_by(Finding.id)))


# ----- 登录 -----

def test_login_and_failed_login_are_audited(client, db, users):
    assert client.post("/api/auth/login", json={"username": "t1", "password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "t1", "password": "password-1"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "teacher"
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200
    actions = [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions == ["login_failed", "login"]


def test_requests_without_token_are_rejected(client, db, users):
    for path in ["/api/lessons", "/api/reports", "/api/users", "/api/audit-logs", "/api/dimensions"]:
        assert client.get(path).status_code == 401


def test_disabled_account_cannot_log_in_or_use_old_token(client, db, users):
    headers = auth(users["t1"])
    r = client.patch(f"/api/users/{users['t1'].id}", json={"active": False}, headers=auth(users["admin"]))
    assert r.status_code == 200
    assert client.get("/api/lessons", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"username": "t1", "password": "password-1"}).status_code == 401


# ----- 权限：老师之间 -----

def test_teacher_cannot_touch_another_teachers_lesson(client, db, users, dispatched):
    lesson = ready_lesson(db, users["t1"])
    fid = finding_ids(db, lesson)[0]
    sid = db.scalar(select(stages.Sentence.id).where(stages.Sentence.lesson_id == lesson.id))
    other = auth(users["t2"])
    L = f"/api/lessons/{lesson.id}"
    calls = [
        ("get", L, None), ("get", f"{L}/video", None), ("get", f"{L}/transcript", None),
        ("get", f"{L}/segments", None), ("get", f"{L}/metrics", None), ("get", f"{L}/findings", None),
        ("post", f"{L}/findings", {"dimension": "Clarity of explanation", "observation": "o", "suggestion": "s",
                                   "evidence": [{"segment_id": "S001", "quote": "Right, it equals one."}]}),
        ("patch", f"/api/findings/{fid}", {"action": "accept"}),
        ("patch", f"/api/sentences/{sid}", {"text": "changed"}),
        ("post", f"{L}/report", {"reflection": ""}), ("post", f"{L}/retry", None),
        ("post", f"{L}/reanalyze", None), ("post", f"{L}/start", None), ("delete", L, None),
    ]
    for method, path, body in calls:
        r = client.request(method, path, json=body, headers=other)
        assert r.status_code == 404, (method, path, r.status_code)
    assert client.get("/api/lessons", headers=other).json() == []
    assert db.get(Lesson, lesson.id) is not None and db.get(Finding, fid).status == "draft"


# ----- 权限：中心 -----

def test_center_sees_only_submitted_reports(client, db, users):
    lesson = ready_lesson(db, users["t1"], n_findings=1)
    t, c = auth(users["t1"]), auth(users["center"])
    client.patch(f"/api/findings/{finding_ids(db, lesson)[0]}", json={"action": "accept"}, headers=t)
    rid = client.post(f"/api/lessons/{lesson.id}/report", json={"reflection": "r"}, headers=t).json()["id"]

    # 未提交：中心看不到
    assert client.get("/api/reports", headers=c).json() == []
    assert client.get(f"/api/reports/{rid}", headers=c).status_code == 404
    assert client.get(f"/api/reports/{rid}/pdf", headers=c).status_code == 404
    assert client.post(f"/api/reports/{rid}/submit", headers=c).status_code == 403

    assert client.post(f"/api/reports/{rid}/submit", headers=t).json()["submitted_at"]
    assert [r["id"] for r in client.get("/api/reports", headers=c).json()] == [rid]
    assert client.get(f"/api/reports/{rid}", headers=c).status_code == 200
    assert client.get(f"/api/reports/{rid}/pdf", headers=c).json()["url"]

    # 草稿、录像、文字稿始终看不到
    L = f"/api/lessons/{lesson.id}"
    for path in [L, f"{L}/video", f"{L}/transcript", f"{L}/segments", f"{L}/metrics", f"{L}/findings", "/api/lessons"]:
        assert client.get(path, headers=c).status_code == 403, path

    # 别的老师也看不到这份报告
    assert client.get(f"/api/reports/{rid}", headers=auth(users["t2"])).status_code == 404


# ----- 权限：管理员 -----

def test_admin_manages_accounts_but_cannot_see_lesson_content(client, db, users):
    lesson = ready_lesson(db, users["t1"])
    a = auth(users["admin"])
    L = f"/api/lessons/{lesson.id}"
    for path in [L, f"{L}/video", f"{L}/transcript", f"{L}/segments", f"{L}/metrics", f"{L}/findings", "/api/reports"]:
        assert client.get(path, headers=a).status_code == 403, path
    listing = client.get("/api/lessons", headers=a).json()
    assert "title" not in listing[0] and listing[0]["status"] == "ready"   # 只有任务状态

    r = client.post("/api/users", headers=a, json={"username": "teacher3", "password": "password-3", "name": "T3",
                                                   "role": "teacher", "dept": "Math"})
    assert r.status_code == 201
    assert client.post("/api/users", headers=a, json={"username": "teacher3", "password": "password-3", "name": "T3",
                                                      "role": "teacher"}).status_code == 409
    assert client.post("/api/auth/login", json={"username": "teacher3", "password": "password-3"}).status_code == 200
    assert client.patch(f"/api/users/{users['admin'].id}", json={"active": False}, headers=a).status_code == 409

    for role in ("t1", "center"):
        for path in ["/api/users", "/api/audit-logs"]:
            assert client.get(path, headers=auth(users[role])).status_code == 403


def test_audit_log_filters(client, db, users):
    lesson = ready_lesson(db, users["t1"])
    client.get(f"/api/lessons/{lesson.id}/transcript", headers=auth(users["t1"]))
    a = auth(users["admin"])
    logs = client.get("/api/audit-logs", headers=a, params={"user_id": users["t1"].id}).json()
    assert logs["total"] == 1 and logs["items"][0]["action"] == "view_lesson"
    assert logs["items"][0]["target_id"] == str(lesson.id)
    assert client.get("/api/audit-logs", headers=a, params={"since": "2999-01-01T00:00:00Z"}).json()["total"] == 0


# ----- 上传与开始 -----

def test_create_and_start_lesson(client, db, users, dispatched, fake_storage):
    t = auth(users["t1"])
    body = {"title": "Limits", "taught_on": "2026-11-02", "video_filename": "class.mp4", "video_size": 1000,
            "slides_filename": "deck.pdf"}
    r = client.post("/api/lessons", json=body, headers=t)
    assert r.status_code == 201
    lid = r.json()["lesson"]["id"]
    assert r.json()["upload"]["video_url"] and r.json()["upload"]["slides_url"]

    assert client.post(f"/api/lessons/{lid}/start", headers=t).status_code == 409      # 还没传完
    fake_storage[f"lessons/{lid}/video.mp4"] = b"v"
    fake_storage[f"lessons/{lid}/slides.pdf"] = b"s"
    r = client.post(f"/api/lessons/{lid}/start", headers=t)
    assert r.status_code == 200 and r.json()["queue_position"] == 0 and dispatched == [(lid, "transcribing")]
    assert client.post(f"/api/lessons/{lid}/start", headers=t).status_code == 409      # 不会重复开始


@pytest.mark.parametrize("patch", [
    {"video_filename": "class.exe"}, {"video_size": 5 * 1024**3}, {"slides_filename": "deck.key"}, {"title": ""},
])
def test_create_lesson_validation(client, db, users, patch):
    body = {"title": "Limits", "taught_on": "2026-11-02", "video_filename": "class.mp4", "video_size": 1000, **patch}
    assert client.post("/api/lessons", json=body, headers=auth(users["t1"])).status_code == 422


def test_center_and_admin_cannot_upload(client, db, users):
    body = {"title": "Limits", "taught_on": "2026-11-02", "video_filename": "class.mp4", "video_size": 1000}
    for role in ("center", "admin"):
        assert client.post("/api/lessons", json=body, headers=auth(users[role])).status_code == 403


# ----- 审阅 -----

def test_findings_response_has_server_side_times_and_no_score_fields(client, db, users):
    lesson = ready_lesson(db, users["t1"])
    items = client.get(f"/api/lessons/{lesson.id}/findings", headers=auth(users["t1"])).json()
    assert set(items[0]) == {"id", "dimension", "observation", "suggestion", "status", "source", "evidence"}
    ev = items[0]["evidence"][0]
    assert (ev["segment_id"], ev["start_ms"], ev["end_ms"]) == ("S001", 0, 70000)
    assert (ev["quote_start_ms"], ev["quote_end_ms"]) == (34000, 37000)


def test_accept_edit_reject_are_recorded(client, db, users):
    lesson = ready_lesson(db, users["t1"])
    a, b = finding_ids(db, lesson)
    t = auth(users["t1"])
    assert client.patch(f"/api/findings/{a}", json={"action": "accept"}, headers=t).json()["status"] == "accepted"
    r = client.patch(f"/api/findings/{b}", headers=t, json={
        "action": "edit", "observation": "My wording", "suggestion": "My idea",
        "evidence": [{"segment_id": "S001", "quote": "Good question, no, they can be different"}]})
    assert r.json()["status"] == "edited" and r.json()["observation"] == "My wording"
    assert r.json()["evidence"][0]["quote_start_ms"] == 52500
    assert client.patch(f"/api/findings/{b}", json={"action": "reject"}, headers=t).json()["status"] == "rejected"

    actions = db.scalars(select(ReviewAction).order_by(ReviewAction.id)).all()
    assert [x.action for x in actions] == ["accept", "edit", "reject"]
    assert actions[1].before["observation"] == "Observation 1"       # 原文保留在 before
    assert actions[1].after["observation"] == "My wording"


def test_edit_with_bad_evidence_is_refused(client, db, users):
    lesson = ready_lesson(db, users["t1"])
    fid = finding_ids(db, lesson)[0]
    t = auth(users["t1"])
    for ev in ([{"segment_id": "S099", "quote": "Right, it equals one."}],
               [{"segment_id": "S001", "quote": "words that were never said in this class"}], []):
        r = client.patch(f"/api/findings/{fid}", json={"action": "edit", "evidence": ev}, headers=t)
        assert r.status_code == 422
    assert db.get(Finding, fid).status == "draft"


def test_teacher_adds_finding_with_evidence(client, db, users):
    lesson = ready_lesson(db, users["t1"], n_findings=0)
    t = auth(users["t1"])
    body = {"dimension": "Clarity of explanation", "observation": "I used the step function as an example.",
            "suggestion": "Draw it next time.",
            "evidence": [{"segment_id": "S001", "quote": "the step function jumps at zero"}]}
    r = client.post(f"/api/lessons/{lesson.id}/findings", json=body, headers=t)
    assert r.status_code == 201 and r.json()["source"] == "teacher" and r.json()["status"] == "accepted"
    assert client.post(f"/api/lessons/{lesson.id}/findings", json={**body, "evidence": []}, headers=t).status_code == 422
    assert client.post(f"/api/lessons/{lesson.id}/findings", json={**body, "dimension": "Overall"},
                       headers=t).status_code == 422


def test_sentence_correction_updates_segment_text_and_metrics(client, db, users):
    lesson = ready_lesson(db, users["t1"])
    t = auth(users["t1"])
    sent = client.get(f"/api/lessons/{lesson.id}/transcript", headers=t).json()[8]
    assert sent["speaker"] == "student"
    before = client.get(f"/api/lessons/{lesson.id}/metrics", headers=t).json()["lesson"]["student_turns"]
    r = client.patch(f"/api/sentences/{sent['id']}", json={"speaker": "teacher", "text": "Corrected text here."}, headers=t)
    assert r.status_code == 200
    after = client.get(f"/api/lessons/{lesson.id}/metrics", headers=t).json()["lesson"]["student_turns"]
    assert (before, after) == (1, 0)
    assert "Corrected text here." in stages.load_segs(db, lesson.id)[0].text


# ----- 报告 -----

def test_report_blocked_until_every_finding_is_handled(client, db, users, fake_storage):
    lesson = ready_lesson(db, users["t1"])
    a, b = finding_ids(db, lesson)
    t = auth(users["t1"])
    assert client.post(f"/api/lessons/{lesson.id}/report", json={}, headers=t).status_code == 409
    client.patch(f"/api/findings/{a}", json={"action": "accept"}, headers=t)
    assert client.post(f"/api/lessons/{lesson.id}/report", json={}, headers=t).status_code == 409
    client.patch(f"/api/findings/{b}", json={"action": "reject"}, headers=t)

    r = client.post(f"/api/lessons/{lesson.id}/report", json={"reflection": "下次多留等待时间。"}, headers=t)
    assert r.status_code == 201
    content = r.json()["content"]
    kept = [f for d in content["dimensions"] for f in d["findings"]]
    assert [f["observation"] for f in kept] == ["Observation 0"]          # 只含保留下来的条目
    assert kept[0]["evidence"][0]["start_ms"] == 0                         # 每条带时间码
    assert content["header_note"] == "Reviewed and confirmed by the teacher" and content["reflection"] == "下次多留等待时间。"
    assert content["metrics"]["question_count"] >= 1
    db.expire_all()
    assert db.get(Lesson, lesson.id).status == "confirmed"
    assert r.json()["submitted_at"] is None

    pdf = fake_storage[db.get(Report, r.json()["id"]).pdf_key]
    assert pdf.startswith(b"%PDF")


def test_report_has_no_score_fields_anywhere(client, db, users):
    lesson = ready_lesson(db, users["t1"], n_findings=1)
    t = auth(users["t1"])
    client.patch(f"/api/findings/{finding_ids(db, lesson)[0]}", json={"action": "accept"}, headers=t)
    content = client.post(f"/api/lessons/{lesson.id}/report", json={}, headers=t).json()["content"]

    def keys(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from keys(v)
        elif isinstance(x, list):
            for v in x:
                yield from keys(v)
    assert not [k for k in keys(content) if any(w in k.lower() for w in ("score", "grade", "rank", "level", "rating"))]


def test_report_is_a_snapshot(client, db, users):
    lesson = ready_lesson(db, users["t1"], n_findings=1)
    fid = finding_ids(db, lesson)[0]
    t = auth(users["t1"])
    client.patch(f"/api/findings/{fid}", json={"action": "accept"}, headers=t)
    rid = client.post(f"/api/lessons/{lesson.id}/report", json={}, headers=t).json()["id"]
    client.patch(f"/api/findings/{fid}", json={"action": "edit", "observation": "Changed later"}, headers=t)
    old = client.get(f"/api/reports/{rid}", headers=t).json()
    assert old["content"]["dimensions"][1]["findings"][0]["observation"] == "Observation 0"
    new = client.post(f"/api/lessons/{lesson.id}/report", json={}, headers=t).json()
    assert new["version"] == 2 and new["content"]["dimensions"][1]["findings"][0]["observation"] == "Changed later"


# ----- 删除 -----

def test_delete_lesson_cascades_everything(client, db, users, fake_storage):
    lesson = ready_lesson(db, users["t1"], n_findings=1)
    lid, t = lesson.id, auth(users["t1"])
    client.patch(f"/api/findings/{finding_ids(db, lesson)[0]}", json={"action": "accept"}, headers=t)
    client.post(f"/api/lessons/{lid}/report", json={}, headers=t)
    fake_storage[f"lessons/{lid}/video.mp4"] = b"v"

    assert client.delete(f"/api/lessons/{lid}", headers=t).status_code == 204
    db.expire_all()
    from app import models
    for model in (models.Sentence, models.Segment, models.Metric, models.Finding, models.Report):
        assert db.scalar(select(model).where(model.lesson_id == lid)) is None, model
    assert db.scalar(select(FindingEvidence)) is None and db.scalar(select(ReviewAction)) is None
    assert not [k for k in fake_storage if k.startswith(f"lessons/{lid}/")]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "delete_lesson")).target_id == str(lid)   # 日志保留


def test_media_token_is_bound_to_one_lesson(client, db, users, fake_storage):
    a, b = ready_lesson(db, users["t1"]), ready_lesson(db, users["t2"])
    fake_storage[f"lessons/{a.id}/hls/index.m3u8"] = b"#EXTM3U\n#EXTINF:4.0,\nseg00000.ts\n#EXT-X-ENDLIST\n"
    fake_storage[f"lessons/{b.id}/hls/index.m3u8"] = fake_storage[f"lessons/{a.id}/hls/index.m3u8"]
    url = client.get(f"/api/lessons/{a.id}/video", headers=auth(users["t1"])).json()["url"]
    r = client.get(url)
    assert r.status_code == 200 and f"lessons/{a.id}/hls/seg00000.ts?sig=get" in r.text
    assert client.get(url.replace(f"/lessons/{a.id}/", f"/lessons/{b.id}/")).status_code == 401
    assert client.get(f"/api/lessons/{a.id}/hls/index.m3u8?token=nope").status_code == 401
