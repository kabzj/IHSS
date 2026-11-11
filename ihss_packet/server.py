"""Local browser interface, served only on 127.0.0.1.

Session answers (including the provider's SSN) are held in memory only; they are
written to disk solely inside the finished packet PDF in the records folder.
"""

from __future__ import annotations

import email.parser
import email.policy
import html
import secrets
import threading
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import appdata, packet, records
from .counties import CA_COUNTIES, module_for
from .forms import FILL
from .questions import QUESTIONS, RECIPIENT_SETUP_KEYS, blank_answers, derive, validate
from .sources import FormStore, PageStore

STATIC = Path(__file__).parent / "static"
MAX_BODY = 25 * 1024 * 1024

# Derived value -> the questions it is built from (for "goes on" hints).
DERIVED_SOURCES = {
    "provider.full_name": ("provider.first", "provider.mi", "provider.last"),
    "provider.home_csz": ("provider.home_city", "provider.home_state", "provider.home_zip"),
}

STATUS_TEXT = {
    "filled": "Filled",
    "empty_required": "EMPTY — required",
    "empty_optional": "Blank (optional)",
    "handwrite": "By hand",
    "county": "County use — leave blank",
    "not_applicable": "Not applicable",
}


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


class App:
    def __init__(self, form_store: FormStore | None = None, page_store: PageStore | None = None):
        self.lock = threading.Lock()
        self.csrf = secrets.token_urlsafe(24)
        self.form_store = form_store
        self.page_store = page_store
        self.prep: packet.Prep | None = None
        self.answers: dict | None = None
        self.errors: dict = {}
        self.pdf: bytes | None = None
        self.archived: Path | None = None
        self.archive_error: str = ""
        self.flash: str = ""

    def stores(self, settings) -> tuple[FormStore, PageStore]:
        fs = self.form_store or FormStore(lang=settings.get("language", "en"))
        ps = self.page_store or PageStore()
        return fs, ps

    def reset_session(self):
        self.prep = None
        self.answers = None
        self.errors = {}
        self.pdf = None
        self.archived = None
        self.archive_error = ""


# ------------------------------------------------------------------ page shell

def page(title: str, body: str, app: App, step: str = "") -> bytes:
    steps = [("setup", "Setup"), ("interview", "Hiring session"), ("review", "Review"), ("done", "Print")]
    nav = "".join(f'<li class="{"on" if k == step else ""}">{e(v)}</li>' for k, v in steps)
    flash = f'<div class="flash">{e(app.flash)}</div>' if app.flash else ""
    app.flash = ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} — IHSS Packet Tool</title><link rel="stylesheet" href="/static/style.css"></head>
