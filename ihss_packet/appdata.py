"""Local storage: where the tool keeps settings, saved recipient details and form copies.

Nothing here ever leaves the machine. Files holding personal details are written
with owner-only permissions (0600) inside an owner-only directory (0700).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "IHSS Packet Tool"


def data_dir() -> Path:
    override = os.environ.get("IHSS_PACKET_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ihss-packet-tool"
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass
    return base


def forms_dir() -> Path:
    d = data_dir() / "forms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_private(path: Path, data: bytes) -> None:
    """Atomically write a file readable only by the current user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj) -> None:
    write_private(path, json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"))


SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "setup_complete": False,
    "language": "en",
    "county": "",
    "records_dir": "",
    "recipient": {},
    "local_forms": {},  # form_id -> stored filename of a user-imported PDF
}


def load_settings() -> dict:
    s = read_json(data_dir() / SETTINGS_FILE, {})
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    merged.update(s)
    return merged


def save_settings(settings: dict) -> None:
    write_json(data_dir() / SETTINGS_FILE, settings)


def default_records_dir() -> str:
    return str(Path.home() / "Documents" / "IHSS Packets")
