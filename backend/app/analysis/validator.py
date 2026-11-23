"""证据校验（设计方案第 9 节）。全部是确定性程序，不调用模型。

规则 1 结构合法 → 整次调用重试（由 runner 处理）
规则 2 维度合法 → 丢弃条目
规则 3 片段存在 → 丢弃证据
规则 4 引文匹配 → 丢弃证据
规则 5 至少一条有效证据 → 退回重新生成一次，仍失败丢弃
规则 6 无打分表述 → 退回重写一次，仍失败丢弃
规则 7 去重 → 合并
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator
from rapidfuzz import fuzz

from .schema import FINDINGS_SCHEMA

FUZZY_THRESHOLD = 90.0   # 相似度 0.9
MIN_FUZZY_CHARS = 12     # 太短的引文不做模糊匹配，必须是严格子串


@dataclass
class SegSentence:
    idx: int
    start_ms: int
    end_ms: int
    speaker: str
    text: str


@dataclass
class Seg:
    code: str
    start_ms: int
    end_ms: int
    sentences: list[SegSentence]
    page_no: int | None = None
    db_id: int | None = None

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


# ---------- 规则 1 ----------

_schema_validator = Draft202012Validator(FINDINGS_SCHEMA)


def parse_output(raw: str) -> tuple[dict | None, str | None]:
    """返回 (数据, 错误)。结构不合法时数据为 None。"""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        return None, f"not valid JSON: {e}"
    errors = sorted(_schema_validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        return None, f"schema violation at {'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
    return data, None


# ---------- 规则 4 ----------

def normalize(text: str) -> str:
    """统一大小写、去掉标点和多余空白。"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(" " if unicodedata.category(c)[0] in "PSZC" else c for c in text)
    return " ".join(text.split())


def quote_matches(quote: str, segment_text: str) -> bool:
    q, t = normalize(quote), normalize(segment_text)
    if not q:
        return False
    if q in t:
        return True
    if len(q) < MIN_FUZZY_CHARS:
        return False
    return fuzz.partial_ratio(q, t) >= FUZZY_THRESHOLD


# ---------- 规则 6 ----------

