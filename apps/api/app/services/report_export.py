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
from docx.shared import Cm, Pt, RGBColor
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
table { border-collapse: collapse; width: 100%; margin: 8pt 0; table-layout: fixed; }
th, td { border: 1px solid #cbd5e1; padding: 5pt 7pt; font-size: 9pt; vertical-align: top; word-wrap: break-word; -pdf-keep-with-next: false; }
th { background-color: #f1f5f9; font-weight: 600; text-align: left; color: #334155; }
/* 5-col Key Findings table: # | Issue | Risk | Recommendation | Severity */
table.findings th:nth-child(1), table.findings td:nth-child(1) { width: 4%; text-align: center; }
table.findings th:nth-child(2), table.findings td:nth-child(2) { width: 32%; }
table.findings th:nth-child(3), table.findings td:nth-child(3) { width: 25%; }
table.findings th:nth-child(4), table.findings td:nth-child(4) { width: 29%; }
table.findings th:nth-child(5), table.findings td:nth-child(5) { width: 10%; text-align: center; }
.severity-critical { color: #b91c1c; font-weight: 700; }
.severity-high     { color: #c2410c; font-weight: 700; }
.severity-medium   { color: #b45309; font-weight: 600; }
.severity-low      { color: #475569; font-weight: 600; }
/* Cover page: full first page, forces a break before the body starts. */
.cover { page-break-after: always; text-align: center; }
.cover .brand { color: #2563eb; font-weight: 700; letter-spacing: 1.5pt; font-size: 11pt; margin-top: 4cm; }
.cover .rule { border-top: 2px solid #2563eb; width: 4cm; margin: 1.2cm auto 0 auto; }
.cover .doc-kind { color: #64748b; font-size: 10pt; letter-spacing: 0.8pt; margin-top: 1.4cm; }
.cover .title { color: #0f172a; font-size: 26pt; font-weight: 600; margin-top: 0.6cm; line-height: 1.2; }
.cover .target-label { color: #64748b; font-size: 9.5pt; letter-spacing: 0.6pt; margin-top: 3cm; }
.cover .target-name { color: #0f172a; font-size: 16pt; font-weight: 600; margin-top: 0.3cm; }
.cover .confidential { color: #b91c1c; font-size: 10.5pt; font-weight: 700; letter-spacing: 1pt; margin-top: 3.5cm; }
.cover .date { color: #475569; font-size: 10pt; margin-top: 0.6cm; font-style: italic; }
/* Table of Contents page. The markdown 'toc' extension adds id="…" to
   every heading; the TOC entries below use <a href="#…"> against the
   same slug for clickable internal navigation in xhtml2pdf. */
.toc-page { page-break-after: always; }
.toc-title { font-size: 18pt; color: #0f172a; font-weight: 600; margin-top: 0.5cm; border-bottom: 2px solid #2563eb; padding-bottom: 6pt; margin-bottom: 14pt; }
.toc { margin-top: 8pt; }
.toc .toc-h2 { font-size: 10.5pt; color: #0f172a; margin: 6pt 0 2pt 0; font-weight: 500; }
.toc .toc-h2 a { color: #0f172a; text-decoration: none; }
.toc .toc-h3 { font-size: 9.5pt; color: #475569; margin: 2pt 0 2pt 1.2cm; }
.toc .toc-h3 a { color: #475569; text-decoration: none; }
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


# Header words that identify a Key Findings table (IT + EN). Used to tag
# the table with class="findings" so the column-width CSS applies.
_FINDINGS_HEADER_RE = re.compile(
    r"<th[^>]*>\s*(Issue|Argomento|Rischio|Risk)\s*</th>",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"<table([^>]*)>([\s\S]*?)</table>")


def _tag_findings_tables(html: str) -> str:
    """Add class="findings" to <table> elements whose headers match the
    Key Findings header row. Detection is content-based (one of the
    distinctive header words is enough)."""

    def _sub(m: re.Match[str]) -> str:
        attrs = m.group(1)
        inner = m.group(2)
        if not _FINDINGS_HEADER_RE.search(inner):
            return m.group(0)
        # Don't double-tag if a class is already there.
        if "class=" in attrs:
            return m.group(0)
        return f'<table{attrs} class="findings">{inner}</table>'

    return _TABLE_RE.sub(_sub, html)


def _detect_report_language(markdown: str) -> str:
    """Best-effort language detection from the rendered markdown."""
    if "Introduzione" in markdown or "STRETTAMENTE CONFIDENZIALE" in markdown:
        return "it"
    return "en"


def _strip_lead_block(markdown: str) -> str:
    """Drop the H1 title + deal-title + confidential + date lines.

    The cover page on PDF / DOCX already carries this information; keeping
    it at the top of the body would duplicate it on page 2. Strips from
    the start of the source to (but not including) the first ``## `` line.
    """
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith("### "):
            return "\n".join(lines[i:])
    return markdown


def _build_cover_html(deal_title: str, lang: str) -> str:
    """Render the PDF cover page (first page, page-break-after)."""
    from packages.agents.report_agent import _format_report_date
    from datetime import date as _date

    if lang == "it":
        doc_kind = "Legal Due Diligence Report"
        target_label = "PROGETTO"
        confidential = "STRETTAMENTE CONFIDENZIALE"
    else:
        doc_kind = "Legal Due Diligence Report"
        target_label = "PROJECT"
        confidential = "STRICTLY PRIVATE AND CONFIDENTIAL"
    title_main = "Red Flag Due Diligence Report"
    date_str = _format_report_date(_date.today(), lang)

    return (
        '<div class="cover">'
        '<div class="brand">DILIGENX</div>'
        '<div class="rule"></div>'
        f'<div class="doc-kind">{doc_kind}</div>'
        f'<div class="title">{title_main}</div>'
        f'<div class="target-label">{target_label}</div>'
        f'<div class="target-name">{html.escape(deal_title or "")}</div>'
        f'<div class="confidential">{confidential}</div>'
        f'<div class="date">{date_str}</div>'
        '</div>'
    )


def _build_toc_section(markdown_body: str, lang: str) -> str:
    """Build the TOC HTML by walking the markdown headings ourselves.

    The Markdown ``toc`` extension is enabled in the body renderer so
    headings receive ``id="..."`` attributes; we discard its auto-generated
    TOC because the nested-<ul> structure mis-nests H2s that have no H3
    children under the previous H2 (xhtml2pdf rendering quirk). Building a
    flat two-level structure here gives predictable layout and clickable
    anchors that match the body ids.
    """
    from markdown.extensions.toc import slugify as _toc_slugify

    entries: list[tuple[int, str, str]] = []
    for line in markdown_body.splitlines():
        if line.startswith("### "):
            text = line[4:].strip()
            entries.append((3, text, _toc_slugify(text, "-")))
        elif line.startswith("## "):
            text = line[3:].strip()
            entries.append((2, text, _toc_slugify(text, "-")))

    if not entries:
        return ""

    title = "Indice" if lang == "it" else "Table of Contents"
    parts: list[str] = [
        '<div class="toc-page">',
        f'<div class="toc-title">{title}</div>',
        '<div class="toc">',
    ]
    for level, text, slug in entries:
        cls = "toc-h2" if level == 2 else "toc-h3"
        parts.append(
            f'<div class="{cls}"><a href="#{slug}">{html.escape(text)}</a></div>'
        )
    parts.append("</div></div>")
    return "\n".join(parts)


def render_pdf(deal: "Deal", report: "Report") -> bytes:
    """Render the report as a branded A4 PDF."""
    raw_md = report.content or ""
    # Cover page already carries title/confidential/date — drop the lead
    # block from the body so it doesn't repeat on page 2.
    body_md = _colorize_severity_markdown(_strip_lead_block(raw_md))

    # Use the Markdown class (not the one-shot function) so we can read
    # the generated TOC and the auto-injected heading ids. ``toc_depth``
    # limits the TOC to ## and ### levels — the report only uses #-####.
    # The ``toc`` extension is enabled only for the side-effect of
    # injecting id="..." attributes on every heading; the TOC HTML itself
    # is rebuilt by _build_toc_section using the same slugify, so the
    # anchors line up.
    md_renderer = md_lib.Markdown(
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
        extension_configs={"toc": {"toc_depth": "2-3"}},
    )
    body_html = md_renderer.convert(body_md)
    body_html = _tag_findings_tables(body_html)

    lang = _detect_report_language(raw_md)
    cover_html = _build_cover_html(deal.title or "", lang)
    toc_section = _build_toc_section(body_md, lang)
    footer_html = (
        '<div id="footer_content">Diligenx &middot; '
        '<pdf:pagenumber/> / <pdf:pagecount/></div>'
    )

    full_html = (
        "<html><head><meta charset='utf-8'>"
        f"<style>{_PDF_CSS}</style></head><body>"
        f"{cover_html}{toc_section}{body_html}{footer_html}"
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
    # On a 5-column Key Findings table, apply the same column widths the
    # PDF export uses (% of A4 minus margins, approx. 16.5 cm usable).
    if _is_findings_header(headers):
        table.autofit = False
        widths_cm = [0.7, 5.5, 4.3, 4.9, 1.6]
        for col_idx, w in enumerate(widths_cm):
            for cell in table.columns[col_idx].cells:
                cell.width = Cm(w)
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


def _is_findings_header(headers: list[str]) -> bool:
    """Detect the Key Findings header row (IT or EN) so column widths apply."""
    if len(headers) != 5:
        return False
    joined = " ".join(headers).lower()
    return any(
        kw in joined
        for kw in ("issue", "argomento", "rischio", "risk")
    )


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


def _append_cover_docx(doc, deal_title: str, lang: str) -> None:
    """Add a single-page cover with brand / title / target / confidential
    label / date. Ends with a page break so the body starts on page 2."""
    from packages.agents.report_agent import _format_report_date
    from datetime import date as _date
    from docx.enum.text import WD_BREAK

    if lang == "it":
        target_label = "PROGETTO"
        confidential = "STRETTAMENTE CONFIDENZIALE"
    else:
        target_label = "PROJECT"
        confidential = "STRICTLY PRIVATE AND CONFIDENTIAL"

    def _centered(text: str, *, size: int, bold: bool = False,
                  color: RGBColor | None = None, italic: bool = False,
                  space_before: int = 0) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if space_before:
            p.paragraph_format.space_before = Pt(space_before)
        run = p.add_run(text)
        run.bold = bold
        run.italic = italic
        run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color

    _centered(
        "DILIGENX",
        size=11, bold=True,
        color=RGBColor(0x25, 0x63, 0xEB),
        space_before=120,  # ~4cm down the page
    )
    _centered("Legal Due Diligence Report", size=10,
              color=RGBColor(0x64, 0x74, 0x8B), space_before=24)
    _centered("Red Flag Due Diligence Report", size=24, bold=True,
              color=RGBColor(0x0F, 0x17, 0x2A), space_before=12)
    _centered(target_label, size=9,
              color=RGBColor(0x64, 0x74, 0x8B), space_before=60)
    _centered(deal_title or "", size=16, bold=True,
              color=RGBColor(0x0F, 0x17, 0x2A), space_before=6)
    _centered(confidential, size=10, bold=True,
              color=RGBColor(0xB9, 0x1C, 0x1C), space_before=80)
    _centered(_format_report_date(_date.today(), lang), size=10,
              italic=True, color=RGBColor(0x47, 0x55, 0x69),
              space_before=12)

    # Page break — body starts on next page.
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)


def render_docx(deal: "Deal", report: "Report") -> bytes:
    """Render the report as a branded DOCX."""
    doc = _DocxDocument()

    # Default font for Normal style
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    raw_md = report.content or ""
    lang = _detect_report_language(raw_md)
    _append_cover_docx(doc, deal.title or "", lang)

    _append_markdown_body(doc, _strip_lead_block(raw_md))

    # Page footer
    footer = doc.sections[0].footer
    fp = footer.paragraphs[0]
    fp.text = "Diligenx"
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
