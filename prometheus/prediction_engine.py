import datetime
import uuid
from typing import Any, Dict, List, Optional

from prometheus.models import Prediction, ThesisResult


class PredictionEngine:
    def __init__(self):
        pass

    def generate(
        self,
        thesis_result: ThesisResult,
        thesis_scores: Dict[str, float],
        expectation: Dict[str, Any],
        catalysts: List[Dict[str, Any]],
        regime: Dict[str, Any],
    ) -> List[Prediction]:
        """Generate falsifiable predictions from an existing ThesisResult.

        Only create predictions when they can be derived from thesis_scores,
        drivers, breakers, expectation, catalysts or regime.
        """
        preds: List[Prediction] = []
        now = datetime.datetime.utcnow()

        snapshot = {
            "ticker": thesis_result.ticker,
            "thesis_score": float(thesis_result.score),
            "state": thesis_result.state,
            "confidence": float(thesis_result.confidence),
            "drivers": list(thesis_result.drivers),
            "thesis_scores": dict(thesis_scores or {}),
            "expectation_gap_score": expectation.get("expectation_gap_score") if isinstance(expectation, dict) else None,
            "regime": regime,
            "created_at": now.isoformat() + "Z",
        }

        # Example rule: if thesis_score is strong, assert thesis_score stays >= threshold
        try:
            thesis_score = float(thesis_result.score)
        except Exception:
            thesis_score = None

        # generate prediction for thesis_score when it's strong
        if thesis_score is not None and thesis_score >= 80.0:
            preds.append(
                Prediction(
                    prediction_id=str(uuid.uuid4()),
                    thesis_id=thesis_result.thesis_id,
                    ticker=thesis_result.ticker,
                    metric="thesis_score",
                    operator=">=",
                    threshold=80.0,
                    horizon_days=30,
                    created_at=now,
                    confidence=thesis_result.confidence,
                    catalyst=None,
                    snapshot={**snapshot, "metric": "thesis_score"},
                )
            )

        # if there is a strong fundamental driver, create a fundamental metric prediction
        if thesis_scores and thesis_scores.get("fundamental", 0.0) >= 75.0:
            preds.append(
                Prediction(
                    prediction_id=str(uuid.uuid4()),
                    thesis_id=thesis_result.thesis_id,
                    ticker=thesis_result.ticker,
                    metric="score_fundamental",
                    operator=">=",
                    threshold=round(thesis_scores.get("fundamental", 0.0), 2),
                    horizon_days=90,
                    created_at=now,
                    confidence=thesis_result.confidence,
                    catalyst=None,
                    snapshot={**snapshot, "metric": "score_fundamental"},
                )
            )

        # Expectation scores are bounded to 10..90, so a threshold of zero would
        # be trivially true. Predict that a positive gap remains above neutral.
        if expectation and expectation.get("expectation_gap_score") is not None:
            gap = float(expectation.get("expectation_gap_score"))
            if gap > 50.0:
                preds.append(
                    Prediction(
                        prediction_id=str(uuid.uuid4()),
                        thesis_id=thesis_result.thesis_id,
                        ticker=thesis_result.ticker,
                        metric="expectation_gap",
                        operator=">",
                        threshold=50.0,
                        horizon_days=30,
                        created_at=now,
                        confidence=thesis_result.confidence,
                        catalyst=None,
                        snapshot={**snapshot, "metric": "expectation_gap"},
                    )
                )

        # avoid inventing predictions: if no preds, return empty
        return preds
