"""Deterministic discovery of relationships among validated operating KPIs.

This additive layer deliberately reports uncertainty when only one period is
available; it never turns arithmetic into an investment conclusion.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


def _values(kpis: Any) -> Dict[str, float]:
    items = kpis.get("metrics", {}) if isinstance(kpis, Mapping) else kpis
    out: Dict[str, float] = {}
    for name, item in (items or {}).items():
        if isinstance(item, Mapping) and item.get("status") == "AVAILABLE" and item.get("value") is not None:
            try:
                out[str(name)] = float(item["value"])
            except (TypeError, ValueError):
                continue
    return out


def discover_relationships(kpis: Any, *, periods_available: int = 1) -> Dict[str, Any]:
    """Return deterministic relationships and explicit evidence limits."""
    values = _values(kpis)
    relationships: List[Dict[str, Any]] = []
    if all(key in values for key in ("vendas_brutas", "vendas_líquidas", "distratos")):
        delta = values["vendas_brutas"] - values["vendas_líquidas"]
        distratos = values["distratos"]
        identity = abs(delta - distratos) <= max(1.0, abs(distratos) * 0.005)
        relationships.append({
            "id": "gross_minus_net_equals_cancellations",
            "inputs": ["vendas_brutas", "vendas_líquidas", "distratos"],
            "formula": "vendas_brutas - vendas_líquidas ≈ distratos",
            "value": delta,
            "classification": "MECHANICAL_IDENTITY" if identity else "INSUFFICIENT_EVIDENCE",
            "insight": False,
        })
    if all(key in values for key in ("vendas_líquidas", "lançamentos")):
        relationships.append({
            "id": "net_sales_to_launches",
            "inputs": ["vendas_líquidas", "lançamentos"],
            "formula": "vendas_líquidas / lançamentos",
            "value": values["vendas_líquidas"] / values["lançamentos"] if values["lançamentos"] else None,
            "classification": "INSUFFICIENT_EVIDENCE" if periods_available < 2 else "EXPECTED_RELATIONSHIP",
            "insight": False,
        })
    if all(key in values for key in ("distratos", "vendas_brutas")):
        relationships.append({
            "id": "cancellations_to_gross_sales",
            "inputs": ["distratos", "vendas_brutas"],
            "formula": "distratos / vendas_brutas",
            "value": values["distratos"] / values["vendas_brutas"] if values["vendas_brutas"] else None,
            "classification": "INSUFFICIENT_EVIDENCE" if periods_available < 2 else "EXPECTED_RELATIONSHIP",
            "insight": False,
        })
    # With one period, prohibit classifications that imply comparative insight.
    if periods_available < 2:
        for relation in relationships:
            if relation["classification"] in {"ANOMALOUS", "POTENTIALLY_INFORMATIVE"}:
                relation["classification"] = "INSUFFICIENT_EVIDENCE"
            relation["insight"] = False
    return {"schema": "prometheus.relationship_discovery.v1", "periods_available": periods_available, "relationships": relationships}


def contradiction_analysis(discovery: Mapping[str, Any], kpis: Any, *, periods_available: int = 1) -> Dict[str, Any]:
    """Attach same-period support, contradiction and missing evidence."""
    values = _values(kpis)
    results: List[Dict[str, Any]] = []
    for relation in discovery.get("relationships", []):
        classification = relation.get("classification")
        if classification not in {"MECHANICAL_IDENTITY", "EXPECTED_RELATIONSHIP"}:
            continue
        inputs = set(relation.get("inputs", []))
        supporting = [{"metric": name, "value": values[name], "period_scope": "same_period"} for name in sorted(values) if name not in inputs]
        results.append({
            "relationship_id": relation.get("id"),
            "supporting_evidence": supporting,
            "contradicting_evidence": [],
            "missing_evidence": ["histórico dos últimos 4 trimestres", "comparação com pares do mesmo setor"],
        })
    return {"schema": "prometheus.contradiction_analysis.v1", "relationships": results}


def confidence_language(*, periods_available: int, supporting_evidence_count: int = 0) -> str:
    if periods_available < 2 and supporting_evidence_count == 0:
        return "Os dados disponíveis ainda não permitem determinar se essa relação é normal ou informativa."
    if periods_available < 2:
        return "Uma hipótese possível é que essa relação ajude a explicar a dinâmica observada, mas ainda falta histórico."
    return "Os dados disponíveis permitem avaliar essa relação em perspectiva histórica."
