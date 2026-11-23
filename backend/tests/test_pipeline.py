"""片段切分的边界、课件对齐、规则统计、说话人标注。"""
from types import SimpleNamespace as NS

from app.pipeline.metrics import compute_metrics, is_question
from app.pipeline.segmenter import MAX_MS, MIN_MS, segment
from app.pipeline.slides import align_slides, extract_terms
from app.pipeline.speakers import label_speakers


def sents(spec):
    """spec: [(speaker, start_s, end_s)]"""
    return [NS(idx=i, speaker=sp, start_ms=int(a * 1000), end_ms=int(b * 1000), text=f"sentence {i} here.")
            for i, (sp, a, b) in enumerate(spec)]


def continuous(n, each=5.0, speaker="teacher", gap=0.0):
    return [(speaker, i * (each + gap), i * (each + gap) + each) for i in range(n)]


def covers_everything(pieces, n):
    assert pieces[0].first == 0 and pieces[-1].last == n - 1
    for a, b in zip(pieces, pieces[1:]):
        assert b.first == a.last + 1


# ----- 切分边界 -----

def test_no_sentences():
    assert segment([], None) == []


def test_empty_slides_falls_back_to_pauses_and_speakers():
    spec = continuous(10) + [("teacher", 60 + i * 5, 65 + i * 5) for i in range(10)]   # 50s 处停顿 10s
    s = sents(spec)
    for slides in (None, [], [None, None]):
        pieces = segment(s, slides)
        covers_everything(pieces, len(s))
        assert [(p.first, p.last) for p in pieces] == [(0, 9), (10, 19)]
        assert all(p.page_idx is None for p in pieces)


def test_no_pauses_at_all_still_respects_max_length():
    s = sents(continuous(240, each=5.0))          # 20 分钟一口气讲完，没有任何停顿
    pieces = segment(s, None)
    covers_everything(pieces, len(s))
    assert len(pieces) > 1
    assert all(MIN_MS <= p.dur <= MAX_MS for p in pieces)


def test_single_speaker_with_pauses():
    s = sents(continuous(60, each=8.0, gap=2.5))  # 只有老师，每句之间停 2.5 秒
    pieces = segment(s, None)
    covers_everything(pieces, len(s))
    assert all(MIN_MS <= p.dur <= MAX_MS for p in pieces)


def test_short_exchanges_are_merged_not_left_as_tiny_segments():
    spec = continuous(12)                                             # 60s 讲授
    t = 60.0
    for i in range(6):                                                # 快速问答，每轮几秒
        spec += [("teacher", t, t + 3), ("student", t + 3.2, t + 5)]
        t += 5.5
    spec += [("teacher", t + i * 5, t + i * 5 + 5) for i in range(12)]
    s = sents(spec)
    pieces = segment(s, None)
    covers_everything(pieces, len(s))
    assert all(p.dur >= MIN_MS for p in pieces)


def test_lesson_shorter_than_minimum_is_one_segment():
    s = sents([("teacher", 0, 5), ("student", 6, 8), ("teacher", 9, 14)])
    assert [(p.first, p.last) for p in segment(s, None)] == [(0, 2)]


def test_slide_change_is_a_cut_point_and_pages_are_assigned():
    s = sents(continuous(24))                                         # 120s 不停顿
    pieces = segment(s, [(0, 60_000), (60_000, 120_000)])
    assert [(p.first, p.last, p.page_idx) for p in pieces] == [(0, 11, 0), (12, 23, 1)]


# ----- 课件对齐 -----

def _lecture():
    topics = [
        "limits function approaches value input point limit definition",
        "derivative slope tangent rate change differentiate derivative",
        "integral area under curve antiderivative integrate sum",
    ]
    out, t = [], 0
    for topic in topics:
        for _ in range(8):
            out.append(NS(start_ms=t, end_ms=t + 14000, text=topic, speaker="teacher"))
            t += 15000
    return out


def test_alignment_follows_page_order():
    pages = ["Limits: the value a function approaches. Definition of a limit.",
             "Derivatives: slope of the tangent, rate of change.",
             "Integrals: area under a curve, antiderivative."]
    spans = align_slides(pages, _lecture())
    assert all(spans)
    assert spans[0][0] < spans[1][0] < spans[2][0]
    assert abs(spans[1][0] - 120_000) <= 30_000 and abs(spans[2][0] - 240_000) <= 30_000


