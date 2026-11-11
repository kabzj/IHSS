# IHSS Packet Tool

A local tool for California IHSS recipients. It downloads the current provider-enrollment forms, walks the recipient and the new provider through one shared session, fills the forms, and produces a single double-sided print packet with a removable cover checklist. Spec: v0.1, November 11, 2026. Phase 1 covers San Diego County, in English.

This tool is not affiliated with IHSS, CDSS, any county, or any Public Authority. It does not give legal advice.

## Run it (macOS)

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
ihss-packet            # or: python -m ihss_packet
```

Your browser opens at `http://127.0.0.1:8765/`. The server listens only on this computer. Press Ctrl+C to stop it. Stopping clears the in-progress session.

## Privacy

- The only network traffic is GET requests for blank forms and public information pages on cdss.ca.gov and sdihsspa.com. No analytics, no telemetry, and no other calls.
- Provider answers, including the SSN, stay in memory. They reach disk only inside the finished packet PDF in the records folder.
- Saved recipient details and the form cache live in `~/Library/Application Support/IHSS Packet Tool/` with owner-only permissions.
- On macOS, Setup can create an AES-256 encrypted disk image for the records folder using the built-in `hdiutil`. The tool never stores the password.

## How it works

| Module | Role |
|---|---|
| `ihss_packet/forms.py` | State form definitions: CDSS URLs, field mapping, required, handwritten, and county-use fields |
| `ihss_packet/counties/` | Self-contained county modules (`san_diego.py`) |
| `ihss_packet/questions.py` | The interview: each question is asked once, and derived values feed every form |
| `ihss_packet/sources.py` | Fresh download on each packet; validation (is it a PDF, the right form, are the mapped fields present); last-good-copy fallback with warnings; revision tracking |
| `ihss_packet/fill.py` | Fills the PDF's own fields, then flattens them. Supports an overlay for non-fillable forms. Never changes page count or order |
| `ihss_packet/packet.py` | Review data, the one-page cover checklist, and duplex assembly (a blank page after each odd-length part) |
| `ihss_packet/records.py` | Archive (`YYYY-MM-DD Name - IHSS packet.pdf`) and the encrypted-image helper |
| `ihss_packet/server.py` | Local web UI: setup, hiring session, review, print |

To add a county, write a module like `counties/san_diego.py` and register it in `counties/__init__.py`.

## Verified against official sources on 2026-11-11

- State forms on cdss.ca.gov:
  - SOC 426 (6/16): 5 pages, fillable
  - SOC 426A (1/16): 3 pages, fillable
  - SOC 846 (11/15): 6 pages, fillable
  - SOC 847 (5/16), SOC 426B (10/09), SOC 426C (10/10): information sheets, optional
- San Diego, from sdihsspa.com, Steps to Enroll and Contact pages:
  - Live Scan fee: $47.00, cash, money order, or cashier's check, payable to "Kingdom Security".
  - Bring the original Social Security card and an unexpired government photo ID.
  - SOC 426 must have no blank boxes and must include an email address.
  - Office: 401 Mile of Cars Way, Ste. 200, National City, CA 91950. Hours: 8–5, Monday–Friday.

The tool re-reads these pages for every packet. If anything differs, it warns you.

## Known gaps

- **Live Scan form:** San Diego does not publish its *Request for Live Scan Service* form online; it comes in the enrollment packet. Setup lets you import that PDF, and the tool includes it unfilled. The page says to complete only the yellow highlighted area.
- **SOC 846:** San Diego has providers sign SOC 846 electronically after the video session. In the San Diego module it is optional and off by default.
- **Typed fields:** SOC 426 and 426A say "Use black or blue ink … Print information clearly." The fillable PDFs come from CDSS, but confirm with the Public Authority that typed entries are accepted.
- **Not yet built:** Spanish forms, other counties, and a packaged app.

## Tests

```sh
pip install -e '.[test]'
pytest
```

The tests run offline against copies of the official forms and pages in `tests/fixtures/`.
