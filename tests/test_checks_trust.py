from __future__ import annotations

from conftest import crawl_from_home

from seelo_audit.checks import trust


def test_trust_signals_rich_page_scores_high() -> None:
    crawl = crawl_from_home("trust_signals_rich.html")
    result = trust.run(crawl)
    assert result.status == "present"
    subchecks = result.detail["subchecks"]
    assert subchecks["legal_notice"]["present"] is True
    assert subchecks["privacy_policy"]["present"] is True
    assert subchecks["terms"]["present"] is True
    assert subchecks["siret"]["present"] is True
    assert subchecks["reviews"]["present"] is True
    assert subchecks["certifications"]["present"] is True
    assert subchecks["address"]["present"] is True
    assert subchecks["phone"]["present"] is True
    assert result.detail["score"] == 1.0


def test_trust_signals_empty_page_scores_absent() -> None:
    crawl = crawl_from_home("booking_present_calendly.html")
    result = trust.run(crawl)
    assert result.status == "absent"
    assert result.detail["score"] == 0.0
