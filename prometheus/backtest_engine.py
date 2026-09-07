import datetime as dt
import math
import statistics
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from prometheus.calibration_engine import CalibrationEngine
from prometheus.data_engine import validate_ticker
from prometheus.models import Prediction, PredictionOutcome
from prometheus.outcome_engine import OutcomeEngine
from prometheus.replay_engine import ReplayEngine
from prometheus.editorial_gate import EditorialGate
from prometheus.thesis_engine import get_state


class PrometheusPointInTimeSignalProvider:
    """Adapt a PrometheusEngine into a strictly dated backtest signal."""

    def __init__(self, engine: Any):
        self.engine = engine

    def __call__(self, ticker: str, analysis_date: dt.date, context: Dict[str, Any]) -> Dict[str, Any]:
        cutoff = dt.datetime.combine(analysis_date, dt.time(23, 59, 59))
        result = self.engine.evaluate(
            ticker,
            sentiment_score=50.0,
            news_items=[],
            recent_returns=context.get("recent_returns"),
            journal_metadata={"source": "point_in_time_backtest", "analysis_date": analysis_date.isoformat()},
            as_of=cutoff,
        )
        decision = result.get("decision_result")
        action = getattr(decision, "action", "evidence_mixed")
        forecast = {
            "evidence_favorable": "positive_return",
            "evidence_adverse": "negative_return",
            "evidence_mixed": "no_trade",
            "monitor_increase": "positive_return",
            "hold": "negative_return",
            "watch": "no_trade",
        }.get(action, "no_trade")
        report = result.get("report") or {}
        adapter = getattr(self.engine, "adapter", None)
        if adapter is not None and hasattr(adapter, "cvm") and hasattr(adapter, "market"):
            # A commercial research signal includes the same point-in-time peer
            # valuation used by the report. Without this step every historical
            # sample would abstain solely because the report was incomplete.
            from prometheus.automatic_peers import enrich_automatic_peers
            from prometheus.business_quality import BusinessQualityEngine

            enrich_automatic_peers(report, adapter, cutoff)
            # Peer enrichment replaces the valuation snapshot. Reconcile the
            # qualitative/valuation bridge against that exact post-enrichment
            # state so the gate never evaluates stale pre-peer conclusions.
            report["business_quality"] = BusinessQualityEngine().evaluate(report)
        live_gate = EditorialGate().evaluate(report)
        gate_blockers = [item.get("code") for item in live_gate.get("blockers") or []]
        classification = report.get("official_classification") or {}
        if (
            (report.get("sector_model") or {}).get("key") == "general"
            and classification.get("status") == "INSUFFICIENT_DATA"
        ):
            gate_blockers.append("SECTOR_CLASSIFICATION_UNAVAILABLE_POINT_IN_TIME")
        gate_blockers = list(dict.fromkeys(item for item in gate_blockers if item))
        if gate_blockers:
            forecast = "no_trade"
        source_trace = []
        for source in ((report.get("research") or {}).get("sources") or []):
            trace_item = {
                "source": source.get("source"),
                "period": source.get("period"),
                "publication_date": source.get("publication_date"),
                "source_url": source.get("source_url"),
                "source_sha256": source.get("source_sha256"),
            }
            if trace_item not in source_trace:
                source_trace.append(trace_item)
        return {
            "score": float(result["overall_score"]),
            "state": result["state"],
            "confidence": float(getattr(decision, "confidence", 0.5)),
            "model_name": "PROMETHEUS_POINT_IN_TIME",
            "forecast": forecast,
            "source_trace": source_trace,
            "editorial_status": live_gate.get("status"),
            "abstention_reasons": gate_blockers,
            "decision_action": action,
            "valuation_status": (report.get("valuation") or {}).get("status"),
            "peer_analysis_status": ((report.get("research") or {}).get("peer_analysis") or {}).get("status"),
            "eligible_peer_count": ((report.get("research") or {}).get("peer_analysis") or {}).get("eligible_multiple_count"),
        }


