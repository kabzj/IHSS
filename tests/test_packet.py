import io
from datetime import date

import pytest
from pypdf import PdfReader

from conftest import FIX, SAMPLE, failing_fetch, fixture_fetch
from ihss_packet import packet, records
from ihss_packet.counties import san_diego
from ihss_packet.forms import STATE_FORMS
from ihss_packet.questions import blank_answers, derive, validate
from ihss_packet.sources import FormStore, PageStore, inspect_pdf


def answers(**over):
    a = blank_answers()
    a.update(SAMPLE)
    a.update(over)
    return a


def prep_sd(tmp_path, fetch=fixture_fetch):
    return packet.prepare("San Diego", FormStore(tmp_path / "forms", fetch=fetch),
                          PageStore(tmp_path / "pages", fetch=fetch))


def page_text(pdf: bytes, i: int) -> str:
    return PdfReader(io.BytesIO(pdf)).pages[i].extract_text()


def test_fixture_forms_match_mappings():
    for fid, form in STATE_FORMS.items():
        ok, rev, reason, notes = inspect_pdf((FIX / f"{fid}.pdf").read_bytes(), form)
        assert ok, (fid, reason)
        assert not notes, notes
        if form.verified_revision:
            assert rev == form.verified_revision


def test_derive_and_validate():
    v = derive(answers())
    assert v["provider.full_name"] == "Alex J Sample Jr."
    assert v["provider.ssn"] == "123-45-6789"
    assert v["provider.phone"] == "(619) 555-0199"
    assert v["provider.dob"] == "02/03/1990"
    assert v["provider.home_csz"] == "Chula Vista, CA 91910"
    assert validate(answers()) == {}
    assert "provider.ssn" in validate(answers(**{"provider.ssn": "1234"}))


def test_every_mapped_value_lands_in_its_form(tmp_path):
    prep = prep_sd(tmp_path)
    prep.optional["SOC846"] = True
    pdf, layout = packet.build(prep, answers(), date(2026, 11, 11))
    starts = {label: (first - 1, n) for label, first, n in layout}
    s426, _ = starts["SOC426"]
    p3 = page_text(pdf, s426 + 2)
    for want in ("Alex J Sample Jr.", "02/03/1990", "22 Example Ave", "Chula Vista", "91910",
                 "(619) 555-0199", "123-45-6789", "alex@example.com", "D1234567", "02/03/2030", "English"):
        assert want in p3, want
    assert "Alex J Sample Jr." in page_text(pdf, s426 + 4)
    s426a, _ = starts["SOC426A"]
    a1 = page_text(pdf, s426a)
    for want in ("Kay Example", "1234567", "Alex J Sample Jr.", "Chula Vista, CA 91910", "12/01/2026", "Friend"):
        assert want in a1, want
    s846, _ = starts["SOC846"]
    assert "Alex J Sample Jr." in page_text(pdf, s846)
    assert "Alex J Sample Jr." in page_text(pdf, s846 + 5)
    # No fillable fields survive (flattened), so nothing collides or prints as empty widgets.
    assert not PdfReader(io.BytesIO(pdf)).get_fields()


def test_checkboxes_and_radio(tmp_path):
    prep = prep_sd(tmp_path)
    vals = derive(answers())
    from ihss_packet.fill import plan
    out, _ = plan(STATE_FORMS["SOC426"], vals)
    assert out["SOC 426 Pg 3 4"] == "/Yes" and "SOC 426 Pg 3 3" not in out  # F
    assert out["SOC 426 Pg 4 3"] == "/Yes" and out["SOC 426 Pg 4 5"] == "/Yes"  # No, No
    assert "SOC 426 Pg 4 6" not in out and "SOC 426 Pg 4 7" not in out  # Q2 not applicable
    out, _ = plan(STATE_FORMS["SOC426A"], vals)
    assert out["pg1-9"] == "/Female" and out["Pg1_16"] == "/Yes"


def test_duplex_layout_each_form_on_fresh_sheet(tmp_path):
    prep = prep_sd(tmp_path)
    for k in prep.optional:
        prep.optional[k] = True
    pdf, layout = packet.build(prep, answers())
    total = len(PdfReader(io.BytesIO(pdf)).pages)
    assert layout[0] == ("Cover checklist", 1, 1)  # cover fits one page; its back is blank
    for label, first, n in layout:
        assert first % 2 == 1, f"{label} starts on a back side"
    expected_pages = {"SOC426": 5, "SOC426A": 3, "SOC846": 6, "SOC847": 4, "SOC426B": 2, "SOC426C": 4}
    for label, first, n in layout[1:]:
        assert n == expected_pages[label]  # original page count kept
    assert total % 2 == 0


def test_official_pages_unchanged_except_fills(tmp_path):
    prep = prep_sd(tmp_path)
    pdf, layout = packet.build(prep, answers())
    first = dict((l, f) for l, f, _ in layout)["SOC426"] - 1
    orig = PdfReader(str(FIX / "SOC426.pdf"))
    for i in (0, 1):  # instruction pages have no fields: text identical
        assert page_text(pdf, first + i) == orig.pages[i].extract_text()


