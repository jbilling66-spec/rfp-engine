"""Upload byte caps (P25 item 6; register P0-8). The owner's ceilings
(B97 §1): generous for any buyer package seen so far, tunable by a
one-line change plus a B-entry.

`read_body_capped` refuses a declared Content-Length over the cap BEFORE
reading, then consumes the stream and aborts the moment the running
total exceeds the cap — a post-hoc `len(body)` check would still have
buffered the whole payload in the single server process.
"""

from fastapi import HTTPException, Request

MiB = 1024 * 1024
MAX_INBOX_UPLOAD_BYTES = 50 * MiB
MAX_XLSX_IMPORT_BYTES = 20 * MiB
MAX_ADDENDUM_BYTES = 10 * MiB


def _too_large(cap: int) -> HTTPException:
    return HTTPException(413, f"upload exceeds the {cap // MiB} MiB cap")


async def read_body_capped(request: Request, cap: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > cap:
                raise _too_large(cap)
        except ValueError:
            raise HTTPException(400, "malformed Content-Length")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise _too_large(cap)
        chunks.append(chunk)
    return b"".join(chunks)
