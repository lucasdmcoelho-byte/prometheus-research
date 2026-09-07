from datetime import datetime
from typing import Any, Dict

from prometheus.models import ThesisEvidence


class RiskEngine:
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        evidence = []
        beta = data.get("beta")
        market_cap = data.get("market_cap")
        debt_to_equity = data.get("debt_to_equity")

        if beta is not None and abs(beta) > 1.2:
            evidence.append(ThesisEvidence(
                claim="Price sensitivity is elevated",
                evidence_type="risk",
                confidence=min(max(abs(beta) / 2.0, 0.0), 1.0),
                details=f"Beta {beta:.2f} suggests above-average volatility.",
                timestamp=datetime.utcnow(),
            ))

        if market_cap is not None and market_cap < 10_000_000_000:
            evidence.append(ThesisEvidence(
                claim="Smaller capitalization implies idiosyncratic risk",
                evidence_type="risk",
                confidence=0.6,
                details=f"Market cap {market_cap:,.0f} implies small/mid cap classification.",
                timestamp=datetime.utcnow(),
            ))

        if debt_to_equity is not None and debt_to_equity > 1.5:
            evidence.append(ThesisEvidence(
                claim="High leverage raises balance sheet risk",
                evidence_type="risk",
                confidence=0.7,
                details=f"Debt/equity {debt_to_equity:.2f} indicates material leverage.",
                timestamp=datetime.utcnow(),
            ))

        beta_risk = 0.5 if beta is None else min(max(abs(beta) / 2.0, 0.0), 1.0)
        leverage_risk = 0.5 if debt_to_equity is None else min(max(debt_to_equity / 2.0, 0.0), 1.0)
        if market_cap is None:
            size_risk = 0.5
        elif market_cap < 5_000_000_000:
            size_risk = 0.65
        elif market_cap < 20_000_000_000:
            size_risk = 0.40
        else:
            size_risk = 0.20
        aggregate_risk = beta_risk * 0.40 + leverage_risk * 0.40 + size_risk * 0.20
        score = round(1.0 - min(max(aggregate_risk, 0.0), 1.0), 4)
        return {
            "risk_score": score,
            "risk_factors": {
                "beta_risk": round(beta_risk, 4),
                "leverage_risk": round(leverage_risk, 4),
                "size_risk": round(size_risk, 4),
            },
            "evidence": evidence,
        }
