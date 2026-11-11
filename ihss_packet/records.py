"""Archiving finished packets, and the optional encrypted disk image (macOS).

Archived packets contain Social Security numbers. The tool recommends keeping the
records folder inside an encrypted disk image and can create one with macOS's
built-in hdiutil. The password is passed to hdiutil on standard input and never
stored or logged by this tool.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from . import appdata

IMAGE_VOLUME_NAME = "IHSS Records"


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w .,'-]+", "", s, flags=re.UNICODE).strip()
    return re.sub(r"\s+", " ", s)[:80] or "Provider"


def archive_name(provider_name: str, day: date) -> str:
    return f"{day.isoformat()} {safe_name(provider_name)} - IHSS packet.pdf"


def archive(records_dir: str, provider_name: str, data: bytes, day: date | None = None,
            replace: Path | None = None) -> Path:
    """Write the packet into the records folder. `replace` is a path this same
    session archived earlier (a corrected version overwrites it)."""
    if not records_dir:
        raise FileNotFoundError("No records folder is set. Choose one in Setup.")
    root = Path(records_dir).expanduser()
    if not root.parent.exists():
        raise FileNotFoundError(f"The records folder's location {root.parent} is not available. "
                                "If it is on an encrypted disk image, open (mount) the image first.")
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    day = day or date.today()
    target = root / archive_name(provider_name, day)
    if replace is not None and replace.parent == root and replace.name.startswith(day.isoformat()):
        if replace != target:
            try:
                replace.unlink()
            except OSError:
                pass
    elif target.exists():
        stem, n = target.stem, 2
        while (root / f"{stem} ({n}).pdf").exists():
            n += 1
        target = root / f"{stem} ({n}).pdf"
    appdata.write_private(target, data)
    return target


def is_mac() -> bool:
    return sys.platform == "darwin"


def default_image_path() -> Path:
    return Path.home() / "Documents" / "IHSS Records.dmg"


def create_encrypted_image(password: str, image_path: Path | None = None, size: str = "1g") -> tuple[bool, str, str]:
    """Create and mount an AES-256 encrypted APFS disk image.

    Returns (ok, message, records_dir)."""
    if not is_mac():
        return False, "Creating an encrypted disk image here is only supported on macOS.", ""
    if len(password) < 8:
        return False, "Use a password of at least 8 characters.", ""
    image = Path(image_path or default_image_path()).expanduser()
    if image.exists():
        return False, f"{image} already exists. Open it in Finder to mount it, then pick its folder.", ""
    secret = password.encode("utf-8") + b"\0"  # hdiutil -stdinpass expects a NUL-terminated passphrase
    create = ["hdiutil", "create", "-size", size, "-fs", "APFS", "-encryption", "AES-256", "-stdinpass",
              "-volname", IMAGE_VOLUME_NAME, str(image)]
    r = subprocess.run(create, input=secret, capture_output=True, timeout=300)
    if r.returncode != 0:
        return False, "hdiutil could not create the image: " + r.stderr.decode(errors="replace").strip(), ""
    r = subprocess.run(["hdiutil", "attach", "-stdinpass", str(image)], input=secret, capture_output=True,
                       timeout=120)
    if r.returncode != 0:
        return False, ("The image was created but could not be opened: "
                       + r.stderr.decode(errors="replace").strip()), ""
    records = Path("/Volumes") / IMAGE_VOLUME_NAME / "IHSS Packets"
    records.mkdir(parents=True, exist_ok=True)
    return True, (f"Created {image} and opened it as “{IMAGE_VOLUME_NAME}”. Do not save the password in your "
                  "keychain if others use this Mac account. To use it later, double-click the image file in "
                  "Finder and enter the password."), str(records)
