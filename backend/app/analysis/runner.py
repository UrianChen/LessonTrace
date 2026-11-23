"""大模型分析 + 证据校验的编排。不碰数据库，输入输出都是普通数据，命令行和阶段任务共用。"""
import json
from dataclasses import dataclass

from . import prompts
from .llm import LLMClient, LLMError
from .schema import FINDINGS_SCHEMA, TITLES_SCHEMA
from .validator import (Seg, attach_times, check_findings, dedupe, new_counts,
                        parse_output)

SCHEMA_ATTEMPTS = 3          # 规则 1：结构不合法时整次调用重试
LONG_LESSON_WORDS = 14000    # 超过则按维度分次调用，每次仍给全部片段


@dataclass
class AnalysisResult:
    findings: list[dict]        # 通过校验的条目，证据带时间
    raw_output: list[dict]      # 每次调用的原始输出
    stats: dict
    model: str
    prompt_version: str


def _call(llm: LLMClient, system: str, user: str, counts: dict, raw: list, purpose: str) -> dict:
    last_err = None
    for _ in range(SCHEMA_ATTEMPTS):
        text = llm.complete_json(system, user, FINDINGS_SCHEMA)
        raw.append({"purpose": purpose, "output": text})
        data, err = parse_output(text)
        if data is not None:
            return data
        counts["rule1_schema_retries"] += 1
        last_err = err
    raise LLMError(f"model output failed schema validation {SCHEMA_ATTEMPTS} times: {last_err}")


def run_analysis(llm: LLMClient, segs: list[Seg], slides: list[dict], metrics: dict,
                 dimensions: list[dict]) -> AnalysisResult:
    counts, raw = new_counts(), []
    seg_map = {s.code: s for s in segs}
    skipped = {}

    # 课件一页都没对齐上：跳过依赖课件的维度并说明原因
    has_aligned = any(s.get("segments") for s in slides)
    active = []
    for d in dimensions:
        if d.get("requires_slides") and not has_aligned:
            skipped[d["name"]] = ("no slides were uploaded" if not slides
                                  else "slides could not be aligned with the transcript")
        else:
            active.append(d)
    names = [d["name"] for d in active]

    words = sum(len(s.text.split()) for s in segs)
    batches = [[d] for d in active] if words > LONG_LESSON_WORDS else [active]

    passed, retry = [], []
    for batch in batches:
        if not batch:
            continue
        user = prompts.build_analysis_prompt(segs, slides, metrics, batch)
        data = _call(llm, prompts.SYSTEM, user, counts, raw, "analysis")
        res = check_findings(data["findings"], seg_map, [d["name"] for d in batch], counts)
        passed += res.passed
        retry += res.retry

    if retry:  # 规则 5、6：退回一次
        user = prompts.build_repair_prompt(retry, seg_map)
        try:
            data = _call(llm, prompts.SYSTEM, user, counts, raw, "repair")
            repaired = check_findings(data["findings"], seg_map, names, counts, is_retry=True).passed
        except LLMError as e:
            raw.append({"purpose": "repair", "error": str(e)})
            repaired = []
        passed += repaired
        # 模型没交回来的条目也算丢弃
        missing = len(retry) - len(repaired) - counts["rule5_no_evidence_dropped"] - counts["rule6_scoring_dropped"]
        if missing > 0:
            r5 = sum(1 for r in retry if r.rule == 5)
            give5 = min(missing, max(0, r5 - counts["rule5_no_evidence_dropped"]))
            counts["rule5_no_evidence_dropped"] += give5
            counts["rule6_scoring_dropped"] += missing - give5

    passed = dedupe(passed, counts)
    counts["findings_passed"] = len(passed)
    stats = {**counts, "skipped_dimensions": skipped, "transcript_words": words,
             "citation_validity": (round(counts["evidence_valid"] / counts["evidence_raw"], 4)
                                   if counts["evidence_raw"] else None)}
    return AnalysisResult(attach_times(passed, seg_map), raw, stats, llm.model, prompts.PROMPT_VERSION)


def generate_titles(llm: LLMClient, segs: list[Seg]) -> dict[str, str]:
    """每段一句标题，只用于界面展示。失败时返回空，不影响流水线。"""
    try:
        text = llm.complete_json(prompts.TITLES_SYSTEM, prompts.build_titles_prompt(segs), TITLES_SCHEMA)
        items = json.loads(text)["titles"]
        return {str(t["segment_id"]).strip().upper(): str(t["title"]).strip()[:200] for t in items}
    except Exception:
        return {}
