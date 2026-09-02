"""P25 item 6 (P0-8): the three upload doors cap the body — a declared
over-cap length is refused before the read, an over-cap chunked stream
is refused mid-read, and nothing lands either way."""

from engine.web import limits
from tests.web.conftest import sign_in


def _capped(monkeypatch, cap):
    monkeypatch.setattr(limits, "MAX_INBOX_UPLOAD_BYTES", cap)
    monkeypatch.setattr(limits, "MAX_XLSX_IMPORT_BYTES", cap)
    monkeypatch.setattr(limits, "MAX_ADDENDUM_BYTES", cap)


def test_declared_length_over_the_cap_refuses_before_reading(offline_app,
                                                             monkeypatch):
    client = offline_app
    sign_in(client, "Cap Tester")
    client.post("/api/pursuits", json={"pursuit_id": "pur_cap"})
    _capped(monkeypatch, 1024)
    r = client.put("/api/pursuits/pur_cap/inbox/big.md", content=b"x" * 2048)
    assert r.status_code == 413 and "1 MiB" not in r.text
    ws = client.app.state.workspace
    assert not (ws / "pur_cap" / "inbox" / "big.md").exists()
    r = client.post("/api/kb/import.xlsx", content=b"x" * 2048)
    assert r.status_code == 413
    r = client.post("/api/pursuits/pur_cap/addenda?filename=a.md",
                    content=b"x" * 2048)
    assert r.status_code == 413
    assert not (ws / "pur_cap" / "addenda").exists() or not any(
        (ws / "pur_cap" / "addenda").iterdir())


def test_chunked_stream_over_the_cap_refuses_mid_read(offline_app, monkeypatch):
    client = offline_app
    sign_in(client, "Cap Tester")
    client.post("/api/pursuits", json={"pursuit_id": "pur_chunk"})
    _capped(monkeypatch, 1024)

    def chunks():
        for _ in range(4):
            yield b"y" * 600  # no Content-Length: the stream is the check

    r = client.put("/api/pursuits/pur_chunk/inbox/stream.md", content=chunks())
    assert r.status_code == 413
    ws = client.app.state.workspace
    assert not (ws / "pur_chunk" / "inbox" / "stream.md").exists()


def test_body_at_the_cap_passes(offline_app, monkeypatch):
    client = offline_app
    sign_in(client, "Cap Tester")
    client.post("/api/pursuits", json={"pursuit_id": "pur_ok"})
    _capped(monkeypatch, 1024)
    r = client.put("/api/pursuits/pur_ok/inbox/fits.md", content=b"z" * 1024)
    assert r.status_code == 200, r.text
    assert r.json()["bytes"] == 1024
