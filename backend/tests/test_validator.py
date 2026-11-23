"""证据校验的每条规则：各有通过和不通过的样例。"""
import json

import pytest

from app.analysis.llm import LLMError
from app.analysis.runner import run_analysis
from app.analysis.validator import (Seg, SegSentence, check_findings, dedupe, find_scoring,
                                    locate_quote, new_counts, parse_output, quote_matches)

from .conftest import FakeLLM, finding

DIMS = [{"name": "Questioning and interaction", "definition": "q"},
        {"name": "Clarity of explanation", "definition": "c"},
        {"name": "Alignment with slides", "definition": "a", "requires_slides": True}]
NAMES = [d["name"] for d in DIMS]


def segs():
    s1 = Seg("S001", 0, 39000, [
        SegSentence(0, 0, 4000, "teacher", "Good morning everyone, today we are going to talk about limits."),
        SegSentence(1, 34000, 37000, "teacher", "So what does this limit equal?"),
        SegSentence(2, 37200, 39000, "teacher", "Right, it equals one."),
    ])
    s2 = Seg("S002", 39500, 70000, [
        SegSentence(3, 39500, 47000, "teacher", "Now let us move on to one sided limits."),
        SegSentence(4, 48000, 52000, "student", "Is the left limit always the same as the right limit?"),
    ])
    return [s1, s2]


def seg_map():
    return {s.code: s for s in segs()}


# ----- 规则 1：结构合法 -----

def test_rule1_valid_structure_passes():
    data, err = parse_output(json.dumps({"findings": [finding()]}))
    assert err is None and len(data["findings"]) == 1


@pytest.mark.parametrize("raw", [
    "not json at all",
    json.dumps({"items": []}),
    json.dumps({"findings": [{"dimension": "x", "observation": "o", "suggestion": "s"}]}),       # 缺 evidence
    json.dumps({"findings": [{**finding(), "score": 8}]}),                                        # 多出分数字段
    json.dumps({"findings": [finding(evidence=[{"segment_id": "S001", "quote": "q", "start_ms": 5}])]}),  # 模型不许给时间
])
def test_rule1_invalid_structure_rejected(raw):
    data, err = parse_output(raw)
    assert data is None and err


def test_rule1_retries_whole_call_then_gives_up():
    llm = FakeLLM("garbage", {"findings": [finding()]})
    result = run_analysis(llm, segs(), [], {}, DIMS)
    assert len(result.findings) == 1 and result.stats["rule1_schema_retries"] == 1

    with pytest.raises(LLMError):
        run_analysis(FakeLLM("garbage", "garbage", "garbage"), segs(), [], {}, DIMS)


# ----- 规则 2：维度合法 -----

def test_rule2_unknown_dimension_dropped():
    counts = new_counts()
    res = check_findings([finding(), finding(dimension="Overall teaching quality")], seg_map(), NAMES, counts)
    assert len(res.passed) == 1 and counts["rule2_dimension_dropped"] == 1


# ----- 规则 3：片段存在 -----

def test_rule3_fabricated_segment_id_drops_that_evidence_only():
    counts = new_counts()
    f = finding(evidence=[{"segment_id": "S999", "quote": "So what does this limit equal?"},
                          {"segment_id": "S001", "quote": "Right, it equals one."}])
    res = check_findings([f], seg_map(), NAMES, counts)
    assert counts["rule3_segment_missing"] == 1
    assert [e["segment_id"] for e in res.passed[0]["evidence"]] == ["S001"]


# ----- 规则 4：引文匹配 -----

@pytest.mark.parametrize("quote", [
    "So what does this limit equal?",
    "so what does this limit equal",                      # 大小写、标点
    "So   what does this limit equal?  Right, it equals one.",   # 多余空白，跨句
    "So what does this limt equal? Right, it equals one.",       # 一处错字，模糊匹配 >= 0.9
])
def test_rule4_matching_quotes(quote):
    assert quote_matches(quote, seg_map()["S001"].text)


@pytest.mark.parametrize("quote", [
    "The teacher asked what the limit equals and then answered it himself.",   # 改写过的引文
    "Is the left limit always the same as the right limit?",                   # 出自别的片段
    "limt",                                                                     # 太短又不是子串
    "",
])
def test_rule4_non_matching_quotes(quote):
    assert not quote_matches(quote, seg_map()["S001"].text)


def test_rule4_paraphrased_quote_counted():
    counts = new_counts()
    f = finding(evidence=[{"segment_id": "S001", "quote": "Students were given no time to answer the question."}])
    check_findings([f], seg_map(), NAMES, counts)
    assert counts["rule4_quote_mismatch"] == 1 and counts["evidence_valid"] == 0


# ----- 规则 5：至少一条有效证据 -----

def test_rule5_regenerated_once_then_kept():
    bad = finding(evidence=[{"segment_id": "S777", "quote": "made up"}])
    llm = FakeLLM({"findings": [bad]}, {"findings": [finding()]})
    result = run_analysis(llm, segs(), [], {}, DIMS)
    assert len(result.findings) == 1 and len(llm.calls) == 2
    assert result.stats["rule5_no_evidence_retried"] == 1 and result.stats["rule5_no_evidence_dropped"] == 0


