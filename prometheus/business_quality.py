from __future__ import annotations

from typing import Any, Dict, List

from prometheus.evidence_engine import EvidenceEngine


class BusinessQualityEngine:
    """Conservative qualitative synthesis from structured, disclosed evidence."""

    def evaluate(self, report: Dict[str, Any]) -> Dict[str, Any]:
        metrics = report.get("official_metrics") or {}
        fre = report.get("reference_form") or {}
        sections = fre.get("sections") or {}
        disclosures = (report.get("official_disclosures") or {}).get("documents") or []
        source_by_metric = {
            source.get("metric"): source.get("source_id")
            for source in (report.get("research") or {}).get("sources") or []
        }
        interpretations: List[Dict[str, Any]] = []
        margin = self._value(metrics, "profit_margin")
        conversion = self._value(metrics, "cash_conversion")
        net_leverage = self._value(metrics, "net_debt_to_equity")
        if margin is not None:
            interpretations.append(self._interpret(
                "business_quality", f"Margem líquida reportada de {margin:.2%}; persistência histórica e comparação setorial são necessárias antes de inferir moat.",
                [source_by_metric.get("profit_margin")], "medium",
            ))
        if conversion is not None:
            interpretations.append(self._interpret(
                "earnings_quality", f"Conversão de caixa operacional sobre lucro de {conversion:.2f}x no período; valores isolados não provam recorrência.",
                [source_by_metric.get("operating_cash_flow")], "high",
            ))
        management = sections.get("management") or []
        governance = {
            "status": "AVAILABLE" if fre.get("status") == "AVAILABLE" else "INSUFFICIENT_DATA",
            "management_records": len(management), "related_party_records": len(sections.get("related_parties") or []),
            "auditor_records": len(sections.get("auditors") or []),
            "limitations": ["Cadastro de administradores não mede qualidade de execução, independência efetiva ou alinhamento econômico sozinho."],
        }
        capital_allocation = {
            "status": "PARTIAL", "cash": self._value(metrics, "cash"), "gross_debt": self._value(metrics, "gross_debt"),
            "net_debt": self._value(metrics, "net_debt"), "net_debt_to_equity": net_leverage,
            "limitations": ["Dividendos, recompras, aquisições e retorno incremental do capital exigem série e documentos específicos."],
        }
        sector_model = report.get("sector_model") or {}
        thesis_breakers = [
            {"condition": f"Deterioração material de {kpi}", "status": "MONITOR", "source": "sector_model"}
            for kpi in list(sector_model.get("kpis") or [])[:5]
        ]
        questions = []
        if not disclosures:
            questions.append("Quais comunicados/apresentações oficiais explicam a estratégia e os KPIs mais recentes?")
        if not management:
            questions.append("O FRE disponível contém composição e histórico suficientes da administração?")
        if report.get("research", {}).get("peer_analysis", {}).get("status") != "AVAILABLE":
            questions.append("Quais empresas possuem modelo e período realmente comparáveis?")
        valuation_reconciliation = self._valuation_reconciliation(report)
        return {
            "status": "AVAILABLE" if interpretations else "INSUFFICIENT_DATA",
            "moat": {"status": "UNPROVEN", "conclusion": "Moat não é inferido apenas de margem ou crescimento; requer persistência, diferenciação e evidência competitiva."},
            "interpretations": interpretations, "governance": governance,
            "capital_allocation": capital_allocation, "thesis_breakers": thesis_breakers,
            "valuation_reconciliation": valuation_reconciliation,
            "clarifying_questions": questions[:3],
        }

    @staticmethod
    def _valuation_reconciliation(report: Dict[str, Any]) -> Dict[str, Any]:
        valuation = report.get("valuation") or {}
        scenarios = valuation.get("scenarios") or {}
        deltas = [
            (scenarios.get(name) or {}).get("upside_downside")
            for name in ("bear", "base", "bull")
        ]
        valid = [float(value) for value in deltas if isinstance(value, (int, float))]
        if len(valid) != 3:
            return {
                "status": "INSUFFICIENT_DATA",
                "business_quality": "SEPARATE_FROM_PRICE",
                "valuation_attractiveness": "INSUFFICIENT_DATA",
                "explanation": "A qualidade operacional e a atratividade do preço são dimensões distintas; o valuation não possui três cenários publicáveis.",
            }
        if max(valid) < 0:
            return {
                "status": "DIVERGENCE_EXPLAINED",
                "business_quality": "SEPARATE_FROM_PRICE",
                "valuation_attractiveness": "PRICE_ABOVE_SENSITIVITY_RANGE",
                "margin_of_safety": "NEGATIVE_IN_STATED_MODEL",
                "explanation": (
                    "Os fundamentos podem sustentar qualidade operacional, enquanto o preço permanece acima de toda a faixa mecânica de sensibilidade. "
                    "O estado do sistema agrega fatores além do valuation; ele não neutraliza a ausência de margem de segurança no modelo declarado."
                ),
            }
        return {
            "status": "NO_MATERIAL_DIVERGENCE",
            "business_quality": "SEPARATE_FROM_PRICE",
            "valuation_attractiveness": "WITHIN_OR_BELOW_SENSITIVITY_RANGE",
            "explanation": "Qualidade operacional e preço continuam separados; ao menos um cenário alcança ou supera a referência.",
        }

    @staticmethod
    def _value(metrics: Dict[str, Any], name: str):
        return (metrics.get(name) or {}).get("normalized")

    @staticmethod
    def _interpret(section: str, text: str, sources: List[Any], materiality: str):
        return EvidenceEngine().build_claim(
            section=section, text=text, claim_type="INTERPRETATION",
            source_ids=[item for item in sources if item], confidence="medium", materiality=materiality,
        )
