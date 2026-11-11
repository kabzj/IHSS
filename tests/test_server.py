import http.client
import re
import threading
from pathlib import Path
from urllib.parse import urlencode

import pytest

from conftest import SAMPLE, fixture_fetch
from ihss_packet.server import App, make_server
from ihss_packet.sources import FormStore, PageStore


@pytest.fixture
def server(tmp_path):
    app = App(FormStore(tmp_path / "forms", fetch=fixture_fetch), PageStore(tmp_path / "pages", fetch=fixture_fetch))
    httpd = make_server(0, app)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd, app
    httpd.shutdown()
    httpd.server_close()


def req(httpd, method, path, body=None, host=None):
    port = httpd.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    data = None
    if body is not None:
        data = urlencode(body)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, data, headers)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_full_flow(server, tmp_path):
    httpd, app = server
    st, h, _ = req(httpd, "GET", "/")
    assert st == 303 and h["Location"] == "/setup"
    rec = {k: v for k, v in SAMPLE.items() if k.startswith("recipient.")}
    st, h, _ = req(httpd, "POST", "/setup", dict(rec, csrf=app.csrf, county="San Diego",
                                                 records_dir=str(tmp_path / "records")))
    assert st == 303 and h["Location"] == "/home"
    st, _, body = req(httpd, "GET", "/home")
    assert b"Kay Example" in body
    st, h, _ = req(httpd, "POST", "/packet/new", {"csrf": app.csrf})
    assert h["Location"] == "/packet/interview"
    st, _, body = req(httpd, "GET", "/packet/interview")
    assert b"Kay Example" in body and b"Required by SOC 426" in body
    prov = {k: v for k, v in SAMPLE.items() if k.startswith("provider.")}
    st, h, _ = req(httpd, "POST", "/packet/interview", dict(prov, csrf=app.csrf, go="review", **{"opt:SOC846": "on"}))
    assert h["Location"] == "/packet/review"
    st, _, body = req(httpd, "GET", "/packet/review")
    assert b"123-45-6789" in body and b"By hand" in body and b"SOC 846" in body
    # Nothing is built or archived before confirmation.
    assert not (tmp_path / "records").exists()
    st, h, _ = req(httpd, "POST", "/packet/build", {"csrf": app.csrf})
    assert h["Location"] == "/packet/done"
    files = list((tmp_path / "records").glob("*.pdf"))
    assert len(files) == 1 and "Alex J Sample Jr." in files[0].name
    st, h, pdf = req(httpd, "GET", "/packet/packet.pdf")
    assert st == 200 and pdf.startswith(b"%PDF") and h["Content-Type"] == "application/pdf"
    # Rebuild after a correction replaces the same archive file.
    req(httpd, "POST", "/packet/interview", dict(prov, csrf=app.csrf, go="review", **{"provider.lang_written": "Spanish"}))
    req(httpd, "POST", "/packet/build", {"csrf": app.csrf})
    assert len(list((tmp_path / "records").glob("*.pdf"))) == 1
    req(httpd, "POST", "/packet/discard", {"csrf": app.csrf})
    assert app.answers is None and app.pdf is None


def test_validation_errors_shown(server, tmp_path):
    httpd, app = server
    rec = {k: v for k, v in SAMPLE.items() if k.startswith("recipient.")}
    req(httpd, "POST", "/setup", dict(rec, csrf=app.csrf, county="San Diego", records_dir=str(tmp_path / "r")))
    req(httpd, "POST", "/packet/new", {"csrf": app.csrf})
    st, h, _ = req(httpd, "POST", "/packet/interview", {"csrf": app.csrf, "provider.ssn": "12", "go": "review"})
    assert h["Location"] == "/packet/interview"
    _, _, body = req(httpd, "GET", "/packet/interview")
    assert b"9 digits" in body


def test_csrf_and_host_checks(server):
    httpd, app = server
    st, _, _ = req(httpd, "POST", "/setup", {"csrf": "wrong"})
    assert st == 403
    st, _, _ = req(httpd, "GET", "/setup", host="evil.example:80")
    assert st == 403


def test_bound_to_localhost_only(server):
    httpd, _ = server
    assert httpd.server_address[0] == "127.0.0.1"
