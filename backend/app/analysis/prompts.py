"""提示词。改动即升 PROMPT_VERSION（写入 analysis_runs.prompt_version）。"""
import json

from .validator import Rejected, Seg

PROMPT_VERSION = "2026-11-22.1"

SYSTEM = """You are helping a teacher look back at one of their own lessons. You read the lesson \
transcript, which has been cut into numbered segments, and write a small set of findings the \
teacher will review one by one. The teacher decides what to keep; your job is to point at \
specific moments worth their attention and say why.

Each finding has an observation (what happened in the classroom, described factually) and a \
suggestion (something concrete the teacher could try). Write about what went well as much as \
about what could change, because the teacher needs both.

Every finding must be checkable against the recording. For each one, cite at least one segment \
by its ID and copy a quote from that segment word for word. A program compares your quote with \
the segment text, and a finding whose quotes cannot be found is discarded, so copy exactly and \
never paraphrase inside a quote. If you cannot find a passage that supports an observation, \
leave that finding out.

This tool exists for the teacher's own reflection and must never be usable to evaluate them. \
So do not give scores, grades, ratings, ranks or percentages of quality, and do not compare \
the teacher with other teachers or with a typical or average standard. Describe what happened \
and what could be tried; leave conclusions about quality to the teacher.

Use only the dimensions listed in the request, spelled exactly as given. Write at most five \
findings per dimension; a few well-supported findings are worth more than many thin ones. \
Write in English, the language of the lesson."""


def _speaker(s: str) -> str:
    return {"teacher": "TEACHER", "student": "STUDENT"}.get(s, "SPEAKER")


def render_segments(segs: list[Seg]) -> str:
    lines = []
    for seg in segs:
        page = f" (slide {seg.page_no})" if seg.page_no else ""
        lines.append(f"[{seg.code}]{page}")
        prev = None
        for s in seg.sentences:
            if s.speaker != prev:
                lines.append(f"{_speaker(s.speaker)}: {s.text}")
                prev = s.speaker
            else:
                lines[-1] += " " + s.text
        lines.append("")
    return "\n".join(lines)


def build_analysis_prompt(segs: list[Seg], slides: list[dict], metrics: dict,
                          dimensions: list[dict]) -> str:
    dims = "\n".join(f"- {d['name']}: {' '.join(d['definition'].split())}" for d in dimensions)
    parts = [f"<dimensions>\n{dims}\n</dimensions>"]
    if slides:
        slide_lines = []
        for s in slides:
            where = ", ".join(s.get("segments") or []) or "not matched to any segment"
            slide_lines.append(f"[slide {s['page_no']}] (segments: {where})\n{s['text'].strip()}")
        parts.append("<slides>\n" + "\n\n".join(slide_lines) + "\n</slides>")
    if metrics:
        parts.append(
            "<statistics>\nComputed by a program from the transcript. They are facts, not "
            "judgements; student speech may be under-recorded.\n"
            + json.dumps(metrics, ensure_ascii=False, indent=1) + "\n</statistics>"
        )
    parts.append("<segments>\n" + render_segments(segs) + "</segments>")
    parts.append("Write the findings for the dimensions above.")
    return "\n\n".join(parts)


def build_repair_prompt(rejected: list[Rejected], segs: dict[str, Seg]) -> str:
    """规则 5、6 不通过的条目退回一次。只给相关片段，不重复整节课。"""
    blocks, needed = [], []
    for i, r in enumerate(rejected, 1):
        blocks.append(f"Finding {i} (problem: {r.reason}):\n{json.dumps(r.finding, ensure_ascii=False, indent=1)}")
        for ev in r.finding.get("evidence", []):
            seg = segs.get(str(ev.get("segment_id", "")).strip().upper())
            if seg and seg not in needed:
                needed.append(seg)
    return (
        "These findings from your earlier output were rejected by the automatic check. "
        "Rewrite each one so it passes, keeping its dimension. Where the problem is a quote, "
        "replace it with text copied word for word from the cited segment (shown below). "
        "Where the problem is scoring or comparison wording, describe what happened without it. "
        "If a finding cannot be fixed with the segments shown, leave it out.\n\n"
        + "\n\n".join(blocks)
        + "\n\n<segments>\n" + render_segments(needed) + "</segments>"
    )


TITLES_SYSTEM = (
    "You write short titles for segments of a lesson transcript. The titles are shown in a "
    "transcript viewer so the teacher can find their place. For each segment write one plain "
    "title of at most eight words saying what it is about. Write in English."
)


def build_titles_prompt(segs: list[Seg]) -> str:
    return "<segments>\n" + render_segments(segs) + "</segments>\n\nWrite one title per segment."