<body><header><a class="brand" href="/">IHSS Packet Tool</a><ol class="steps">{nav}</ol></header>
<main>{flash}{body}</main>
<footer>Runs only on this computer. Not affiliated with IHSS, CDSS, any county, or any Public Authority; not legal
advice. Verify requirements with your local IHSS office.</footer></body></html>""".encode("utf-8")


def csrf_field(app: App) -> str:
    return f'<input type="hidden" name="csrf" value="{e(app.csrf)}">'


def input_for(q, value: str, error: str = "", extra_hint: str = "", disabled: bool = False) -> str:
    name = e(q.key)
    attrs = f'id="{name}" name="{name}"' + (" disabled" if disabled else "")
    sensitive = q.section == "provider"
    ac = ' autocomplete="off"' if sensitive else ""
    if q.kind == "choice":
        opts = "".join(f'<option value="{e(v)}"{" selected" if v == value else ""}>{e(lbl)}</option>'
                       for v, lbl in q.choices)
        ctl = f"<select {attrs}>{opts}</select>"
    else:
        typ = {"date": "date", "phone": "tel", "email": "email"}.get(q.kind, "text")
        mode = ' inputmode="numeric"' if q.kind in ("ssn", "zip") else ""
        size = {"state": ' maxlength="2" class="short"', "initial": ' maxlength="2" class="short"',
                "zip": ' class="mid"', "ssn": ' class="mid"', "date": ' class="mid"', "phone": ' class="mid"'}
        ctl = f'<input type="{typ}" {attrs} value="{e(value)}"{mode}{size.get(q.kind, "")}{ac}>'
    hint = " ".join(h for h in (q.hint, extra_hint) if h)
    return (f'<div class="q{" err" if error else ""}"><label for="{name}">{e(q.label)}</label>{ctl}'
            + (f'<div class="error">{e(error)}</div>' if error else "")
            + (f'<div class="hint">{hint}</div>' if hint else "") + "</div>")


# ------------------------------------------------------------------ views

def view_home(app: App, s: dict) -> bytes:
    r = s.get("recipient", {})
    mod = module_for(s.get("county", ""))
    rec_dir = s.get("records_dir", "")
    rec_ok = bool(rec_dir) and Path(rec_dir).expanduser().parent.exists()
    in_image = rec_dir.startswith(f"/Volumes/{records.IMAGE_VOLUME_NAME}")
    county_line = (f"{e(s.get('county'))} County — county module installed (local forms, fee and office details)."
                   if mod else f"{e(s.get('county'))} County — no county module yet; state forms only.")
    local = ""
    if mod:
        fs, _ = app.stores(s)
        for fid, f in mod.local_forms.items():
            c = fs.imported(f)
            status = (f"imported {e(c.downloaded[:10])}" if c.usable else "not imported")
            local += f"<li>{e(f.title)}: <b>{status}</b> — <a href='/setup#local'>manage</a></li>"
        local = f"<h3>County forms you supply</h3><ul>{local}</ul>" if local else ""
    resume = ""
    if app.prep is not None:
        resume = '<p><a class="button secondary" href="/packet/interview">Resume the current packet</a></p>'
    body = f"""
<h1>Ready</h1>
<section class="card">
<p><b>Recipient:</b> {e(r.get('recipient.name', '—'))} · Case # {e(r.get('recipient.case_number', '—'))}</p>
<p>{county_line}</p>
<p><b>Records folder:</b> {e(rec_dir or 'not set')} {'' if rec_ok else '<span class="bad">(not available — if it is on an encrypted disk image, open the image first)</span>'}</p>
{'' if in_image else '<p class="note">Archived packets contain Social Security numbers. Keeping the records folder inside an encrypted disk image is recommended — see Setup.</p>'}
{local}
<p><a href="/setup">Edit setup</a></p>
</section>
<form method="post" action="/packet/new">{csrf_field(app)}
<p>Starting a new packet downloads fresh copies of every form (a few seconds).</p>
<button type="submit">Start a new hiring packet</button></form>{resume}"""
    return page("Home", body, app)


def view_setup(app: App, s: dict, errors: dict | None = None, values: dict | None = None) -> bytes:
    errors = errors or {}
    r = values if values is not None else s.get("recipient", {})
    rq = [q for q in QUESTIONS if q.key in RECIPIENT_SETUP_KEYS]
    fields = "".join(input_for(q, r.get(q.key, ""), errors.get(q.key, "")) for q in rq)
    county = s.get("county", "")
    opts = "".join(f'<option{" selected" if c == county else ""}>{e(c)}</option>' for c in CA_COUNTIES)
    rec_dir = s.get("records_dir") or appdata.default_records_dir()
    mod = module_for(county)
    local = ""
    if mod:
        fs, _ = app.stores(s)
        for fid, f in mod.local_forms.items():
            c = fs.imported(f)
            state = f"Imported {e(c.downloaded[:10])}." if c.usable else "Not imported yet."
            remove = (f'<form method="post" action="/import/{e(fid)}/remove" class="inline">{csrf_field(app)}'
                      f'<button class="link">Remove</button></form>') if c.usable else ""
            local += f"""<div class="card"><h3>{e(f.title)}</h3><p>{e(f.notes)}</p><p><b>{state}</b> {remove}</p>
<form method="post" action="/import/{e(fid)}" enctype="multipart/form-data">{csrf_field(app)}
<label for="file-{e(fid)}">Choose the PDF</label> <input id="file-{e(fid)}" type="file" name="file" accept="application/pdf">
<button type="submit" class="secondary">Import</button></form></div>"""
        local = f'<h2 id="local">County forms not published online</h2>{local}'
    image = ""
    if records.is_mac():
        image = f"""<details class="card"><summary>Create an encrypted disk image for records (recommended)</summary>
