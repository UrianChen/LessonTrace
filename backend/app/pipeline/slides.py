"""课件解析与对齐（设计方案第 7 节第 3 步）。

按页提取文字；计算每页与各时间窗口内文字稿的相似度；
用「页码大体递增」的约束求整体最优对应；相似度低的页标记为未对齐。
"""
import math
import re
from collections import Counter

WINDOW_MS = 30_000
MIN_SIMILARITY = 0.08     # 低于此值的页标记为未对齐
BACK_PENALTY = 0.25       # 往回翻一页的代价
SKIP_PENALTY = 0.01       # 每跳过一页的代价

_STOP = set("""a an the and or but if then so of to in on at for from by with as is are was were be been being
this that these those it its we you they i he she our your their there here what which who how why when where
do does did can could will would should may might must have has had not no yes just very also about into over
than them us me my his her let lets going go get got one two three now okay ok right well like know think see
up out all some any each more most other such only own same too s t don""".split())

_word = re.compile(r"[a-z][a-z0-9'\-]*")


def tokens(text: str) -> list[str]:
    return [w for w in _word.findall(text.lower()) if w not in _STOP and len(w) > 1]


def parse_slides(path: str) -> list[str]:
    """按页提取文字。支持 PDF 和 PPTX。"""
    lower = path.lower()
    if lower.endswith(".pdf"):
        import pymupdf
        with pymupdf.open(path) as doc:
            return [page.get_text("text").strip() for page in doc]
    if lower.endswith(".pptx"):
        from pptx import Presentation
        pages = []
        for slide in Presentation(path).slides:
            parts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    parts.append(shape.text_frame.text)
                if getattr(shape, "has_table", False) and shape.has_table:
                    for row in shape.table.rows:
                        parts.append(" ".join(c.text for c in row.cells))
            pages.append("\n".join(p for p in parts if p.strip()).strip())
        return pages
    raise ValueError("slides must be .pdf or .pptx")


def extract_terms(pages: list[str], limit: int = 60) -> list[str]:
    """从课件文字里抽专业术语，作为提示词传给识别模型。取较长、反复出现或首字母大写的词。"""
    counts, display = Counter(), {}
    for text in pages:
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9'\-]{3,}", text):
            key = raw.lower()
            if key in _STOP:
                continue
            counts[key] += 2 if raw[0].isupper() and len(raw) > 5 else 1
            display.setdefault(key, raw)
    ranked = sorted(counts, key=lambda k: (-counts[k] * min(len(k), 12), k))
    return [display[k] for k in ranked[:limit]]


def _tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    df = Counter(w for d in docs for w in set(d))
    n = len(docs)
    vecs = []
    for d in docs:
        tf = Counter(d)
        v = {w: (1 + math.log(c)) * math.log((n + 1) / (df[w] + 0.5)) for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    return vecs


def _cos(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def align_slides(pages: list[str], sentences: list) -> list[tuple[int, int] | None]:
    """返回每页的 (start_ms, end_ms)，未对齐的页为 None。

    sentences: 有 start_ms / end_ms / text 属性的对象，按时间排序。
    """
    if not pages or not sentences:
        return [None] * len(pages)
    total = sentences[-1].end_ms
    n_win = max(1, math.ceil(total / WINDOW_MS))
    win_tokens: list[list[str]] = [[] for _ in range(n_win)]
    for s in sentences:
        w = min(n_win - 1, ((s.start_ms + s.end_ms) // 2) // WINDOW_MS)
        win_tokens[w] += tokens(s.text)
    page_tokens = [tokens(p) for p in pages]
    if not any(page_tokens):
        return [None] * len(pages)

    vecs = _tfidf(page_tokens + win_tokens)
    pv, wv = vecs[:len(pages)], vecs[len(pages):]
    P, W = len(pages), n_win
    sim = [[_cos(wv[w], pv[p]) for p in range(P)] for w in range(W)]

    # 动态规划：每个窗口选一页，总相似度最大；往回翻和跳页有代价
    NEG = float("-inf")
    score = [sim[0][p] - SKIP_PENALTY * p for p in range(P)]
    back = []
    for w in range(1, W):
        new, ptr = [NEG] * P, [0] * P
        for p in range(P):
            v, q = NEG, 0
            for prev in range(P):
                cost = (SKIP_PENALTY * max(0, p - prev - 1) if p >= prev
                        else BACK_PENALTY * (prev - p))
                if score[prev] - cost > v:
                    v, q = score[prev] - cost, prev
            new[p], ptr[p] = v + sim[w][p], q
        score = new
        back.append(ptr)
    p = max(range(P), key=lambda i: score[i])
    path = [p]
    for ptr in reversed(back):
        p = ptr[p]
        path.append(p)
    path.reverse()

    # 每页取被分配到的最长连续窗口段
    result: list[tuple[int, int] | None] = [None] * P
    runs: dict[int, tuple[int, int]] = {}
    w = 0
    while w < W:
        e = w
        while e + 1 < W and path[e + 1] == path[w]:
            e += 1
        pg = path[w]
        if pg not in runs or (e - w) > (runs[pg][1] - runs[pg][0]):
            runs[pg] = (w, e)
        w = e + 1
    for pg, (a, b) in runs.items():
        mean = sum(sim[x][pg] for x in range(a, b + 1)) / (b - a + 1)
        if mean >= MIN_SIMILARITY:
            result[pg] = (a * WINDOW_MS, min(total, (b + 1) * WINDOW_MS))
    return result
