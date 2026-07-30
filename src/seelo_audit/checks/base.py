"""Modèles de page et chargement des signatures — utilisés par tous les checks."""

from __future__ import annotations

import functools
import unicodedata
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from selectolax.parser import HTMLParser

ATTR_TAGS = ("script", "iframe", "link", "a")
ATTR_NAMES = ("src", "href")


def normalize_text(text: str) -> str:
    """Supprime les accents et met en minuscule (matching insensible aux accents)."""
    nfkd = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return without_accents.lower()


@dataclass
class PageDocument:
    url: str
    html: str

    @cached_property
    def tree(self) -> HTMLParser:
        return HTMLParser(self.html)

    @cached_property
    def visible_text(self) -> str:
        clean = HTMLParser(self.html)
        for tag in clean.css("script, style, noscript"):
            tag.decompose()
        return clean.body.text(separator=" ", strip=True) if clean.body else ""

    @cached_property
    def visible_text_normalized(self) -> str:
        return normalize_text(self.visible_text)

    def attribute_values(self) -> list[str]:
        values: list[str] = []
        for tag in self.tree.css(",".join(ATTR_TAGS)):
            for attr_name, attr_value in tag.attributes.items():
                if attr_value is None or attr_name is None:
                    continue
                lname = attr_name.lower()
                if lname in ATTR_NAMES or lname.startswith("data-"):
                    values.append(attr_value)
        return values


@dataclass
class CrawlResult:
    home: PageDocument
    pages: dict[str, PageDocument] = field(default_factory=dict)
    platform: str | None = None
    robots_restricted: bool = False

    def all_documents(self) -> list[PageDocument]:
        return [self.home, *self.pages.values()]

    def document_for(self, category: str) -> PageDocument | None:
        return self.pages.get(category)


@dataclass
class SignatureMatch:
    provider_id: str
    label: str
    evidence: str


@functools.lru_cache(maxsize=1)
def load_signatures(path: Path) -> dict[str, list[dict[str, Any]]]:
    with path.open(encoding="utf-8") as f:
        data: dict[str, list[dict[str, Any]]] = yaml.safe_load(f) or {}
    return data


def find_signature(
    entries: list[dict[str, Any]], documents: list[PageDocument]
) -> SignatureMatch | None:
    """Ordre imposé par la spec : attributs src/href/data-*, puis sélecteurs CSS,
    puis patterns texte. Le premier match gagne."""
    for entry in entries:
        domains = [d.lower() for d in entry.get("domains", [])]
        if not domains:
            continue
        for doc in documents:
            for value in doc.attribute_values():
                lowered = value.lower()
                for domain in domains:
                    if domain in lowered:
                        return SignatureMatch(entry["id"], entry["label"], value[:200])

    for entry in entries:
        for selector in entry.get("selectors", []):
            for doc in documents:
                try:
                    found = doc.tree.css_first(selector)
                except Exception:  # sélecteur CSS invalide, on ignore
                    continue
                if found is not None:
                    return SignatureMatch(entry["id"], entry["label"], f"sélecteur {selector!r}")

    for entry in entries:
        for pattern in entry.get("text_patterns", []):
            normalized_pattern = normalize_text(pattern)
            for doc in documents:
                idx = doc.visible_text_normalized.find(normalized_pattern)
                if idx != -1:
                    snippet = doc.visible_text[max(0, idx - 20) : idx + len(pattern) + 20]
                    return SignatureMatch(entry["id"], entry["label"], snippet.strip()[:200])
    return None
