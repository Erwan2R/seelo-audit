"""Registry des checks déterministes basés HTML/DOM (pas de navigateur requis).

`mobile.py` est appelé séparément par le pipeline car il a besoin d'une page
Playwright réellement rendue en contexte mobile.
"""

from __future__ import annotations

from seelo_audit.checks import booking, forms, payment, policy, pricing, structured_data, trust
from seelo_audit.checks.base import CrawlResult
from seelo_audit.models import CheckResult

_HTML_CHECK_MODULES = (booking, payment, pricing, forms, policy, trust, structured_data)


def run_html_checks(crawl: CrawlResult) -> list[CheckResult]:
    results: list[CheckResult] = []
    for module in _HTML_CHECK_MODULES:
        try:
            results.append(module.run(crawl))
        except Exception as exc:  # isolation stricte : un check ne fait jamais planter l'audit
            check_id = module.__name__.rsplit(".", 1)[-1]
            results.append(
                CheckResult(id=check_id, status="error", evidence=f"erreur du check : {exc}"[:200])
            )
    return results
