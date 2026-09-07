import datetime
from typing import Any, Dict, List, Optional

from prometheus.models import ThesisBreaker, ThesisEvidence, ThesisResult


class ThesisBreakerEngine:
    SEVERITY_ORDER = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }

    def identify(
        self,
        thesis_result: ThesisResult,
        fundamental_summary: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        risk_result: Dict[str, Any],
        expectation_result: Dict[str, Any],
        pricing_result: Dict[str, Any],
        catalysts: List[Dict[str, Any]],
        regime_result: Dict[str, Any],
    ) -> List[ThesisBreaker]:
        breakers: List[ThesisBreaker] = []

        breakers.extend(self._fundamental_breakers(fundamental_summary, thesis_result))
        breakers.extend(self._valuation_breakers(pricing_result, thesis_result))
        breakers.extend(self._expectation_breakers(expectation_result, thesis_result))
        breakers.extend(self._regime_breakers(regime_result, thesis_result))
        breakers.extend(self._catalyst_breakers(catalysts, thesis_result))
        breakers.extend(self._risk_breakers(risk_result, thesis_result))

        return breakers

    def _fundamental_breakers(
        self,
        fundamental_summary: Dict[str, Any],
        thesis_result: ThesisResult,
    ) -> List[ThesisBreaker]:
        breakers: List[ThesisBreaker] = []
        confidence = fundamental_summary.get("confidence", 0.0)
        score = fundamental_summary.get("score", 0.0)

        if score < 35.0:
            breakers.append(self._build_breaker(
                id="fundamental-weakness",
                name="Fundamental weakness",
                description="Pontuação fundamental baixa sugere que a tese não está sustentada nos fundamentos.",
                category="FUNDAMENTAL",
                condition="fundamental_score < 35",
                threshold=35.0,
                current_value=score,
                severity="HIGH",
                impact_score=0.72,
                status="TRIGGERED" if score < 35.0 else "INACTIVE",
                triggered=score < 35.0,
                evidence=ThesisEvidence(
                    claim="Fundamentos insuficientes",
                    evidence_type="breaker",
                    confidence=min(0.9, confidence / 100.0),
                    details=f"Score fundamental {score:.2f} abaixo do limiar de 35.",
                    timestamp=datetime.datetime.utcnow(),
                ),
            ))

        if confidence < 40.0:
            breakers.append(self._build_breaker(
                id="fundamental-low-confidence",
                name="Fundamental low confidence",
                description="Baixa confiança nos dados financeiros reduz a robustez da tese.",
                category="FINANCIAL",
                condition="data confidence < 40%",
                threshold=40.0,
                current_value=confidence,
                severity="MEDIUM",
                impact_score=0.46,
                status="WARNING" if confidence < 40.0 else "INACTIVE",
                triggered=confidence < 40.0,
                evidence=ThesisEvidence(
                    claim="Baixa confiabilidade de dados",
                    evidence_type="breaker",
                    confidence=0.55,
                    details=f"Confiança de dados fundamental {confidence:.2f}% indica maior incerteza.",
                    timestamp=datetime.datetime.utcnow(),
                ),
            ))

        return breakers

    def _valuation_breakers(
        self,
        pricing_result: Dict[str, Any],
        thesis_result: ThesisResult,
    ) -> List[ThesisBreaker]:
        breakers: List[ThesisBreaker] = []
        status = pricing_result.get("pricing_status", "UNKNOWN")
        confidence = pricing_result.get("pricing_confidence", 0.0)

        if status == "OVERPRICED":
            breakers.append(self._build_breaker(
                id="valuation-overpriced",
                name="Valuation overpriced",
                description="O preço sugere que a tese está sendo negociada em múltiplos altos demais.",
                category="VALUATION",
                condition="pricing_status == OVERPRICED",
                threshold=None,
                current_value=None,
                severity="MEDIUM",
                impact_score=0.58,
                status="WARNING",
                triggered=False,
                evidence=ThesisEvidence(
                    claim="Valuation esticada",
                    evidence_type="breaker",
                    confidence=confidence,
                    details=f"Status de avaliação {status} com confiança {confidence:.2f}.",
                    timestamp=datetime.datetime.utcnow(),
                ),
            ))

        return breakers

    def _expectation_breakers(
        self,
        expectation_result: Dict[str, Any],
        thesis_result: ThesisResult,
    ) -> List[ThesisBreaker]:
        breakers: List[ThesisBreaker] = []
        score = expectation_result.get("expectation_gap_score", 50.0)
        reasons = expectation_result.get("reasons", [])

        if score <= 30.0:
            breakers.append(self._build_breaker(
                id="expectation-compression",
                name="Expectation compression",
                description="O gap de expectativa é baixo, indicando que a tese pode não estar descontando surpresa positiva.",
                category="EXPECTATION",
                condition="expectation_gap_score < 30",
                threshold=30.0,
                current_value=score,
                severity="HIGH",
                impact_score=0.65,
                status="WARNING" if score < 30.0 else "INACTIVE",
                triggered=False,
                evidence=ThesisEvidence(
                    claim="Expectativa comprimida",
                    evidence_type="breaker",
                    confidence=0.60,
                    details=f"Gap de expectativa {score:.2f}. Razões: {'; '.join(reasons)}.",
                    timestamp=datetime.datetime.utcnow(),
                ),
            ))

        return breakers

    def _regime_breakers(
        self,
        regime_result: Dict[str, Any],
        thesis_result: ThesisResult,
    ) -> List[ThesisBreaker]:
        breakers: List[ThesisBreaker] = []
        regime = regime_result.get("regime", "UNKNOWN")
        signals = regime_result.get("signals", [])

        if regime == "HIGH_SENSITIVITY":
            breakers.append(self._build_breaker(
                id="regime-sensitivity",
                name="High sensitivity regime",
                description="Ambiente de mercado sensível aumenta o risco de reversão para a tese.",
                category="REGIME",
                condition="regime == HIGH_SENSITIVITY",
                threshold=None,
                current_value=None,
                severity="MEDIUM",
                impact_score=0.54,
                status="WARNING",
                triggered=False,
                evidence=ThesisEvidence(
                    claim="Regime sensível detectado",
                    evidence_type="breaker",
                    confidence=regime_result.get("confidence", 0.0),
                    details=f"Regime {regime} com sinais: {', '.join(signals)}.",
                    timestamp=datetime.datetime.utcnow(),
                ),
            ))

        return breakers

    def _catalyst_breakers(
        self,
        catalysts: List[Dict[str, Any]],
        thesis_result: ThesisResult,
    ) -> List[ThesisBreaker]:
        breakers: List[ThesisBreaker] = []
        if catalysts:
            for idx, catalyst in enumerate(catalysts, start=1):
                if catalyst.get("category") == "earnings" and catalyst.get("published_at") is None:
                    breakers.append(self._build_breaker(
                        id=f"catalyst-delay-{idx}",
                        name="Catalyst delay",
                        description="Catalisador esperado não possui data de publicação clara."
                        if catalyst.get("published_at") is None
                        else "Catalisador com atraso ou incerteza.",
                        category="CATALYST",
                        condition="catalyst date missing",
                        threshold=None,
                        current_value=None,
                        severity="LOW",
                        impact_score=0.35,
                        status="WARNING",
                        triggered=False,
                        evidence=ThesisEvidence(
                            claim="Catalyst timing uncertain",
                            evidence_type="breaker",
                            confidence=0.45,
                            details=f"Catalisador {catalyst.get('title')} sem data de publicação definida.",
                            timestamp=datetime.datetime.utcnow(),
                        ),
                    ))

        return breakers

    def _risk_breakers(
        self,
        risk_result: Dict[str, Any],
        thesis_result: ThesisResult,
    ) -> List[ThesisBreaker]:
        breakers: List[ThesisBreaker] = []
        evidence = risk_result.get("evidence", [])
        for idx, item in enumerate(evidence[:2], start=1):
            breakers.append(self._build_breaker(
                id=f"risk-evidence-{idx}",
                name="Risk evidence alert",
                description="Evidência de risco inclui fatores relevantes que podem enfraquecer a tese.",
                category="RISK",
                condition="risk evidence present",
                threshold=None,
                current_value=None,
                severity="MEDIUM",
                impact_score=0.45,
                status="WARNING",
                triggered=False,
                evidence=item,
            ))

        return breakers

    def _build_breaker(
        self,
        id: str,
        name: str,
        description: str,
        category: str,
        condition: str,
        threshold: Optional[float],
        current_value: Optional[float],
        severity: str,
        impact_score: float,
        status: str,
        triggered: bool,
        evidence: Optional[ThesisEvidence],
    ) -> ThesisBreaker:
        distance = None
        if threshold is not None and current_value is not None:
            distance = round(current_value - threshold, 2)

        return ThesisBreaker(
            id=id,
            name=name,
            description=description,
            category=category,
            condition=condition,
            threshold=threshold,
            current_value=current_value,
            distance_to_threshold=distance,
            severity=severity,
            impact_score=impact_score,
            status=status,
            triggered=triggered,
            evidence=evidence,
            timestamp=datetime.datetime.utcnow(),
        )
