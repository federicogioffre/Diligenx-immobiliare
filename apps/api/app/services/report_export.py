"""Due-diligence report export — Markdown → PDF and Markdown → DOCX.

Both renderers accept the already-generated `Report` row (markdown in
`Report.content`) plus the owning `Deal` for branding metadata, and return
the binary file as `bytes`. No LLM calls, no DB writes.

PDF is produced by running Markdown through `markdown` → HTML and then
`xhtml2pdf` → PDF. xhtml2pdf is pure Python, so no extra system packages
are required in the Railway container.

DOCX is built with python-docx directly from a line-by-line Markdown
walk. Full Markdown parsing isn't needed: the report follows a known
shape (## sections, bullet lists, one pipe-table, `[SEVERITY]` labels,
**bold** inline), and a small state machine handles all of it.
"""
from __future__ import annotations

import html
import io
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import markdown as md_lib
from docx import Document as _DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from xhtml2pdf import pisa

if TYPE_CHECKING:
    from app.models.deal import Deal
    from app.models.report import Report


# ── PDF rendering ──────────────────────────────────────────────────────────

_PDF_CSS = """
@page {
  size: A4;
  margin: 2.2cm 2cm 2.5cm 2cm;
  @frame footer_frame {
    -pdf-frame-content: footer_content;
    bottom: 1.2cm;
    margin-left: 2cm;
    margin-right: 2cm;
    height: 0.8cm;
  }
}
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; color: #1e293b; line-height: 1.5; text-align: justify; }
h1 { font-size: 18pt; color: #0f172a; margin-top: 0; text-align: left; }
h2 { font-size: 14pt; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 4pt; margin-top: 18pt; text-align: left; }
h3 { font-size: 11pt; color: #334155; margin-top: 10pt; text-align: left; }
h4 { font-size: 10.5pt; color: #0f172a; margin-top: 10pt; margin-bottom: 4pt; text-align: left; }
p  { margin: 6pt 0; text-align: justify; }
ul, ol { margin: 6pt 0; padding-left: 20pt; }
li { margin: 2pt 0; text-align: justify; }
strong { color: #0f172a; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
th, td { border: 1px solid #cbd5e1; padding: 5pt 8pt; font-size: 9.5pt; }
th { background-color: #f1f5f9; font-weight: 600; text-align: left; color: #334155; }
.severity-critical { color: #b91c1c; font-weight: 700; }
.severity-high     { color: #c2410c; font-weight: 700; }
.severity-medium   { color: #b45309; font-weight: 600; }
.severity-low      { color: #475569; font-weight: 600; }
.doc-header { border-bottom: 2px solid #2563eb; padding-bottom: 12pt; margin-bottom: 16pt; }
.doc-header .brand { color: #2563eb; font-weight: 700; letter-spacing: 0.5pt; font-size: 10pt; }
.doc-header .deal-title { font-size: 16pt; font-weight: 600; margin-top: 4pt; color: #0f172a; }
.doc-header .deal-meta { font-size: 9pt; color: #64748b; margin-top: 4pt; }
#footer_content { font-size: 8.5pt; color: #94a3b8; text-align: center; }
"""


_SEVERITY_RE = re.compile(r"\[(CRITICAL|HIGH|MEDIUM|LOW)\]")


def _colorize_severity_markdown(md_text: str) -> str:
    """Wrap [SEVERITY] labels in colored spans.

    The substitution happens on the Markdown source BEFORE md→HTML conversion,
    so the spans land inside whatever enclosing element Markdown produces
    (paragraph, list item, heading).
    """

    def _sub(m: re.Match[str]) -> str:
        level = m.group(1)
        return f'<span class="severity-{level.lower()}">[{level}]</span>'

    return _SEVERITY_RE.sub(_sub, md_text)


def render_pdf(deal: "Deal", report: "Report") -> bytes:
    """Render the report as a branded A4 PDF."""
    body_md = _colorize_severity_markdown(report.content or "")
    body_html = md_lib.markdown(
        body_md,
        extensions=["tables", "fenced_code", "sane_lists"],
    )

    generated_on = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    header_html = (
        '<div class="doc-header">'
        '<div class="brand">DILIGENX &middot; DUE DILIGENCE REPORT</div>'
        f'<div class="deal-title">{html.escape(deal.title or "")}</div>'
        f'<div class="deal-meta">Generato il {generated_on}</div>'
        "</div>"
    )
    footer_html = (
        '<div id="footer_content">Diligenx &middot; '
        '<pdf:pagenumber/> / <pdf:pagecount/></div>'
    )

    full_html = (
        "<html><head><meta charset='utf-8'>"
        f"<style>{_PDF_CSS}</style></head><body>"
        f"{header_html}{body_html}{footer_html}"
        "</body></html>"
    )

    buf = io.BytesIO()
    result = pisa.CreatePDF(src=full_html, dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"xhtml2pdf produced {result.err} error(s)")
    return buf.getvalue()


