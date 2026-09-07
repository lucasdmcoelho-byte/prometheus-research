import datetime
from typing import Any, Dict, List, Optional

from prometheus.models import MarketSnapshot, ThesisEvidence


class RegimeEngine:
    def detect(self, asset_data: Dict[str, Any], recent_returns: Optional[List[float]] = None) -> Dict[str, Any]:
        regime = "UNKNOWN"
        signals: List[str] = []
        evidence: List[ThesisEvidence] = []

        beta = asset_data.get("beta")
        market_cap = asset_data.get("market_cap")
        price_change = asset_data.get("price_change_percent")
        momentum = None
        if recent_returns:
            momentum = sum(recent_returns[-3:]) / len(recent_returns)

        if beta is not None and beta > 1.2:
            regime = "HIGH_SENSITIVITY"
            signals.append("beta_high")
        elif beta is not None and beta < 0.8:
            regime = "LOW_SENSITIVITY"
            signals.append("beta_low")

        if market_cap is not None and market_cap > 75_000_000_000:
            signals.append("large_cap")
        if market_cap is not None and market_cap < 10_000_000_000:
            signals.append("small_cap")

        if price_change is not None and abs(price_change) > 8.0:
            signals.append("volatile_move")

        if momentum is not None:
            if momentum > 4.0:
                signals.append("positive_trend")
            elif momentum < -4.0:
                signals.append("negative_trend")

        if regime == "UNKNOWN":
            if "small_cap" in signals:
                regime = "SMALL_CAP_DRIFT"
            elif "large_cap" in signals:
                regime = "BLUE_CHIP_STABILITY"
            else:
                regime = "BASELINE"

        confidence = 0.5 + min(len(signals) * 0.1, 0.4)
        evidence.append(
            ThesisEvidence(
                claim=f"Regime detectado: {regime}",
                evidence_type="regime",
                confidence=confidence,
                details=f"Sinais ativos: {', '.join(signals) if signals else 'nenhum sinal adicional'}.",
                timestamp=datetime.datetime.utcnow(),
            )
        )

        return {
            "regime": regime,
            "signals": signals,
            "confidence": round(confidence, 2),
            "evidence": evidence,
        }
