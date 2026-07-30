"""Détection de la plateforme technique (Wix, WordPress, Webflow, ...).

Ne produit pas de CheckResult — alimente directement `Audit.platform` pour
personnaliser l'accroche et estimer la difficulté de migration.
"""

from __future__ import annotations

from seelo_audit.checks.base import CrawlResult, find_signature, load_signatures
from seelo_audit.config import SIGNATURES_PATH


def detect_platform(crawl: CrawlResult) -> str | None:
    signatures = load_signatures(SIGNATURES_PATH)
    match = find_signature(signatures.get("platform", []), crawl.all_documents())
    return match.provider_id if match else None