# ── DOCX rendering ─────────────────────────────────────────────────────────

_SEVERITY_COLORS: dict[str, RGBColor] = {
    "CRITICAL": RGBColor(0xB9, 0x1C, 0x1C),
    "HIGH":     RGBColor(0xC2, 0x41, 0x0C),
    "MEDIUM":   RGBColor(0xB4, 0x53, 0x09),
    "LOW":      RGBColor(0x47, 0x55, 0x69),
}

# Split a line into pieces, preserving [SEVERITY] tokens and **bold** segments.
# Capture groups ensure the delimiters survive re.split().
_INLINE_SPLIT_RE = re.compile(
    r"(\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|\*\*[^*]+\*\*)"
)


def _render_inline(paragraph, text: str) -> None:
    """Append `text` to `paragraph`, styling severity labels and bold runs."""
    for piece in _INLINE_SPLIT_RE.split(text):
        if not piece:
            continue
        sev_match = _SEVERITY_RE.fullmatch(piece)
        if sev_match:
            run = paragraph.add_run(piece)
            run.bold = True
            run.font.color.rgb = _SEVERITY_COLORS[sev_match.group(1)]
            continue
        if piece.startswith("**") and piece.endswith("**"):
            run = paragraph.add_run(piece[2:-2])
            run.bold = True
            continue
        paragraph.add_run(piece)


def _render_table(doc, lines: list[str], start: int) -> int:
    """Render a Markdown pipe-table into the DOCX document.

    Returns the index immediately AFTER the last consumed line.
    """
    header_line = lines[start]
    # skip separator line (lines[start+1])
    body_start = start + 2

    def _cells(row: str) -> list[str]:
        # Strip leading/trailing pipes, then split.
        inner = row.strip()
        if inner.startswith("|"):
            inner = inner[1:]
        if inner.endswith("|"):
            inner = inner[:-1]
        return [c.strip() for c in inner.split("|")]

    headers = _cells(header_line)

    # Collect body rows until the table ends (blank line or non-pipe line).
    i = body_start
    rows: list[list[str]] = []
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip() or not line.startswith("|"):
            break
        rows.append(_cells(line))
        i += 1

    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Grid Accent 1"
    hdr_cells = table.rows[0].cells
    for col, text in enumerate(headers):
        hdr_cells[col].text = ""
        p = hdr_cells[col].paragraphs[0]
        run = p.add_run(text)
        run.bold = True
    for r, row in enumerate(rows, start=1):
        cells = table.rows[r].cells
        for col, text in enumerate(row[: len(headers)]):
            cells[col].text = ""
            _render_inline(cells[col].paragraphs[0], text)

    return i


def _append_markdown_body(doc, md_text: str) -> None:
    """Line-by-line Markdown → DOCX renderer for the known report shape."""
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        # Headings (order matters: check longer prefix first)
        if line.startswith("#### "):
            # Finding headings carry [SEVERITY] tokens — render inline so
            # they get their color in DOCX too.
            h = doc.add_heading("", level=4)
            _render_inline(h, line[5:].strip())
            i += 1
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
            i += 1
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
            i += 1
            continue
        if line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
            i += 1
            continue

        # Bullet list
        m = re.match(r"^[-*]\s+(.*)", line)
        if m:
            p = doc.add_paragraph(style="List Bullet")
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            _render_inline(p, m.group(1))
            i += 1
            continue

        # Numbered list
        m = re.match(r"^\d+\.\s+(.*)", line)
        if m:
            p = doc.add_paragraph(style="List Number")
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            _render_inline(p, m.group(1))
            i += 1
            continue

        # Pipe-table (current line starts with `|` and next line is the separator)
        if (
            line.startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[i + 1])
        ):
            i = _render_table(doc, lines, i)
            continue

        # Plain paragraph
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _render_inline(p, line)
        i += 1


def render_docx(deal: "Deal", report: "Report") -> bytes:
    """Render the report as a branded DOCX."""
    doc = _DocxDocument()

    # Default font for Normal style
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Title block (brand + deal + date)
    p = doc.add_paragraph()
    run = p.add_run("DILIGENX · DUE DILIGENCE REPORT")
    run.bold = True
    run.font.color.rgb = RGBColor(0x25, 0x63, 0xEB)
    run.font.size = Pt(9)

    p = doc.add_paragraph()
    run = p.add_run(deal.title or "")
    run.bold = True
    run.font.size = Pt(16)

    p = doc.add_paragraph()
    run = p.add_run(
        f"Generato il {datetime.now(timezone.utc).strftime('%d/%m/%Y')}"
    )
    run.italic = True
    run.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
    run.font.size = Pt(9)

    doc.add_paragraph()  # spacer before body

    _append_markdown_body(doc, report.content or "")

    # Page footer
    footer = doc.sections[0].footer
    fp = footer.paragraphs[0]
    fp.text = "Diligenx"
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
