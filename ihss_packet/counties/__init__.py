"""County modules. Each module is self-contained: its local forms, source pages,
field mappings, fees, office details and checklist text.

To add a county, create a module exposing MODULE (a CountyModule) and register
it in MODULES below.
"""

from __future__ import annotations

from .base import CountyModule, CountyFacts  # noqa: F401
from . import san_diego

MODULES: dict[str, CountyModule] = {
    san_diego.MODULE.county_id: san_diego.MODULE,
}

CA_COUNTIES = (
    "Alameda", "Alpine", "Amador", "Butte", "Calaveras", "Colusa", "Contra Costa", "Del Norte",
    "El Dorado", "Fresno", "Glenn", "Humboldt", "Imperial", "Inyo", "Kern", "Kings", "Lake",
    "Lassen", "Los Angeles", "Madera", "Marin", "Mariposa", "Mendocino", "Merced", "Modoc", "Mono",
    "Monterey", "Napa", "Nevada", "Orange", "Placer", "Plumas", "Riverside", "Sacramento",
    "San Benito", "San Bernardino", "San Diego", "San Francisco", "San Joaquin", "San Luis Obispo",
    "San Mateo", "Santa Barbara", "Santa Clara", "Santa Cruz", "Shasta", "Sierra", "Siskiyou",
    "Solano", "Sonoma", "Stanislaus", "Sutter", "Tehama", "Trinity", "Tulare", "Tuolumne",
    "Ventura", "Yolo", "Yuba",
)


def county_id(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def module_for(county_name: str) -> CountyModule | None:
    return MODULES.get(county_id(county_name))
