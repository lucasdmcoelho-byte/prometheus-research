import datetime
from typing import Any, Dict, List, Optional

from prometheus.models import ThesisBreaker, ThesisEvidence, ThesisResult


class ThesisStateEngine:
    def __init__(self):
        self.previous_scores: Dict[str, float] = {}
        self.previous_timestamps: Dict[str, datetime.datetime] = {}
        self.thesis_versions: Dict[str, int] = {}

    def evaluate(
        self,
        ticker: str,
        current_score: float,
        confidence: float,
        thesis_scores: Dict[str, float],
        evidence: List[ThesisEvidence],
        pricing_result: Dict[str, Any],
        catalysts: List[Dict[str, Any]],
        risk_result: Dict[str, Any],
    ) -> ThesisResult:
        now = datetime.datetime.utcnow()
        previous_score = self.previous_scores.get(ticker)
        previous_time = self.previous_timestamps.get(ticker)

        velocity = 0.0
        acceleration = 0.0
        age_days = None
        state = "UNKNOWN"
        direction = "NEUTRAL"

        if previous_score is not None and previous_time is not None:
            elapsed = (now - previous_time).total_seconds() / 86400.0
            age_days = max(1, int(elapsed))
            velocity = round(current_score - previous_score, 2)
            if elapsed > 0:
                acceleration = round(velocity / elapsed, 3)

        if current_score >= 85.0:
            direction = "BULLISH"
        elif current_score >= 70.0:
            direction = "MODERATELY_BULLISH"
        elif current_score >= 50.0:
            direction = "NEUTRAL"
        elif current_score >= 30.0:
            direction = "MODERATELY_BEARISH"
        else:
            direction = "BEARISH"

        if velocity >= 5.0:
            state = "ACCELERATING"
        elif velocity >= 1.0:
            state = "STRENGTHENING"
        elif velocity <= -5.0:
            state = "DETERIORATING"
        elif velocity <= -1.0:
            state = "WEAKENING"
        else:
            state = "STABLE"

        thesis_id = self._current_thesis_id(ticker, now)

        self.previous_scores[ticker] = current_score
        self.previous_timestamps[ticker] = now

        return ThesisResult(
            thesis_id=thesis_id,
            ticker=ticker,
            score=round(current_score, 2),
            state=state,
            direction=direction,
            velocity=velocity,
            acceleration=acceleration,
            confidence=round(confidence, 4),
            age_days=age_days,
            status="ACTIVE",
            lifecycle="ACTIVE",
            drivers=[
                "fundamental momentum",
                "expectation gap",
                "pricing bias",
            ],
            thesis_breakers=[],
            pricing_status=pricing_result.get("pricing_status", "UNKNOWN"),
            pricing_confidence=pricing_result.get("pricing_confidence", 0.0),
            pricing_details=pricing_result.get("pricing_details"),
            evidence=evidence,
            timestamp=now,
        )

    def _current_thesis_id(self, ticker: str, now: datetime.datetime) -> str:
        version = self.thesis_versions.get(ticker, 0)
        if version == 0:
            version = 1
        thesis_id = f"{ticker}-{now.strftime('%Y-%m-%d')}-{version:03d}"
        self.thesis_versions[ticker] = version
        return thesis_id

    def apply_breakers(self, thesis_result: ThesisResult, breakers: List[ThesisBreaker]) -> ThesisResult:
        thesis_result.thesis_breakers = breakers
        warnings = [b for b in breakers if b.status == "WARNING"]
        triggered = [b for b in breakers if b.status == "TRIGGERED"]
        critical = [b for b in breakers if b.status == "TRIGGERED" and b.severity == "CRITICAL"]

        if critical:
            thesis_result.status = "BROKEN"
            thesis_result.lifecycle = "BROKEN"
        elif triggered:
            thesis_result.status = "DETERIORATING"
            thesis_result.lifecycle = "ACTIVE"
        elif warnings and thesis_result.state in {"ACCELERATING", "STRENGTHENING"}:
            thesis_result.status = "STRENGTHENING_WITH_RISK"
            thesis_result.lifecycle = "ACTIVE"
        elif warnings:
            thesis_result.status = "WEAKENING"
            thesis_result.lifecycle = "ACTIVE"
        else:
            thesis_result.status = thesis_result.state
            thesis_result.lifecycle = "ACTIVE"

        if thesis_result.lifecycle == "BROKEN":
            self._advance_thesis_version(thesis_result.ticker)

        return thesis_result

    def _advance_thesis_version(self, ticker: str) -> None:
        current = self.thesis_versions.get(ticker, 1)
        self.thesis_versions[ticker] = current + 1
