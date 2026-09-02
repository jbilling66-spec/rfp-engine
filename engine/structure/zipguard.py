"""The office-zip guard (P25 item 6; register P0-8). xlsx and docx are
zip containers; openpyxl and python-docx inflate them whole, in-process.
Before any parser opens an UNTRUSTED document this guard reads the
central directory only and refuses a container whose member count, total
uncompressed size, or per-member compression ratio exceeds the owner's
ceilings (B97 §1) — the zip-bomb class, distinct from the byte caps at
the upload doors. Internal-entity expansion (the XML class) is closed
separately by defusedxml, which openpyxl adopts on import (P2-25).
"""

import zipfile
from pathlib import Path

MiB = 1024 * 1024
MAX_MEMBERS = 10_000
MAX_UNCOMPRESSED = 250 * MiB
MAX_RATIO = 100
RATIO_FLOOR = 16 * MiB  # small XML parts legitimately compress 50:1+


class ZipGuardError(ValueError):
    """The container exceeds a ceiling — refuse before inflating."""


def check_office_zip(path, *, max_members: int = MAX_MEMBERS,
                     max_uncompressed: int = MAX_UNCOMPRESSED,
                     max_ratio: int = MAX_RATIO) -> dict:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise ZipGuardError(f"{path.name}: not a zip container ({exc})")
    if len(infos) > max_members:
        raise ZipGuardError(
            f"{path.name}: {len(infos)} members exceed the {max_members} "
            "ceiling")
    total = sum(info.file_size for info in infos)
    if total > max_uncompressed:
        raise ZipGuardError(
            f"{path.name}: {total // MiB} MiB uncompressed exceeds the "
            f"{max_uncompressed // MiB} MiB ceiling")
    for info in infos:
        if (info.file_size > RATIO_FLOOR and info.compress_size
                and info.file_size / info.compress_size > max_ratio):
            raise ZipGuardError(
                f"{path.name}: member {info.filename!r} inflates "
                f"{info.file_size // max(info.compress_size, 1)}:1, over "
                f"the {max_ratio}:1 ceiling")
    return {"members": len(infos), "uncompressed": total}