<p>Creates <code>{e(records.default_image_path())}</code>, an AES-256 encrypted disk image, opens it, and sets the
records folder inside it. You will need the password each time you open it; it cannot be recovered if lost.</p>
<form method="post" action="/setup/image">{csrf_field(app)}
<div class="q"><label for="pw1">Password</label><input id="pw1" type="password" name="pw1" autocomplete="new-password"></div>
<div class="q"><label for="pw2">Repeat password</label><input id="pw2" type="password" name="pw2" autocomplete="new-password"></div>
<button type="submit" class="secondary">Create and open encrypted image</button></form></details>"""
    else:
        image = ("<p class='note'>Archived packets contain Social Security numbers. Store the records folder on an "
                 "encrypted drive (on macOS the tool can create an encrypted disk image for you).</p>")
    body = f"""
<h1>Setup</h1>
<form method="post" action="/setup">{csrf_field(app)}
<h2>Recipient</h2><p class="note">Saved on this computer only (owner-only file permissions) and reused for every packet.</p>
{fields}
<h2>County</h2>
<div class="q"><label for="county">County</label><select id="county" name="county">
<option value="">Choose…</option>{opts}</select>
<div class="hint">San Diego has a full county module. Other counties get the state forms plus a reminder to check
local requirements.</div>{f'<div class="error">{e(errors["county"])}</div>' if "county" in errors else ""}</div>
<h2>Records folder</h2>
<div class="q"><label for="records_dir">Folder where finished packets are archived</label>
<input id="records_dir" name="records_dir" value="{e(rec_dir)}" class="wide">
{f'<div class="error">{e(errors["records_dir"])}</div>' if "records_dir" in errors else ""}</div>
<button type="submit">Save setup</button></form>
{image}{local}"""
    return page("Setup", body, app, "setup")


def usage_map(prep: packet.Prep, values: dict) -> tuple[dict, dict]:
    """question key -> ["SOC 426 (Part A 1. Full name)", ...], and -> set of form codes requiring it."""
    used: dict[str, list[str]] = {}
    req: dict[str, set[str]] = {}
    for fid in prep.included():
        f = prep.form(fid)
        extra = prep.extra_required(fid)
        for fm in f.fields:
            if fm.mode != FILL or not fm.key:
                continue
            for k in DERIVED_SOURCES.get(fm.key, (fm.key,)):
                tag = f"{f.code}"
                if tag not in used.setdefault(k, []):
                    used[k].append(tag)
                if (fm.is_required(values) or fm.key in extra) and k != "provider.mi":
                    req.setdefault(k, set()).add(f.code)
    return used, req


def downloads_panel(prep: packet.Prep) -> str:
    rows = ""
    for fid in prep.order:
        c = prep.copies[fid]
        inc = fid not in prep.optional or prep.optional[fid]
        cls = {"fresh": "ok", "imported": "ok", "fallback": "warn", "unavailable": "bad"}[c.status]
        rows += (f"<tr class='{'' if inc else 'muted'}'><td>{e(c.form.code)}</td><td>{e(c.form.title)}</td>"
                 f"<td class='{cls}'>{e(packet.describe_copy(c))}</td></tr>")
    warns = "".join(f"<li>{e(w)}</li>" for fid in prep.order for w in prep.copies[fid].warnings)
    warns += "".join(f"<li>{e(w)}</li>" for w in prep.facts.warnings)
    return (f"<details class='card' {'open' if warns else ''}><summary>Form downloads and county checks"
            f"{' — warnings' if warns else ' — all current'}</summary><table class='plain'>{rows}</table>"
            + (f"<ul class='warnings'>{warns}</ul>" if warns else "") + "</details>")


def view_interview(app: App) -> bytes:
    prep, ans = app.prep, app.answers
    values = derive(ans)
    used, req = usage_map(prep, values)

    def block(section):
        out = ""
        for q in QUESTIONS:
            if q.section != section:
                continue
            tags = ""
            if q.key in used:
                tags += "Goes on: " + ", ".join(e(t) for t in used[q.key]) + ". "
            if q.key in req:
                tags += "<span class='req'>Required by " + ", ".join(e(t) for t in sorted(req[q.key])) + "</span>"
            elif q.key not in used:
                tags += "<span class='muted'>For your records and the checklist only.</span>"
            out += input_for(q, ans.get(q.key, ""), app.errors.get(q.key, ""), tags)
        return out

    opts = ""
    for fid, on in prep.optional.items():
        f = prep.form(fid)
        opts += (f'<div class="check"><input type="checkbox" id="opt-{e(fid)}" name="opt:{e(fid)}"'
                 f'{" checked" if on else ""}><label for="opt-{e(fid)}"><b>{e(f.code)}</b> {e(f.title)}'
                 f'<span class="hint">{e(prep.optional_notes.get(fid, ""))}</span></label></div>')
    body = f"""
