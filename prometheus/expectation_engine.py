import datetime
from typing import Any, Dict, List, Optional

from prometheus.models import ThesisEvidence


class ExpectationEngine:
    def quantify(
        self,
        market_snapshot: Dict[str, Any],
        fundamental_summary: Dict[str, Any],
        sentiment_score: float,
    ) -> Dict[str, Any]:
        price_change = market_snapshot.get("price_change_percent")
        volatility = market_snapshot.get("beta")
        quality = fundamental_summary.get("confidence", 0.0)
        score = 50.0
        reasons: List[str] = []
        evidence: List[ThesisEvidence] = []

        if price_change is not None:
            if price_change > 8.0:
                score -= 10.0
                reasons.append("Ação já reagiu rapidamente")
            elif price_change < -8.0:
                score += 10.0
                reasons.append("Queda intensa pode gerar expectativa positiva de reversão")

        if volatility is not None and volatility > 1.2:
            score -= 5.0
            reasons.append("Alta sensibilidade ao risco incentiva precificação mais rápida")

        if quality >= 60.0:
            score += 5.0
            reasons.append("Dados fundamentais confiáveis suportam uma expectativa mais clara")

        if sentiment_score >= 65.0:
            score -= 5.0
            reasons.append("Expectativas de mercado já estão aquecidas")
        elif sentiment_score <= 35.0:
            score += 5.0
            reasons.append("Sentimento negativo pode criar gap de expectativa")

        score = round(max(10.0, min(90.0, score)), 2)
        evidence.append(
            ThesisEvidence(
                claim="Gap de expectativa quantificado",
                evidence_type="expectation",
                confidence=0.6,
                details=f"Score de gap = {score:.2f}, razões: {'; '.join(reasons) if reasons else 'nenhuma razão adicional'}.",
                timestamp=datetime.datetime.utcnow(),
            )
        )

        return {
            "expectation_gap_score": score,
            "reasons": reasons,
            "evidence": evidence,
        }