def test_required_and_handwritten_marking(tmp_path):
    prep = prep_sd(tmp_path)
    reviews = {r.form_id: r for r in packet.review(prep, answers(**{"provider.email": ""}))}
    missing = [r.label for r in reviews["SOC426"].missing_required]
    assert any("E-mail" in m for m in missing)  # San Diego requires an email
    hand = [r for r in reviews["SOC426"].rows if r.status == "handwrite"]
    assert {h.who for h in hand} == {"Provider"} and len(hand) == 2
    county = [r for r in reviews["SOC426A"].rows if r.status == "county"]
    assert len(county) == 2
    assert not reviews["SD_LIVESCAN"].usable  # nothing imported yet


def test_rehab_required_only_after_tier2_yes(tmp_path):
    prep = prep_sd(tmp_path)
    r = {x.form_id: x for x in packet.review(prep, answers(**{"provider.tier2": "Y"}))}
    assert any("Part B 2" in m.label for m in r["SOC426"].missing_required)


def test_fallback_to_last_good_copy_with_warning(tmp_path):
    prep_sd(tmp_path)  # populates the cache
    prep = prep_sd(tmp_path, fetch=failing_fetch)
    c = prep.copies["SOC426"]
    assert c.status == "fallback" and c.usable
    assert "could not get a fresh copy" in c.warnings[0] and c.downloaded[:10] in c.warnings[0]
    assert prep.facts.fee_amount == "$47.00"
    assert any("using the copy read" in w for w in prep.facts.warnings)
    pdf, _ = packet.build(prep, answers())
    assert "could not get a fresh copy" in page_text(pdf, 0)


def test_changed_shape_falls_back(tmp_path):
    prep_sd(tmp_path)

    def wrong(url):
        if url.endswith("SOC426A.pdf"):
            return (FIX / "SOC426B.pdf").read_bytes()  # a different document at the same address
        if url.endswith("SOC426.pdf"):
            return b"<html>moved</html>"
        return fixture_fetch(url)

    prep = prep_sd(tmp_path, fetch=wrong)
    assert prep.copies["SOC426"].status == "fallback"
    assert "not a PDF" in prep.copies["SOC426"].warnings[0]
    assert prep.copies["SOC426A"].status == "fallback"


def test_no_copy_at_all(tmp_path):
    prep = prep_sd(tmp_path, fetch=failing_fetch)
    assert prep.copies["SOC426"].status == "unavailable"


def test_revision_change_flagged(tmp_path):
    from ihss_packet.forms import FormDef
    store = FormStore(tmp_path / "forms", fetch=fixture_fetch)
    f = STATE_FORMS["SOC426"]
    store.refresh(f)
    meta_path = tmp_path / "forms" / "en" / "SOC426" / "meta.json"
    import json
    meta = json.loads(meta_path.read_text())
    meta["history"][-1]["revision"] = "1/10"
    meta["history"][-1]["sha256"] = "different"
    meta_path.write_text(json.dumps(meta))
    c = store.refresh(f)
    assert c.status == "fresh"
    assert any("revision changed from (1/10) to (6/16)" in w for w in c.warnings)


def test_county_page_change_detected():
    text = (FIX / "steps-to-enroll.html").read_text().replace("$47.00", "$52.00").replace("Kingdom Security", "New Vendor")

    class R:
        def __init__(self, t): self.text, self.warning = t, ""
        def describe(self): return "checked"

    def fetch(key, url):
        from ihss_packet.sources import html_to_text
        if "steps" in key:
            return R(html_to_text(text))
        return R(html_to_text((FIX / "contact.html").read_text()))

    facts = san_diego.check_live(fetch)
    assert facts.fee_amount == "$52.00" and facts.fee_payee == "New Vendor"
    assert len([w for w in facts.warnings if "now shows" in w]) == 2


def test_non_module_county_state_forms_only(tmp_path):
    prep = packet.prepare("Alameda", FormStore(tmp_path / "f", fetch=fixture_fetch), PageStore(tmp_path / "p", fetch=fixture_fetch))
    assert prep.included() == ["SOC426", "SOC426A", "SOC846"]
    assert any("No county module" in w for w in prep.facts.warnings)


def test_imported_local_form_included_unchanged(tmp_path):
    store = FormStore(tmp_path / "forms", fetch=fixture_fetch)
    ok, _ = store.import_local(san_diego.LIVE_SCAN, (FIX / "SOC426B.pdf").read_bytes())
    assert ok
    prep = packet.prepare("San Diego", store, PageStore(tmp_path / "p", fetch=fixture_fetch))
    pdf, layout = packet.build(prep, answers())
    assert ("SD_LIVESCAN", 13, 2) in layout


def test_archive_naming_and_replace(tmp_path):
    d = tmp_path / "rec"
    p1 = records.archive(str(d), "Alex J Sample Jr.", b"%PDF-1", date(2026, 11, 11))
    assert p1.name == "2026-11-11 Alex J Sample Jr. - IHSS packet.pdf"
    p2 = records.archive(str(d), "Alex J Sample Jr.", b"%PDF-2", date(2026, 11, 11))
    assert p2.name.endswith("(2).pdf")
    p3 = records.archive(str(d), "Alex J Sample Jr.", b"%PDF-3", date(2026, 11, 11), replace=p2)
    assert p3 == p1 and not p2.exists() and p3.read_bytes() == b"%PDF-3"
    assert oct(p3.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(FileNotFoundError):
        records.archive(str(tmp_path / "missing" / "deeper"), "x", b"", date(2026, 1, 1))
