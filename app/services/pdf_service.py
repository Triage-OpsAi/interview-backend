import math
import textwrap
from typing import Any, Iterable, List, Optional


PAGE_WIDTH = 612
PAGE_HEIGHT = 842
MARGIN = 42

INK = (0.07, 0.09, 0.13)
MUTED = (0.34, 0.38, 0.45)
TEAL = (0.05, 0.46, 0.43)
CYAN = (0.06, 0.62, 0.74)
GREEN = (0.10, 0.63, 0.36)
AMBER = (0.92, 0.57, 0.09)
RED = (0.80, 0.18, 0.18)
NAVY = (0.05, 0.08, 0.15)
LIGHT_BG = (0.96, 0.98, 0.99)
BORDER = (0.82, 0.87, 0.91)
WHITE = (1.0, 1.0, 1.0)


def _sanitize(text: Any) -> str:
    return str(text or "").encode("latin-1", errors="replace").decode("latin-1")


def _escape(text: Any) -> str:
    value = _sanitize(text)
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _color(rgb: tuple[float, float, float], op: str = "rg") -> str:
    return f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} {op}"


def _wrap(text: Any, width: int) -> List[str]:
    value = _sanitize(text).replace("\r", " ").strip()
    if not value:
        return [""]
    lines: List[str] = []
    for paragraph in value.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=width) or [""])
    return lines


def _recommendation_color(recommendation: str) -> tuple[float, float, float]:
    value = recommendation.lower()
    if "strong hire" in value or value == "hire":
        return GREEN
    if "borderline" in value:
        return AMBER
    if "no hire" in value:
        return RED
    return CYAN


def _score_color(score: int) -> tuple[float, float, float]:
    if score >= 8:
        return GREEN
    if score >= 6:
        return CYAN
    if score >= 4:
        return AMBER
    return RED