_NUM = r"\d+(?:\.\d+)?"
SCORING_PATTERNS = [
    r"\bscor(?:e|es|ed|ing)\b",
    r"\bgrad(?:e|es|ed|ing)\b",
    r"\brat(?:ing|ings|ed)\b",
    r"\brank(?:s|ed|ing|ings)?\b",
    rf"\b{_NUM}\s*(?:out\s+of|/)\s*(?:5|10|100)\b",
    r"\bout\s+of\s+(?:five|ten|a\s+hundred)\b",
    rf"\b{_NUM}\s*(?:%|percent)\s+(?:mark|effective|effectiveness|quality|performance|success)\b",
    r"\b(?:mark|marks)\s+(?:of|is|was)\b",
    rf"\b{_NUM}\s*stars?\b",
    r"\b[A-F][+-]?\s+(?:level|grade|tier)\b",
    r"\b(?:above|below|around|about)\s+(?:the\s+)?average\b",
    r"\b(?:better|worse|stronger|weaker|more\s+\w+|less\s+\w+)\s+than\s+(?:most|other|many|typical|average|the\s+average)\b",
    r"\bcompared\s+(?:to|with)\s+(?:other|most|typical|average|peer)",
    r"\b(?:other|most|typical|average)\s+(?:teachers?|instructors?|lecturers?|colleagues?|classes)\b",
    r"\b(?:than|compared\s+(?:to|with)|relative\s+to|among|versus|vs\.?)\s+(?:(?:your|his|her|their|its|the)\s+)?peers\b",
    r"\btop\s+\d+\s*(?:%|percent)",
    r"\bpercentile\b",
    r"\bbenchmark",
]
# 课堂内容里正常出现的说法，不是在给老师打分：课程的成绩构成、学生的成绩、年级。
# 匹配前先把它们拿掉，其余的 grade / score 仍按打分表述处理。
_ALLOWED = re.compile(
    r"\bgrad(?:e|ing)\s+(?:weights?|weighting|breakdown|polic(?:y|ies)|components?|scheme|rubrics?|criteria|levels?|school)\b"
    r"|\b(?:course|final|letter|homework|exam|assignment|participation|students?(?:'s|')?|their)\s+grades?\b"
    r"|\bgrade\s+(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE)
_scoring_re = re.compile("|".join(f"(?:{p})" for p in SCORING_PATTERNS), re.IGNORECASE)


def find_scoring(text: str) -> str | None:
    """返回命中的打分/排名/比较表述，没有则 None。"""
    m = _scoring_re.search(_ALLOWED.sub(" ", text))
    return m.group(0) if m else None


# ---------- 引文定位 ----------

def locate_quote(quote: str, seg: Seg) -> tuple[int, int]:
    """在片段内定位引文所在的句子，返回 (start_ms, end_ms)；定位不到退回片段起止。"""
    q = normalize(quote)
    if not q or not seg.sentences:
        return seg.start_ms, seg.end_ms
    norms = [normalize(s.text) for s in seg.sentences]
    # 引文可能跨句：找最短的连续句子窗口，使引文是其子串
    for width in range(1, len(norms) + 1):
        for i in range(0, len(norms) - width + 1):
            if q in " ".join(norms[i:i + width]):
                return seg.sentences[i].start_ms, seg.sentences[i + width - 1].end_ms
    # 模糊匹配通过的引文：取最像的那一句
    best = max(range(len(norms)), key=lambda i: fuzz.partial_ratio(q, norms[i]))
    return seg.sentences[best].start_ms, seg.sentences[best].end_ms


# ---------- 规则 2–6 ----------

@dataclass
class Rejected:
    finding: dict
    rule: int
    reason: str


@dataclass
class PassResult:
    passed: list[dict] = field(default_factory=list)
    retry: list[Rejected] = field(default_factory=list)      # 规则 5、6：可退回一次
    counts: dict = field(default_factory=dict)


def new_counts() -> dict:
    return {
        "findings_raw": 0, "evidence_raw": 0, "evidence_valid": 0,
        "rule1_schema_retries": 0, "rule2_dimension_dropped": 0,
        "rule3_segment_missing": 0, "rule4_quote_mismatch": 0,
        "rule5_no_evidence_retried": 0, "rule5_no_evidence_dropped": 0,
        "rule6_scoring_retried": 0, "rule6_scoring_dropped": 0,
        "rule7_merged": 0, "findings_passed": 0,
    }


def check_findings(findings: list[dict], segs: dict[str, Seg], dimensions: list[str],
                   counts: dict, is_retry: bool = False) -> PassResult:
    """对一批条目跑规则 2–6。is_retry=True 时规则 5、6 不再退回，直接丢弃。"""
    res = PassResult(counts=counts)
    for f in findings:
        if not is_retry:
            counts["findings_raw"] += 1
            counts["evidence_raw"] += len(f["evidence"])
        if f["dimension"] not in dimensions:                      # 规则 2
            counts["rule2_dimension_dropped"] += 1
            continue
        valid = []
        for ev in f["evidence"]:
            seg = segs.get(ev["segment_id"].strip().upper())
            if seg is None:                                       # 规则 3
                if not is_retry:
                    counts["rule3_segment_missing"] += 1
                continue
            if not quote_matches(ev["quote"], seg.text):          # 规则 4
                if not is_retry:
                    counts["rule4_quote_mismatch"] += 1
                continue
            if not is_retry:
                counts["evidence_valid"] += 1
            valid.append({"segment_id": seg.code, "quote": ev["quote"].strip()})
        cleaned = {**f, "evidence": valid}
        if not valid:                                             # 规则 5
            if is_retry:
                counts["rule5_no_evidence_dropped"] += 1
            else:
                counts["rule5_no_evidence_retried"] += 1
                res.retry.append(Rejected(f, 5, "no evidence quote could be found verbatim in the cited segment"))
            continue
        hit = find_scoring(f["observation"] + "\n" + f["suggestion"])
        if hit:                                                   # 规则 6
            if is_retry:
                counts["rule6_scoring_dropped"] += 1
            else:
                counts["rule6_scoring_retried"] += 1
                res.retry.append(Rejected(cleaned, 6, f'contains scoring/ranking/comparison wording: "{hit}"'))
            continue
        res.passed.append(cleaned)
    return res


# ---------- 规则 7 ----------

def dedupe(findings: list[dict], counts: dict) -> list[dict]:
    """同一维度且证据片段相同的条目合并为一条：保留先出现的文字，证据取并集。"""
    merged: dict[tuple, dict] = {}
    for f in findings:
        key = (f["dimension"], frozenset(e["segment_id"] for e in f["evidence"]))
        if key not in merged:
            merged[key] = {**f, "evidence": list(f["evidence"])}
            continue
        counts["rule7_merged"] += 1
        seen = {(e["segment_id"], normalize(e["quote"])) for e in merged[key]["evidence"]}
        for e in f["evidence"]:
            if (e["segment_id"], normalize(e["quote"])) not in seen:
                merged[key]["evidence"].append(e)
    return list(merged.values())


def attach_times(findings: list[dict], segs: dict[str, Seg]) -> list[dict]:
    """从片段表查出每个证据的起止时间，并定位引文所在句子。"""
    out = []
    for f in findings:
        evidence = []
        for e in f["evidence"]:
            seg = segs[e["segment_id"]]
            qs, qe = locate_quote(e["quote"], seg)
            evidence.append({**e, "start_ms": seg.start_ms, "end_ms": seg.end_ms,
                             "quote_start_ms": qs, "quote_end_ms": qe})
        out.append({**f, "evidence": evidence})
    return out
