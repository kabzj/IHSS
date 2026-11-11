"""Filling official forms.

Only blanks are filled. Pages are never added, removed, reordered or reflowed:
values go into the PDF's own fillable fields (then flattened so every viewer and
printer shows them the same way), or, for non-fillable pages, are drawn as an
overlay at fixed coordinates on top of the unchanged page.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from .forms import COUNTY, FILL, HANDWRITE, FormDef


@dataclass
class ReviewRow:
    label: str
    value: str
    status: str  # filled | empty_required | empty_optional | handwrite | county | not_applicable
    who: str = ""
    page: int = 0


def plan(form: FormDef, values: dict, extra_required: set[str] = frozenset()) -> tuple[dict, list[ReviewRow]]:
    """Return (pdf field values, review rows) for one form."""
    out: dict[str, str] = {}
    rows: list[ReviewRow] = []
    for f in form.fields:
        if f.mode == HANDWRITE:
            rows.append(ReviewRow(f.label, "", "handwrite", f.who, f.page))
            continue
        if f.mode == COUNTY:
            rows.append(ReviewRow(f.label, "", "county", "", f.page))
            continue
        v = values.get(f.key, "")
        required = f.is_required(values) or f.key in extra_required
        if f.kind == "check":
            if v in ("HAND",):
                rows.append(ReviewRow(f.label, "", "handwrite", "Provider", f.page))
                continue
            if v == "NA":
                rows.append(ReviewRow(f.label, "", "not_applicable", "", f.page))
                continue
            checked = v == f.on
            if checked:
                out[f.pdf_field] = "/Yes"
            if v:
                rows.append(ReviewRow(f.label, "☒" if checked else "☐", "filled", "", f.page))
            else:
                rows.append(ReviewRow(f.label, "", "empty_required" if required else "empty_optional", "", f.page))
            continue
        if f.kind == "radio":
            if v == "HAND":
                rows.append(ReviewRow(f.label, "", "handwrite", "Recipient", f.page))
                continue
            export = dict(f.radio).get(v)
            if export:
                out[f.pdf_field] = export
                rows.append(ReviewRow(f.label, export.lstrip("/"), "filled", "", f.page))
            else:
                rows.append(ReviewRow(f.label, "", "empty_required" if required else "empty_optional", "", f.page))
            continue
        if v:
            out[f.pdf_field] = v
            rows.append(ReviewRow(f.label, v, "filled", "", f.page))
        else:
            rows.append(ReviewRow(f.label, "", "empty_required" if required else "empty_optional", "", f.page))
    for o in form.overlays:
        v = values.get(o.key, "")
        rows.append(ReviewRow(o.label, v, "filled" if v else ("empty_required" if o.required else "empty_optional"),
                              "", o.page))
    for h in form.hand_items:
        rows.append(ReviewRow(h.label, "", "handwrite", h.who, h.page))
    return out, rows


def fill_pdf(src: Path, form: FormDef, values: dict) -> bytes:
    """Return the filled, flattened PDF bytes. Page count and order are unchanged."""
    from pypdf import PdfReader, PdfWriter

    field_values, _ = plan(form, values)
    reader = PdfReader(str(src))
    n_pages = len(reader.pages)
    writer = PdfWriter(clone_from=reader)
    if form.fillable:
        writer.set_need_appearances_writer(False)
        for page in writer.pages:
            names = _page_field_names(page)
            vals = {k: v for k, v in field_values.items() if k in names}
            if vals:
                writer.update_page_form_field_values(page, vals, auto_regenerate=False, flatten=True)
        # Leftover (blank) widgets would otherwise print as empty boxes in some viewers
        # and collide by name with other forms when combined; the printed boxes remain.
        writer.remove_annotations(subtypes="/Widget")
        if "/AcroForm" in writer._root_object:
            del writer._root_object["/AcroForm"]
    if form.overlays:
        _apply_overlays(writer, form, values)
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()
    if len(PdfReader(io.BytesIO(data)).pages) != n_pages:  # never ship an altered page count
        raise RuntimeError(f"{form.code}: page count changed while filling")
    return data


def _page_field_names(page) -> set[str]:
    names = set()
    for a in page.get("/Annots") or []:
        a = a.get_object()
        if a.get("/Subtype") != "/Widget":
            continue
        n = a.get("/T")
        if n is None and a.get("/Parent") is not None:
            n = a["/Parent"].get_object().get("/T")
        if n is not None:
            names.add(str(n))
    return names


def _apply_overlays(writer, form: FormDef, values: dict) -> None:
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas

    by_page: dict[int, list] = {}
    for o in form.overlays:
        if values.get(o.key):
            by_page.setdefault(o.page, []).append(o)
    for idx, items in by_page.items():
        page = writer.pages[idx]
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(w, h))
        for o in items:
            c.setFont("Helvetica", o.size)
            c.drawString(o.x, o.y, values[o.key])
        c.save()
        page.merge_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])


def passthrough(src: Path) -> bytes:
    """Unfilled form (informational sheets, imported county forms) — bytes unchanged."""
    return Path(src).read_bytes()
