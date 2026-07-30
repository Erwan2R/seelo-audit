from __future__ import annotations

from conftest import crawl_from_home

from seelo_audit.checks import booking


def test_booking_present_via_calendly() -> None:
    crawl = crawl_from_home("booking_present_calendly.html")
    result = booking.run(crawl)
    assert result.status == "present"
    assert result.provider == "calendly"
    assert "calendly" in result.evidence.lower()


def test_booking_absent_mailto_only() -> None:
    crawl = crawl_from_home("booking_absent_mailto.html")
    result = booking.run(crawl)
    assert result.status == "absent"
    assert result.detail["mailto_count"] == 2
    assert result.detail["tel_count"] == 1


def test_booking_partial_form_with_date_field() -> None:
    crawl = crawl_from_home("booking_partial_formdate.html")
    result = booking.run(crawl)
    assert result.status == "partial"
