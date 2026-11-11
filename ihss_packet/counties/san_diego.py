"""San Diego County module.

Verified 2026-11-11 against the San Diego IHSS Public Authority site:
  https://sdihsspa.com/caregiver/provider-enrollment/steps-to-enroll/
  https://sdihsspa.com/contact

What the Steps to Enroll page said on that date:
  * Bring to the in-person appointment: original SOC 426 ("No boxes should be
    blank. You MUST include an email address"), Social Security card
    (unaltered, no copies), unexpired U.S. federal or state government photo ID
    (names must match, including suffixes), work authorization if applicable,
    original SOC 426A completed by the recipient, and the Request for Live Scan
    Service form (complete the yellow highlighted area only) with $47.00 in
    cash, money order, or cashier's check payable to "Kingdom Security".
  * The Request for Live Scan Service form is NOT published online; it comes in
    the enrollment packet requested at (866) 351-7722 or via the online request
    form. The tool therefore lets the user import their copy.
  * SOC 846 is signed electronically (AdobeSign) after the online video
    session, so it is optional in the printed packet.

On each packet the module re-reads those pages and warns when the fee, payee,
office address, hours, or the list of forms no longer matches what was verified.
"""

from __future__ import annotations

import re

from ..forms import FormDef
from .base import CountyFacts, CountyModule

STEPS_URL = "https://sdihsspa.com/caregiver/provider-enrollment/steps-to-enroll/"
CONTACT_URL = "https://sdihsspa.com/contact"

VERIFIED = {
    "fee_amount": "$47.00",
    "fee_payee": "Kingdom Security",
    "fee_methods": "Cash, money order, or cashier's check",
    "office_name": "San Diego IHSS Public Authority — Caregiver Enrollment",
    "office_address": "401 Mile of Cars Way, Ste. 200, National City, CA 91950",
    "office_hours": "8:00 am – 5:00 pm, Monday – Friday, except legal holidays",
    "office_phone": "(866) 351-7722",
}

LIVE_SCAN = FormDef(
    form_id="SD_LIVESCAN",
    code="Live Scan",
    title="Request for Live Scan Service (from the San Diego enrollment packet)",
    completed_by="Provider — yellow highlighted area only",
    url=None,
    kind="form",
    notes="Not published online. Import the copy from your enrollment packet; it is included as-is "
          "for the provider to complete by hand.",
    source_page=STEPS_URL,
)


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


def parse_steps(text: str) -> dict:
    t = _norm(text)
    out: dict = {}
    m = re.search(r"Live Scan.{0,400}?(\$\s?\d+(?:\.\d{2})?)", t, re.I | re.S)
    if m:
        amt = m.group(1).replace(" ", "")
        out["fee_amount"] = amt if "." in amt else amt + ".00"
    m = re.search(r'payable to\s*"([^"]{2,80})"', t, re.I)
    if m:
        out["fee_payee"] = m.group(1).strip()
    m = re.search(r"\$\s?\d+(?:\.\d{2})?\s+in\s+([^.\-–]{3,80}?)\s+payable", t, re.I)
    if m:
        out["fee_methods"] = m.group(1).strip()
    out["mentions"] = {
        "SOC 426": bool(re.search(r"SOC\s*426\b(?!A)", t)),
        "SOC 426A": bool(re.search(r"SOC\s*426A\b", t)),
        "Live Scan": "live scan" in t.lower(),
        "email required": bool(re.search(r"must include an email", t, re.I)),
        "SOC 846 electronic": bool(re.search(r"SOC\s*846.{0,200}(AdobeSign|electronically)", t, re.I | re.S)),
    }
    return out


def parse_contact(text: str) -> dict:
    t = _norm(text)
    out: dict = {}
    out["address_found"] = "401 mile of cars way" in t.lower()
    m = re.search(r"Office Hours:\s*(.{5,90}?)(?:Submit|Follow|$)", t, re.I)
    if m:
        out["office_hours"] = m.group(1).strip()
    out["phone_found"] = "351-7722" in t
    return out