class PdfReport:
    def __init__(self) -> None:
        self.pages: List[List[str]] = []
        self.ops: List[str] = []
        self.y = PAGE_HEIGHT - MARGIN
        self.new_page()

    def new_page(self) -> None:
        if self.ops:
            self.pages.append(self.ops)
        self.ops = []
        self.y = PAGE_HEIGHT - MARGIN

    def finish(self) -> bytes:
        if self.ops:
            self.pages.append(self.ops)
            self.ops = []
        total = len(self.pages)
        for index, ops in enumerate(self.pages, start=1):
            ops.append(_color(BORDER, "RG"))
            ops.append("0.6 w")
            ops.append(f"{MARGIN:.2f} 28.00 m {PAGE_WIDTH - MARGIN:.2f} 28.00 l S")
            ops.append(_color(MUTED, "rg"))
            ops.append(f"BT /F1 8 Tf 1 0 0 1 {MARGIN:.2f} 16.00 Tm (Confidential hiring report) Tj ET")
            ops.append(f"BT /F1 8 Tf 1 0 0 1 {PAGE_WIDTH - MARGIN - 54:.2f} 16.00 Tm (Page {index} of {total}) Tj ET")
        return _serialize_pdf(self.pages)

    def ensure(self, height: float) -> None:
        if self.y - height < MARGIN:
            self.new_page()

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: Optional[tuple[float, float, float]] = None,
        stroke: Optional[tuple[float, float, float]] = None,
    ) -> None:
        if fill:
            self.ops.append(_color(fill, "rg"))
        if stroke:
            self.ops.append(_color(stroke, "RG"))
            self.ops.append("0.8 w")
        operator = "B" if fill and stroke else "f" if fill else "S"
        self.ops.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re {operator}")

    def text(
        self,
        value: Any,
        x: float,
        y: float,
        *,
        size: int = 10,
        font: str = "F1",
        color: tuple[float, float, float] = INK,
    ) -> None:
        self.ops.append(_color(color, "rg"))
        self.ops.append(f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape(value)}) Tj ET")

    def wrapped(
        self,
        value: Any,
        x: float,
        width: float,
        *,
        size: int = 10,
        line_height: int = 14,
        font: str = "F1",
        color: tuple[float, float, float] = MUTED,
    ) -> None:
        max_chars = max(24, int(width / (size * 0.48)))
        for line in _wrap(value, max_chars):
            self.ensure(line_height + 6)
            self.text(line, x, self.y, size=size, font=font, color=color)
            self.y -= line_height

    def section(self, title: str, color: tuple[float, float, float] = TEAL) -> None:
        self.ensure(34)
        self.y -= 8
        self.rect(MARGIN, self.y - 6, 7, 18, fill=color)
        self.text(title, MARGIN + 14, self.y, size=14, font="F2", color=INK)
        self.y -= 22

    def paragraph_card(self, title: str, body: Any, color: tuple[float, float, float] = TEAL) -> None:
        lines = _wrap(body, 88)
        first = True
        while lines:
            available = self.y - MARGIN - 54
            max_lines = max(1, int(available // 13))
            if max_lines < 3:
                self.new_page()
                continue
            chunk = lines[:max_lines]
            lines = lines[max_lines:]
            height = max(62, 42 + len(chunk) * 13)
            top = self.y
            self.rect(MARGIN, top - height, PAGE_WIDTH - (MARGIN * 2), height, fill=LIGHT_BG, stroke=BORDER)
            self.rect(MARGIN, top - 5, PAGE_WIDTH - (MARGIN * 2), 5, fill=color)
            card_title = title if first else f"{title} (continued)"
            self.text(card_title, MARGIN + 14, top - 24, size=11, font="F2", color=INK)
            y = top - 42
            for line in chunk:
                self.text(line, MARGIN + 14, y, size=9, color=MUTED)
                y -= 13
            self.y = top - height - 12
            first = False
            if lines:
                self.new_page()

    def star(self, cx: float, cy: float, radius: float, color: tuple[float, float, float], filled: bool) -> None:
        points = []
        for index in range(10):
            angle = -math.pi / 2 + (index * math.pi / 5)
            current_radius = radius if index % 2 == 0 else radius * 0.42
            points.append((cx + math.cos(angle) * current_radius, cy + math.sin(angle) * current_radius))
        path = [f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
        path.extend(f"{x:.2f} {y:.2f} l" for x, y in points[1:])
        path.append("h")
        if filled:
            self.ops.append(_color(color, "rg"))
            self.ops.append(" ".join(path) + " f")
        else:
            self.ops.append(_color(BORDER, "RG"))
            self.ops.append("0.7 w")
            self.ops.append(" ".join(path) + " S")

    def stars(self, score: int, x: float, y: float) -> None:
        safe_score = max(0, min(10, int(score or 0)))
        color = _score_color(safe_score)
        for index in range(10):
            self.star(x + index * 12, y, 5, color, index < safe_score)

    def score_card(self, score: dict) -> None:
        category = score.get("category", "Uncategorized")
        value = max(0, min(10, int(score.get("score") or 0)))
        reasoning = score.get("reasoning") or "No reasoning provided."
        lines = _wrap(reasoning, 76)
        height = 82 + len(lines) * 12
        self.ensure(height + 8)
        top = self.y
        accent = _score_color(value)
        self.rect(MARGIN, top - height, PAGE_WIDTH - (MARGIN * 2), height, fill=WHITE, stroke=BORDER)
        self.rect(MARGIN, top - height, 6, height, fill=accent)
        self.text(category, MARGIN + 16, top - 22, size=11, font="F2", color=INK)
        self.text(f"{value}/10", PAGE_WIDTH - MARGIN - 44, top - 22, size=11, font="F2", color=accent)
        self.stars(value, MARGIN + 16, top - 42)
        bar_width = PAGE_WIDTH - (MARGIN * 2) - 32
        self.rect(MARGIN + 16, top - 60, bar_width, 7, fill=(0.90, 0.93, 0.96))
        self.rect(MARGIN + 16, top - 60, bar_width * (value / 10), 7, fill=accent)
        y = top - 76
        for line in lines:
            self.text(line, MARGIN + 16, y, size=8, color=MUTED)
            y -= 12
        self.y = top - height - 10


def _serialize_pdf(page_ops: List[List[str]]) -> bytes:
    objects: List[bytes] = []
    page_object_numbers = []

    def add_object(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    catalog_num = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_num = add_object(b"")
    font_regular = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    for ops in page_ops:
        content = "\n".join(ops).encode("latin-1", errors="replace")
        content_num = add_object(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
        page_num = add_object(
            f"<< /Type /Page /Parent {pages_num} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
            f"/Contents {content_num} 0 R >>".encode()
        )
        page_object_numbers.append(page_num)

    kids = " ".join(f"{num} 0 R" for num in page_object_numbers)
    objects[pages_num - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_numbers)} >>".encode()
    objects[catalog_num - 1] = b"<< /Type /Catalog /Pages 2 0 R >>"

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(payload)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


def build_curated_report_pdf(payload: dict) -> bytes:
    candidate = payload.get("candidate") or {}
    job = payload.get("job") or {}
    interview = payload.get("interview") or {}
    report = payload.get("report") or {}
    scores = payload.get("scores") or []
    transcript = payload.get("transcript") or []

    recommendation = report.get("recommendation") or "Pending"
    recommendation_color = _recommendation_color(recommendation)
    overall = interview.get("overall_score")

    pdf = PdfReport()
    pdf.rect(0, PAGE_HEIGHT - 116, PAGE_WIDTH, 116, fill=NAVY)
    pdf.rect(0, PAGE_HEIGHT - 116, PAGE_WIDTH, 8, fill=TEAL)
    pdf.text("AI Interview Report", MARGIN, PAGE_HEIGHT - 50, size=24, font="F2", color=WHITE)
    pdf.text(candidate.get("full_name", "Candidate"), MARGIN, PAGE_HEIGHT - 76, size=13, font="F2", color=(0.80, 0.92, 0.94))
    pdf.text(f"{job.get('job_title', 'Role')} at {job.get('company_name', 'Company')}", MARGIN, PAGE_HEIGHT - 96, size=10, color=(0.70, 0.77, 0.86))
    pdf.rect(PAGE_WIDTH - MARGIN - 126, PAGE_HEIGHT - 82, 126, 34, fill=recommendation_color)
    pdf.text(str(recommendation), PAGE_WIDTH - MARGIN - 114, PAGE_HEIGHT - 62, size=11, font="F2", color=WHITE)
    pdf.y = PAGE_HEIGHT - 142

    pdf.section("Decision Snapshot", TEAL)
    card_width = (PAGE_WIDTH - (MARGIN * 2) - 20) / 3
    top = pdf.y
    cards = [
        ("Overall", f"{overall if overall is not None else 'N/A'}/100", CYAN),
        ("Status", interview.get("status", "N/A"), TEAL),
        ("Transcript", f"{len(transcript)} turns", AMBER),
    ]
    for index, (label, value, color) in enumerate(cards):
        x = MARGIN + index * (card_width + 10)
        pdf.rect(x, top - 56, card_width, 56, fill=LIGHT_BG, stroke=BORDER)
        pdf.rect(x, top - 5, card_width, 5, fill=color)
        pdf.text(label, x + 10, top - 22, size=8, font="F2", color=MUTED)
        pdf.text(value, x + 10, top - 42, size=13, font="F2", color=INK)
    pdf.y = top - 76

    pdf.paragraph_card("Recommendation", f"{recommendation}. {report.get('recommendation_reason', '')}", recommendation_color)
    pdf.paragraph_card("Summary", report.get("summary", "Report has not been generated."), TEAL)
    pdf.paragraph_card("Strengths", report.get("strengths", "N/A"), GREEN)
    pdf.paragraph_card("Risks And Weaknesses", report.get("weaknesses", "N/A"), RED)
    pdf.paragraph_card("Key Observations", report.get("key_observations", "N/A"), CYAN)
    pdf.paragraph_card("Technical Assessment", report.get("technical_assessment", "N/A"), TEAL)
    pdf.paragraph_card("Behavioral Assessment", report.get("behavioral_assessment", "N/A"), AMBER)

    pdf.section("Skill Scorecard", CYAN)
    if scores:
        for score in scores:
            pdf.score_card(score)
    else:
        pdf.paragraph_card("No Scores", "No score rows were available for this report.", RED)

    pdf.section("Evidence Appendix", TEAL)
    pdf.wrapped(
        "The full transcript remains available in the recruiter dashboard. This appendix includes concise excerpts only; "
        "scores and recommendations are based on the complete captured interview.",
        MARGIN,
        PAGE_WIDTH - (MARGIN * 2),
        size=9,
        line_height=13,
    )
    pdf.y -= 8
    for item in transcript:
        question = item.get("question_text") or "Question unavailable"
        answer = item.get("answer_text") or "[no answer]"
        words = len(str(answer).split()) if answer != "[no answer]" else 0
        excerpt = str(answer).strip()
        if len(excerpt) > 420:
            excerpt = excerpt[:417].rsplit(" ", 1)[0] + "..."
        pdf.paragraph_card(
            f"Q{item.get('sequence_number')} evidence - {item.get('category') or 'general'}",
            f"Prompt: {question}\nResponse excerpt ({words} words total): {excerpt}",
            CYAN,
        )

    return pdf.finish()


def build_report_pdf(lines: Iterable[str]) -> bytes:
    payload = {
        "candidate": {"full_name": "Candidate"},
        "job": {"job_title": "Interview", "company_name": "Company"},
        "interview": {"overall_score": None, "status": "N/A"},
        "report": {
            "recommendation": "N/A",
            "summary": "\n".join(_sanitize(line) for line in lines),
            "recommendation_reason": "",
        },
        "scores": [],
        "transcript": [],
    }
    return build_curated_report_pdf(payload)
