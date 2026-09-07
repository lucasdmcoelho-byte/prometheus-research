import datetime
from typing import Any, Callable, Dict, List, Optional

from prometheus.data_engine import get_asset_data, get_fundamental_data
from prometheus.fundamental_engine import calculate_fundamental_score
from prometheus.thesis_engine import calculate_thesis_scores, calculate_score
from prometheus.expectation_engine import ExpectationEngine
from prometheus.models import Prediction, PredictionOutcome


class OutcomeEngine:
    def __init__(self, metric_resolver: Optional[Callable[[Prediction, datetime.datetime], Optional[float]]] = None):
        self.expectation_engine = ExpectationEngine()
        self.metric_resolver = metric_resolver

    def resolve(self, prediction: Prediction, as_of: Optional[datetime.datetime] = None) -> PredictionOutcome:
        now = as_of or datetime.datetime.utcnow()

        # idempotent: if prediction already not pending, return no-op outcome
        if prediction.status != "PENDING":
            return PredictionOutcome(
                prediction_id=prediction.prediction_id,
                actual_value=None,
                resolved_at=None,
                status=prediction.status,
                error=None,
                snapshot=getattr(prediction, "snapshot", None),
            )

        created = prediction.created_at
        horizon = datetime.timedelta(days=prediction.horizon_days)
        if now < created + horizon:
            return PredictionOutcome(
                prediction_id=prediction.prediction_id,
                actual_value=None,
                resolved_at=None,
                status="PENDING",
                error=None,
                snapshot=getattr(prediction, "snapshot", None),
            )

        if as_of is not None and as_of.date() < datetime.datetime.utcnow().date() and self.metric_resolver is None:
            return PredictionOutcome(
                prediction_id=prediction.prediction_id,
                actual_value=None,
                resolved_at=now,
                status="INVALID",
                error="Historical resolution requires a point-in-time metric resolver.",
                snapshot=getattr(prediction, "snapshot", None),
            )

        if self.metric_resolver is not None:
            try:
                actual = self.metric_resolver(prediction, now)
            except Exception as error:
                return PredictionOutcome(
                    prediction_id=prediction.prediction_id,
                    actual_value=None,
                    resolved_at=now,
                    status="INVALID",
                    error=str(error),
                    snapshot=getattr(prediction, "snapshot", None),
                )
            return self._compare(prediction, actual, now)

        # Fetch the current metric only when no historical cutoff was requested.
        metric = prediction.metric
        ticker = prediction.ticker
        try:
            if metric in {"revenue_growth", "earnings_growth", "profit_margin", "roe", "debt_to_equity"}:
                fund = get_fundamental_data(ticker)
                field = fund.get(metric, {})
                actual = field.get("normalized")
            elif metric == "score_fundamental":
                fund = get_fundamental_data(ticker)
                comp = {k: (v.get("normalized") if isinstance(v, dict) else None) for k, v in fund.items()}
                res = calculate_fundamental_score({
                    "revenue_growth": comp.get("revenue_growth"),
                    "earnings_growth": comp.get("earnings_growth"),
                    "profit_margin": comp.get("profit_margin"),
                    "roe": comp.get("roe"),
                    "debt_to_equity": comp.get("debt_to_equity"),
                })
                actual = res.get("score")
            elif metric == "thesis_score":
                asset = get_asset_data(ticker)
                thesis_scores = calculate_thesis_scores(asset, news_sentiment=asset.get("news_sentiment", 50.0))
                actual = calculate_score(thesis_scores)
            elif metric == "expectation_gap":
                asset = get_asset_data(ticker)
                fundamental = {k: v.get("normalized") for k, v in get_fundamental_data(ticker).items()}
                expectation = self.expectation_engine.quantify(
                    market_snapshot={
                        "price_change_percent": asset.get("price_change_percent"),
                        "beta": asset.get("beta"),
                    },
                    fundamental_summary={"confidence": 50.0},
                    sentiment_score=asset.get("news_sentiment", 50.0),
                )
                actual = expectation.get("expectation_gap_score")
            else:
                actual = None
        except Exception:
            actual = None

        return self._compare(prediction, actual, now)

    def _compare(self, prediction: Prediction, actual: Optional[float], resolved_at: datetime.datetime) -> PredictionOutcome:
        if actual is None:
            return PredictionOutcome(
                prediction_id=prediction.prediction_id,
                actual_value=None,
                resolved_at=resolved_at,
                status="INVALID",
                error="Metric was unavailable at resolution time.",
                snapshot=getattr(prediction, "snapshot", None),
            )

        # compare according to operator
        op = prediction.operator
        th = prediction.threshold
        status = "INCORRECT"
        error = None
        try:
            if op == ">=":
                status = "CORRECT" if actual >= float(th) else "INCORRECT"
                error = float(actual) - float(th)
            elif op == ">":
                status = "CORRECT" if actual > float(th) else "INCORRECT"
                error = float(actual) - float(th)
            elif op == "<=":
                status = "CORRECT" if actual <= float(th) else "INCORRECT"
                error = float(actual) - float(th)
            elif op == "<":
                status = "CORRECT" if actual < float(th) else "INCORRECT"
                error = float(actual) - float(th)
            elif op == "entre":
                low, high = th
                status = "CORRECT" if (actual >= float(low) and actual <= float(high)) else "INCORRECT"
                error = float(actual) - float((low + high) / 2.0)
        except Exception:
            status = "INVALID"
            error = None

        return PredictionOutcome(
            prediction_id=prediction.prediction_id,
            actual_value=actual,
            resolved_at=resolved_at,
            status=status,
            error=error,
            snapshot=getattr(prediction, "snapshot", None),
        )
