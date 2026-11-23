"""规则统计（设计方案第 7 节第 5 步）。只算可以精确计算的事实，不设阈值，不判好坏。"""
import re

_STARTERS = (
    "what", "why", "how", "who", "whom", "whose", "when", "where", "which",
    "do", "does", "did", "is", "are", "was", "were", "can", "could", "will", "would",
    "should", "shall", "have", "has", "had", "may", "might", "am",
)
_first_word = re.compile(r"[A-Za-z']+")


def is_question(text: str) -> bool:
    """句末问号，加上以疑问词或助动词开头的句式规则粗筛。"""
    t = text.strip()
    if not t:
        return False
    if t.rstrip("\"')] ").endswith("?"):
        return True
    m = _first_word.match(t)
    return bool(m) and m.group(0).lower() in _STARTERS


def _words(text: str) -> int:
    return len(text.split())


def _talk(sentences, speaker) -> int:
    return sum(s.end_ms - s.start_ms for s in sentences if s.speaker == speaker)


def _turns(sentences, speaker) -> int:
    n, prev = 0, None
    for s in sentences:
        if s.speaker == speaker and prev != speaker:
            n += 1
        prev = s.speaker
    return n


def _wpm(sentences, speaker="teacher") -> float | None:
    ms = _talk(sentences, speaker)
    if ms <= 0:
        return None
    return round(sum(_words(s.text) for s in sentences if s.speaker == speaker) / (ms / 60000), 1)


def _ratio(a: int, b: int) -> float | None:
    return round(a / (a + b), 4) if a + b else None


def compute_metrics(sentences: list, segments: list, slides: list) -> list[tuple[str, object, int | None]]:
    """返回 [(key, value, segment_index 或 None)]。None 表示整节课。

    sentences: idx / start_ms / end_ms / speaker / text
    segments:  code / sentence_from / sentence_to / start_ms / end_ms（下标与返回值对应）
    slides:    page_no / start_ms / end_ms
    """
    out: list[tuple[str, object, int | None]] = []
    seg_of = {}
    for gi, g in enumerate(segments):
        for i in range(g.sentence_from, g.sentence_to + 1):
            seg_of[i] = gi

    # 没做说话人分离时所有句子都是 unknown：师生占比算不了，提问和语速退到按全部句子统计
    identified = any(s.speaker != "unknown" for s in sentences)
    who = "teacher" if identified else "unknown"

    t_ms, s_ms = _talk(sentences, "teacher"), _talk(sentences, "student")
    out += [
        ("speakers_identified", identified, None),
        ("teacher_talk_ms", t_ms, None),
        ("student_talk_ms", s_ms, None),
        ("teacher_talk_ratio", _ratio(t_ms, s_ms), None),
        ("student_talk_ratio", _ratio(s_ms, t_ms), None),
        ("teacher_turns", _turns(sentences, "teacher"), None),
        ("student_turns", _turns(sentences, "student"), None),
        ("speech_rate_wpm", _wpm(sentences, who), None),
    ]

    # 提问次数、位置、等待时长（问句结束到下一句开始）
    questions = []
    for i, s in enumerate(sentences):
        if s.speaker != who or not is_question(s.text):
            continue
        nxt = sentences[i + 1] if i + 1 < len(sentences) else None
        gi = seg_of.get(s.idx)
        questions.append({
            "sentence_idx": s.idx,
            "at_ms": s.start_ms,
            "segment": segments[gi].code if gi is not None else None,
            "wait_ms": max(0, nxt.start_ms - s.end_ms) if nxt else None,
            "answered_by": nxt.speaker if nxt else None,
        })
    waits = [q["wait_ms"] for q in questions if q["wait_ms"] is not None]
    out += [
        ("question_count", len(questions), None),
        ("questions", questions, None),
        ("avg_wait_ms", round(sum(waits) / len(waits)) if waits else None, None),
        ("student_question_count",
         sum(1 for s in sentences if s.speaker == "student" and is_question(s.text)), None),
    ]

    # 每页课件停留时长
    out.append(("slide_dwell", [
        {"page_no": sl.page_no, "start_ms": sl.start_ms, "end_ms": sl.end_ms,
         "dwell_ms": (sl.end_ms - sl.start_ms) if sl.start_ms is not None else None}
        for sl in slides
    ], None))

    # 片段级
    by_seg: dict[int, list] = {}
    for s in sentences:
        if s.idx in seg_of:
            by_seg.setdefault(seg_of[s.idx], []).append(s)
    for gi, sents in by_seg.items():
        t, st = _talk(sents, "teacher"), _talk(sents, "student")
        out += [
            ("teacher_talk_ratio", _ratio(t, st), gi),
            ("speech_rate_wpm", _wpm(sents, who), gi),
            ("question_count", sum(1 for q in questions if q["segment"] == segments[gi].code), gi),
        ]
    return out


def summary_for_model(metrics: list[tuple[str, object, int | None]]) -> dict:
    """给大模型的输入：整节课的事实，不含逐片段明细。"""
    d = {k: v for k, v, seg in metrics if seg is None}
    qs = d.pop("questions", []) or []
    d["questions"] = [{"segment": q["segment"], "wait_ms": q["wait_ms"], "answered_by": q["answered_by"]} for q in qs]
    return d
