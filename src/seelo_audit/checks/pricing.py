"""Tarifs visibles (poids 12) — le check le plus sujet aux faux positifs."""

from __future__ import annotations

import re

from seelo_audit.checks.base import CrawlResult, PageDocument, normalize_text
from seelo_audit.models import CheckResult

PRICE_PATTERN = re.compile(
    r"(?<![\d.,])\d{1,4}(?:[.,]\d{2})?\s?(?:€|EUR\b|euros?\b)|(?:€|EUR)\s?\d{1,4}",
    re.IGNORECASE,
)
SEANCE_VOCAB = (
    "seance",
    "consultation",
    "forfait",
    "cure",
    "accompagnement",
    "atelier",
    "bilan",
    "suivi",
    "pack",
    "module",
    "rendez-vous",
)
EXCLUSION_PATTERN = re.compile(r"\b(siret|capital|rcs)\b", re.IGNORECASE)
NEAR_WINDOW = 120
EXCLUSION_WINDOW = 80


def _price_matches(doc: PageDocument) -> list[tuple[int, int]]:
    text = doc.visible_text
    matches: list[tuple[int, int]] = []
    for m in PRICE_PATTERN.finditer(text):
        preceding = text[max(0, m.start() - EXCLUSION_WINDOW) : m.start()]
        if EXCLUSION_PATTERN.search(preceding):
            continue
        matches.append((m.start(), m.end()))
    return matches


def run(crawl: CrawlResult) -> CheckResult:
    pricing_doc = crawl.document_for("pricing")
    if pricing_doc is not None:
        matches = _price_matches(pricing_doc)
        if len(matches) >= 2:
            start, end = matches[0]
            snippet = pricing_doc.visible_text[start : min(end + 30, len(pricing_doc.visible_text))]
            return CheckResult(
                id="pricing_visible",
                status="present",
                evidence=f"page tarifs dédiée, {len(matches)} montant(s), ex. {snippet.strip()!r}",
                detail={"occurrences": len(matches), "page": "pricing"},
            )

    weak_hits = 0
    weak_evidence = ""
    for doc in crawl.all_documents():
        norm = doc.visible_text_normalized
        text = doc.visible_text
        for start, end in _price_matches(doc):
            window = norm[max(0, start - NEAR_WINDOW) : min(end + NEAR_WINDOW, len(norm))]
            if any(normalize_text(v) in window for v in SEANCE_VOCAB):
                weak_hits += 1
                if not weak_evidence:
                    weak_evidence = text[start:end].strip()

    if weak_hits >= 2:
        return CheckResult(
            id="pricing_visible",
            status="partial",
            evidence=(
                f"signal faible : {weak_hits} mention(s) de prix proches du vocabulaire séance, "
                f"ex. {weak_evidence!r}"
            ),
            detail={"occurrences": weak_hits},
        )

    return CheckResult(
        id="pricing_visible",
        status="absent",
        evidence="aucun tarif détecté (pas de page tarifs, pas de montant près du vocab. séance)",
        detail={"occurrences": weak_hits},
    )
