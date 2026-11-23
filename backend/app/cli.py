"""里程碑 1：命令行最小闭环。

输入一份片段 JSON，调用大模型生成条目，跑证据校验，输出通过的条目。

    python -m app.cli analyze samples/segments_example.json --out findings.json

输入格式：
{
  "segments": [{"id": "S001", "start_ms": 0, "end_ms": 42000, "slide_page": 1,
                "sentences": [{"speaker": "teacher", "text": "...", "start_ms": 0, "end_ms": 3100}]}],
  "slides":   [{"page_no": 1, "text": "..."}],      # 可省略
  "metrics":  {...}                                  # 可省略
}
片段也可以只给 "text"（手工整理的文字稿），此时整段视为一句。
"""
import argparse
import json
import sys

from .analysis.llm import get_llm
from .analysis.runner import run_analysis
from .analysis.validator import Seg, SegSentence
from .config import load_dimensions


def load_segments(data: dict) -> tuple[list[Seg], list[dict]]:
    segs = []
    for s in data["segments"]:
        sentences = s.get("sentences") or [{"speaker": s.get("speaker", "teacher"), "text": s["text"],
                                             "start_ms": s["start_ms"], "end_ms": s["end_ms"]}]
        segs.append(Seg(
            code=s["id"], start_ms=s["start_ms"], end_ms=s["end_ms"], page_no=s.get("slide_page"),
            sentences=[SegSentence(i, x.get("start_ms", s["start_ms"]), x.get("end_ms", s["end_ms"]),
                                   x.get("speaker", "teacher"), x["text"]) for i, x in enumerate(sentences)],
        ))
    slides = []
    for sl in data.get("slides", []):
        slides.append({**sl, "segments": [g.code for g in segs if g.page_no == sl["page_no"]]})
    return segs, slides


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="片段 JSON → 通过校验的条目")
    a.add_argument("segments")
    a.add_argument("--out", help="输出文件，默认打印到标准输出")
    args = ap.parse_args(argv)

    with open(args.segments, encoding="utf-8") as f:
        data = json.load(f)
    segs, slides = load_segments(data)
    result = run_analysis(get_llm(), segs, slides, data.get("metrics", {}), load_dimensions())
    out = {"model": result.model, "prompt_version": result.prompt_version,
           "stats": result.stats, "findings": result.findings}
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"{len(result.findings)} findings passed → {args.out}", file=sys.stderr)
        print(json.dumps(result.stats, ensure_ascii=False, indent=2), file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