def test_unrelated_page_is_left_unaligned():
    pages = ["Limits: the value a function approaches.", "Photosynthesis chlorophyll mitochondria ribosome",
             "Integrals: area under a curve."]
    spans = align_slides(pages, _lecture())
    assert spans[1] is None and spans[0] and spans[2]


def test_alignment_with_no_slides_or_blank_slides():
    assert align_slides([], _lecture()) == []
    assert align_slides(["", "   "], _lecture()) == [None, None]


def test_terms_prefer_subject_words():
    terms = extract_terms(["The Squeeze Theorem and the epsilon-delta definition", "Squeeze Theorem examples"])
    assert "Squeeze" in terms and "the" not in [t.lower() for t in terms]


# ----- 规则统计 -----

def test_question_rule():
    assert is_question("So what does this limit equal?")
    assert is_question("Can anyone tell me the answer")       # 助动词开头，没有问号
    assert not is_question("The limit equals one.")


def test_metrics_are_facts():
    s = [NS(idx=0, speaker="teacher", start_ms=0, end_ms=30000, text="word " * 60),
         NS(idx=1, speaker="teacher", start_ms=30000, end_ms=33000, text="So what is the answer?"),
         NS(idx=2, speaker="student", start_ms=37000, end_ms=47000, text="I think it is one."),
         NS(idx=3, speaker="teacher", start_ms=48000, end_ms=58000, text="Yes exactly.")]
    segs = [NS(code="S001", sentence_from=0, sentence_to=3, start_ms=0, end_ms=58000)]
    slides = [NS(page_no=1, start_ms=0, end_ms=58000), NS(page_no=2, start_ms=None, end_ms=None)]
    m = {(k, g): v for k, v, g in compute_metrics(s, segs, slides)}
    assert m[("teacher_talk_ms", None)] == 43000 and m[("student_talk_ms", None)] == 10000
    assert m[("teacher_turns", None)] == 2 and m[("student_turns", None)] == 1
    assert m[("question_count", None)] == 1
    q = m[("questions", None)][0]
    assert q["wait_ms"] == 4000 and q["segment"] == "S001" and q["answered_by"] == "student"
    assert m[("slide_dwell", None)][1]["dwell_ms"] is None
    assert m[("question_count", 0)] == 1
    assert not any("score" in k or "grade" in k for k, _ in m)


def test_metrics_with_no_students():
    s = [NS(idx=0, speaker="teacher", start_ms=0, end_ms=10000, text="Just me talking today.")]
    m = {(k, g): v for k, v, g in compute_metrics(s, [], [])}
    assert m[("student_talk_ratio", None)] == 0 and m[("student_turns", None)] == 0


def test_metrics_without_speaker_labels_fall_back_to_all_sentences():
    s = [NS(idx=0, speaker="unknown", start_ms=0, end_ms=30000, text="word " * 60),
         NS(idx=1, speaker="unknown", start_ms=30000, end_ms=33000, text="So what is the answer?"),
         NS(idx=2, speaker="unknown", start_ms=37000, end_ms=47000, text="I think it is one.")]
    m = {(k, g): v for k, v, g in compute_metrics(s, [], [])}
    assert m[("speakers_identified", None)] is False
    assert m[("question_count", None)] == 1 and m[("questions", None)][0]["wait_ms"] == 4000
    assert m[("speech_rate_wpm", None)] > 0
    assert m[("teacher_talk_ratio", None)] is None      # 占比不编


# ----- 说话人 -----

def test_longest_speaker_is_teacher():
    raw = [{"speaker": "SPEAKER_01", "start_ms": 0, "end_ms": 2000, "text": "a"},
           {"speaker": "SPEAKER_00", "start_ms": 2000, "end_ms": 60000, "text": "b"},
           {"speaker": None, "start_ms": 60000, "end_ms": 61000, "text": "c"}]
    assert [s["speaker"] for s in label_speakers(raw)] == ["student", "teacher", "unknown"]
