from __future__ import annotations

from conftest import crawl_from_home

from seelo_audit.checks import forms


def test_forms_mailto_only_flagged_explicitly() -> None:
    """Cas le plus vendeur commercialement : aucun formulaire, mailto seul."""
    crawl = crawl_from_home("booking_absent_mailto.html")
    result = forms.run(crawl)
    assert result.status == "absent"
    assert result.detail["contact_is_mailto_only"] is True


def test_forms_native_form_with_email_detected() -> None:
    crawl = crawl_from_home("booking_partial_formdate.html")
    result = forms.run(crawl)
    assert result.status == "present"
    assert result.detail["field_count"] >= 3
    assert result.detail["contact_is_mailto_only"] is False
