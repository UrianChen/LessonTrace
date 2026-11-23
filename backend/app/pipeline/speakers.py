"""说话人标注：累计说话时长最长的说话人标为老师，其余标为学生。老师可在审阅页纠正。"""
from collections import defaultdict


def label_speakers(raw: list[dict]) -> list[dict]:
    """raw: [{start_ms, end_ms, speaker(分离模型给的标签或 None), text}]
    返回同样的列表，speaker 换成 teacher / student / unknown。
    """
    total = defaultdict(int)
    for s in raw:
        if s.get("speaker"):
            total[s["speaker"]] += s["end_ms"] - s["start_ms"]
    teacher = max(total, key=total.get) if total else None
    out = []
    for s in raw:
        sp = s.get("speaker")
        role = "unknown" if not sp else ("teacher" if sp == teacher else "student")
        out.append({**s, "speaker": role})
    return out
