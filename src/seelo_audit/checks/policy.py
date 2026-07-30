"""Politique d'annulation (poids 8) — argument no-show / relance."""

from __future__ import annotations

from seelo_audit.checks.base import CrawlResult, normalize_text
from seelo_audit.models import CheckResult

CANCELLATION_PATTERNS = (
    "annulation",
    "annuler",
    "conditions d'annulation",
    "report de seance",
    "48 heures",
    "48h",
    "24 heures",
    "24h a l'avance",
    "seance non annulee",
    "seance due",
)
SEANCE_VOCAB = ("seance", "consultation", "rendez-vous", "rdv")
CONTEXT_WINDOW = 150


def run(crawl: CrawlResult) -> CheckResult:
    for doc in crawl.all_documents():
        norm = doc.visible_text_normalized
        for pattern in CANCELLATION_PATTERNS:
            idx = norm.find(normalize_text(pattern))
            if idx == -1:
                continue
            window = norm[max(0, idx - CONTEXT_WINDOW) : idx + CONTEXT_WINDOW]
            if any(normalize_text(v) in window for v in SEANCE_VOCAB):
                original = doc.visible_text[max(0, idx - 60) : idx + 140]
                return CheckResult(
                    id="cancellation_policy",
                    status="present",
                    evidence=original.strip()[:200],
                    detail={},
                )

    return CheckResult(
        id="cancellation_policy",
        status="absent",
        evidence="aucune mention de politique d'annulation trouvée",
        detail={},
    )
