"""Downloading blank forms and county pages, with a last-good-copy fallback.

The only network traffic the tool makes is here, and it only GETs public
blank forms and public information pages. No personal data is ever sent.
"""

from __future__ import annotations

import hashlib
import html
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import appdata
from .forms import FormDef

USER_AGENT = "IHSS-Packet-Tool/0.1 (local form downloader)"
KEEP_COPIES = 3


def http_get(url: str) -> bytes:
    import requests

    r = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.content


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _day(ts: str) -> str:
    return ts[:10] if ts else "unknown date"


# ---------------------------------------------------------------- forms

@dataclass
class FormCopy:
    form: FormDef
    path: Path | None
    status: str  # fresh | fallback | imported | unavailable
    downloaded: str = ""
    revision: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.path is not None


def code_regex(code: str) -> str:
    # "SOC 426A" -> r"SOC\s*426A(?![A-Z0-9])"
    parts = code.split()
    return r"\s*".join(re.escape(p) for p in parts) + r"(?![A-Z0-9])"


def inspect_pdf(data: bytes, form: FormDef) -> tuple[bool, str, str, list[str]]:
    """Return (valid, revision, reason_if_invalid, notes)."""
    from pypdf import PdfReader

    notes: list[str] = []
    if not data.startswith(b"%PDF"):
        return False, "", "the download was not a PDF (the page may have moved)", notes
    try:
        reader = PdfReader(io.BytesIO(data))
        n = len(reader.pages)
        first_text = reader.pages[0].extract_text() or ""
        last_text = reader.pages[-1].extract_text() or ""
    except Exception as e:  # noqa: BLE001 - any parse failure means a bad copy
        return False, "", f"the PDF could not be read ({e.__class__.__name__})", notes
    text = first_text + "\n" + last_text
    if not re.search(code_regex(form.code), text):
        return False, "", f"the file does not identify itself as {form.code}", notes
    m = re.search(code_regex(form.code) + r"\s*\((\d{1,2}/\d{2,4})\)", text)
    revision = m.group(1) if m else ""
    if form.fillable:
        names = set((reader.get_fields() or {}).keys())
        missing = sorted({f.pdf_field for f in form.fields} - names)
        if missing:
            return False, revision, (f"the form's fillable fields changed ({len(missing)} expected field(s) "
                                     "missing), so the tool's mapping no longer fits"), notes
    if form.expected_pages and n != form.expected_pages:
        notes.append(f"{form.code} now has {n} pages (the mapping was checked with {form.expected_pages}).")
    return True, revision, "", notes