def check_live(fetch_page) -> CountyFacts:
    """fetch_page(cache_key, url) -> PageResult (see sources.py)."""
    f = CountyFacts(
        office_name=VERIFIED["office_name"],
        office_address=VERIFIED["office_address"],
        office_hours=VERIFIED["office_hours"],
        office_phone=VERIFIED["office_phone"],
        appointment_note="The in-person appointment is scheduled through the link in your enrollment packet; "
                         "confirm the appointment location there.",
        fee_amount=VERIFIED["fee_amount"],
        fee_payee=VERIFIED["fee_payee"],
        fee_methods=VERIFIED["fee_methods"],
        id_requirements=[
            "Original Social Security card (unaltered; no copies).",
            "Original unexpired U.S. federal or state government photo ID (e.g., DMV driver's license or ID, "
            "U.S. military ID, Permanent Resident Card, or U.S. passport).",
            "The full name on both must match exactly, including suffixes.",
            "If applicable: minor's work permit or other work-authorization documents.",
        ],
        bring_items=[
            "SOC 426, signed by the provider — every box completed, including an email address.",
            "SOC 426A, completed and signed by the recipient.",
            "Request for Live Scan Service form (yellow highlighted area completed) with the Live Scan fee.",
        ],
        steps_notes=[
            "After the in-person appointment, the provider schedules an online video session (Zoom; audio and "
            "video required). The link is given after the appointment.",
            "SOC 846 (Provider Enrollment Agreement) is emailed to the provider after the video session and "
            "signed electronically.",
            "Questions or a replacement form: Caregiver Enrollment, (866) 351-7722.",
        ],
    )

    steps = fetch_page("san_diego_steps", STEPS_URL)
    f.sources.append((STEPS_URL, steps.describe()))
    if steps.warning:
        f.warnings.append(steps.warning)
    if steps.text:
        p = parse_steps(steps.text)
        for k in ("fee_amount", "fee_payee"):
            if k not in p:
                f.warnings.append(f"Could not find the Live Scan {k.split('_')[1]} on the Steps to Enroll page; "
                                  f"showing the value verified on {MODULE.verified_on}. Confirm before the appointment.")
            elif p[k].lower() != VERIFIED[k].lower():
                f.warnings.append(f"The Steps to Enroll page now shows Live Scan {k.split('_')[1]} "
                                  f"'{p[k]}' (previously verified: '{VERIFIED[k]}'). The checklist uses the "
                                  f"page's current value.")
                setattr(f, k, p[k])
        if p.get("fee_methods"):
            f.fee_methods = p["fee_methods"][:1].upper() + p["fee_methods"][1:]
        missing = [name for name, ok in p["mentions"].items() if not ok]
        if missing:
            f.warnings.append("The Steps to Enroll page no longer mentions: " + ", ".join(missing)
                              + ". The enrollment steps may have changed; check the page.")
    else:
        f.warnings.append("Live Scan fee and the list of required items could not be checked; the checklist "
                          f"uses values verified on {MODULE.verified_on}.")

    contact = fetch_page("san_diego_contact", CONTACT_URL)
    f.sources.append((CONTACT_URL, contact.describe()))
    if contact.warning:
        f.warnings.append(contact.warning)
    if contact.text:
        c = parse_contact(contact.text)
        if not c["address_found"]:
            f.warnings.append("The Public Authority contact page no longer shows the verified office address. "
                              "Check the current address before going.")
        if c.get("office_hours") and _norm(c["office_hours"]).lower() != "8:00 am - 5:00 pm monday - friday except legal holidays":
            f.warnings.append(f"Office hours on the contact page now read: '{c['office_hours']}'.")
            f.office_hours = c["office_hours"]
    return f


MODULE = CountyModule(
    county_id="san_diego",
    name="San Diego",
    local_forms={LIVE_SCAN.form_id: LIVE_SCAN},
    core_forms=("SOC426", "SOC426A", "SD_LIVESCAN"),
    optional_forms={"SOC846": False, "SOC847": False, "SOC426B": False, "SOC426C": False},
    optional_notes={
        "SOC846": "San Diego sends SOC 846 by email after the video session for electronic signature, "
                  "so a paper copy is usually not needed.",
        "SOC847": "State information sheet: steps to becoming a provider.",
        "SOC426B": "State information sheet about the enrollment form.",
        "SOC426C": "Text of the crime code sections SOC 426 refers to.",
    },
    required_overrides={"SOC426": {"provider.email"}},
    check_live=check_live,
    verified_on="2026-11-11",
)