<h1>Hiring session</h1>
<p>Fill this in together. Each answer is asked once and placed on every form that needs it. Leave anything
blank that should be written by hand. Signatures and signing dates are always left for the pen.</p>
{downloads_panel(prep)}
<form method="post" action="/packet/interview">{csrf_field(app)}
<fieldset><legend>Recipient</legend><p class="note">Prefilled from setup. Changes here apply to this packet only.</p>
{block('recipient')}</fieldset>
<fieldset><legend>New provider</legend>{block('provider')}</fieldset>
<fieldset><legend>Include in the packet</legend>{opts}</fieldset>
<div class="actions"><button type="submit" name="go" value="review">Continue to review</button>
<button type="submit" name="go" value="save" class="secondary">Save and stay here</button></div>
</form>
<form method="post" action="/packet/discard" class="inline">{csrf_field(app)}
<button class="link danger">Discard this packet</button></form>"""
    return page("Hiring session", body, app, "interview")


def view_review(app: App) -> bytes:
    prep = app.prep
    reviews = packet.review(prep, app.answers)
    total_missing = sum(len(r.missing_required) for r in reviews if r.usable)
    total_hand = sum(1 for r in reviews if r.usable for row in r.rows if row.status == "handwrite")
    sections = ""
    for r in reviews:
        if not r.usable:
            sections += (f"<section class='card bad'><h2>{e(r.code)} — {e(r.title)}</h2>"
                         f"<p><b>Not available, so not in the packet.</b> {e(r.note)}</p></section>")
            continue
        rows = "".join(
            f"<tr class='{e(row.status)}'><td>{e(row.label)}</td><td>{e(row.value)}</td>"
            f"<td>{e(STATUS_TEXT[row.status])}{(' — ' + e(row.who)) if row.who else ''}</td></tr>"
            for row in r.rows)
        table = (f"<table><thead><tr><th>Field</th><th>Value</th><th>Status</th></tr></thead>{rows}</table>"
                 if r.rows else f"<p class='note'>{e(r.note)}</p>")
        sections += (f"<section class='card'><h2>{e(r.code)} — {e(r.title)}</h2>"
                     f"<p class='note'>Completed by {e(r.completed_by)} · copy: {e(r.copy_status)}</p>{table}</section>")
    warns = "".join(f"<li>{e(w)}</li>" for w in packet.cover_warnings(prep, reviews))
    summary = (f"<p class='{'bad' if total_missing else 'ok'}'><b>{total_missing}</b> required field(s) empty. "
               f"<b>{total_hand}</b> item(s) to complete by hand (highlighted).</p>")
    body = f"""
<h1>Review</h1>{summary}
{f"<div class='card warn'><h3>Warnings</h3><ul class='warnings'>{warns}</ul></div>" if warns else ""}
{sections}
<div class="actions">
<a class="button secondary" href="/packet/interview">Go back and correct</a>
<form method="post" action="/packet/build" class="inline">{csrf_field(app)}
<button type="submit">Confirm — build, archive, and open for printing</button></form></div>
{"<p class='note'>Empty required fields will be listed on the cover checklist so they can be completed by hand.</p>" if total_missing else ""}"""
    return page("Review", body, app, "review")


def view_done(app: App) -> bytes:
    archived = (f"<p class='ok'>Archived to <code>{e(app.archived)}</code></p>" if app.archived else
                f"<p class='bad'><b>Not archived:</b> {e(app.archive_error)} Fix the records folder in Setup, then "
                f"confirm again from the review screen.</p>")
    body = f"""
