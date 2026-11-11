"""State (CDSS) form definitions and field mappings.

Field names, item numbers and revision markings below were read from the
official PDFs downloaded from cdss.ca.gov on 2026-11-11. When CDSS publishes
a new revision, the downloader flags it; check the mapping before relying on it.

County-specific forms live in ihss_packet/counties/, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# Field modes
FILL = "fill"            # tool fills it from the session answers
HANDWRITE = "handwrite"  # must be completed by hand (signing dates etc.); left blank
COUNTY = "county"        # for county use only; left blank


@dataclass(frozen=True)
class FieldMap:
    pdf_field: str
    label: str                       # item as printed on the form
    key: str = ""                    # value key from questions.derive()
    mode: str = FILL
    kind: str = "text"               # text | check | radio
    on: str = ""                     # check: value of `key` that ticks the box; radio: unused
    radio: tuple[tuple[str, str], ...] = ()  # radio: (value of key, PDF export name)
    required: bool | Callable[[dict], bool] = False
    who: str = ""                    # for HANDWRITE: who writes it
    page: int = 0                    # 0-based page index where the field sits

    def is_required(self, values: dict) -> bool:
        return self.required(values) if callable(self.required) else bool(self.required)


@dataclass(frozen=True)
class HandItem:
    """Something on the form that must be done by hand that is not a fillable field
    (signature lines)."""
    label: str
    who: str
    page: int


@dataclass(frozen=True)
class OverlayText:
    """Text placed on a non-fillable page at fixed coordinates (PDF points, origin bottom-left)."""
    key: str
    label: str
    page: int
    x: float
    y: float
    size: float = 10
    required: bool = False


@dataclass(frozen=True)
class FormDef:
    form_id: str                 # e.g. "SOC426"
    code: str                    # as printed, e.g. "SOC 426"
    title: str
    completed_by: str
    url: str | None              # None => no public download (user imports a copy)
    kind: str = "form"           # form | info
    fields: tuple[FieldMap, ...] = ()
    overlays: tuple[OverlayText, ...] = ()
    hand_items: tuple[HandItem, ...] = ()
    verified_revision: str = ""  # revision the mapping was checked against
    expected_pages: int | None = None
    notes: str = ""
    source_page: str = ""        # human-facing page that links the form, for warnings

    @property
    def fillable(self) -> bool:
        return bool(self.fields)


CDSS_FORM_URL = "https://www.cdss.ca.gov/cdssweb/entres/forms/{lang_dir}/{form_id}.pdf"
LANG_DIRS = {"en": "English"}  # Spanish later: separate form IDs/mappings are needed.


def cdss_url(form_id: str, lang: str = "en") -> str:
    return CDSS_FORM_URL.format(lang_dir=LANG_DIRS[lang], form_id=form_id)


def _rehab_required(v: dict) -> bool:
    return v.get("provider.tier2") == "Y"


def _yes_no(prefix_field_yes: str, prefix_field_no: str, key: str, item: str, page: int,
            required=True) -> tuple[FieldMap, FieldMap]:
    return (
        FieldMap(prefix_field_yes, f"{item} — YES box", key, kind="check", on="Y", required=required, page=page),
        FieldMap(prefix_field_no, f"{item} — NO box", key, kind="check", on="N", required=required, page=page),
    )


SOC426 = FormDef(
    form_id="SOC426",
    code="SOC 426",
    title="IHSS Program Provider Enrollment Form",
    completed_by="Provider",
    url=cdss_url("SOC426"),
    verified_revision="6/16",
    expected_pages=5,
    fields=(
        FieldMap("SOC 426 Pg 3 1", "Part A 1. Full name", "provider.full_name", required=True, page=2),
        FieldMap("SOC 426 Pg 3 2", "Part A 2. Date of birth", "provider.dob", required=True, page=2),
        FieldMap("SOC 426 Pg 3 3", "Part A 3. Gender — M box", "provider.gender", kind="check", on="M",
                 required=True, page=2),
        FieldMap("SOC 426 Pg 3 4", "Part A 3. Gender — F box", "provider.gender", kind="check", on="F",
                 required=True, page=2),
        FieldMap("SOC426 Pg 3 5", "Part A 4. Home address", "provider.home_address", required=True, page=2),
        FieldMap("SOC 426 Pg 3 6", "Part A 4. City", "provider.home_city", required=True, page=2),
        FieldMap("SOC 426 Pg 3 7", "Part A 4. State", "provider.home_state", required=True, page=2),
        FieldMap("SOC 426 Pg 3 8", "Part A 4. Zip", "provider.home_zip", required=True, page=2),
        FieldMap("SOC 426 Pg 3 9", "Part A 5. Mailing address (if different)", "provider.mail_address", page=2),
        FieldMap("SOC 426 Pg 3 10", "Part A 5. City", "provider.mail_city", page=2),
        FieldMap("SOC 426 Pg 3 11", "Part A 5. State", "provider.mail_state", page=2),
        FieldMap("SOC 426 Pg 3 12", "Part A 5. Zip", "provider.mail_zip", page=2),
        FieldMap("SOC 426 Pg 3 13", "Part A 6. Telephone number", "provider.phone", required=True, page=2),
        FieldMap("SOC 426 Pg 3 14", "Part A 7. Social Security number", "provider.ssn", required=True, page=2),
        FieldMap("SOC 426 Pg 3 15", "Part A 8. E-mail address (if any)", "provider.email", page=2),
        FieldMap("SOC 426 Pg 3 16", "Part A 9a. Driver's license # or government ID #", "provider.id_number",
                 required=True, page=2),
        FieldMap("SOC 426 Pg 3 17", "Part A 9b. Expiration date", "provider.id_expires", required=True, page=2),
        FieldMap("SOC 426 Pg 3 18", "Part A 9c. Issuing state", "provider.id_state", required=True, page=2),
        FieldMap("SOC 426 Pg 3 19", "Part A 10a. Primary spoken language", "provider.lang_spoken",
                 required=True, page=2),
        FieldMap("SOC 426 Pg 3 20", "Part A 10b. Primary written language", "provider.lang_written",
                 required=True, page=2),
        FieldMap("SOC 426 Pg 4 1", "Provider's name (header, pages 4 and 5)", "provider.full_name",
                 required=True, page=3),
        *_yes_no("SOC 426 Pg 4 2", "SOC 426 Pg 4 3", "provider.tier1", "Part B 1a. Tier 1 crime", 3),
        *_yes_no("SOC 426 Pg 4 4", "SOC 426 Pg 4 5", "provider.tier2", "Part B 1b. Tier 2 crime", 3),
        *_yes_no("SOC 426 Pg 4 6", "SOC 426 Pg 4 7", "provider.rehab",
                 "Part B 2. Certificate of rehabilitation / expungement", 3, required=_rehab_required),
        FieldMap("SOC 426 Pg 5 1", "Part C. Date (next to provider's signature)", mode=HANDWRITE,
                 who="Provider", page=4),
        FieldMap("soc 426 Pg 5 2", "Part C. Printed name", "provider.full_name", required=True, page=4),
        FieldMap("SOC 426 Pg 5 3", "County representative's date", mode=COUNTY, page=4),
    ),
    hand_items=(
        HandItem("Part C. Provider's signature (under penalty of perjury)", "Provider", 4),
    ),
    notes="Return in person with original photo ID and original Social Security card.",
)

SOC426A = FormDef(
    form_id="SOC426A",
    code="SOC 426A",
    title="Recipient Designation of Provider",
    completed_by="Recipient (or authorized representative)",
    url=cdss_url("SOC426A"),
    verified_revision="1/16",
    expected_pages=3,
    fields=(
        FieldMap("pg1-1", "1. Recipient's name", "recipient.name", required=True),
        FieldMap("pg1-2", "2. County IHSS case #", "recipient.case_number", required=True),
        FieldMap("pg1-3", "3. Provider's name", "provider.full_name", required=True),
        FieldMap("pg1-4", "4. Provider's address", "provider.home_address", required=True),
        FieldMap("pg1-5", "4. City, State, ZIP code", "provider.home_csz", required=True),
        FieldMap("pg1-6", "5. Provider's telephone number", "provider.phone", required=True),
        FieldMap("pg1-7", "6. Provider's date of birth", "provider.dob", required=True),
        FieldMap("pg1-8", "7. Provider's Social Security #", "provider.ssn", required=True),
        FieldMap("pg1-9", "8. Provider's gender", "provider.gender", kind="radio",
                 radio=(("M", "/Male"), ("F", "/Female")), required=True),
        FieldMap("pg1_10", "9. Relationship — Parent", "provider.relationship", kind="check", on="parent"),
        FieldMap("Pg 1_11", "9. Relationship — Child", "provider.relationship", kind="check", on="child"),
        FieldMap("Pg1_12", "9. Relationship — Spouse/Domestic Partner", "provider.relationship",
                 kind="check", on="spouse"),
        FieldMap("Pg1_13", "9. Relationship — Conservator", "provider.relationship", kind="check",
                 on="conservator"),
        FieldMap("Pg1_14", "9. Relationship — Guardian", "provider.relationship", kind="check", on="guardian"),
        FieldMap("Pg1_16", "9. Relationship — Other", "provider.relationship", kind="check", on="other"),
        FieldMap("pg1-11", "9. Other: specify", "provider.relationship_other",
                 required=lambda v: v.get("provider.relationship") == "other"),
        FieldMap("pg1-12", "10. Provider's start date", "provider.start_date", required=True),
        FieldMap("pg3-1", "Part C. Date (next to recipient's signature)", mode=HANDWRITE,
                 who="Recipient", page=2),
        FieldMap("pg3-2", "Part C. Recipient's printed name", "recipient.name", required=True, page=2),
        FieldMap("pg3-3", "Part C. Date (next to authorized representative's signature)", mode=HANDWRITE,
                 who="Authorized representative (only if one signs)", page=2),
        FieldMap("pg3-4", "Part C. Authorized representative's printed name", "recipient.auth_rep_name", page=2),
        FieldMap("pg3-5", "For county use: worker name", mode=COUNTY, page=2),
        FieldMap("pg3-6", "For county use: date", mode=COUNTY, page=2),
    ),
    hand_items=(
        HandItem("Part C. Recipient's signature", "Recipient", 2),
        HandItem("Part C. Authorized representative's signature",
                 "Authorized representative (only if one signs)", 2),
    ),
)

SOC846 = FormDef(
    form_id="SOC846",
    code="SOC 846",
    title="Provider Enrollment Agreement",
    completed_by="Provider",
    url=cdss_url("SOC846"),
    verified_revision="11/15",
    expected_pages=6,
    fields=(
        FieldMap("number", "Provider number (page 1)", "provider.number"),
        FieldMap("provider", "Provider name (page 1)", "provider.full_name", required=True),
        FieldMap("number_header", "Provider number (header, pages 2–6)", "provider.number", page=1),
        FieldMap("date", "Date signed by IHSS provider", mode=HANDWRITE, who="Provider", page=5),
        FieldMap("provider_2", "Provider name (page 6, signature block)", "provider.full_name",
                 required=True, page=5),
    ),
    hand_items=(HandItem("Provider's signature (page 6)", "Provider", 5),),
)

SOC847 = FormDef("SOC847", "SOC 847", "Steps to Becoming an IHSS Provider (information)", "—",
                 cdss_url("SOC847"), kind="info", verified_revision="5/16", expected_pages=4)
SOC426B = FormDef("SOC426B", "SOC 426B", "Provider Enrollment Form FAQ (information)", "—",
                  cdss_url("SOC426B"), kind="info", expected_pages=2)
SOC426C = FormDef("SOC426C", "SOC 426C", "Text of the Tier 1 and Tier 2 crime code sections (information)", "—",
                  cdss_url("SOC426C"), kind="info", verified_revision="10/10", expected_pages=4,
                  notes="SOC 426 refers to SOC 426C as attached; CDSS publishes it separately.")

STATE_FORMS: dict[str, FormDef] = {f.form_id: f for f in (SOC426, SOC426A, SOC846, SOC847, SOC426B, SOC426C)}

# Default state-only packet (counties without a module).
STATE_CORE = ("SOC426", "SOC426A", "SOC846")
STATE_INFO = ("SOC847", "SOC426B", "SOC426C")


def keys_used(form: FormDef) -> set[str]:
    return {f.key for f in form.fields if f.key and f.mode == FILL} | {o.key for o in form.overlays}
