"""Baseline security headers + the cross-site write guard (P25 item 4;
register P0-7).

A loopback bind is not a security boundary for a browser: a page on any
origin can address 127.0.0.1. `TrustedHostMiddleware` (wired in
`create_app`) closes DNS rebinding — the Host header must be one the
operator serves. This middleware adds the headers every response should
carry (a strict CSP fits: the UI has no inline scripts or styles), marks
API responses no-store, and refuses any non-safe request a browser
labels `Sec-Fetch-Site: cross-site` — the raw-body upload doors accept
`text/plain`, so a cross-origin "simple" PUT would otherwise execute
even though its response is unreadable. curl and the pilot's scripts
send no Sec-Fetch-Site and pass.
"""

SECURITY_HEADERS = {
    "content-security-policy": ("default-src 'self'; frame-ancestors 'none'; "
                                "base-uri 'none'; form-action 'self'; "
                                "object-src 'none'"),
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
_REFUSAL = (b'{"detail":"cross-site writes are refused (Sec-Fetch-Site: '
            b'cross-site) - the engine serves its own UI only"}')


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                           for k, v in scope.get("headers", [])}
        extra = [(k.encode("latin-1"), v.encode("latin-1"))
                 for k, v in SECURITY_HEADERS.items()]
        if scope["path"].startswith("/api/"):
            extra.append((b"cache-control", b"no-store"))
        if (scope["method"] not in SAFE_METHODS
                and request_headers.get("sec-fetch-site") == "cross-site"):
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length",
                                     str(len(_REFUSAL)).encode())] + extra})
            await send({"type": "http.response.body", "body": _REFUSAL})
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                raw = list(message.get("headers", []))
                present = {k.lower() for k, _ in raw}
                raw += [(k, v) for k, v in extra if k not in present]
                message = {**message, "headers": raw}
            await send(message)

        await self.app(scope, receive, send_with_headers)