<h1>Packet ready</h1>{archived}
<p><a class="button" href="/packet/packet.pdf" target="_blank" rel="noopener">Open the packet PDF to print</a></p>
<ul><li>Print double-sided, flip on long edge. Blank backs are intentional.</li>
<li>Page 1 is the checklist: remove it before handing in the forms.</li>
<li>Signatures and signing dates are left blank for the pen.</li></ul>
<div class="actions"><a class="button secondary" href="/packet/review">Back to review</a>
<form method="post" action="/packet/discard" class="inline">{csrf_field(app)}
<button class="secondary">Finish and clear this session</button></form></div>"""
    return page("Print", body, app, "done")


# ------------------------------------------------------------------ handler

class Handler(BaseHTTPRequestHandler):
    app: App = None  # set by make_server
    server_version = "IHSSPacketTool"
    sys_version = ""

    def log_message(self, fmt, *args):  # keep the console free of request details
        pass

    # helpers
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, status, body: bytes, ctype="text/html; charset=utf-8", extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self'; script-src 'none'; frame-ancestors 'none'; "
                         "form-action 'self'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, to: str):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("too large")
        return self.rfile.read(n)

    def _form(self, raw: bytes) -> dict[str, str]:
        q = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
        return {k: v[-1] for k, v in q.items()}

    # dispatch
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
        path = urlsplit(self.path).path
        app = self.app
        if path == "/static/style.css":
            return self._send(HTTPStatus.OK, (STATIC / "style.css").read_bytes(), "text/css; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(HTTPStatus.NOT_FOUND, b"", "text/plain")
        with app.lock:
            s = appdata.load_settings()
            if path == "/":
                return self._redirect("/home" if s.get("setup_complete") else "/setup")
            if path == "/setup":
                return self._send(HTTPStatus.OK, view_setup(app, s))
            if not s.get("setup_complete"):
                return self._redirect("/setup")
            if path == "/home":
                return self._send(HTTPStatus.OK, view_home(app, s))
            if path.startswith("/packet/") and app.prep is None:
                app.flash = "No packet in progress. Start a new one."
                return self._redirect("/home")
            if path == "/packet/interview":
                return self._send(HTTPStatus.OK, view_interview(app))
            if path == "/packet/review":
                return self._send(HTTPStatus.OK, view_review(app))
            if path == "/packet/done":
                if app.pdf is None:
                    return self._redirect("/packet/review")
                return self._send(HTTPStatus.OK, view_done(app))
            if path == "/packet/packet.pdf":
                if app.pdf is None:
                    return self._redirect("/packet/review")
                name = records.archive_name(derive(app.answers)["provider.full_name"], date.today())
                return self._send(HTTPStatus.OK, app.pdf, "application/pdf",
                                  {"Content-Disposition": f'inline; filename="{name}"'})
        return self._send(HTTPStatus.NOT_FOUND, page("Not found", "<h1>Not found</h1>", app))

    def do_POST(self):
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
        app = self.app
        path = urlsplit(self.path).path
        try:
            raw = self._body()
        except ValueError:
            return self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"Too large", "text/plain")
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            form, files = parse_multipart(ctype, raw)
        else:
            form, files = self._form(raw), {}
        if not secrets.compare_digest(form.get("csrf", ""), app.csrf):
            return self._send(HTTPStatus.FORBIDDEN, page("Expired", "<h1>This page expired</h1>"
                              "<p><a href='/'>Reload the tool</a> and try again.</p>", app))
        with app.lock:
            s = appdata.load_settings()
            if path == "/setup":
                return self._post_setup(s, form)
            if path == "/setup/image":
                return self._post_image(s, form)
            if path.startswith("/import/"):
                return self._post_import(s, path, files)
            if not s.get("setup_complete"):
                return self._redirect("/setup")
            if path == "/packet/new":
                fs, ps = app.stores(s)
                app.reset_session()
                app.prep = packet.prepare(s.get("county", ""), fs, ps)
                app.answers = blank_answers(s.get("recipient", {}))
                return self._redirect("/packet/interview")
            if path == "/packet/discard":
                app.reset_session()
                app.flash = "Session cleared. Nothing from it remains except any archived packet."
                return self._redirect("/home")
            if app.prep is None:
                return self._redirect("/home")
            if path == "/packet/interview":
                for q in QUESTIONS:
                    if q.key in form:
                        app.answers[q.key] = form[q.key].strip()
                for fid in app.prep.optional:
                    app.prep.optional[fid] = f"opt:{fid}" in form
                app.errors = validate(app.answers)
                app.pdf = None
                if app.errors:
                    app.flash = "Please fix the highlighted answers."
                    return self._redirect("/packet/interview")
                if form.get("go") == "review":
                    return self._redirect("/packet/review")
                app.flash = "Saved (in memory for this session)."
                return self._redirect("/packet/interview")
            if path == "/packet/build":
                if validate(app.answers):
                    return self._redirect("/packet/interview")
                pdf, _ = packet.build(app.prep, app.answers)
                app.pdf = pdf
                name = derive(app.answers)["provider.full_name"]
                try:
                    app.archived = records.archive(s.get("records_dir", ""), name, pdf, replace=app.archived)
                    app.archive_error = ""
                except OSError as ex:
                    app.archived = None
                    app.archive_error = str(ex)
                return self._redirect("/packet/done")
        return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")

    def _post_setup(self, s: dict, form: dict):
        app = self.app
        recipient = {k: form.get(k, "").strip() for k in RECIPIENT_SETUP_KEYS}
        errors = {k: v for k, v in validate(recipient).items()}
        for k in ("recipient.name", "recipient.case_number"):
            if not recipient.get(k):
                errors[k] = "Needed on the forms."
        county = form.get("county", "").strip()
        if county not in CA_COUNTIES:
            errors["county"] = "Choose a county."
        rec_dir = form.get("records_dir", "").strip()
        if not rec_dir:
            errors["records_dir"] = "Choose a folder."
        if errors:
            s2 = dict(s, county=county, records_dir=rec_dir)
            return self._send(HTTPStatus.OK, view_setup(app, s2, errors, recipient))
        s.update(recipient=recipient, county=county, records_dir=rec_dir, setup_complete=True)
        appdata.save_settings(s)
        app.flash = "Setup saved."
        return self._redirect("/home")

    def _post_image(self, s: dict, form: dict):
        app = self.app
        p1, p2 = form.get("pw1", ""), form.get("pw2", "")
        if p1 != p2:
            app.flash = "The passwords did not match."
            return self._redirect("/setup")
        ok, msg, rec_dir = records.create_encrypted_image(p1)
        app.flash = msg
        if ok:
            s["records_dir"] = rec_dir
            appdata.save_settings(s)
        return self._redirect("/setup")

    def _post_import(self, s: dict, path: str, files: dict):
        app = self.app
        parts = path.strip("/").split("/")
        mod = module_for(s.get("county", ""))
        if not mod or len(parts) < 2 or parts[1] not in mod.local_forms:
            return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
        form_def = mod.local_forms[parts[1]]
        fs, _ = app.stores(s)
        if len(parts) == 3 and parts[2] == "remove":
            fs.remove_imported(form_def.form_id)
            app.flash = f"Removed the imported {form_def.code} form."
        else:
            data = files.get("file", b"")
            ok, msg = fs.import_local(form_def, data) if data else (False, "Choose a PDF file first.")
            app.flash = f"{form_def.code}: {msg}"
        if app.prep is not None and form_def.form_id in app.prep.copies:
            app.prep.copies[form_def.form_id] = fs.imported(form_def)
        return self._redirect("/setup#local")


def parse_multipart(ctype: str, raw: bytes) -> tuple[dict[str, str], dict[str, bytes]]:
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + ctype.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
    form: dict[str, str] = {}
    files: dict[str, bytes] = {}
    if not msg.is_multipart():
        return form, files
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            files[name] = payload
        else:
            form[name] = payload.decode("utf-8", errors="replace")
    return form, files


def make_server(port: int = 0, app: App | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app or App()})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)
