"""Exports (PLAN.md C1–C4): one JSON document (schema v1, see docs/export-schema.md)
rendered three ways: JSON, Word (python-docx) and PDF (reportlab). Word and PDF use
the same layout so the two downloads read the same."""

import io
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Jurisdiction, Rule, Source, SourceStatus, Taxonomy
from app.pipeline import UPLOAD_SCHEME
from app.regulations import Regulations

SCHEMA_VERSION = "1.0"
BRAND = (0xB5, 0x20, 0x25)
INK = (0x22, 0x22, 0x22)
MUTED = (0x6B, 0x6B, 0x6B)
DISCLAIMER = (
    "This summary is compiled from public sources for internal use by Jordan & Skala "
    "Engineers. Items marked Pending have not been verified by a reviewer. Always confirm "
    "requirements with the authority having jurisdiction before relying on them for design "
    "or permitting."
)
TYPE_LABEL = {"state": "State", "county": "County", "city": "City",
              "consolidated": "City-county", "district": "District"}
STATUS_LABEL = {"verified": "Verified", "pending": "Pending"}


def _layer(j: Jurisdiction) -> dict[str, Any]:
    return {"fips": j.fips, "name": j.name, "type": j.type.value, "state": j.state_code}


def _source_ref(s: Source | None) -> dict[str, Any] | None:
    if s is None:
        return None
    upload = s.url.startswith(UPLOAD_SCHEME)
    return {
        "id": s.id, "url": None if upload else s.url, "title": s.title,
        "kind": "upload" if upload else "web",
        "last_checked": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
    }


def build_export(
    session: Session, regs: Regulations, *, disciplines: set[str] | None = None,
    address: str | None = None,
) -> dict[str, Any]:
    tax = {t.id: t for t in session.scalars(select(Taxonomy))}
    layer_ids = {j.id: j for j in regs.stack}
    rules: list[Rule] = [
        r for r in regs.rules
        if not disciplines or (r.discipline_id and tax[r.discipline_id].key in disciplines)
    ]
    srcs = {s.id: s for s in session.scalars(select(Source).where(
        Source.id.in_({r.source_id for r in rules if r.source_id})))}
    monitored = list(session.scalars(select(Source).where(
        Source.jurisdiction_id.in_(layer_ids), Source.status == SourceStatus.APPROVED)
        .order_by(Source.jurisdiction_id, Source.id)))

    def tax_ref(tid: int | None) -> dict[str, str] | None:
        return {"key": tax[tid].key, "label": tax[tid].label} if tid and tid in tax else None

    shown_rule_ids = {r.id for r in rules}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "JSE Local Regulations",
        "jurisdiction": _layer(regs.jurisdiction),
        "address": address,
        "stack": [_layer(j) for j in regs.stack],
        "filters": {"include_pending": regs.include_pending,
                    "disciplines": sorted(disciplines) if disciplines else None},
        "disclaimer": DISCLAIMER,
        "effective_codes": [
            {
                "code": e.code, "edition": e.edition,
                "effective_on": e.effective_on.isoformat() if e.effective_on else None,
                "status": e.status.value, "layer": _layer(e.jurisdiction),
                "overrides": [{"layer": _layer(o.jurisdiction), "edition": o.edition}
                              for o in e.overrides],
                "rule_id": e.rule.id,
            }
            for e in regs.effective_codes if e.rule.id in shown_rule_ids
        ],
        "rules": [
            {
                "id": r.id, "layer": _layer(layer_ids[r.jurisdiction_id]),
                "title": r.title, "summary": r.summary,
                "discipline": tax_ref(r.discipline_id), "category": tax_ref(r.category_id),
                "code_ref": r.code_ref, "code_edition": r.code_edition,
                "effective_on": r.effective_on.isoformat() if r.effective_on else None,
                "status": r.status.value, "origin": r.origin.value,
                "excerpt": _clean_excerpt(r.excerpt),
                "source": _source_ref(srcs.get(r.source_id) if r.source_id else None),
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            }
            for r in rules
        ],
        "sources": [
            {**(_source_ref(s) or {}), "layer": _layer(layer_ids[s.jurisdiction_id]),
             "health": s.health.value}
            for s in monitored
        ],
    }