def test_rule5_still_failing_after_retry_is_dropped():
    bad = finding(evidence=[{"segment_id": "S777", "quote": "made up"}])
    llm = FakeLLM({"findings": [bad]}, {"findings": [bad]})
    result = run_analysis(llm, segs(), [], {}, DIMS)
    assert result.findings == [] and len(llm.calls) == 2      # 只退回一次
    assert result.stats["rule5_no_evidence_dropped"] == 1


def test_rule5_empty_evidence_list():
    counts = new_counts()
    res = check_findings([finding(evidence=[])], seg_map(), NAMES, counts)
    assert not res.passed and res.retry[0].rule == 5


# ----- 规则 6：无打分表述 -----

@pytest.mark.parametrize("text", [
    "I would score this explanation 8 out of 10.",
    "This questioning deserves a high grade.",
    "Overall rating: strong.",
    "This ranks among the clearest explanations.",
    "Clarity: 7/10.",
    "The pacing was better than most teachers manage.",
    "Wait time is below average.",
    "Compared to other instructors, there were few questions.",
    "This would be in the top 10% of lessons.",
    "A typical teacher would pause longer here.",
    "The explanation was clearer than their peers usually manage.",
    "I would grade this explanation highly.",
    "The grade for this lesson would be a B.",
])
def test_rule6_scoring_language_detected(text):
    assert find_scoring(text)


@pytest.mark.parametrize("text", [
    "The question was answered by the teacher almost immediately, leaving students no time to respond.",
    "Pause for a few seconds after asking, or invite one student to share their reasoning first.",
    "The teacher spoke for about 90% of the lesson time.",
    "The slide lists three steps, and the explanation covered two of them.",
    "Students were asked to compare the left and right limits.",
    "The explanation was upgraded with a concrete example.",
    # 真实公开课上遇到过的误判：同学、课程成绩构成
    "The teacher acknowledged the answer and then invited peers to build on it.",
    "Briefly stating the grade weights aloud might pre-empt later questions.",
    "The slide lists how the final grade is split between homework and exams.",
    "This example comes from a grade 9 textbook.",
])
def test_rule6_plain_description_passes(text):
    assert find_scoring(text) is None


def test_rule6_rewritten_once_then_dropped_if_still_scoring():
    scored = finding(observation="The questioning scores 4 out of 10.")
    llm = FakeLLM({"findings": [scored]}, {"findings": [scored]})
    result = run_analysis(llm, segs(), [], {}, DIMS)
    assert result.findings == []
    assert result.stats["rule6_scoring_retried"] == 1 and result.stats["rule6_scoring_dropped"] == 1

    llm = FakeLLM({"findings": [scored]}, {"findings": [finding()]})
    assert len(run_analysis(llm, segs(), [], {}, DIMS).findings) == 1


# ----- 规则 7：去重 -----

def test_rule7_same_dimension_same_segments_merged():
    counts = new_counts()
    a = finding(evidence=[{"segment_id": "S001", "quote": "So what does this limit equal?"}])
    b = finding(observation="Another wording.", evidence=[{"segment_id": "S001", "quote": "Right, it equals one."}])
    out = dedupe([a, b], counts)
    assert len(out) == 1 and counts["rule7_merged"] == 1
    assert out[0]["observation"] == a["observation"] and len(out[0]["evidence"]) == 2


def test_rule7_different_dimension_or_segments_kept():
    counts = new_counts()
    a = finding()
    b = finding(dimension="Clarity of explanation")
    c = finding(evidence=[{"segment_id": "S002", "quote": "Now let us move on to one sided limits."}])
    assert len(dedupe([a, b, c], counts)) == 3 and counts["rule7_merged"] == 0


# ----- 时间从片段表查，引文定位到句子 -----

def test_times_come_from_segments_and_quote_is_located():
    result = run_analysis(FakeLLM({"findings": [finding()]}), segs(), [], {}, DIMS)
    ev = result.findings[0]["evidence"][0]
    assert (ev["start_ms"], ev["end_ms"]) == (0, 39000)
    assert (ev["quote_start_ms"], ev["quote_end_ms"]) == (34000, 37000)


def test_locate_quote_spanning_two_sentences():
    seg = seg_map()["S001"]
    assert locate_quote("what does this limit equal? Right, it equals one.", seg) == (34000, 39000)


# ----- 其他 -----

def test_slides_dimension_skipped_when_nothing_aligned():
    f = finding(dimension="Alignment with slides")
    result = run_analysis(FakeLLM({"findings": [f, finding()]}), segs(), [], {}, DIMS)
    assert "Alignment with slides" in result.stats["skipped_dimensions"]
    assert [x["dimension"] for x in result.findings] == ["Questioning and interaction"]


def test_citation_validity_stat():
    f = finding(evidence=[{"segment_id": "S001", "quote": "So what does this limit equal?"},
                          {"segment_id": "S404", "quote": "nope"}])
    result = run_analysis(FakeLLM({"findings": [f]}), segs(), [], {}, DIMS)
    assert result.stats["citation_validity"] == 0.5
    assert result.raw_output[0]["purpose"] == "analysis"
