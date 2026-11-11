"""Packet preparation (downloads), review data, and assembly of the single
double-sided print PDF: cover checklist sheet, then each form on fresh sheets."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date

from . import fill
from .counties import CountyFacts, CountyModule, module_for
from .forms import STATE_CORE, STATE_FORMS, STATE_INFO, FormDef
from .questions import derive
from .sources import FormCopy, FormStore, PageStore

DISCLAIMER = ("This packet was prepared with an independent tool. It is not affiliated with IHSS, the California "
              "Department of Social Services, any county, or any IHSS Public Authority, and it does not give legal "
              "advice. Requirements change: verify everything with your local IHSS office or Public Authority.")

STATE_ONLY_FACTS = CountyFacts(
    id_requirements=[
        "Original federal or state government-issued identification.",
        "Original Social Security card.",
        "(As stated in the SOC 426 instructions.)",
    ],
    bring_items=["SOC 426, signed by the provider, returned in person.",
                 "SOC 426A, completed and signed by the recipient."],
)


@dataclass
class Prep:
    county: str
    module: CountyModule | None
    copies: dict[str, FormCopy]
    order: list[str]                 # form ids in packet order
    optional: dict[str, bool]        # optional form id -> currently included
    optional_notes: dict[str, str]
    facts: CountyFacts
    warnings: list[str] = field(default_factory=list)

    def form(self, form_id: str) -> FormDef:
        return self.copies[form_id].form

    def included(self) -> list[str]:
        return [fid for fid in self.order if fid not in self.optional or self.optional[fid]]

    def extra_required(self, form_id: str) -> set[str]:
        return set(self.module.required_overrides.get(form_id, set())) if self.module else set()


def all_form_defs(module: CountyModule | None) -> dict[str, FormDef]:
    defs = dict(STATE_FORMS)
    if module:
        defs.update(module.local_forms)
    return defs


def prepare(county: str, form_store: FormStore, page_store: PageStore) -> Prep:
    """Called once per new packet: tries fresh downloads of every form."""
    module = module_for(county)
    defs = all_form_defs(module)
    if module:
        core = list(module.core_forms)
        optional = dict(module.optional_forms)
        notes = dict(module.optional_notes)
    else:
        core = list(STATE_CORE)
        optional = {fid: False for fid in STATE_INFO}
        notes = {"SOC847": "State information sheet: steps to becoming a provider.",
                 "SOC426B": "State information sheet about the enrollment form.",
                 "SOC426C": "Text of the crime code sections SOC 426 refers to."}
    order = core + [fid for fid in optional if fid not in core]
    copies = {fid: form_store.refresh(defs[fid]) for fid in order}
    if module:
        facts = module.check_live(page_store.get)
    else:
        facts = CountyFacts(**{k: (list(v) if isinstance(v, list) else v)
                               for k, v in STATE_ONLY_FACTS.__dict__.items()})
        facts.warnings.append(f"No county module for {county or 'this'} County yet: this packet has the state forms "
                              "only. Check with your local IHSS office or Public Authority for county-specific "
                              "forms (such as a Live Scan request form), fees, and office details.")
    return Prep(county, module, copies, order, optional, notes, facts)


@dataclass
class FormReview:
    form_id: str
    code: str
    title: str
    completed_by: str
    copy_status: str
    rows: list[fill.ReviewRow]
    usable: bool
    note: str = ""

    @property
    def missing_required(self) -> list[fill.ReviewRow]:
        return [r for r in self.rows if r.status == "empty_required"]


def review(prep: Prep, answers: dict) -> list[FormReview]:
    values = derive(answers)
    out = []
    for fid in prep.included():
        copy = prep.copies[fid]
        f = copy.form
        _, rows = fill.plan(f, values, prep.extra_required(fid))
        note = f.notes
        if f.kind == "info":
            note = "Information sheet — included as published, nothing to fill."
        elif not f.fillable and f.url is None:
            note = f.notes
        out.append(FormReview(fid, f.code, f.title, f.completed_by, describe_copy(copy), rows, copy.usable, note))
    return out


def describe_copy(c: FormCopy) -> str:
    day = c.downloaded[:10] if c.downloaded else ""
    rev = f", revision {c.revision}" if c.revision else ""
    return {
        "fresh": f"downloaded {day}{rev}",
        "fallback": f"OLDER COPY from {day}{rev}",
        "imported": f"imported copy ({day})",
        "unavailable": "NOT AVAILABLE",
    }[c.status]


def all_warnings(prep: Prep) -> list[str]:
    w: list[str] = []
    for fid in prep.included():
        w.extend(prep.copies[fid].warnings)
    w.extend(prep.facts.warnings)
    w.extend(prep.warnings)
    return w


# ---------------------------------------------------------------- assembly

def _blank_page_pdf(w: float = 612, h: float = 792) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setFont("Helvetica", 8)
    c.setFillGray(0.6)
    c.drawCentredString(w / 2, 36, "This page intentionally left blank.")
    c.showPage()
    c.save()
    return buf.getvalue()


def cover_pdf(prep: Prep, answers: dict, reviews: list[FormReview], prepared: date,
              page_counts: dict[str, int]) -> bytes:
    """The checklist sheet. Shrinks type a little if needed to stay on one page."""
    from pypdf import PdfReader

    data = b""
    for scale in (1.0, 0.94, 0.88, 0.82, 0.76):
        data = _cover_at(prep, answers, reviews, prepared, page_counts, scale)
        if len(PdfReader(io.BytesIO(data)).pages) == 1:
            break
    return data


def cover_warnings(prep: Prep, reviews: list[FormReview]) -> list[str]:
    usable = {r.form_id for r in reviews if r.usable}
    w: list[str] = []
    for fid in prep.included():
        if fid in usable:
            w.extend(prep.copies[fid].warnings)
    return w + prep.facts.warnings + prep.warnings


def _cover_at(prep, answers, reviews, prepared, page_counts, scale: float) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape as x

    values = derive(answers)
    ss = getSampleStyleSheet()
    k = scale
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.6 * k, leading=10.4 * k, spaceBefore=0,
                          spaceAfter=0.5, alignment=TA_LEFT)
    small = ParagraphStyle("s", parent=body, fontSize=7.4 * k, leading=8.8 * k)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=14 * k, leading=17 * k, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=10 * k, leading=12 * k, spaceBefore=5 * k,
                        spaceAfter=1.5)
    warn = ParagraphStyle("w", parent=body, textColor=colors.HexColor("#8a1c00"))
    from reportlab.platypus import Flowable

    class Box(Flowable):  # an empty tick box
        def wrap(self, *_):
            return 9, 8 * k

        def draw(self):
            self.canv.setLineWidth(0.7)
            self.canv.rect(0, 0, 7 * k, 7 * k)

    def P(t, st=body):
        return Paragraph(t, st)

    def table(rows, widths):
        t = Table([[P(c, small) for c in r] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        return t

    f = prep.facts
    story = [
        P("IHSS Provider Enrollment Packet — Checklist", h1),
        P("<b>Remove this sheet before handing in the forms.</b> Print the whole packet double-sided "
          "(flip on long edge). Each form starts on its own sheet.", body),
        P(f"Prepared {prepared.strftime('%B')} {prepared.day}, {prepared.year} · "
          f"Recipient: {x(values['recipient.name'] or '—')} · "
          f"Provider: {x(values['provider.full_name'] or '—')} · County: {x(prep.county or '—')}", body),
    ]

    story.append(P("Forms in this packet", h2))
    rows = [["Form", "Pages", "Completed by", "Copy used"]]
    for r in reviews:
        if r.usable:
            rows.append([f"<b>{x(r.code)}</b> {x(r.title)}", str(page_counts.get(r.form_id, "")),
                         x(r.completed_by), x(r.copy_status)])
    story.append(table(rows, [3.3 * inch, 0.5 * inch, 1.6 * inch, 2.0 * inch]))
    for r in reviews:
        if not r.usable:
            story.append(P(f"<b>Not in this packet:</b> {x(r.code)} — {x(r.title)}. {x(r.note)}", warn))

    # One row per signer per form page: signature and date lines together.
    story.append(P("Sign and date by hand", h2))
    grouped: dict[tuple[str, str, int], list[str]] = {}
    for r in reviews:
        if not r.usable:
            continue
        for row in r.rows:
            if row.status == "handwrite":
                grouped.setdefault((r.code, row.who or "—", row.page), []).append(row.label)
        if r.form_id == "SD_LIVESCAN":
            grouped.setdefault((r.code, "Provider", -1), []).append("The yellow highlighted area, by hand")
    rows = [["Who", "What", "Where"]]
    for (code, who, page), labels in grouped.items():
        where = f"{x(code)}, page {page + 1}" if page >= 0 else x(code)
        rows.append([x(who), x("; ".join(labels)), where])
    story.append(table(rows, [1.7 * inch, 4.2 * inch, 1.5 * inch]))

    story.append(P("Bring to the appointment (originals)", h2))
    items = Table([[Box(), P(x(item))] for item in f.id_requirements + f.bring_items],
                  colWidths=[14, 7.25 * inch])
    items.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story.append(items)

    if f.fee_amount:
        story.append(P("Live Scan fee", h2))
        story.append(P(f"<b>{x(f.fee_amount)}</b> — {x(f.fee_methods)}, payable to “{x(f.fee_payee)}”."))

    if f.office_address or f.office_phone:
        story.append(P("Office", h2))
        story.append(P(f"{x(f.office_name)} · {x(f.office_address)}<br/>Hours: {x(f.office_hours)} · "
                       f"Phone: {x(f.office_phone)}"))
        if f.appointment_note:
            story.append(P(x(f.appointment_note)))
    if f.steps_notes:
        story.append(P("After the appointment", h2))
        for n in f.steps_notes:
            story.append(P("• " + x(n)))

    warnings = cover_warnings(prep, reviews)
    missing = [(r.code, row.label) for r in reviews if r.usable for row in r.missing_required]
    if warnings or missing:
        story.append(P("Warnings", h2))
        for w in warnings:
            story.append(P("<b>!</b> " + x(w), warn))
        for code, label in missing:
            story.append(P(f"<b>!</b> {x(code)}: “{x(label)}” is blank — complete it by hand before handing in.",
                           warn))

    if f.sources:
        story.append(P("Sources checked: " + "; ".join(f"{x(u)} ({x(d)})" for u, d in f.sources), small))
    story.append(Spacer(1, 4))
    story.append(P(x(DISCLAIMER), small))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.55 * inch, rightMargin=0.55 * inch,
                      topMargin=0.45 * inch, bottomMargin=0.45 * inch,
                      title="IHSS packet checklist").build(story)
    return buf.getvalue()


def build(prep: Prep, answers: dict, prepared: date | None = None) -> tuple[bytes, list[tuple[str, int, int]]]:
    """Return (combined PDF bytes, layout) where layout lists (label, first page, page count)."""
    from pypdf import PdfReader, PdfWriter

    prepared = prepared or date.today()
    values = derive(answers)
    reviews = review(prep, answers)
    parts: list[tuple[str, bytes]] = []
    page_counts: dict[str, int] = {}
    for r in reviews:
        if not r.usable:
            continue
        copy = prep.copies[r.form_id]
        form = copy.form
        data = fill.fill_pdf(copy.path, form, values) if (form.fillable or form.overlays) else fill.passthrough(copy.path)
        parts.append((r.form_id, data))
        page_counts[r.form_id] = len(PdfReader(io.BytesIO(data)).pages)

    writer = PdfWriter()
    blank = PdfReader(io.BytesIO(_blank_page_pdf())).pages[0]
    layout: list[tuple[str, int, int]] = []

    def add(label: str, data: bytes):
        reader = PdfReader(io.BytesIO(data))
        start = len(writer.pages)
        writer.append(reader)
        n = len(reader.pages)
        layout.append((label, start + 1, n))
        if n % 2:
            writer.add_page(blank)

    add("Cover checklist", cover_pdf(prep, answers, reviews, prepared, page_counts))
    for fid, data in parts:
        add(fid, data)
    writer.add_metadata({"/Title": f"IHSS packet — {values['provider.full_name']}", "/Producer": "IHSS Packet Tool"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), layout