def _clean_excerpt(text: str | None) -> str | None:
    """Drop the "[page N]" markers our PDF text extraction inserts."""
    if not text:
        return text
    return re.sub(r"\s*\[page \d+\]\s*", "\n", text).strip()


def filename(data: dict[str, Any], ext: str) -> str:
    j = data["jurisdiction"]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{j['name']} {j['state']}").strip("-")
    return f"JSE-MEP-regulations-{slug}-{data['generated_at'][:10]}.{ext}"


# --- shared layout ------------------------------------------------------------


def _logo_path() -> Path | None:
    static = get_settings().static_dir
    candidates = ([static / "jse-logo.png"] if static else []) + [
        Path(__file__).resolve().parents[2] / "frontend" / "public" / "jse-logo.png"]
    return next((p for p in candidates if p.exists()), None)


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}, {d.year}"


def _place_title(data: dict[str, Any]) -> str:
    j = data["jurisdiction"]
    if j["type"] in ("state", "district"):
        return j["name"]
    return f"{j['name']}, {j['state']}"


def _sections(data: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Non-adoption rules grouped by category, in first-seen order."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in data["rules"]:
        cat = r["category"]
        if cat and cat["key"] == "adopted_code":
            continue
        groups.setdefault(cat["label"] if cat else "Other", []).append(r)
    return list(groups.items())


def _source_line(r: dict[str, Any]) -> str:
    s = r["source"]
    if not s:
        return "Source: manual entry" + (f" ({r['origin']})" if r["origin"] else "")
    if s["kind"] == "upload":
        return f"Source: uploaded document “{s['title'] or 'PDF'}”"
    return f"Source: {s['title'] + ' — ' if s['title'] else ''}{s['url']}"


def _meta_line(r: dict[str, Any]) -> str:
    parts = [r["layer"]["name"]]
    if r["discipline"]:
        parts.append(r["discipline"]["label"])
    if r["code_ref"]:
        parts.append(r["code_ref"] + (f" {r['code_edition']}" if r["code_edition"] else ""))
    if r["effective_on"]:
        parts.append(f"effective {_fmt_date(r['effective_on'])}")
    parts.append(STATUS_LABEL.get(r["status"], r["status"]))
    return " · ".join(parts)


def _intro(data: dict[str, Any]) -> list[str]:
    lines = [f"Generated {_fmt_date(data['generated_at'])}"]
    if data["address"]:
        lines.append(f"Project address: {data['address']}")
    lines.append("Layers: " + " › ".join(
        f"{s['name']} ({TYPE_LABEL[s['type']]})" for s in data["stack"]))
    f = data["filters"]
    lines.append("Includes items pending review" if f["include_pending"]
                 else "Verified items only")
    if f["disciplines"]:
        lines.append("Disciplines: " + ", ".join(f["disciplines"]))
    return lines


# --- Word ---------------------------------------------------------------------


def to_docx(data: dict[str, Any]) -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    brand, muted = RGBColor(*BRAND), RGBColor(*MUTED)
    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = Inches(0.9)
        section.top_margin = section.bottom_margin = Inches(0.8)
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        st = doc.styles[name]
        st.font.name = "Arial"
        st.font.color.rgb = brand if name != "Heading 3" else RGBColor(*INK)

    def red_rule(paragraph: Any) -> None:
        p_pr = paragraph._p.get_or_add_pPr()
        border = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for k, v in {"w:val": "single", "w:sz": "18", "w:space": "4", "w:color": "B52025"}.items():
            bottom.set(qn(k), v)
        border.append(bottom)
        p_pr.append(border)

    logo = _logo_path()
    if logo:
        doc.add_picture(str(logo), width=Inches(2.2))
    title = doc.add_paragraph()
    run = title.add_run("MEP Regulations Summary")
    run.bold, run.font.size, run.font.color.rgb = True, Pt(22), RGBColor(*INK)
    sub = doc.add_paragraph()
    run = sub.add_run(_place_title(data))
    run.font.size, run.font.color.rgb = Pt(15), brand
    red_rule(sub)
    for line in _intro(data):
        p = doc.add_paragraph()
        r = p.add_run(line)
        r.font.color.rgb, r.font.size = muted, Pt(9)
        p.paragraph_format.space_after = Pt(0)

    doc.add_heading("Adopted codes", level=1)
    codes = data["effective_codes"]
    if codes:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Light Grid Accent 2"
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        headers = ["Code", "Edition", "Effective", "Adopted by", "Status"]
        for cell, text in zip(table.rows[0].cells, headers, strict=True):
            cell.text = text
        for c in codes:
            adopted_by = c["layer"]["name"]
            if c["overrides"]:
                adopted_by += " (replaces " + ", ".join(
                    f"{o['layer']['name']} {o['edition']}" for o in c["overrides"]) + ")"
            row = table.add_row().cells
            for cell, text in zip(row, [c["code"], c["edition"], _fmt_date(c["effective_on"]),
                                        adopted_by, STATUS_LABEL.get(c["status"], c["status"])],
                                  strict=True):
                cell.text = text
    else:
        doc.add_paragraph("No code adoptions recorded yet.").runs[0].font.color.rgb = muted

    for label, rules in _sections(data):
        doc.add_heading(label, level=1)
        for item in rules:
            doc.add_heading(item["title"], level=3)
            meta = doc.add_paragraph()
            m = meta.add_run(_meta_line(item))
            m.font.size, m.font.color.rgb = Pt(8.5), muted
            meta.paragraph_format.space_after = Pt(2)
            doc.add_paragraph(item["summary"])
            if item["excerpt"]:
                q = doc.add_paragraph()
                q.paragraph_format.left_indent = Inches(0.3)
                qr = q.add_run(f"“{item['excerpt']}”")
                qr.italic, qr.font.size, qr.font.color.rgb = True, Pt(9), muted
            s = doc.add_paragraph()
            sr = s.add_run(_source_line(item))
            sr.font.size, sr.font.color.rgb = Pt(8.5), muted

    if data["sources"]:
        doc.add_heading("Monitored sources", level=1)
        for s in data["sources"]:
            where = s["url"] or f"uploaded document “{s['title']}”"
            doc.add_paragraph(f"{s['layer']['name']}: {s['title'] or ''} {where}".strip(),
                              style="List Bullet")

    doc.add_heading("Disclaimer", level=2)
    d = doc.add_paragraph()
    dr = d.add_run(data["disclaimer"])
    dr.font.size, dr.font.color.rgb = Pt(8.5), muted

    footer = doc.sections[0].footer.paragraphs[0]
    fr = footer.add_run(f"JSE Local Regulations · {_place_title(data)} · "
                        f"generated {_fmt_date(data['generated_at'])}")
    fr.font.size, fr.font.color.rgb = Pt(7.5), muted

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- PDF ----------------------------------------------------------------------


def _pdf_text(s: str | None) -> str:
    """Escape for reportlab markup; the built-in fonts only cover Windows-1252."""
    s = (s or "").encode("cp1252", "replace").decode("cp1252")
    return escape(s).replace("\n", "<br/>")


def to_pdf(data: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Image,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    brand = colors.Color(*(c / 255 for c in BRAND))
    ink = colors.Color(*(c / 255 for c in INK))
    muted = colors.Color(*(c / 255 for c in MUTED))

    def style(name: str, **kw: Any) -> ParagraphStyle:
        base = {"fontName": "Helvetica", "fontSize": 10, "leading": 13.5, "textColor": ink,
                "alignment": TA_LEFT}
        return ParagraphStyle(name, **{**base, **kw})

    s_title = style("title", fontName="Helvetica-Bold", fontSize=22, leading=26)
    s_place = style("place", fontSize=15, leading=19, textColor=brand)
    s_meta = style("meta", fontSize=8.5, leading=11, textColor=muted)
    s_h1 = style("h1", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=brand,
                 spaceBefore=14, spaceAfter=6, keepWithNext=1)
    s_h3 = style("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=8,
                 keepWithNext=1)
    s_body = style("body")
    s_quote = style("quote", fontName="Helvetica-Oblique", fontSize=9, leading=12,
                    textColor=muted, leftIndent=14, spaceBefore=3)
    s_cell = style("cell", fontSize=9, leading=11.5)
    s_cell_h = style("cellh", fontName="Helvetica-Bold", fontSize=9, leading=11.5,
                     textColor=colors.white)

    story: list[Any] = []
    logo = _logo_path()
    if logo:
        story.append(Image(str(logo), width=2.2 * inch, height=2.2 * inch * 430 / 1563,
                           hAlign="LEFT"))
        story.append(Spacer(1, 10))
    story += [Paragraph("MEP Regulations Summary", s_title), Spacer(1, 4),
              Paragraph(_pdf_text(_place_title(data)), s_place), Spacer(1, 4),
              HRFlowable(width="100%", thickness=2.5, color=brand, spaceAfter=6)]
    story += [Paragraph(_pdf_text(line), s_meta) for line in _intro(data)]

    story.append(Paragraph("Adopted codes", s_h1))
    if data["effective_codes"]:
        rows: list[list[Any]] = [[Paragraph(h, s_cell_h) for h in
                                  ["Code", "Edition", "Effective", "Adopted by", "Status"]]]
        for c in data["effective_codes"]:
            adopted_by = c["layer"]["name"]
            if c["overrides"]:
                adopted_by += " (replaces " + ", ".join(
                    f"{o['layer']['name']} {o['edition']}" for o in c["overrides"]) + ")"
            rows.append([Paragraph(_pdf_text(v), s_cell) for v in [
                c["code"], c["edition"], _fmt_date(c["effective_on"]), adopted_by,
                STATUS_LABEL.get(c["status"], c["status"])]])
        table = Table(rows, colWidths=[1.0 * inch, 0.8 * inch, 1.1 * inch, 2.9 * inch,
                                       0.9 * inch], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), brand),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(1, .97, .95)]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.Color(.85, .85, .85)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No code adoptions recorded yet.", s_meta))

    for label, rules in _sections(data):
        for n, r in enumerate(rules):
            # The section heading travels with its first item so it never ends a page.
            block = [Paragraph(_pdf_text(label), s_h1)] if n == 0 else []
            block += [Paragraph(_pdf_text(r["title"]), s_h3),
                     Paragraph(_pdf_text(_meta_line(r)), s_meta),
                     Spacer(1, 2), Paragraph(_pdf_text(r["summary"]), s_body)]
            if r["excerpt"]:
                block.append(Paragraph(_pdf_text(f"“{r['excerpt']}”"), s_quote))
            block.append(Paragraph(_pdf_text(_source_line(r)), s_meta))
            story.append(KeepTogether(block))

    if data["sources"]:
        story.append(Paragraph("Monitored sources", s_h1))
        for s in data["sources"]:
            where = s["url"] or f"uploaded document “{s['title']}”"
            story.append(Paragraph(_pdf_text(f"• {s['layer']['name']}: "
                                             f"{(s['title'] + ' — ') if s['title'] else ''}"
                                             f"{where}"), s_meta))

    story += [Paragraph("Disclaimer", s_h1), Paragraph(_pdf_text(data["disclaimer"]), s_meta)]

    footer_text = (f"JSE Local Regulations · {_place_title(data)} · "
                   f"generated {_fmt_date(data['generated_at'])}")

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(doc.leftMargin, 0.5 * inch,
                          footer_text.encode("cp1252", "replace").decode("cp1252"))
        canvas.drawRightString(LETTER[0] - doc.rightMargin, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                      topMargin=0.8 * inch, bottomMargin=0.85 * inch,
                      title=f"MEP Regulations Summary — {_place_title(data)}",
                      author="Jordan & Skala Engineers").build(
        story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
