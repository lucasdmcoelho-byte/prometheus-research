import datetime
from typing import Any, Dict, List

from prometheus.models import ThesisEvidence


class PricingEngine:
    def assess(
        self,
        market_snapshot: Dict[str, Any],
        expectation_result: Dict[str, Any],
        thesis_scores: Dict[str, float],
    ) -> Dict[str, Any]:
        price_change = market_snapshot.get("price_change_percent")
        expectation_gap = expectation_result.get("expectation_gap_score", 50.0)
        valuation_margin = thesis_scores.get("valuation_margin", 0.0)
        evidence: List[ThesisEvidence] = []

        if expectation_gap >= 65.0 and (price_change is None or price_change < 4.0):
            pricing_status = "UNDERPRICED"
            pricing_confidence = 0.72
            details = "Expectation gap permanece alto enquanto o preço não avançou de forma significativa."
            evidence.append(
                ThesisEvidence(
                    claim="Desvio de precificação indica potencial de alta",
                    evidence_type="pricing",
                    confidence=0.72,
                    details=details,
                    timestamp=datetime.datetime.utcnow(),
                )
            )
        elif expectation_gap <= 35.0 and price_change is not None and price_change > 6.0:
            pricing_status = "OVERPRICED"
            pricing_confidence = 0.68
            details = "Expectativa comprimida e preço já se moveu de forma acentuada."
            evidence.append(
                ThesisEvidence(
                    claim="Movimento de preço já embute a expectativa",
                    evidence_type="pricing",
                    confidence=0.68,
                    details=details,
                    timestamp=datetime.datetime.utcnow(),
                )
            )
        else:
            pricing_status = "FAIRLY_PRICED"
            pricing_confidence = 0.58
            details = "Movimento de preço e gap de expectativa sugerem precificação equilibrada."
            evidence.append(
                ThesisEvidence(
                    claim="Precificação em nível razoável",
                    evidence_type="pricing",
                    confidence=0.58,
                    details=details,
                    timestamp=datetime.datetime.utcnow(),
                )
            )

        if valuation_margin >= 80.0 and pricing_status == "FAIRLY_PRICED":
            pricing_status = "UNDERPRICED"
            pricing_confidence = 0.62
            details += " Valuation attractiveness elevado reforça margem de segurança."
            evidence.append(
                ThesisEvidence(
                    claim="Valuation atrativo amplia a margem de segurança",
                    evidence_type="pricing",
                    confidence=0.62,
                    details="O múltiplo relativo sugere desconto em relação à referência adotada.",
                    timestamp=datetime.datetime.utcnow(),
                )
            )

        return {
            "pricing_status": pricing_status,
            "pricing_confidence": round(pricing_confidence, 2),
            "pricing_details": details,
            "evidence": evidence,
        }
