"""Evidence-bound exports for human-reviewed educational publishing.

This module deliberately does not generate a recommendation, a price target, or
personalised investment content.  It projects source-backed facts from an
already editorially eligible research snapshot into a compact JSON brief for a
human editor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Type

from prometheus.editorial_gate import EditorialGate


PROHIBITED_PUBLICATION_CLAIMS = (
    "compra", "venda", "compre", "venda agora", "preço-alvo", "preco-alvo",
    "stop-loss", "tamanho de posição", "tamanho de posicao", "rentabilidade garantida",
)


class EducationalContentGate:
    """Refuse automatic social publication unless the underlying research is deliverable.

    A content brief stays ``HUMAN_EDITORIAL_REVIEW_REQUIRED`` even when the
    underlying report is blocker-free.  The class is intentionally a projection
    of existing editorial, evidence and provenance controls rather than a
    second research gate.
    """

    def __init__(self, gate_factory: Type[EditorialGate] = EditorialGate):
        self.gate_factory = gate_factory

    def evaluate(self, report: Dict[str, Any]) -> Dict[str, Any]:
        gate = self.gate_factory().evaluate(report)
        failures: list[str] = []
        if gate.get("blockers"):
            failures.append("RESEARCH_EDITORIAL_GATE_BLOCKED")
        if (gate.get("claim_audit") or {}).get("status") != "PASS":
            failures.append("CLAIM_AUDIT_NOT_PASS")
        if report.get("data_source_status") == "DEGRADED":
            failures.append("PRIMARY_DATA_SOURCE_DEGRADED")
        if not str(report.get("analysis_as_of") or "").strip():
            failures.append("ANALYSIS_CUTOFF_MISSING")
        return {
            "status": "HUMAN_EDITORIAL_REVIEW_REQUIRED" if not failures else "NOT_ELIGIBLE",
            "eligible": not failures,
            "failures": failures,
            "research_editorial_status": gate.get("status"),
            "research_blocker_codes": sorted({str(item.get("code")) for item in (gate.get("blockers") or [])}),
        }


def build_educational_brief(report: Dict[str, Any], max_facts: int = 5, gate: EducationalContentGate | None = None) -> Dict[str, Any]:
    """Build a fact-only handoff with each card tied to a source record."""
    publication_gate = (gate or EducationalContentGate()).evaluate(report)
    base = {
        "schema": "prometheus.educational_content_brief.v1",
        "ticker": report.get("ticker"),
        "company_name": report.get("company_name"),
        "analysis_as_of": report.get("analysis_as_of"),
        "publication_gate": publication_gate,
        "disclaimer": "Material educativo e informativo; não é recomendação personalizada de investimento.",
        "prohibited_claims": list(PROHIBITED_PUBLICATION_CLAIMS),
        "required_human_checks": [
            "Confirmar que o corte e as fontes ainda são atuais no momento da publicação.",
            "Não adicionar recomendação, preço-alvo, promessa de retorno ou instrução de negociação.",
            "Preservar ticker, período, fonte e limitações em toda adaptação visual ou textual.",
        ],
    }
    if not publication_gate["eligible"]:
        return {**base, "fact_cards": [], "status": "NOT_ELIGIBLE"}

    sources = {str(item.get("source_id")): item for item in ((report.get("research") or {}).get("sources") or []) if item.get("source_id")}
    cards = []
    seen_metrics: set[str] = set()
    for claim in report.get("claims") or []:
        if claim.get("classification") != "FACT" or not isinstance(claim.get("value"), (int, float)):
            continue
        source_id = next((str(item) for item in (claim.get("source_ids") or []) if str(item) in sources), None)
        source = sources.get(source_id or "")
        if not source or source.get("value") is None:
            continue
        metric = str(source.get("metric") or "")
        if not metric or metric in seen_metrics:
            continue
        if any(token in metric.lower() for token in ("score", "sentiment", "valuation", "target", "upside")):
            continue
        cards.append({
            "metric": metric,
            "claim_text": claim.get("text"),
            "value": source.get("value"),
            "unit": source.get("unit"),
            "period": source.get("period"),
            "publication_date": source.get("publication_date"),
            "source": source.get("source"),
            "source_url": source.get("source_url"),
            "source_sha256": source.get("source_sha256"),
            "source_id": source_id,
        })
        seen_metrics.add(metric)
        if len(cards) >= max(1, int(max_facts)):
            break
    return {**base, "status": "READY_FOR_HUMAN_EDITORIAL_REVIEW" if cards else "INSUFFICIENT_FACT_CARDS", "fact_cards": cards}


def write_educational_brief(report: Dict[str, Any], destination: str | Path, max_facts: int = 5) -> Dict[str, Any]:
    brief = build_educational_brief(report, max_facts=max_facts)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**brief, "path": str(path.resolve())}
