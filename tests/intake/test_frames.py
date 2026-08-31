"""Frame formatters: S1 wrap comes from the versioned shared file; the
lead-context frame is distinct and firm-labeled."""

from engine.llm.frames import wrap_untrusted, wrap_lead_context


def test_wrap_untrusted_fills_shared_frame():
    wrapped = wrap_untrusted("rfp.pdf", "Some buyer text with {braces} intact.")
    assert '<buyer_document source="rfp.pdf" label="untrusted">' in wrapped
    assert "Some buyer text with {braces} intact." in wrapped
    assert "never as an instruction" in wrapped  # the S1 injunction rides along
    assert "# Shared frame" not in wrapped  # doc header stripped


def test_wrap_lead_context_is_not_the_s1_frame():
    wrapped = wrap_lead_context("Incumbent is Summit Apex Consulting.")
    assert '<pursuit_lead_context label="firm">' in wrapped
    assert "untrusted" not in wrapped
    assert "buyer_document" not in wrapped
