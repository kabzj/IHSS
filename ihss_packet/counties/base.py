from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..forms import FormDef


@dataclass
class CountyFacts:
    """Facts shown on the cover checklist. `warnings` explain anything that could
    not be confirmed against the live source pages for this packet."""
    office_name: str = ""
    office_address: str = ""
    office_hours: str = ""
    office_phone: str = ""
    appointment_note: str = ""
    fee_amount: str = ""
    fee_payee: str = ""
    fee_methods: str = ""
    id_requirements: list[str] = field(default_factory=list)
    bring_items: list[str] = field(default_factory=list)
    steps_notes: list[str] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)  # (url, "checked <date>" / "cached copy from <date>")
    warnings: list[str] = field(default_factory=list)


@dataclass
class CountyModule:
    county_id: str
    name: str
    local_forms: dict[str, FormDef]
    core_forms: tuple[str, ...]              # always in the packet, in order
    optional_forms: dict[str, bool]          # form_id -> included by default
    optional_notes: dict[str, str]
    required_overrides: dict[str, set[str]]  # form_id -> value keys this county requires
    check_live: Callable[[Callable], CountyFacts]  # given fetch_page, returns facts
    verified_on: str = ""
