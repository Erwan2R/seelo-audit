"""Détection du paiement / acompte en ligne (poids 15)."""

from __future__ import annotations

from seelo_audit.checks.base import CrawlResult, find_signature, load_signatures, normalize_text
from seelo_audit.config import SIGNATURES_PATH
from seelo_audit.models import CheckResult

PARTIAL_TEXT_PATTERNS = (
    "paiement cb accepte",
    "paiement par carte accepte",
    "acompte a verser",
    "reglement par virement",
    "paiement en ligne",
    "acompte par virement",
)


def run(crawl: CrawlResult) -> CheckResult:
    signatures = load_signatures(SIGNATURES_PATH)
    documents = crawl.all_documents()

    match = find_signature(signatures.get("payment", []), documents)
    if match:
        return CheckResult(
            id="online_payment",
            status="present",
            provider=match.provider_id,
            evidence=f"{match.label} détecté ({match.evidence})",
            detail={},
        )

    for doc in documents:
        norm = doc.visible_text_normalized
        for pattern in PARTIAL_TEXT_PATTERNS:
            if normalize_text(pattern) in norm:
                return CheckResult(
                    id="online_payment",
                    status="partial",
                    evidence=f"mention textuelle sans widget : {pattern!r}",
                    detail={},
                )

    return CheckResult(
        id="online_payment",
        status="absent",
        evidence="aucun widget ni mention de paiement/acompte en ligne",
        detail={},
    )
