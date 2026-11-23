"""导入示例数据：一节处理好的课，启动后即可审阅。可重复执行（已导入则跳过）。

    python -m scripts.seed_demo            # 导入 samples/ 下全部示例
    python -m scripts.seed_demo --force    # 删掉旧的重新导入

示例课是为本项目编写的合成课（不是真实课堂录像）：文字稿是手写的，
时间按词数推算，录像用 FFmpeg 生成——画面上滚动显示当前句子和时间码，没有人声。
对齐、切分、统计走的是真实的程序；条目是手写的，但要过同一套证据校验才会入库。
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
from datetime import date

from sqlalchemy import delete, select

from app import storage
from app.analysis.validator import attach_times, check_findings, dedupe, new_counts, quote_matches
from app.config import BASE_DIR, load_dimensions
from app.db import SessionLocal
from app.models import AnalysisRun, Finding, FindingEvidence, Lesson, Segment, Sentence, Slide, User
from app.pipeline import media, stages
from app.pipeline.segmenter import code_for, segment
from app.pipeline.slides import align_slides

WORDS_PER_SEC = 2.35     # 约 140 词/分钟
GAP_S = 0.35


def build_sentences(script: list) -> list[dict]:
    out, t = [], 1.0
    for speaker, pause, text in script:
        t += pause
        dur = max(1.2, len(text.split()) / WORDS_PER_SEC)
        out.append({"speaker": speaker, "start_ms": int(t * 1000), "end_ms": int((t + dur) * 1000), "text": text})
        t += dur + GAP_S
    return out


def _ass_time(ms: int) -> str:
    cs = ms // 10
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def make_video(sentences: list[dict], title: str, path: str):
    """生成示例录像：深色背景，字幕显示当前句子，左上角是时间码。"""
    total = sentences[-1]["end_ms"] / 1000 + 2
    ass = os.path.join(os.path.dirname(path), "subs.ass")
    with open(ass, "w", encoding="utf-8") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 0\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
                "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
                "Style: T,DejaVu Sans,40,&H00F2F2F2,&H00000000,&H00000000,0,1,0,0,5,90,90,40\n"
                "Style: S,DejaVu Sans,40,&H0066D9FF,&H00000000,&H00000000,0,1,0,0,5,90,90,40\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Text\n")
        for s in sentences:
            who = "TEACHER" if s["speaker"] == "teacher" else "STUDENT"
            style = "T" if s["speaker"] == "teacher" else "S"
            text = s["text"].replace("{", "(").replace("}", ")")
            f.write(f"Dialogue: 0,{_ass_time(s['start_ms'])},{_ass_time(s['end_ms'])},{style},"
                    f"{{\\fs24}}{who}\\N{{\\fs40}}{text}\n")
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    safe_title = title.replace(":", " ").replace("'", "").replace("—", "-")
    vf = (f"drawtext=fontfile={font}:text='%{{pts\\:hms}}':x=40:y=36:fontsize=30:fontcolor=0x9fb3c8,"
          f"drawtext=fontfile={font}:text='{safe_title}':x=40:y=h-70:fontsize=22:fontcolor=0x6b7f94,"
          f"drawtext=fontfile={font}:text='Synthetic sample - no real recording':x=w-tw-40:y=40:fontsize=20:fontcolor=0x6b7f94,"
          f"subtitles={ass}")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x16202b:s=1280x720:r=10",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{total:.2f}", "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-g", "40",
         "-c:a", "aac", "-b:a", "48k", path], check=True)
    return int(total * 1000)


def seed_one(db, teacher: User, sample: dict, force: bool):
    existing = db.scalar(select(Lesson).where(Lesson.teacher_id == teacher.id, Lesson.title == sample["title"]))
    if existing:
        if not force:
            print(f"[seed] '{sample['title']}' already imported, skipping", flush=True)
            return
        storage.delete_prefix(storage.lesson_prefix(existing.id))
        db.execute(delete(Lesson).where(Lesson.id == existing.id))
        db.commit()

    lesson = Lesson(teacher_id=teacher.id, title=sample["title"], taught_on=date.fromisoformat(sample["taught_on"]),
                    status="analyzing")
    db.add(lesson)
    db.flush()
    lesson.video_key = storage.lesson_prefix(lesson.id) + "video.mp4"

    raw = build_sentences(sample["script"])
    for i, s in enumerate(raw):
        db.add(Sentence(lesson_id=lesson.id, idx=i, **s))
    db.flush()

    # 录像：生成、转 HLS、上传
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "video.mp4")
        lesson.duration_ms = make_video(raw, sample["title"], video)
        storage.upload(video, lesson.video_key, "video/mp4")
        hls = os.path.join(tmp, "hls")
        media.make_hls(video, hls, {"vcodec": "h264", "acodec": "aac"})
        media.upload_hls(hls, lesson.id)

    # 对齐、切分、统计：真实的程序
    sentences = stages.get_sentences(db, lesson.id)
    spans = align_slides(sample["slides"], sentences)
    slides = []
    for i, text in enumerate(sample["slides"]):
        sl = Slide(lesson_id=lesson.id, page_no=i + 1, text=text,
                   start_ms=spans[i][0] if spans[i] else None, end_ms=spans[i][1] if spans[i] else None)
        db.add(sl)
        slides.append(sl)
    db.flush()
    for i, p in enumerate(segment(sentences, spans)):
        title = next((t for at, t in sample.get("titles", []) if p.first <= at <= p.last), "")
        db.add(Segment(lesson_id=lesson.id, code=code_for(i), start_ms=p.start_ms, end_ms=p.end_ms, title=title,
                       slide_id=slides[p.page_idx].id if p.page_idx is not None else None,
                       sentence_from=p.first, sentence_to=p.last))
    db.flush()
    stages.store_metrics(db, lesson.id)

    # 条目：按引文找到所在片段，再过同一套证据校验
    segs = stages.load_segs(db, lesson.id)
    seg_map = {g.code: g for g in segs}
    drafts = []
    for f in sample["findings"]:
        evidence = []
        for q in f["quotes"]:
            seg = next((g for g in segs if quote_matches(q, g.text)), None)
            evidence.append({"segment_id": seg.code if seg else "S000", "quote": q})
        drafts.append({"dimension": f["dimension"], "observation": f["observation"],
                       "suggestion": f["suggestion"], "evidence": evidence})
    counts = new_counts()
    res = check_findings(drafts, seg_map, [d["name"] for d in load_dimensions()], counts)
    if res.retry or len(res.passed) != len(drafts):
        raise SystemExit(f"[seed] sample findings failed validation: {counts} {[r.reason for r in res.retry]}")
    passed = attach_times(dedupe(res.passed, counts), seg_map)
    counts["findings_passed"] = len(passed)
    run = AnalysisRun(lesson_id=lesson.id, model="sample-data (hand-written, not model output)",
                      prompt_version="n/a", raw_output=[{"purpose": "sample", "output": json.dumps({"findings": drafts})}],
                      stats={**counts, "skipped_dimensions": {}}, status="ok")
    db.add(run)
    db.flush()
    for f in passed:
        db.add(Finding(run_id=run.id, lesson_id=lesson.id, dimension=f["dimension"], observation=f["observation"],
                       suggestion=f["suggestion"], status="draft", source="model",
                       evidence=[FindingEvidence(segment_id=seg_map[e["segment_id"]].db_id, quote=e["quote"])
                                 for e in f["evidence"]]))
    lesson.status = "ready"
    db.commit()
    print(f"[seed] imported '{sample['title']}': {len(raw)} sentences, {len(segs)} segments, "
          f"{len(passed)} findings, slides aligned: {sum(1 for s in spans if s)}/{len(spans)}", flush=True)


def main():
    force = "--force" in sys.argv
    db = SessionLocal()
    try:
        teacher = db.scalar(select(User).where(User.username == "teacher"))
        if teacher is None:
            raise SystemExit("[seed] run scripts.init_db first")
        for path in sorted(glob.glob(str(BASE_DIR / "samples" / "*.json"))):
            with open(path, encoding="utf-8") as f:
                sample = json.load(f)
            if "script" in sample:
                seed_one(db, teacher, sample, force)
    finally:
        db.close()


if __name__ == "__main__":
    main()
