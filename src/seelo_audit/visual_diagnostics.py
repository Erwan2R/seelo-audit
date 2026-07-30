"""Diagnostic visuel automatique (règles, sans IA).

Remplace la passe LLM vision de la spec d'origine (voir DECISIONS.md).
Chaque critère porte un champ `method` honnête :
- "regle_deterministe" : calcul exact sur des valeurs DOM/CSS/pixels mesurées.
- "heuristique_proxy" : approximation structurelle, moins fine qu'un jugement
  humain — documenté comme limite connue, notamment pour la clarté du message.

Aucun appel réseau, aucune clé API, aucune dépendance à un fournisseur d'IA.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import cv2
from PIL import Image

from seelo_audit.checks.base import CrawlResult
from seelo_audit.models import CheckResult, VisualCriterion, VisualDiagnostic

logger = logging.getLogger(__name__)

CONTRAST_AA_THRESHOLD = 4.5
MIN_FONT_SIZE_PX = 14
DOMINANT_COLOR_FRACTION_THRESHOLD = 0.05
MANY_COLORS_THRESHOLD = 6
FEW_COLORS_THRESHOLD = 3

_CONTRAST_JS = """
() => {
  function luminance(rgb) {
    const a = rgb.map(v => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
  }
  function parseColor(str) {
    const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
    if (!m) return null;
    const alpha = m[4] !== undefined ? parseFloat(m[4]) : 1;
    if (alpha === 0) return null;
    return [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])];
  }
  const body = document.body;
  if (!body) return null;
  const style = getComputedStyle(body);
  const textColor = parseColor(style.color) || [0, 0, 0];
  let bgColor = [255, 255, 255];
  let el = body;
  while (el) {
    const parsed = parseColor(getComputedStyle(el).backgroundColor);
    if (parsed) { bgColor = parsed; break; }
    el = el.parentElement;
  }
  const l1 = luminance(textColor) + 0.05;
  const l2 = luminance(bgColor) + 0.05;
  return l1 > l2 ? l1 / l2 : l2 / l1;
}
"""


class DesktopPage(Protocol):
    async def evaluate(self, script: str) -> Any: ...


async def compute_desktop_contrast(page: DesktopPage) -> float | None:
    try:
        value = await page.evaluate(_CONTRAST_JS)
    except Exception:
        return None
    return float(value) if value is not None else None


_FACE_CASCADE_PATH = str(
    Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"  # type: ignore[attr-defined]
)


def detect_face(image_path: Path) -> bool | None:
    """Détection de visage locale (OpenCV Haar cascade) — gratuite, hors ligne."""
    try:
        cascade = cv2.CascadeClassifier(_FACE_CASCADE_PATH)
        image = cv2.imread(str(image_path))
        if image is None:
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        return len(faces) > 0
    except Exception as exc:  # jamais bloquant
        logger.warning("Détection de visage impossible sur %s : %s", image_path, exc)
        return None


def dominant_color_count(
    image_path: Path, threshold: float = DOMINANT_COLOR_FRACTION_THRESHOLD
) -> int | None:
    """Proxy de cohérence visuelle : nombre de couleurs dominantes (>= seuil)."""
    try:
        with Image.open(image_path) as img:
            small = img.convert("RGB").resize((150, 150))
            quantized = small.quantize(colors=24, method=Image.Quantize.MEDIANCUT)
            histogram = quantized.histogram()
            total = sum(histogram)
            if total == 0:
                return None
            return sum(1 for count in histogram if count / total >= threshold)
    except Exception as exc:
        logger.warning("Analyse de palette impossible sur %s : %s", image_path, exc)
        return None


def _criterion_primary_cta(mobile_check: CheckResult | None) -> VisualCriterion:
    if mobile_check is None:
        return VisualCriterion(
            id="primary_cta",
            verdict="non_evalue",
            method="regle_deterministe",
            observation="parcours mobile non mesuré",
            evidence="check mobile absent",
        )
    cta_visible = bool(mobile_check.detail.get("cta_above_fold"))
    return VisualCriterion(
        id="primary_cta",
        verdict="bon" if cta_visible else "faible",
        method="regle_deterministe",
        observation=(
            "un lien/bouton de réservation ou contact est visible dans le premier écran mobile"
            if cta_visible
            else "aucun lien/bouton de réservation ou contact visible dans le premier écran mobile"
        ),
        evidence=f"cta_above_fold={cta_visible}",
        action=None
        if cta_visible
        else "Placer un bouton de prise de RDV visible sans scroll sur mobile.",
    )


def _criterion_mobile_journey(mobile_check: CheckResult | None) -> VisualCriterion:
    if mobile_check is None:
        return VisualCriterion(
            id="mobile_journey",
            verdict="non_evalue",
            method="regle_deterministe",
            observation="parcours mobile non mesuré",
            evidence="check mobile absent",
        )
    verdict = {"present": "bon", "partial": "moyen", "absent": "faible", "error": "non_evalue"}[
        mobile_check.status
    ]
    return VisualCriterion(
        id="mobile_journey",
        verdict=verdict,  # type: ignore[arg-type]
        method="regle_deterministe",
        observation=mobile_check.evidence,
        evidence=mobile_check.evidence,
        action=None
        if verdict == "bon"
        else "Corriger les problèmes mobiles listés (viewport/débordement/CTA).",
    )


def _criterion_readability(
    mobile_check: CheckResult | None, contrast_ratio: float | None
) -> VisualCriterion:
    font_size = mobile_check.detail.get("base_font_size_px") if mobile_check else None
    problems = []
    if font_size is not None and font_size < MIN_FONT_SIZE_PX:
        problems.append(f"police de base à {font_size:.0f}px (< {MIN_FONT_SIZE_PX}px)")
    if contrast_ratio is not None and contrast_ratio < CONTRAST_AA_THRESHOLD:
        problems.append(
            f"contraste texte/fond insuffisant ({contrast_ratio:.1f}:1, seuil AA "
            f"{CONTRAST_AA_THRESHOLD}:1)"
        )

    if font_size is None and contrast_ratio is None:
        verdict = "non_evalue"
        observation = "taille de police et contraste non mesurés"
    elif not problems:
        verdict = "bon"
        observation = "taille de police et contraste conformes aux seuils WCAG AA"
    elif len(problems) == 2:
        verdict = "faible"
        observation = " ; ".join(problems)
    else:
        verdict = "moyen"
        observation = " ; ".join(problems)

    return VisualCriterion(
        id="readability",
        verdict=verdict,  # type: ignore[arg-type]
        method="regle_deterministe",
        observation=observation,
        evidence=f"font_size_px={font_size}, contrast_ratio={contrast_ratio}",
        action=None
        if verdict == "bon"
        else "Augmenter la taille de police et/ou le contraste texte/fond.",
    )


def _criterion_practitioner_photo(face_present: bool | None) -> VisualCriterion:
    if face_present is None:
        return VisualCriterion(
            id="practitioner_photo",
            verdict="non_evalue",
            method="regle_deterministe",
            observation="détection de visage non exécutée (screenshot indisponible)",
            evidence="face_detection=non_execute",
        )
    return VisualCriterion(
        id="practitioner_photo",
        verdict="bon" if face_present else "faible",
        method="regle_deterministe",
        observation=(
            "un visage humain est détecté sur la capture desktop"
            if face_present
            else "aucun visage humain détecté sur la capture desktop"
        ),
        evidence=f"face_detected={face_present}",
        action=None if face_present else "Ajouter une photo du praticien avec un visage visible.",
    )


def _criterion_value_proposition(crawl: CrawlResult) -> VisualCriterion:
    """Heuristique_proxy — limite connue : ne juge pas la compréhension réelle
    du message, seulement des proxys structurels (H1 présent, longueur du texte)."""
    tree = crawl.home.tree
    h1_nodes = tree.css("h1")
    h1_text = h1_nodes[0].text(strip=True) if h1_nodes else ""
    text_len = len(crawl.home.visible_text)

    if not h1_nodes:
        verdict = "faible"
        observation = "aucun titre <h1> détecté sur la page d'accueil"
    elif not h1_text:
        verdict = "faible"
        observation = "un <h1> existe mais est vide"
    elif text_len < 100:
        verdict = "moyen"
        observation = (
            f"<h1> présent ({h1_text!r}) mais très peu de texte sur la page ({text_len} caractères)"
        )
    else:
        verdict = "moyen"
        observation = (
            f"<h1> présent : {h1_text!r} — pas de jugement de clarté réelle possible sans IA"
        )

    return VisualCriterion(
        id="value_proposition",
        verdict=verdict,  # type: ignore[arg-type]
        method="heuristique_proxy",
        observation=observation,
        evidence=f"h1={h1_text!r}, text_len={text_len}",
        action=(
            "Vérifier manuellement qu'un visiteur comprend en 5 secondes qui/quoi/pour qui "
            "— ce critère n'est pas jugé de façon fiable sans analyse humaine ou IA."
        ),
    )


def _criterion_visual_hierarchy(crawl: CrawlResult) -> VisualCriterion:
    """Heuristique_proxy — nombre de titres et profondeur DOM comme proxy de hiérarchie."""
    tree = crawl.home.tree
    heading_count = len(tree.css("h1, h2, h3, h4, h5, h6"))
    max_depth = 0
    for node in tree.css("*"):
        depth = 0
        current = node
        while current.parent is not None:
            depth += 1
            current = current.parent
        max_depth = max(max_depth, depth)

    if heading_count == 0:
        verdict = "faible"
    elif heading_count < 3 or max_depth > 30:
        verdict = "moyen"
    else:
        verdict = "bon"

    return VisualCriterion(
        id="visual_hierarchy",
        verdict=verdict,  # type: ignore[arg-type]
        method="heuristique_proxy",
        observation=f"{heading_count} titre(s) hN, profondeur DOM max {max_depth}",
        evidence=f"heading_count={heading_count}, max_dom_depth={max_depth}",
        action=None
        if verdict == "bon"
        else "Structurer le contenu avec des titres hiérarchisés (h1 > h2 > h3).",
    )


def _criterion_professionalism(color_count: int | None) -> VisualCriterion:
    """Heuristique_proxy — nombre de couleurs dominantes comme proxy de cohérence
    (pas un jugement esthétique réel)."""
    if color_count is None:
        return VisualCriterion(
            id="professionalism",
            verdict="non_evalue",
            method="heuristique_proxy",
            observation="analyse de palette non exécutée (screenshot indisponible)",
            evidence="dominant_color_count=non_execute",
        )
    if color_count > MANY_COLORS_THRESHOLD:
        verdict = "faible"
    elif color_count > FEW_COLORS_THRESHOLD:
        verdict = "moyen"
    else:
        verdict = "bon"

    return VisualCriterion(
        id="professionalism",
        verdict=verdict,  # type: ignore[arg-type]
        method="heuristique_proxy",
        observation=f"{color_count} couleur(s) dominante(s) détectée(s) sur la capture desktop",
        evidence=f"dominant_color_count={color_count}",
        action=None
        if verdict == "bon"
        else "Réduire le nombre de couleurs dominantes pour une palette plus cohérente.",
    )


_VERDICT_RANK = {"faible": 0, "moyen": 1, "non_evalue": 2, "bon": 3}


def _biggest_blocker(criteria: list[VisualCriterion]) -> str:
    worst = min(criteria, key=lambda c: _VERDICT_RANK[c.verdict])
    if worst.verdict == "bon":
        return "aucun blocage visuel majeur détecté par les règles automatiques"
    return f"{worst.id} : {worst.observation}"


async def analyze(
    crawl: CrawlResult,
    mobile_check: CheckResult | None,
    desktop_page: DesktopPage | None,
    desktop_screenshot_path: Path | None,
) -> VisualDiagnostic:
    contrast_ratio = await compute_desktop_contrast(desktop_page) if desktop_page else None
    face_present = detect_face(desktop_screenshot_path) if desktop_screenshot_path else None
    color_count = dominant_color_count(desktop_screenshot_path) if desktop_screenshot_path else None

    criteria = [
        _criterion_value_proposition(crawl),
        _criterion_primary_cta(mobile_check),
        _criterion_practitioner_photo(face_present),
        _criterion_readability(mobile_check, contrast_ratio),
        _criterion_visual_hierarchy(crawl),
        _criterion_professionalism(color_count),
        _criterion_mobile_journey(mobile_check),
    ]
    return VisualDiagnostic(
        criteria=criteria, biggest_conversion_blocker=_biggest_blocker(criteria)
    )
