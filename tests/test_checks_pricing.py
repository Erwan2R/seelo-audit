from __future__ import annotations

from conftest import crawl_from_home

from seelo_audit.checks import pricing


def test_pricing_present_on_dedicated_page() -> None:
    crawl = crawl_from_home("pricing_present.html")
    crawl.pages["pricing"] = crawl.home
    result = pricing.run(crawl)
    assert result.status == "present"
    assert result.detail["occurrences"] >= 2


def test_pricing_ignores_siret_and_capital_social() -> None:
    """Anti-faux-positif : SIRET/capital social ne doivent jamais compter comme tarif."""
    crawl = crawl_from_home("pricing_false_positive_siret.html")
    result = pricing.run(crawl)
    assert result.status == "absent"


def test_pricing_absent_with_no_price_mentions() -> None:
    crawl = crawl_from_home("booking_absent_mailto.html")
    result = pricing.run(crawl)
    assert result.status == "absent"
