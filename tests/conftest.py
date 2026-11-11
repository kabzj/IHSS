from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"

URL_TO_FIXTURE = {
    "SOC426.pdf": "SOC426.pdf", "SOC426A.pdf": "SOC426A.pdf", "SOC846.pdf": "SOC846.pdf",
    "SOC847.pdf": "SOC847.pdf", "SOC426B.pdf": "SOC426B.pdf", "SOC426C.pdf": "SOC426C.pdf",
    "steps-to-enroll/": "steps-to-enroll.html", "contact": "contact.html",
}


def fixture_fetch(url: str) -> bytes:
    for suffix, name in URL_TO_FIXTURE.items():
        if url.endswith(suffix):
            return (FIX / name).read_bytes()
    raise AssertionError(f"unexpected URL {url}")


def failing_fetch(url: str) -> bytes:
    raise ConnectionError("offline")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("IHSS_PACKET_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


SAMPLE = {
    "recipient.name": "Kay Example", "recipient.case_number": "1234567",
    "recipient.address": "1 Test St", "recipient.city": "San Diego", "recipient.state": "CA",
    "recipient.zip": "92101", "recipient.phone": "6195550100",
    "provider.first": "Alex", "provider.mi": "J", "provider.last": "Sample Jr.",
    "provider.dob": "1990-02-03", "provider.gender": "F",
    "provider.home_address": "22 Example Ave", "provider.home_city": "Chula Vista",
    "provider.home_state": "ca", "provider.home_zip": "91910", "provider.phone": "619-555-0199",
    "provider.ssn": "123456789", "provider.email": "alex@example.com", "provider.id_number": "D1234567",
    "provider.id_expires": "2030-02-03", "provider.id_state": "CA", "provider.lang_spoken": "English",
    "provider.lang_written": "English", "provider.tier1": "N", "provider.tier2": "N",
    "provider.relationship": "other", "provider.relationship_other": "Friend",
    "provider.start_date": "2026-12-01",
}