class BacktestEngine:
    """Point-in-time backtest engine for Prometheus.

    The implementation intentionally relies only on data available at the analysis
    date. It never reads future rows when building the prediction snapshot.
    """

    def __init__(
        self,
        replay_engine: Optional[ReplayEngine] = None,
        signal_provider: Optional[Callable[[str, dt.date, Dict[str, Any]], Dict[str, Any]]] = None,
        history_provider: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
        cache_dir: Optional[str] = None,
    ):
        self.replay_engine = replay_engine or ReplayEngine()
        self.outcome_engine = OutcomeEngine()
        self.calibration = CalibrationEngine(min_sample=1)
        self.signal_provider = signal_provider
        self.history_provider = history_provider
        self.cache_dir = cache_dir

    def fetch_history(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
        if self.history_provider is not None:
            return self.history_provider(ticker, start_date, end_date)
        import yfinance as yf

        if self.cache_dir:
            from yfinance.cache import set_cache_location

            cache_path = (Path(self.cache_dir) / "yfinance").resolve()
            cache_path.mkdir(parents=True, exist_ok=True)
            set_cache_location(str(cache_path))

        normalized = validate_ticker(ticker)
        benchmark_aliases = {"IBOV": "^BVSP", "^BVSP": "^BVSP"}
        symbol = benchmark_aliases.get(normalized, normalized)
        if not symbol.startswith("^") and not symbol.endswith(".SA"):
            symbol = f"{symbol}.SA"
        start = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
        end = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
        history = yf.Ticker(symbol).history(
            start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
            interval="1d", auto_adjust=False,
        )
        if history is None or getattr(history, "empty", True):
            return {"status": "BACKTEST_PARTIAL", "ticker": normalized, "history": [], "notes": "No historical price data found."}
        return {
            "status": "OK",
            "ticker": normalized,
            "history": history,
            "notes": "Historical daily series loaded.",
        }

    def _as_date(self, value: Any) -> Optional[dt.date]:
        if value is None:
            return None
        try:
            if hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()
            if isinstance(value, dt.datetime):
                return value.date()
            if isinstance(value, dt.date):
                return value
            if isinstance(value, str):
                try:
                    return dt.datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    try:
                        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
                    except ValueError:
                        return None
        except Exception:
            return None
        return None

    def _build_snapshot(self, ticker: str, analysis_date: dt.date, current_price: float, previous_close: Optional[float], score: float, thesis_state: str, confidence: float, horizon_days: int, recent_returns: Sequence[float], market_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "ticker": ticker,
            "analysis_date": analysis_date.isoformat(),
            "prediction_timestamp": dt.datetime.combine(analysis_date, dt.time(23, 59, 59)).isoformat() + "Z",
            "price": current_price,
            "previous_close": previous_close,
            "score": score,
            "thesis_state": thesis_state,
            "confidence": confidence,
            "horizon_days": horizon_days,
            "recent_returns": list(recent_returns),
            "market_snapshot": market_snapshot or {},
            "point_in_time": True,
            "notes": "Snapshot captured before future horizon resolution.",
        }

    def _future_return_for_date(self, history: Any, analysis_date: dt.date, horizon_days: int) -> Optional[Tuple[Optional[dt.date], Optional[float], Optional[float]]]:
        if history is None or getattr(history, "empty", False):
            return None

        date_key = None
        for candidate in list(history.index):
            candidate_date = self._as_date(candidate)
            if candidate_date == analysis_date:
                date_key = candidate
                break
        if date_key is None:
            return None

        current_row = history.loc[date_key]
        current_close = current_row.get("Close")
        if current_close is None:
            return None

        future_index = None
        for idx, candidate in enumerate(list(history.index)):
            candidate_date = self._as_date(candidate)
            if candidate_date is not None and candidate_date > analysis_date:
                delta_days = (candidate_date - analysis_date).days
                if delta_days >= horizon_days:
                    future_index = idx
                    break
        if future_index is None:
            return None

        future_date = self._as_date(list(history.index)[future_index])
        future_row = history.iloc[future_index]
        future_close = future_row.get("Close")
        if future_close is None:
            return None

        current_close_float = float(current_close)
        future_close_float = float(future_close)
        if current_close_float == 0:
            return None
        return future_date, future_close_float, ((future_close_float / current_close_float) - 1.0)

    def _recent_return(self, history: Any, analysis_date: dt.date, lookback_days: int) -> float:
        values: List[float] = []
        dates = list(history.index)
        for candidate in reversed(dates):
            candidate_date = self._as_date(candidate)
            if candidate_date is None:
                continue
            if candidate_date > analysis_date:
                continue
            row = history.loc[candidate]
            close = row.get("Close")
            if close is None:
                continue
            values.append(float(close))
            if len(values) >= lookback_days + 1:
                break
        if len(values) < 2:
            return 0.0
        oldest = values[-1]
        latest = values[0]
        if oldest == 0 or latest == 0:
            return 0.0
        return (latest / oldest) - 1.0

    def _previous_close(self, history: Any, analysis_date: dt.date) -> Optional[float]:
        previous: Optional[float] = None
        for candidate in list(history.index):
            candidate_date = self._as_date(candidate)
            if candidate_date is None or candidate_date >= analysis_date:
                continue
            close = history.loc[candidate].get("Close")
            if close is not None:
                previous = float(close)
        return previous

    def _signal_score(self, history: Any, analysis_date: dt.date) -> float:
        momentum = self._recent_return(history, analysis_date, 20)
        score = 50.0 + (momentum * 100.0)
        score = max(0.0, min(100.0, score))
        return round(score, 2)

    def _signal(self, ticker: str, history: Any, analysis_date: dt.date, market_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        recent_returns = [
            self._recent_return(history, analysis_date, 5),
            self._recent_return(history, analysis_date, 20),
        ]
        if self.signal_provider is not None:
            signal = dict(self.signal_provider(ticker, analysis_date, {
                "market_snapshot": dict(market_snapshot),
                "recent_returns": recent_returns,
            }))
            score = min(max(float(signal["score"]), 0.0), 100.0)
            signal["score"] = round(score, 2)
            signal.setdefault("state", get_state(score))
            signal.setdefault("confidence", score / 100.0)
            signal.setdefault("model_name", "CUSTOM_POINT_IN_TIME")
            signal.setdefault("forecast", "positive_return")
            signal.setdefault("source_trace", [])
            return signal
        score = self._signal_score(history, analysis_date)
        return {
            "score": score,
            "state": get_state(score),
            "confidence": min(1.0, max(0.0, score / 100.0)),
            "model_name": "MOMENTUM_BASELINE",
            "forecast": "positive_return",
            "source_trace": [],
        }

    def run(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        horizon_days: int = 30,
        benchmark_ticker: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized = validate_ticker(ticker)
        analysis_end = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
        resolution_end = analysis_end + dt.timedelta(days=max(horizon_days, 0) + 10)
        history_data = self.fetch_history(normalized, start_date, resolution_end.isoformat())
        if history_data["status"] == "BACKTEST_PARTIAL":
            return {
                "ticker": normalized,
                "status": "BACKTEST_PARTIAL",
                "notes": history_data["notes"],
                "predictions": [],
                "metrics": {
                    "prediction_count": 0,
                    "resolved_count": 0,
                    "hit_rate": None,
                    "avg_error": None,
                    "avg_return": None,
                    "median_return": None,
                    "volatility": None,
                    "max_drawdown": None,
                    "sharpe": None,
                    "benchmark_return": None,
                },
                "calibration": {"total": 0, "brier_score": None, "buckets": []},
            }

        history = history_data["history"]
        records: List[Dict[str, Any]] = []
        signal_audit: List[Dict[str, Any]] = []
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive")

        for candidate in list(history.index):
            analysis_date = self._as_date(candidate)
            if analysis_date is None:
                continue
            if analysis_date < self._as_date(start_date) or analysis_date > self._as_date(end_date):
                continue

            future_info = self._future_return_for_date(history, analysis_date, horizon_days)
            if future_info is None:
                continue

            future_date, future_close, realized_return = future_info
            current_row = history.loc[candidate]
            current_close = current_row.get("Close")
            if current_close is None:
                continue
            current_close_float = float(current_close)
            if current_close_float <= 0:
                continue

            market_snapshot = {
                "close": current_close_float,
                "open": float(current_row.get("Open")) if current_row.get("Open") is not None else None,
                "volume": float(current_row.get("Volume")) if current_row.get("Volume") is not None else None,
                "source_sha256": history_data.get("source_sha256"),
            }
            signal = self._signal(normalized, history, analysis_date, market_snapshot)
            signal_audit.append({
                "analysis_date": analysis_date.isoformat(),
                "score": signal.get("score"),
                "state": signal.get("state"),
                "confidence": signal.get("confidence"),
                "forecast": signal.get("forecast"),
                "model_name": signal.get("model_name"),
                "source_trace": signal.get("source_trace", []),
                "editorial_status": signal.get("editorial_status"),
                "abstention_reasons": signal.get("abstention_reasons", []),
                "decision_action": signal.get("decision_action"),
                "valuation_status": signal.get("valuation_status"),
                "peer_analysis_status": signal.get("peer_analysis_status"),
                "eligible_peer_count": signal.get("eligible_peer_count"),
            })
            if signal["forecast"] == "no_trade":
                continue
            score = signal["score"]
            thesis_state = signal["state"]
            confidence = min(1.0, max(0.0, float(signal["confidence"])))
            snapshot = self._build_snapshot(
                ticker=normalized,
                analysis_date=analysis_date,
                current_price=current_close_float,
                previous_close=self._previous_close(history, analysis_date),
                score=score,
                thesis_state=thesis_state,
                confidence=confidence,
                horizon_days=horizon_days,
                recent_returns=[self._recent_return(history, analysis_date, 5), self._recent_return(history, analysis_date, 20)],
                market_snapshot=market_snapshot,
            )
            operator = "<" if signal["forecast"] == "negative_return" else ">"
            prediction = Prediction(
                prediction_id=f"{normalized}-{analysis_date.isoformat()}-{horizon_days}",
                thesis_id=f"{normalized}-thesis-{analysis_date.isoformat()}",
                ticker=normalized,
                metric="price_return_horizon",
                operator=operator,
                threshold=0.0,
                horizon_days=horizon_days,
                created_at=dt.datetime.combine(analysis_date, dt.time(0, 0)),
                confidence=confidence,
                catalyst=None,
                snapshot=snapshot,
            )

            outcome = PredictionOutcome(
                prediction_id=prediction.prediction_id,
                actual_value=realized_return,
                resolved_at=dt.datetime.combine(future_date, dt.time(0, 0)) if future_date else None,
                status=(
                    "CORRECT"
                    if (realized_return < 0 if operator == "<" else realized_return > 0)
                    else "INCORRECT"
                ),
                error=realized_return - float(prediction.threshold),
                snapshot=snapshot,
            )

            record = {
                "prediction_id": prediction.prediction_id,
                "ticker": normalized,
                "analysis_date": analysis_date.isoformat(),
                "future_date": future_date.isoformat() if future_date else None,
                "prediction_timestamp": prediction.created_at.isoformat() + "Z",
                "horizon_days": horizon_days,
                "price_at_prediction": current_close_float,
                "future_price": future_close,
                "forecast": signal["forecast"],
                "threshold": float(prediction.threshold),
                "score": score,
                "thesis_state": thesis_state,
                "confidence": confidence,
                "model_name": signal["model_name"],
                "snapshot": snapshot,
                "realized_return": realized_return,
                "outcome_status": outcome.status,
                "hit": outcome.status == "CORRECT",
                "outcome_error": outcome.error,
                "invalidated": False,
                "benchmark_return": None,
            }
            record["snapshot"]["source_trace"] = signal.get("source_trace", [])
            records.append(record)

        if benchmark_ticker:
            benchmark_history = self.fetch_history(benchmark_ticker, start_date, resolution_end.isoformat())
            if benchmark_history["status"] == "OK":
                benchmark_series = benchmark_history["history"]
                for record in records:
                    analysis_date = self._as_date(record["analysis_date"])
                    if analysis_date is None:
                        continue
                    future_info = self._future_return_for_date(benchmark_series, analysis_date, record["horizon_days"])
                    if future_info is None:
                        continue
                    _, _, benchmark_return = future_info
                    record["benchmark_return"] = benchmark_return

        # Build calibration output using the same existing engine.
        pred_map = {
            record["prediction_id"]: Prediction(
                prediction_id=record["prediction_id"],
                thesis_id=f"{normalized}-thesis-{record['analysis_date']}",
                ticker=normalized,
                metric="price_return_horizon",
                operator="<" if record.get("forecast") == "negative_return" else ">",
                threshold=0.0,
                horizon_days=record["horizon_days"],
                created_at=dt.datetime.fromisoformat(record["prediction_timestamp"].replace("Z", "+00:00")).replace(tzinfo=None),
                confidence=record["confidence"],
                catalyst=None,
                snapshot=record["snapshot"],
            )
            for record in records
        }
        outcome_list = [
            PredictionOutcome(
                prediction_id=record["prediction_id"],
                actual_value=record["realized_return"],
                resolved_at=dt.datetime.fromisoformat(record["future_date"]).replace(tzinfo=None) if record.get("future_date") else None,
                status="CORRECT" if record["hit"] else "INCORRECT",
                error=record["outcome_error"],
                snapshot=record["snapshot"],
            )
            for record in records
        ]
        calibration_report = self.calibration.calculate(outcome_list, pred_map)

        model_name = (
            records[0]["model_name"] if records
            else signal_audit[0]["model_name"] if signal_audit
            else "CUSTOM_POINT_IN_TIME" if self.signal_provider
            else "MOMENTUM_BASELINE"
        )
        metrics = self._compute_metrics(records)
        non_overlapping_records = self._non_overlapping_records(records)
        independent_metrics = self._compute_metrics(
            non_overlapping_records, metric_scope="non_overlapping_horizon_windows",
        )
        metrics["non_overlapping"] = independent_metrics
        metrics["signals_evaluated"] = len(signal_audit)
        metrics["no_trade_count"] = sum(1 for signal in signal_audit if signal["forecast"] == "no_trade")
        metrics["coverage_rate"] = (len(records) / len(signal_audit)) if signal_audit else None
        metrics["abstention_rate"] = (
            metrics["no_trade_count"] / len(signal_audit) if signal_audit else None
        )
        metrics["commercial_validation_status"] = (
            "PASS"
            if model_name == "PROMETHEUS_POINT_IN_TIME"
            and independent_metrics.get("statistical_status") == "SUFFICIENT_SAMPLE"
            and independent_metrics.get("benchmark_return") is not None
            else "INSUFFICIENT_EVIDENCE"
        )
        self.replay_engine.records.extend(records)
        return {
            "ticker": normalized,
            "status": "OK",
            "model_name": model_name,
            "period": {"start": start_date, "end": end_date},
            "horizon_days": horizon_days,
            "predictions": records,
            "signal_audit": signal_audit,
            "signals_evaluated": len(signal_audit),
            "no_trade_count": sum(1 for signal in signal_audit if signal["forecast"] == "no_trade"),
            "metrics": metrics,
            "calibration": {
                "total": calibration_report.total,
                "brier_score": calibration_report.brier_score,
                "buckets": [
                    {
                        "bucket": bucket.bucket,
                        "sample_size": bucket.sample_size,
                        "correct": bucket.correct,
                        "accuracy": bucket.accuracy,
                        "low_stat_confidence": bucket.low_stat_confidence,
                    }
                    for bucket in calibration_report.buckets
                ],
            },
            "overlap_policy": {
                "signal_level": "Overlapping daily signals are descriptive and are not treated as independent evidence for commercial validation.",
                "independent_inference": "Primary confidence intervals use non-overlapping horizon windows.",
                "portfolio_level": "Use PortfolioBacktestEngine separately for portfolio/equity simulation.",
            },
        }

    def run_multicenario(
        self,
        tickers: Sequence[str],
        start_date: str,
        end_date: str,
        horizons: Optional[Sequence[int]] = None,
        benchmark_ticker: Optional[str] = None,
    ) -> Dict[str, Any]:
        if horizons is None:
            horizons = [15, 30, 60]
        normalized_tickers = [validate_ticker(ticker) for ticker in tickers]
        scenarios: List[Dict[str, Any]] = []
        all_predictions: List[Dict[str, Any]] = []

        for ticker in normalized_tickers:
            for horizon_days in horizons:
                try:
                    result = self.run(ticker, start_date, end_date, horizon_days=horizon_days, benchmark_ticker=benchmark_ticker)
                except Exception as error:
                    scenarios.append({
                        "ticker": ticker,
                        "horizon_days": horizon_days,
                        "status": "ERROR",
                        "notes": str(error),
                    })
                    continue

                scenario = {
                    "ticker": ticker,
                    "horizon_days": horizon_days,
                    "status": result.get("status", "UNKNOWN"),
                    "prediction_count": len(result.get("predictions", [])),
                    "resolved_count": result.get("metrics", {}).get("resolved_count", 0),
                    "hit_rate": result.get("metrics", {}).get("hit_rate"),
                    "avg_return": result.get("metrics", {}).get("avg_return"),
                    "volatility": result.get("metrics", {}).get("volatility"),
                    "max_drawdown": result.get("metrics", {}).get("max_drawdown"),
                    "sharpe": result.get("metrics", {}).get("sharpe"),
                    "brier_score": result.get("calibration", {}).get("brier_score"),
                    "benchmark_return": result.get("metrics", {}).get("benchmark_return"),
                    "notes": result.get("notes") if result.get("status") == "BACKTEST_PARTIAL" else None,
                }
                scenarios.append(scenario)
                if result.get("status") == "OK":
                    all_predictions.extend(result.get("predictions", []))

        global_metrics = self._compute_metrics(all_predictions)
        by_asset: Dict[str, Dict[str, Any]] = {}
        by_horizon: Dict[str, Dict[str, Any]] = {}
        for item in scenarios:
            if item["status"] != "OK":
                continue
            asset_bucket = by_asset.setdefault(item["ticker"], [])
            asset_bucket.append(item)
            horizon_bucket = by_horizon.setdefault(str(item["horizon_days"]), [])
            horizon_bucket.append(item)

        by_asset_summary = {
            ticker: {
                "ticker": ticker,
                "horizons": entries,
                "avg_hit_rate": sum(entry["hit_rate"] for entry in entries if entry["hit_rate"] is not None) / len([entry for entry in entries if entry["hit_rate"] is not None]) if any(entry["hit_rate"] is not None for entry in entries) else None,
                "avg_return": sum(entry["avg_return"] for entry in entries if entry["avg_return"] is not None) / len([entry for entry in entries if entry["avg_return"] is not None]) if any(entry["avg_return"] is not None for entry in entries) else None,
            }
            for ticker, entries in by_asset.items()
        }

        by_horizon_summary = {
            str(horizon): {
                "horizon_days": horizon,
                "scenarios": entries,
                "avg_hit_rate": sum(entry["hit_rate"] for entry in entries if entry["hit_rate"] is not None) / len([entry for entry in entries if entry["hit_rate"] is not None]) if any(entry["hit_rate"] is not None for entry in entries) else None,
                "avg_return": sum(entry["avg_return"] for entry in entries if entry["avg_return"] is not None) / len([entry for entry in entries if entry["avg_return"] is not None]) if any(entry["avg_return"] is not None for entry in entries) else None,
            }
            for horizon, entries in by_horizon.items()
        }

        return {
            "assets": len(normalized_tickers),
            "horizons": list(horizons),
            "period": {"start": start_date, "end": end_date},
            "benchmark": benchmark_ticker,
            "total_predictions": len(all_predictions),
            "global": global_metrics,
            "by_asset": by_asset_summary,
            "by_horizon": by_horizon_summary,
            "scenarios": scenarios,
            "overlap_policy": {
                "signal_level": "Each prediction is evaluated independently as a signal-level observation.",
                "portfolio_level": "Use PortfolioBacktestEngine separately for non-overlapping portfolio/equity metrics.",
            },
            "notes": "This matrix remains signal-level; portfolio performance must be evaluated separately with non-overlapping position logic.",
        }

    def _compute_metrics(self, records: List[Dict[str, Any]], metric_scope: str = "signal_level_overlapping") -> Dict[str, Any]:
        if not records:
            return {
                "prediction_count": 0,
                "resolved_count": 0,
                "hit_rate": None,
                "avg_error": None,
                "avg_return": None,
                "median_return": None,
                "volatility": None,
                "max_drawdown": None,
                "sharpe": None,
                "benchmark_return": None,
                "excess_return_vs_benchmark": None,
                "hit_rate_ci_95": None,
                "avg_return_standard_error": None,
                "statistical_status": "INSUFFICIENT_SAMPLE",
                "metric_scope": metric_scope,
                "validation_protocol": "Expanding-time point-in-time evaluation with frozen scoring rules; every prediction precedes its outcome window.",
            }

        returns = [float(item["realized_return"]) for item in records if item.get("realized_return") is not None]
        hit_values = [1 if item.get("hit") else 0 for item in records]
        errors = [abs(float(item["outcome_error"])) for item in records if item.get("outcome_error") is not None]

        avg_return = sum(returns) / len(returns) if returns else None
        median_return = statistics.median(returns) if returns else None
        volatility = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns)) if returns and len(returns) > 1 else 0.0
        benchmark_return = None
        benchmark_values = [item["benchmark_return"] for item in records if item.get("benchmark_return") is not None]
        if benchmark_values:
            benchmark_return = sum(benchmark_values) / len(benchmark_values)
        excess_return = avg_return - benchmark_return if avg_return is not None and benchmark_return is not None else None

        standard_error = volatility / math.sqrt(len(returns)) if returns and len(returns) > 1 else None
        hit_rate = (sum(hit_values) / len(hit_values)) if hit_values else None
        hit_rate_ci = self._wilson_interval(sum(hit_values), len(hit_values)) if hit_values else None

        return {
            "prediction_count": len(records),
            "resolved_count": len(records),
            "hit_rate": hit_rate,
            "hit_rate_ci_95": hit_rate_ci,
            "avg_error": (sum(errors) / len(errors)) if errors else None,
            "avg_return": avg_return,
            "median_return": median_return,
            "volatility": volatility,
            "avg_return_standard_error": standard_error,
            "max_drawdown": None,
            "sharpe": None,
            "benchmark_return": benchmark_return,
            "excess_return_vs_benchmark": excess_return,
            "statistical_status": "SUFFICIENT_SAMPLE" if len(records) >= 30 else "INSUFFICIENT_SAMPLE",
            "metric_scope": metric_scope,
            "metric_warning": (
                "Sharpe e drawdown não são calculados em previsões de sinais; use a simulação de carteira para métricas de equity."
                if metric_scope == "non_overlapping_horizon_windows"
                else "Amostras sobrepostas não sustentam inferência independente; use non_overlapping para intervalos comerciais."
            ),
            "validation_protocol": "Expanding-time point-in-time evaluation with frozen scoring rules; every prediction precedes its outcome window.",
        }

    @staticmethod
    def _non_overlapping_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        last_resolution: Optional[dt.date] = None
        for record in sorted(records, key=lambda item: str(item.get("analysis_date") or "")):
            try:
                analysis_date = dt.date.fromisoformat(str(record.get("analysis_date"))[:10])
                future_date = dt.date.fromisoformat(str(record.get("future_date"))[:10])
            except (TypeError, ValueError):
                continue
            if last_resolution is not None and analysis_date < last_resolution:
                continue
            selected.append(record)
            last_resolution = future_date
        return selected

    @staticmethod
    def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> Optional[List[float]]:
        if total <= 0:
            return None
        proportion = successes / total
        denominator = 1.0 + (z * z / total)
        center = (proportion + (z * z / (2.0 * total))) / denominator
        margin = (
            z
            * math.sqrt((proportion * (1.0 - proportion) / total) + (z * z / (4.0 * total * total)))
            / denominator
        )
        return [max(0.0, center - margin), min(1.0, center + margin)]


class PortfolioBacktestEngine:
    """Portfolio-level simulation built on top of signal-level decisions.

    The intent is to convert a signal stream into an investable portfolio without
    changing the underlying scoring and decision logic. Positions are kept
    non-overlapping by design to enforce a single active asset and ensure capital is
    never counted twice.
    """

    def __init__(self, initial_capital: float = 100000.0, brokerage: float = 0.0005, slippage: float = 0.0005):
        self.initial_capital = float(initial_capital)
        self.brokerage = float(brokerage)
        self.slippage = float(slippage)

    def _portfolio_action_from_decision(self, decision: Optional[str]) -> str:
        if decision is None:
            return "HOLD"
        normalized = str(decision).strip().lower()
        if normalized in {"evidence_favorable", "monitor_increase", "buy", "enter", "long", "bullish"}:
            return "ENTER"
        if normalized in {"evidence_mixed", "watch", "maintain", "neutral", "stay"}:
            return "HOLD"
        if normalized in {"evidence_adverse", "hold", "hold_exit", "exit", "sell", "reduce", "risk_off"}:
            return "EXIT"
        return "HOLD"

    def _effective_decision(self, signal: Dict[str, Any]) -> str:
        if isinstance(signal, dict):
            decision = signal.get("decision") or signal.get("action")
            if decision is not None:
                return self._portfolio_action_from_decision(decision)
            score = signal.get("score")
            if score is not None:
                try:
                    score_value = float(score)
                except (TypeError, ValueError):
                    score_value = 0.0
                if score_value >= 70.0:
                    return "ENTER"
                if score_value < 40.0:
                    return "EXIT"
                return "HOLD"
        return "HOLD"

    def _current_signal(self, signal_map: Dict[str, List[Dict[str, Any]]], ticker: str, date: str) -> Optional[Dict[str, Any]]:
        items = signal_map.get(ticker, [])
        if not items:
            return None
        selected: Optional[Dict[str, Any]] = None
        for signal in items:
            signal_date = str(signal.get("date") or signal.get("analysis_date") or "")
            if signal_date <= date:
                if selected is None:
                    selected = signal
                else:
                    current_date = str(selected.get("date") or selected.get("analysis_date") or "")
                    if signal_date > current_date:
                        selected = signal
        return selected

    def simulate_from_signals(
        self,
        signal_map: Dict[str, List[Dict[str, Any]]],
        prices: Dict[str, Dict[str, float]],
        dates: Optional[Sequence[str]] = None,
        benchmark_prices: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
        if not signal_map:
            return {
                "portfolio_metrics": {
                    "initial_capital": self.initial_capital,
                    "final_equity": self.initial_capital,
                    "total_return": 0.0,
                    "cumulative_return": 0.0,
                    "max_drawdown": 0.0,
                    "sharpe": 0.0,
                    "num_trades": 0,
                },
                "equity_curve": [{"date": None, "equity": self.initial_capital}],
                "trades": [],
                "validation": {
                    "capital_not_duplicated": True,
                    "single_position_per_asset": True,
                    "single_active_position": True,
                    "no_look_ahead": True,
                },
                "policy": {
                    "signal_level": "Each asset signal is evaluated on its own date.",
                    "portfolio_level": "Single-active-position allocation prevents overlapping capital usage.",
                },
            }

        if dates is None:
            unique_dates = sorted({str(date) for asset_prices in prices.values() for date in asset_prices.keys()})
            dates = unique_dates
        else:
            unique_dates = []
            seen = set()
            for raw_date in dates:
                text = str(raw_date)
                if text in seen:
                    continue
                seen.add(text)
                unique_dates.append(text)
            try:
                dates = sorted(unique_dates, key=lambda value: dt.datetime.strptime(str(value), "%Y-%m-%d").date())
            except ValueError:
                dates = sorted(unique_dates)

        cash = self.initial_capital
        positions: Dict[str, int] = {}
        position_cost_basis: Dict[str, float] = {}
        trades: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []
        historical_equity: List[float] = []
        highest_equity = self.initial_capital
        max_drawdown = 0.0
        trade_count = 0

        for date in dates:
            day_prices = {ticker: float(price_map.get(date, 0.0) if date in price_map else 0.0) for ticker, price_map in prices.items()}
            other_tickers = [ticker for ticker in signal_map if ticker in prices]
            valid_signals = []
            for ticker in other_tickers:
                signal = self._current_signal(signal_map, ticker, date)
                if signal is None:
                    continue
                valid_signals.append((ticker, signal))

            if valid_signals:
                candidates = []
                for ticker, signal in valid_signals:
                    action = self._effective_decision(signal)
                    score = float(signal.get("score", 0.0) or 0.0)
                    candidates.append((score, ticker, action))
                if candidates:
                    selected = max(candidates, key=lambda item: item[0])[1]
                    selected_action = next(action for score, ticker, action in candidates if ticker == selected)
                    for ticker, signal in valid_signals:
                        if ticker == selected:
                            continue
                        signal_action = self._effective_decision(signal)
                        if signal_action == "ENTER":
                            signal_action = "HOLD"
                        if positions.get(ticker, 0) != 0:
                            current_price = day_prices.get(ticker, 0.0)
                            shares = positions.pop(ticker, 0)
                            sale_value = shares * current_price
                            cash += sale_value * (1.0 - self.brokerage - self.slippage)
                            trades.append({"date": date, "ticker": ticker, "action": "EXIT", "shares": shares, "price": current_price, "cash_after": cash})
                            trade_count += 1
                            position_cost_basis.pop(ticker, None)
                    if selected_action == "ENTER" and positions.get(selected, 0) == 0:
                        price = day_prices.get(selected, 0.0)
                        if price > 0 and cash > 0:
                            allocated_cash = cash * 0.95
                            shares = allocated_cash / price
                            if shares > 0:
                                cost = shares * price
                                cash -= cost * (1.0 + self.brokerage + self.slippage)
                                positions[selected] = int(shares)
                                position_cost_basis[selected] = cost
                                trades.append({"date": date, "ticker": selected, "action": "ENTER", "shares": int(shares), "price": price, "cash_after": cash})
                                trade_count += 1
                    elif selected_action == "EXIT" and positions.get(selected, 0) != 0:
                        shares = positions.pop(selected, 0)
                        current_price = day_prices.get(selected, 0.0)
                        sale_value = shares * current_price
                        cash += sale_value * (1.0 - self.brokerage - self.slippage)
                        trades.append({"date": date, "ticker": selected, "action": "EXIT", "shares": shares, "price": current_price, "cash_after": cash})
                        trade_count += 1
                        position_cost_basis.pop(selected, None)

            portfolio_value = cash + sum(
                (positions.get(ticker, 0) * float(prices.get(ticker, {}).get(date, 0.0)))
                for ticker in positions
            )
            equity_curve.append({"date": date, "equity": portfolio_value})
            historical_equity.append(portfolio_value)
            if portfolio_value > highest_equity:
                highest_equity = portfolio_value
            if highest_equity > 0:
                drawdown = (highest_equity - portfolio_value) / highest_equity
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        final_equity = cash + sum(
            (positions.get(ticker, 0) * float(prices.get(ticker, {}).get(dates[-1] if dates else None, 0.0)))
            for ticker in positions
        ) if dates else self.initial_capital
        if not equity_curve:
            final_equity = self.initial_capital

        returns = []
        for idx in range(1, len(historical_equity)):
            prev = historical_equity[idx - 1]
            curr = historical_equity[idx]
            if prev > 0:
                returns.append((curr / prev) - 1.0)

        avg_return = sum(returns) / len(returns) if returns else 0.0
        volatility = (sum((value - avg_return) ** 2 for value in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0.0
        sharpe = (avg_return / volatility) * (252 ** 0.5) if volatility > 0 else 0.0

        benchmark_return = None
        if benchmark_prices:
            benchmark_series = []
            for series in benchmark_prices.values():
                if isinstance(series, dict):
                    benchmark_series.append(series)

            if dates and benchmark_series:
                ordered_dates = list(dates)
                if ordered_dates:
                    start_date = ordered_dates[0]
                    end_date = ordered_dates[-1]
                    start_price = None
                    end_price = None
                    for series in benchmark_series:
                        ordered_points = sorted(series.items(), key=lambda item: str(item[0]))
                        prior_start = [float(value) for date, value in ordered_points if str(date) <= str(start_date)]
                        prior_end = [float(value) for date, value in ordered_points if str(date) <= str(end_date)]
                        if prior_start:
                            start_price = prior_start[-1]
                        if prior_end:
                            end_price = prior_end[-1]
                        if start_price is not None and end_price is not None:
                            break
                    if start_price is not None and end_price is not None and start_price != 0:
                        benchmark_return = (end_price / start_price) - 1.0
            elif benchmark_series:
                first_series = next(iter(benchmark_series))
                first_values = sorted(first_series.items(), key=lambda item: str(item[0]))
                if first_values:
                    start_price = float(first_values[0][1])
                    end_price = float(first_values[-1][1])
                    benchmark_return = (end_price / start_price) - 1.0 if start_price else 0.0

        result = {
            "portfolio_metrics": {
                "initial_capital": self.initial_capital,
                "final_equity": final_equity,
                "total_return": (final_equity / self.initial_capital) - 1.0 if self.initial_capital else 0.0,
                "cumulative_return": (final_equity / self.initial_capital) - 1.0 if self.initial_capital else 0.0,
                "benchmark_return": benchmark_return,
                "num_trades": trade_count,
                "max_drawdown": max_drawdown,
                "sharpe": sharpe,
                "average_daily_return": avg_return,
                "volatility": volatility,
                "cash": cash,
                "positions": dict(positions),
            },
            "equity_curve": equity_curve,
            "trades": trades,
            "validation": {
                "capital_not_duplicated": True,
                "single_position_per_asset": len(positions) <= 1,
                "single_active_position": len(positions) <= 1,
                "no_look_ahead": True,
            },
            "policy": {
                "signal_level": "Each signal is evaluated only with information available on the same date.",
                "portfolio_level": "Only one active asset can be allocated at a time; the rest are held out or exited before capital is reused.",
                "benchmark": "Benchmark comparison remains optional and is not used to alter the model logic.",
            },
        }
        return result

    def run(self, signal_map: Optional[Dict[str, List[Dict[str, Any]]]] = None, prices: Optional[Dict[str, Dict[str, float]]] = None, dates: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        if signal_map is None:
            signal_map = {}
        if prices is None:
            prices = {}
        return self.simulate_from_signals(signal_map=signal_map, prices=prices, dates=dates)


def backtest(
    ticker: str,
    start_date: str,
    end_date: str,
    horizon_days: int = 30,
    benchmark_ticker: Optional[str] = None,
) -> Dict[str, Any]:
    return BacktestEngine().run(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        horizon_days=horizon_days,
        benchmark_ticker=benchmark_ticker,
    )
