from datetime import datetime
from typing import Any, Dict, List

from prometheus.models import DecisionResult, ThesisEvidence


class DecisionEngine:
    def decide(self, thesis_result: Any, risk_result: Dict[str, Any], news_sentiment: float) -> DecisionResult:
        thesis_score = min(max(float(self._value(thesis_result, "score", 0.0)) / 100.0, 0.0), 1.0)
        risk_score = min(max(float(risk_result.get("risk_score", 0.0)), 0.0), 1.0)
        score = thesis_score * 0.7 + risk_score * 0.3
        confidence = min(max((self._value(thesis_result, "confidence", 0.5) + risk_result.get("risk_score", 0.5)) / 2.0, 0.0), 1.0)
        action = self._derive_action(score)
        reasoning = self._compose_reasoning(thesis_result, risk_result, news_sentiment)
        evidence = self._collect_evidence(thesis_result, risk_result)
        return DecisionResult(
            action=action,
            reasoning=reasoning,
            score=score,
            confidence=confidence,
            factors={
                "thesis_score": self._value(thesis_result, "score"),
                "risk_score": risk_result.get("risk_score"),
                "news_sentiment": news_sentiment,
            },
            evidence=evidence,
            timestamp=datetime.utcnow(),
        )

    def _derive_action(self, score: float) -> str:
        if score >= 0.75:
            return "evidence_favorable"
        if score >= 0.5:
            return "evidence_mixed"
        return "evidence_adverse"

    def _compose_reasoning(self, thesis_result: Any, risk_result: Dict[str, Any], news_sentiment: float) -> str:
        return (
            f"Força da tese {self._value(thesis_result, 'score', 0.0):.2f}, "
            f"escore de risco {risk_result.get('risk_score', 0.0):.2f}, "
            f"sentimento informacional {news_sentiment:.1f}. "
            "O estado descreve o conjunto de evidências e não instrui compra, venda ou manutenção de posição."
        )

    def _collect_evidence(self, thesis_result: Any, risk_result: Dict[str, Any]) -> List[ThesisEvidence]:
        evidence = self._value(thesis_result, "evidence", []) or []
        evidence.extend(risk_result.get("evidence", []) or [])
        return evidence

    def _value(self, source: Any, name: str, default: Any = None) -> Any:
        if isinstance(source, dict):
            return source.get(name, default)
        return getattr(source, name, default)
