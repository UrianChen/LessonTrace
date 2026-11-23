"""报告 PDF。只打印时间码，不带链接；没有总分、等级或排名。"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT = "STSong-Light"   # reportlab 内置的中文 CID 字体，不需要字体文件
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

INK, MUTED, RULE = colors.HexColor("#1c2733"), colors.HexColor("#5b6875"), colors.HexColor("#d5dbe1")


def _style(name, size, leading, color=INK, **kw):
    return ParagraphStyle(name, fontName=FONT, fontSize=size, leading=leading, textColor=color,
                          wordWrap="CJK", **kw)


TITLE = _style("title", 18, 24, spaceAfter=4)
META = _style("meta", 9.5, 14, MUTED)
H2 = _style("h2", 13, 18, spaceBefore=14, spaceAfter=6)
BODY = _style("body", 10, 15)
LABEL = _style("label", 8.5, 12, MUTED, spaceBefore=6)
QUOTE = _style("quote", 9.5, 14, MUTED, leftIndent=10)


def tc(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def _p(text, style):
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def _pct(v):
    return "-" if v is None else f"{v * 100:.0f}%"


def render_pdf(content: dict) -> bytes:
    buf = BytesIO()
    note = content["header_note"]

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, A4[1] - 12 * mm, f"LessonTrace  |  {note}")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, str(doc.page))
        canvas.setStrokeColor(RULE)
        canvas.line(20 * mm, A4[1] - 14 * mm, A4[0] - 20 * mm, A4[1] - 14 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=22 * mm, bottomMargin=18 * mm, title=content["lesson"]["title"])
    L = content["lesson"]
    story = [_p(L["title"], TITLE),
             _p(f"Taught {L['taught_on']}  |  {L['teacher']}"
                + (f"  |  {L['dept']}" if L.get("dept") else "")
                + (f"  |  {tc(L['duration_ms'])}" if L.get("duration_ms") else ""), META),
             _p(f"Generated {content['generated_at'][:16].replace('T', ' ')} UTC  |  Version {content['version']}", META)]

    m = content.get("metrics") or {}
    story.append(_p("Class data", H2))
    rows = [
        ["Teacher talk", _pct(m.get("teacher_talk_ratio")), "Student talk", _pct(m.get("student_talk_ratio"))],
        ["Teacher turns", m.get("teacher_turns", "-"), "Student turns", m.get("student_turns", "-")],
        ["Questions", m.get("question_count", "-"), "Avg. wait after a question",
         "-" if m.get("avg_wait_ms") is None else f"{m['avg_wait_ms'] / 1000:.1f} s"],
        ["Speech rate", "-" if m.get("speech_rate_wpm") is None else f"{m['speech_rate_wpm']:.0f} wpm", "", ""],
    ]
    t = Table([[str(c) for c in r] for r in rows], colWidths=[36 * mm, 46 * mm, 36 * mm, 46 * mm])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                           ("TEXTCOLOR", (0, 0), (0, -1), MUTED), ("TEXTCOLOR", (2, 0), (2, -1), MUTED),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [t, _p("Computed facts, not judgements. Student speech may be under-recorded.", LABEL)]

    for d in content["dimensions"]:
        if not d["findings"]:
            continue
        story.append(_p(d["name"], H2))
        for i, f in enumerate(d["findings"], 1):
            story += [_p(f"{i}. {f['observation']}", BODY), _p("Suggestion", LABEL), _p(f["suggestion"], BODY),
                      _p("Evidence", LABEL)]
            for e in f["evidence"]:
                story.append(_p(f"[{tc(e['start_ms'])} - {tc(e['end_ms'])}]  \"{e['quote']}\"", QUOTE))
            story.append(Spacer(1, 8))

    if content.get("reflection"):
        story += [_p("Teacher's reflection", H2), _p(content["reflection"], BODY)]

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()