class FormStore:
    def __init__(self, root: Path | None = None, lang: str = "en", fetch: Callable[[str], bytes] = http_get):
        self.root = (root or appdata.forms_dir()) / lang
        self.local_root = (root or appdata.forms_dir()) / "imported"
        self.fetch = fetch

    def _dir(self, form_id: str) -> Path:
        d = self.root / form_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _meta(self, form_id: str) -> dict:
        return appdata.read_json(self._dir(form_id) / "meta.json", {"history": []})

    def _save_meta(self, form_id: str, meta: dict) -> None:
        appdata.write_json(self._dir(form_id) / "meta.json", meta)

    def last_good(self, form_id: str) -> dict | None:
        hist = self._meta(form_id)["history"]
        for entry in reversed(hist):
            if (self._dir(form_id) / entry["file"]).exists():
                return entry
        return None

    def refresh(self, form: FormDef) -> FormCopy:
        """Try a fresh download; fall back to the last good copy with a warning."""
        if form.url is None:
            return self.imported(form)
        d = self._dir(form.form_id)
        meta = self._meta(form.form_id)
        prev = self.last_good(form.form_id)
        reason = ""
        try:
            data = self.fetch(form.url)
            ok, rev, reason, notes = inspect_pdf(data, form)
        except Exception as e:  # noqa: BLE001 - network errors of any kind
            ok, rev, notes = False, "", []
            reason = f"download failed ({e.__class__.__name__})"
        if ok:
            sha = hashlib.sha256(data).hexdigest()
            now = _now()
            warnings = list(notes)
            if prev and prev.get("sha256") == sha:
                prev["downloaded"] = now
                entry = prev
            else:
                fname = f"{form.form_id}_{now[:10]}_{sha[:8]}.pdf"
                appdata.write_private(d / fname, data)
                entry = {"file": fname, "downloaded": now, "first_seen": now, "sha256": sha, "revision": rev}
                meta["history"].append(entry)
                if prev and prev.get("revision") != rev:
                    warnings.append(f"{form.code} revision changed from ({prev.get('revision') or '?'}) to "
                                    f"({rev or 'unmarked'}) since the copy from {_day(prev.get('first_seen', ''))}.")
                elif prev:
                    warnings.append(f"{form.code} file changed since the last download, but its revision "
                                    f"marking is still ({rev or 'unmarked'}).")
            if form.verified_revision and rev != form.verified_revision:
                warnings.append(f"{form.code} is revision ({rev or 'unmarked'}); the tool's field mapping was "
                                f"checked against ({form.verified_revision}). Review the filled form carefully.")
            self._prune(form.form_id, meta)
            self._save_meta(form.form_id, meta)
            return FormCopy(form, d / entry["file"], "fresh", entry["downloaded"], rev, warnings)
        if prev:
            return FormCopy(form, d / prev["file"], "fallback", prev["downloaded"], prev.get("revision", ""),
                            [f"{form.code}: could not get a fresh copy — {reason}. Using the copy downloaded "
                             f"{_day(prev['downloaded'])}" + (f" (revision {prev['revision']})" if prev.get("revision") else "")
                             + ". Check that it is still current."])
        return FormCopy(form, None, "unavailable", warnings=[
            f"{form.code}: could not download it ({reason}) and no earlier copy exists."])

    def _prune(self, form_id: str, meta: dict) -> None:
        hist = meta["history"]
        while len(hist) > KEEP_COPIES:
            old = hist.pop(0)
            try:
                (self._dir(form_id) / old["file"]).unlink()
            except OSError:
                pass

    # User-imported forms (county forms with no public download)
    def import_local(self, form: FormDef, data: bytes) -> tuple[bool, str]:
        if not data.startswith(b"%PDF"):
            return False, "That file is not a PDF."
        from pypdf import PdfReader
        try:
            n = len(PdfReader(io.BytesIO(data)).pages)
        except Exception:  # noqa: BLE001
            return False, "That PDF could not be read."
        self.local_root.mkdir(parents=True, exist_ok=True)
        appdata.write_private(self.local_root / f"{form.form_id}.pdf", data)
        appdata.write_json(self.local_root / f"{form.form_id}.json", {"imported": _now(), "pages": n})
        return True, f"Imported ({n} page{'s' if n != 1 else ''})."

    def imported(self, form: FormDef) -> FormCopy:
        p = self.local_root / f"{form.form_id}.pdf"
        if p.exists():
            info = appdata.read_json(self.local_root / f"{form.form_id}.json", {})
            return FormCopy(form, p, "imported", info.get("imported", ""), "", [])
        return FormCopy(form, None, "unavailable", warnings=[
            f"{form.title}: not published online, and no copy has been imported. Bring the copy from the "
            "enrollment packet."])

    def remove_imported(self, form_id: str) -> None:
        for ext in (".pdf", ".json"):
            try:
                (self.local_root / f"{form_id}{ext}").unlink()
            except OSError:
                pass


# ---------------------------------------------------------------- pages

@dataclass
class PageResult:
    url: str
    text: str
    fetched: str
    fresh: bool
    warning: str = ""

    def describe(self) -> str:
        if not self.text:
            return "could not be checked"
        return f"checked {_day(self.fetched)}" if self.fresh else f"cached copy from {_day(self.fetched)}"


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    m = re.search(r"(?is)<main\b.*?</main>", raw) or re.search(r"(?is)<article\b.*?</article>", raw)
    body = m.group(0) if m else raw
    txt = html.unescape(re.sub(r"<[^>]+>", " ", body))
    return re.sub(r"\s+", " ", txt).strip()


class PageStore:
    def __init__(self, root: Path | None = None, fetch: Callable[[str], bytes] = http_get):
        self.root = root or (appdata.data_dir() / "pages")
        self.fetch = fetch

    def get(self, key: str, url: str) -> PageResult:
        cache = self.root / f"{key}.json"
        try:
            raw = self.fetch(url).decode("utf-8", errors="replace")
            text = html_to_text(raw)
            if len(text) < 200:
                raise ValueError("page content too short")
            now = _now()
            appdata.write_json(cache, {"url": url, "text": text, "fetched": now})
            return PageResult(url, text, now, True)
        except Exception as e:  # noqa: BLE001
            old = appdata.read_json(cache, None)
            if old:
                return PageResult(url, old["text"], old["fetched"], False,
                                  f"Could not reach {url} ({e.__class__.__name__}); using the copy read "
                                  f"{_day(old['fetched'])}.")
            return PageResult(url, "", "", False, f"Could not reach {url} ({e.__class__.__name__}).")
