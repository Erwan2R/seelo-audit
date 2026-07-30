"""Détection de la réservation en ligne — cœur du produit (poids 25 dans le score)."""

from __future__ import annotations

from seelo_audit.checks.base import CrawlResult, find_signature, load_signatures, normalize_text
from seelo_audit.config import SIGNATURES_PATH
from seelo_audit.models import CheckResult

DATE_FIELD_PATTERNS = (
    "date souhaitee",
    "date de rendez-vous",
    "creneau souhaite",
    "date preferee",
    "date de votre choix",
)


def _count_links(crawl: CrawlResult) -> tuple[int, int, bool]:
    mailto_count = 0
    tel_count = 0
    contact_form = False
    for doc in crawl.all_documents():
        for a in doc.tree.css("a[href]"):
            href = (a.attributes.get("href") or "").lower()
            if href.startswith("mailto:"):
                mailto_count += 1
            elif href.startswith("tel:"):
                tel_count += 1
        if doc.tree.css_first("form") is not None:
            contact_form = True
    return mailto_count, tel_count, contact_form


def run(crawl: CrawlResult) -> CheckResult:
    signatures = load_signatures(SIGNATURES_PATH)
    documents = crawl.all_documents()
    mailto_count, tel_count, contact_form = _count_links(crawl)
    detail = {"mailto_count": mailto_count, "tel_count": tel_count, "contact_form": contact_form}

    match = find_signature(signatures.get("booking", []), documents)
    if match:
        return CheckResult(
            id="online_booking",
            status="present",
            provider=match.provider_id,
            evidence=f"{match.label} détecté ({match.evidence})",
            detail=detail,
        )

    # partial : formulaire de demande de RDV sans confirmation immédiate
    for doc in documents:
        for form in doc.tree.css("form"):
            form_text = normalize_text(form.text(separator=" "))
            if any(normalize_text(p) in form_text for p in DATE_FIELD_PATTERNS):
                return CheckResult(
                    id="online_booking",
                    status="partial",
                    evidence="formulaire de demande de RDV détecté, sans confirmation immédiate",
                    detail=detail,
                )

    evidence = f"aucun script/iframe de réservation ; {mailto_count} lien(s) mailto: détecté(s)"
    return CheckResult(id="online_booking", status="absent", evidence=evidence, detail=detail)
