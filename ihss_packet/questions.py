"""The hiring-session questions. Each is asked once; form definitions map the
answers (and values derived from them) onto every field that needs them."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Question:
    key: str
    label: str
    section: str  # "recipient" | "provider"
    kind: str = "text"  # text | date | ssn | phone | email | state | zip | choice | initial
    choices: tuple[tuple[str, str], ...] = ()
    hint: str = ""
    show_if: tuple[str, str] | None = None  # (other key, value) controls visibility hint only


GENDER = (("", "Not chosen yet"), ("M", "Male"), ("F", "Female"), ("HAND", "Leave blank — mark by hand"))
YES_NO = (("", "Not answered"), ("Y", "Yes"), ("N", "No"), ("HAND", "Leave blank — mark by hand"))
YES_NO_NA = (("", "Not answered"), ("Y", "Yes"), ("N", "No"),
             ("NA", "Does not apply (answered No to 1b)"), ("HAND", "Leave blank — mark by hand"))
RELATIONSHIP = (("", "None"), ("parent", "Parent"), ("child", "Child"),
                ("spouse", "Spouse/Domestic Partner"), ("conservator", "Conservator"),
                ("guardian", "Guardian"), ("other", "Other (specify)"))


QUESTIONS: tuple[Question, ...] = (
    # Recipient (prefilled from setup; editable per packet)
    Question("recipient.name", "Recipient's full name", "recipient"),
    Question("recipient.case_number", "County IHSS case number", "recipient"),
    Question("recipient.address", "Street address", "recipient"),
    Question("recipient.city", "City", "recipient"),
    Question("recipient.state", "State", "recipient", "state"),
    Question("recipient.zip", "ZIP code", "recipient", "zip"),
    Question("recipient.phone", "Phone", "recipient", "phone"),
    Question("recipient.auth_rep_name", "Authorized representative's name (if any)", "recipient",
             hint="Leave blank if the recipient signs for themselves."),
    # Provider
    Question("provider.first", "First name", "provider",
             hint="Use the full official name exactly as it appears on the Social Security card, including any suffix."),
    Question("provider.mi", "Middle initial", "provider", "initial"),
    Question("provider.last", "Last name (with suffix, if any)", "provider"),
    Question("provider.dob", "Date of birth", "provider", "date",
             hint="Providers under 18 must also bring a valid work permit."),
    Question("provider.gender", "Gender (as the forms ask it)", "provider", "choice", GENDER,
             hint="The state forms offer only these two boxes. Choose the last option to mark it by hand instead."),
    Question("provider.home_address", "Home street address", "provider",
             hint="Must be a physical address, not a P.O. Box."),
    Question("provider.home_city", "Home city", "provider"),
    Question("provider.home_state", "Home state", "provider", "state"),
    Question("provider.home_zip", "Home ZIP code", "provider", "zip"),
    Question("provider.mail_address", "Mailing street address (only if different from home)", "provider"),
    Question("provider.mail_city", "Mailing city", "provider"),
    Question("provider.mail_state", "Mailing state", "provider", "state"),
    Question("provider.mail_zip", "Mailing ZIP code", "provider", "zip"),
    Question("provider.phone", "Phone (with area code)", "provider", "phone"),
    Question("provider.ssn", "Social Security number", "provider", "ssn",
             hint="Kept in memory only for this session; it is written only into the packet PDF and its archived copy."),
    Question("provider.email", "Email address", "provider", "email"),
    Question("provider.id_number", "Driver's license or government-issued ID number", "provider"),
    Question("provider.id_expires", "ID expiration date", "provider", "date"),
    Question("provider.id_state", "ID issuing state", "provider", "state"),
    Question("provider.lang_spoken", "Primary spoken language", "provider"),
    Question("provider.lang_written", "Primary written language", "provider"),
    Question("provider.tier1", "SOC 426 Part B, 1a: Within the past 10 years, convicted of or incarcerated "
             "following a conviction for a Tier 1 crime?", "provider", "choice", YES_NO,
             hint="The provider answers this under penalty of perjury. Tier definitions are on page 1 of SOC 426."),
    Question("provider.tier2", "SOC 426 Part B, 1b: Within the past 10 years, convicted of or incarcerated "
             "following a conviction for a Tier 2 crime?", "provider", "choice", YES_NO),
    Question("provider.rehab", "SOC 426 Part B, 2: If Yes to 1b, obtained a certificate of rehabilitation "
             "or expungement?", "provider", "choice", YES_NO_NA),
    Question("provider.relationship", "Provider's relationship to the recipient (if any)", "provider",
             "choice", RELATIONSHIP),
    Question("provider.relationship_other", "If Other, specify", "provider"),
    Question("provider.start_date", "Provider's start date", "provider", "date"),
    Question("provider.number", "IHSS provider number (only if already assigned)", "provider",
             hint="New providers usually leave this blank; the county assigns it."),
)

QUESTION_BY_KEY = {q.key: q for q in QUESTIONS}

RECIPIENT_SETUP_KEYS = [q.key for q in QUESTIONS if q.section == "recipient"]


def fmt_date(iso: str) -> str:
    """'2026-01-05' -> '01/05/2026' (the MM/DD/YYYY the state forms use)."""
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso).strftime("%m/%d/%Y")
    except ValueError:
        return iso


def fmt_ssn(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return f"{d[:3]}-{d[3:5]}-{d[5:]}" if len(d) == 9 else (s or "").strip()


def fmt_phone(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else (s or "").strip()


def validate(answers: dict) -> dict[str, str]:
    """Format problems only (missing values are handled per form as 'required')."""
    errs: dict[str, str] = {}
    for q in QUESTIONS:
        v = (answers.get(q.key) or "").strip()
        if not v:
            continue
        if q.kind == "ssn" and len(re.sub(r"\D", "", v)) != 9:
            errs[q.key] = "A Social Security number has 9 digits."
        elif q.kind == "phone" and len(re.sub(r"\D", "", v)) not in (10, 11):
            errs[q.key] = "Enter a 10-digit phone number with area code."
        elif q.kind == "zip" and not re.fullmatch(r"\d{5}(-\d{4})?", v):
            errs[q.key] = "ZIP code should be 5 digits (or ZIP+4)."
        elif q.kind == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            errs[q.key] = "That doesn't look like an email address."
        elif q.kind == "state" and not re.fullmatch(r"[A-Za-z]{2}", v):
            errs[q.key] = "Use the 2-letter state code, e.g. CA."
        elif q.kind == "initial" and len(v.rstrip(".")) > 1:
            errs[q.key] = "Middle initial only (one letter)."
        elif q.kind == "date":
            try:
                date.fromisoformat(v)
            except ValueError:
                errs[q.key] = "Enter a date."
    return errs


def derive(answers: dict) -> dict[str, str]:
    """Flat value table: formatted answers plus combined values used on forms."""
    a = {k: (answers.get(k) or "").strip() for k in QUESTION_BY_KEY}
    v: dict[str, str] = dict(a)
    for q in QUESTIONS:
        if q.kind == "date":
            v[q.key] = fmt_date(a[q.key])
        elif q.kind == "ssn":
            v[q.key] = fmt_ssn(a[q.key])
        elif q.kind == "phone":
            v[q.key] = fmt_phone(a[q.key])
        elif q.kind == "state":
            v[q.key] = a[q.key].upper()
        elif q.kind == "initial":
            v[q.key] = a[q.key].rstrip(".").upper()
    mi = v["provider.mi"]
    v["provider.full_name"] = " ".join(p for p in (a["provider.first"], mi, a["provider.last"]) if p)
    city_state_zip = ", ".join(p for p in (a["provider.home_city"], v["provider.home_state"]) if p)
    v["provider.home_csz"] = (city_state_zip + " " + a["provider.home_zip"]).strip()
    if a["provider.relationship"] != "other":
        v["provider.relationship_other"] = ""
    if a["provider.tier2"] != "Y" and a["provider.rehab"] in ("", "NA"):
        v["provider.rehab"] = "NA"
    return v


def blank_answers(recipient: dict | None = None) -> dict:
    ans = {q.key: "" for q in QUESTIONS}
    for k, val in (recipient or {}).items():
        if k in ans:
            ans[k] = val
    return ans
