"""片段切分（设计方案第 7 节第 4 步）。纯程序，切分边界不由大模型决定。

切点来自三类信号：翻页、较长的停顿、师生说话人切换。
目标长度 30 秒到 3 分钟：过短的合并，过长的在停顿处再切。
"""
from dataclasses import dataclass

MIN_MS = 30_000
MAX_MS = 180_000
PAUSE_MS = 2_000

# 边界强度：越大越不该被合并掉
W_SPEAKER, W_PAUSE, W_SLIDE = 1, 2, 3


@dataclass
class Piece:
    first: int   # 句子下标（闭区间）
    last: int
    start_ms: int
    end_ms: int
    page_idx: int | None = None

    @property
    def dur(self) -> int:
        return self.end_ms - self.start_ms


def _page_at(ms: int, spans: list[tuple[int, int] | None]) -> int | None:
    for i, sp in enumerate(spans):
        if sp and sp[0] <= ms < sp[1]:
            return i
    return None


def segment(sentences: list, slide_spans: list[tuple[int, int] | None] | None = None) -> list[Piece]:
    """sentences: 有 start_ms / end_ms / speaker 的对象，按时间排序。
    slide_spans: 每页课件的时间段（未对齐为 None）；没有课件传 None 或空列表，
    此时只用停顿和说话人切换。
    """
    n = len(sentences)
    if n == 0:
        return []
    spans = slide_spans or []
    pages = [_page_at(s.start_ms, spans) for s in sentences]

    # 相邻句子之间的边界强度，strength[i] 是句 i 与 i+1 之间
    strength = []
    for i in range(n - 1):
        a, b = sentences[i], sentences[i + 1]
        w = 0
        if a.speaker != b.speaker and "unknown" not in (a.speaker, b.speaker):
            w = W_SPEAKER
        if b.start_ms - a.end_ms >= PAUSE_MS:
            w = W_PAUSE
        if pages[i] is not None and pages[i + 1] is not None and pages[i] != pages[i + 1]:
            w = W_SLIDE
        strength.append(w)

    def make(first, last):
        return Piece(first, last, sentences[first].start_ms, sentences[last].end_ms)

    # 1. 在所有信号处切开
    pieces, start = [], 0
    for i, w in enumerate(strength):
        if w:
            pieces.append(make(start, i))
            start = i + 1
    pieces.append(make(start, n - 1))

    # 2. 过短的合并：每次取最短的一段，并入边界较弱的一侧（一样弱则并入较短的邻居）
    while len(pieces) > 1:
        k = min(range(len(pieces)), key=lambda i: pieces[i].dur)
        if pieces[k].dur >= MIN_MS:
            break
        left = strength[pieces[k].first - 1] if k > 0 else None
        right = strength[pieces[k].last] if k < len(pieces) - 1 else None
        if right is None or (left is not None and (
                left < right or (left == right and pieces[k - 1].dur <= pieces[k + 1].dur))):
            pieces[k - 1:k + 1] = [make(pieces[k - 1].first, pieces[k].last)]
        else:
            pieces[k:k + 2] = [make(pieces[k].first, pieces[k + 1].last)]

    # 3. 过长的再切：优先在最长的停顿处，全程无停顿就在最接近中点的句子边界
    out, stack = [], pieces[::-1]
    while stack:
        p = stack.pop()
        if p.dur <= MAX_MS or p.first == p.last:
            out.append(p)
            continue
        cands = []
        for i in range(p.first, p.last):
            l = sentences[i].end_ms - p.start_ms
            r = p.end_ms - sentences[i + 1].start_ms
            gap = sentences[i + 1].start_ms - sentences[i].end_ms
            cands.append((min(l, r) >= MIN_MS, gap if gap >= 300 else 0, -abs(l - r), i))
        cut = max(cands)[3]
        stack.append(make(cut + 1, p.last))
        stack.append(make(p.first, cut))

    for p in out:
        p.page_idx = _page_at((p.start_ms + p.end_ms) // 2, spans)
    return out


def code_for(i: int) -> str:
    """片段编号：S001、S002……"""
    return f"S{i + 1:03d}"
