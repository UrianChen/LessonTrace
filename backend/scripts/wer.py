"""转写词错率（设计方案第 14 节）。把人工校对过的参考文本和系统的转写结果做对比。

    python -m scripts.wer reference.txt --lesson 3                 # 整节课
    python -m scripts.wer reference.txt --lesson 3 --from 600 --to 1200   # 只比第 10–20 分钟（抽查 10 分钟）
    python -m scripts.wer reference.txt --hyp hypothesis.txt       # 两个文本文件

词错率 = (替换 + 删除 + 插入) / 参考词数。比较前统一大小写、去掉标点。
"""
import argparse

from app.analysis.validator import normalize


def wer(reference: str, hypothesis: str) -> dict:
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    # 编辑距离，同时记录三类错误
    prev = [(j, 0, 0, j) for j in range(len(hyp) + 1)]          # (cost, sub, del, ins)
    for i in range(1, len(ref) + 1):
        cur = [(i, 0, i, 0)]
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur.append(prev[j - 1])
                continue
            s, d, n = prev[j - 1], prev[j], cur[j - 1]
            best = min((s[0], 0), (d[0], 1), (n[0], 2))
            if best[1] == 0:
                cur.append((s[0] + 1, s[1] + 1, s[2], s[3]))
            elif best[1] == 1:
                cur.append((d[0] + 1, d[1], d[2] + 1, d[3]))
            else:
                cur.append((n[0] + 1, n[1], n[2], n[3] + 1))
        prev = cur
    cost, sub, dele, ins = prev[-1]
    return {"wer": round(cost / max(1, len(ref)), 4), "reference_words": len(ref), "hypothesis_words": len(hyp),
            "substitutions": sub, "deletions": dele, "insertions": ins}


def main():
    ap = argparse.ArgumentParser(prog="python -m scripts.wer")
    ap.add_argument("reference", help="人工校对过的参考文本")
    ap.add_argument("--lesson", type=int, help="课程 ID，从数据库取转写结果")
    ap.add_argument("--hyp", help="转写结果文本文件（不用数据库时）")
    ap.add_argument("--from", dest="start", type=float, default=0, help="起始秒")
    ap.add_argument("--to", dest="end", type=float, default=None, help="结束秒")
    args = ap.parse_args()

    with open(args.reference, encoding="utf-8") as f:
        reference = f.read()
    if args.hyp:
        with open(args.hyp, encoding="utf-8") as f:
            hypothesis = f.read()
    elif args.lesson:
        from app.db import SessionLocal
        from app.pipeline.stages import get_sentences
        db = SessionLocal()
        try:
            lo, hi = args.start * 1000, (args.end * 1000 if args.end is not None else float("inf"))
            hypothesis = " ".join(s.text for s in get_sentences(db, args.lesson) if lo <= s.start_ms < hi)
        finally:
            db.close()
    else:
        ap.error("give --lesson or --hyp")
    for k, v in wer(reference, hypothesis).items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
