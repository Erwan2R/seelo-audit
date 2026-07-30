from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

CheckStatus = Literal["present", "partial", "absent", "error"]


class CheckResult(BaseModel):
    id: str
    status: CheckStatus
    evidence: str = Field(min_length=1)
    provider: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class PageSpeedResult(BaseModel):
    performance_score: int | None = None
    seo_score: int | None = None
    lcp_ms: float | None = None
    cls: float | None = None
    tbt_ms: float | None = None
    speed_index_ms: float | None = None
    top_opportunities: list[dict[str, Any]] = Field(default_factory=list)


VisualCriterionId = Literal[
    "value_proposition",
    "primary_cta",
    "practitioner_photo",
    "readability",
    "visual_hierarchy",
    "professionalism",
    "mobile_journey",
]
VisualVerdict = Literal["bon", "moyen", "faible", "non_evalue"]
VisualMethod = Literal["regle_deterministe", "heuristique_proxy"]


class VisualCriterion(BaseModel):
    """Un critère du diagnostic visuel — jamais issu d'un jugement LLM.

    `method` documente honnêtement la nature du calcul :
    - "regle_deterministe" : calcul exact sur des valeurs DOM/CSS mesurées.
    - "heuristique_proxy" : approximation structurelle, moins fine qu'un
      jugement humain (voir DECISIONS.md).
    """

    id: VisualCriterionId
    verdict: VisualVerdict
    method: VisualMethod
    observation: str
    evidence: str = Field(min_length=1)
    action: str | None = None


class VisualDiagnostic(BaseModel):
    """Diagnostic visuel automatique (règles, sans IA). Voir DECISIONS.md."""

    criteria: list[VisualCriterion]
    biggest_conversion_blocker: str


class Audit(BaseModel):
    domain: str
    url: HttpUrl
    audited_at: datetime
    status: Literal["ok", "partial", "failed", "timeout"]
    platform: str | None = None
    robots_restricted: bool = False
    pages_crawled: dict[str, str] = Field(default_factory=dict)
    checks: list[CheckResult] = Field(default_factory=list)
    pagespeed: PageSpeedResult | None = None
    visual_diagnostic: VisualDiagnostic | None = None
    score_tunnel: int = 0
    temperature: Literal["CHAUD", "TIEDE", "FROID", "EXCLU"] = "EXCLU"
    competitor_locked: bool = False
    diy_tooling: bool = False
    outreach_hook: str | None = None
    errors: list[str] = Field(default_factory=list)
