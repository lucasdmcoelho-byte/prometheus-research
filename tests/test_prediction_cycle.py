import datetime
import math

import pandas as pd
import pytest

from prometheus.backtest_engine import (
    BacktestEngine,
    PortfolioBacktestEngine,
    PrometheusPointInTimeSignalProvider,
)
from prometheus.prediction_engine import PredictionEngine
from prometheus.outcome_engine import OutcomeEngine
from prometheus.calibration_engine import CalibrationEngine
from prometheus.models import Prediction, PredictionOutcome, ThesisResult


def test_prediction_generation_from_thesis():
    engine = PredictionEngine()
    thesis = ThesisResult(
        thesis_id="T-1",
        ticker="TEST",
        score=82.0,
        state="BULL",
        direction="BULLISH",
        velocity=1.0,
        acceleration=0.0,
        confidence=0.8,
        age_days=1,
        status="ACTIVE",
        lifecycle="ACTIVE",
        drivers=["fundamental momentum"],
        thesis_breakers=[],
        pricing_status="FAIR",
        pricing_confidence=0.6,
        pricing_details=None,
        evidence=[],
        timestamp=datetime.datetime.utcnow(),
    )
    thesis_scores = {"fundamental": 76.0}
    expectation = {"expectation_gap_score": 60.0}
    preds = engine.generate(thesis, thesis_scores, expectation, [], {})
    ids = [p.metric for p in preds]
    assert "thesis_score" in ids
    assert "score_fundamental" in ids
    assert "expectation_gap" in ids
    expectation_prediction = next(p for p in preds if p.metric == "expectation_gap")
    assert expectation_prediction.threshold == 50.0


def test_outcome_resolution_and_idempotence(monkeypatch):
    outcome = OutcomeEngine()
    # prepare prediction due now
    pred = Prediction(
        prediction_id="p1",
        thesis_id="T-1",
        ticker="TEST",
        metric="score_fundamental",
        operator=">=",
        threshold=50.0,
        horizon_days=0,
        created_at=datetime.datetime.utcnow() - datetime.timedelta(days=2),
        confidence=0.8,
        catalyst=None,
    )

    # monkeypatch fundamental fetch to return normalized value >= threshold
    monkeypatch.setattr("prometheus.outcome_engine.get_fundamental_data", lambda t: {
        "revenue_growth": {"normalized": 0.12},
        "earnings_growth": {"normalized": 0.08},
        "profit_margin": {"normalized": 0.20},
        "roe": {"normalized": 0.15},
        "debt_to_equity": {"normalized": 0.6},
    })

    # resolve first time
    res1 = outcome.resolve(pred)
    assert res1.status in {"CORRECT", "INCORRECT", "PARTIAL"} or res1.status == "INVALID"

    # idempotence: calling again should not raise and should produce same status
    res2 = outcome.resolve(pred)
    assert res1.status == res2.status


def test_historical_outcome_requires_point_in_time_resolver():
    as_of = datetime.datetime(2024, 1, 10)
    pred = Prediction(
        prediction_id="historical",
        thesis_id="T-1",
        ticker="TEST",
        metric="thesis_score",
        operator=">=",
        threshold=50.0,
        horizon_days=1,
        created_at=datetime.datetime(2024, 1, 1),
        confidence=0.8,
        catalyst=None,
    )

    unresolved = OutcomeEngine().resolve(pred, as_of=as_of)
    resolved = OutcomeEngine(metric_resolver=lambda prediction, cutoff: 60.0).resolve(pred, as_of=as_of)

    assert unresolved.status == "INVALID"
    assert "point-in-time" in unresolved.error
    assert resolved.status == "CORRECT"
    assert resolved.resolved_at == as_of


def test_calibration_buckets_and_brier():
    calib = CalibrationEngine(min_sample=2)
    # build fake predictions mapping
    p1 = Prediction(prediction_id="a", thesis_id="T", ticker="T", metric="m", operator=">=", threshold=1, horizon_days=0, created_at=datetime.datetime.utcnow(), confidence=0.9, catalyst=None)
    p2 = Prediction(prediction_id="b", thesis_id="T", ticker="T", metric="m", operator=">=", threshold=1, horizon_days=0, created_at=datetime.datetime.utcnow(), confidence=0.7, catalyst=None)
    p3 = Prediction(prediction_id="c", thesis_id="T", ticker="T", metric="m", operator=">=", threshold=1, horizon_days=0, created_at=datetime.datetime.utcnow(), confidence=0.55, catalyst=None)

    o1 = PredictionOutcome(prediction_id="a", actual_value=2.0, resolved_at=datetime.datetime.utcnow(), status="CORRECT", error=1.0)
    o2 = PredictionOutcome(prediction_id="b", actual_value=0.0, resolved_at=datetime.datetime.utcnow(), status="INCORRECT", error=-1.0)
    o3 = PredictionOutcome(prediction_id="c", actual_value=1.0, resolved_at=datetime.datetime.utcnow(), status="PARTIAL", error=0.0)

    outcomes = [o1, o2, o3]
    preds_map = {"a": p1, "b": p2, "c": p3}

    report = calib.calculate(outcomes, preds_map)
    assert report.total == 3
    assert report.brier_score is not None
    assert isinstance(report.buckets, list)
    assert sum(bucket.sample_size for bucket in report.buckets) == report.total
    assert 0.0 <= report.brier_score <= 1.0


def test_calibration_clamps_confidence_and_keeps_low_confidence_predictions():
    prediction = Prediction(
        prediction_id="low", thesis_id="T", ticker="T", metric="m", operator=">=",
        threshold=1, horizon_days=0, created_at=datetime.datetime.utcnow(), confidence=-20.0, catalyst=None,
    )
    outcome = PredictionOutcome(
        prediction_id="low", actual_value=0.0, resolved_at=datetime.datetime.utcnow(), status="INCORRECT", error=-1.0,
    )

    report = CalibrationEngine(min_sample=1).calculate([outcome], {"low": prediction})

    assert report.total == 1
    assert report.brier_score == 0.0
    assert report.buckets[0].sample_size == 1


def test_prediction_snapshot_is_tracked_in_outcome():
    outcome = OutcomeEngine()
    snapshot = {
        "ticker": "TEST",
        "score": 82.0,
        "state": "BULL",
        "confidence": 0.8,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    pred = Prediction(
        prediction_id="p-snapshot",
        thesis_id="T-1",
        ticker="TEST",
        metric="thesis_score",
        operator=">=",
        threshold=80.0,
        horizon_days=0,
        created_at=datetime.datetime.utcnow() - datetime.timedelta(days=2),
        confidence=0.8,
        catalyst=None,
        snapshot=snapshot,
    )

    resolved = outcome.resolve(pred)
    assert resolved.snapshot is not None
    assert resolved.snapshot["ticker"] == "TEST"
    assert resolved.snapshot["score"] == 82.0


def test_portfolio_action_mapping_and_no_duplicate_capital():
    engine = PortfolioBacktestEngine(initial_capital=100000.0, brokerage=0.0, slippage=0.0)
    assert engine._portfolio_action_from_decision("monitor_increase") == "ENTER"
    assert engine._portfolio_action_from_decision("watch") == "HOLD"
    assert engine._portfolio_action_from_decision("hold") == "EXIT"
    assert engine._portfolio_action_from_decision("evidence_favorable") == "ENTER"
    assert engine._portfolio_action_from_decision("evidence_mixed") == "HOLD"
    assert engine._portfolio_action_from_decision("evidence_adverse") == "EXIT"

    synthetic_signals = {
        "A": [
            {"date": "2024-01-01", "score": 80.0},
            {"date": "2024-01-03", "score": 80.0},
        ],
        "B": [
            {"date": "2024-01-02", "score": 40.0},
        ],
    }
    result = engine.simulate_from_signals(
        signal_map=synthetic_signals,
        prices={
            "A": {"2024-01-01": 100.0, "2024-01-02": 102.0, "2024-01-03": 105.0},
            "B": {"2024-01-01": 50.0, "2024-01-02": 49.0, "2024-01-03": 48.0},
        },
        dates=["2024-01-01", "2024-01-02", "2024-01-03"],
    )
    assert result["portfolio_metrics"]["initial_capital"] == 100000.0
    assert result["portfolio_metrics"]["final_equity"] > 0
    assert result["validation"]["capital_not_duplicated"] is True
    assert result["validation"]["single_position_per_asset"] is True


def test_backtest_generates_historical_predictions(monkeypatch):
    history = pd.DataFrame(
        {
            "Open": [10.0, 10.5, 11.0, 12.0, 13.0],
            "Close": [10.0, 11.0, 10.5, 12.5, 14.0],
        },
        index=pd.to_datetime([
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]),
    )
    monkeypatch.setattr(BacktestEngine, "fetch_history", lambda self, ticker, start_date, end_date: {"status": "OK", "history": history})

    result = BacktestEngine().run("CURY3", "2024-01-01", "2024-01-05", horizon_days=2)
    assert result["status"] == "OK"
    assert result["metrics"]["prediction_count"] > 0
    assert result["predictions"][0]["ticker"] == "CURY3"
    assert result["predictions"][0]["snapshot"]["point_in_time"] is True
    assert result["model_name"] == "MOMENTUM_BASELINE"


def test_backtest_uses_explicit_point_in_time_signal_provider(monkeypatch):
    history = pd.DataFrame(
        {"Open": [10.0, 11.0, 12.0], "Close": [10.0, 11.0, 12.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    monkeypatch.setattr(BacktestEngine, "fetch_history", lambda self, ticker, start_date, end_date: {"status": "OK", "history": history})
    seen = []

    def provider(ticker, analysis_date, context):
        seen.append((analysis_date, context))
        return {"score": 72.0, "state": "BULL", "confidence": 0.65, "model_name": "TEST_PIT"}

    result = BacktestEngine(signal_provider=provider).run("CURY3", "2024-01-01", "2024-01-03", horizon_days=1)

    assert result["model_name"] == "TEST_PIT"
    assert result["predictions"][0]["score"] == 72.0
    assert result["signals_evaluated"] == len(seen)
    assert all("future_close" not in context["market_snapshot"] for _, context in seen)


def test_backtest_preserves_snapshot_and_avoids_look_ahead(monkeypatch):
    history = pd.DataFrame(
        {
            "Open": [90.0, 95.0, 100.0, 101.0, 110.0],
            "Close": [90.0, 95.0, 100.0, 101.0, 110.0],
        },
        index=pd.to_datetime([
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]),
    )
    monkeypatch.setattr(BacktestEngine, "fetch_history", lambda self, ticker, start_date, end_date: {"status": "OK", "history": history})

    engine = BacktestEngine()
    score = engine._signal_score(history, datetime.date(2024, 1, 3))
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0
    assert score < 100.0

    prediction = engine.run("CURY3", "2024-01-01", "2024-01-05", horizon_days=2)
    first = prediction["predictions"][0]
    assert first["snapshot"]["analysis_date"] == "2024-01-01"
    assert "future_close" not in first["snapshot"]["market_snapshot"]
    assert "future_date" not in first["snapshot"]["market_snapshot"]
    assert first["realized_return"] > 0.0


def test_backtest_metrics_and_horizon_resolution(monkeypatch):
    history = pd.DataFrame(
        {
            "Open": [100.0, 100.0, 100.0, 100.0, 100.0],
            "Close": [100.0, 90.0, 110.0, 115.0, 120.0],
        },
        index=pd.to_datetime([
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]),
    )
    monkeypatch.setattr(BacktestEngine, "fetch_history", lambda self, ticker, start_date, end_date: {"status": "OK", "history": history})

    result = BacktestEngine().run("CURY3", "2024-01-01", "2024-01-05", horizon_days=2)
    metrics = result["metrics"]
    assert metrics["prediction_count"] > 0
    assert metrics["hit_rate"] is not None
    assert metrics["avg_return"] is not None
    assert metrics["median_return"] is not None
    assert metrics["volatility"] is not None
    assert metrics["hit_rate_ci_95"] is not None
    assert metrics["hit_rate_ci_95"][0] <= metrics["hit_rate"] <= metrics["hit_rate_ci_95"][1]
    assert metrics["sharpe"] is None
    assert metrics["max_drawdown"] is None
    assert metrics["metric_scope"] == "signal_level_overlapping"
    assert metrics["non_overlapping"]["metric_scope"] == "non_overlapping_horizon_windows"
    assert metrics["non_overlapping"]["prediction_count"] < metrics["prediction_count"]


def test_recent_return_direction_and_previous_close_use_only_past_rows():
    history = pd.DataFrame(
        {"Close": [100.0, 110.0, 121.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    engine = BacktestEngine()
    assert engine._recent_return(history, datetime.date(2024, 1, 3), 5) == pytest.approx(0.21)
    assert engine._previous_close(history, datetime.date(2024, 1, 3)) == 110.0


def test_prometheus_signal_provider_abstains_when_live_editorial_gate_blocks():
    class Decision:
        action = "evidence_favorable"
        confidence = 0.9

    class Engine:
        def evaluate(self, *args, **kwargs):
            return {
                "overall_score": 90, "state": "STRONG", "decision_result": Decision(),
                "report": {
                    "ticker": "CURY3", "company_name": "Cury", "analysis_as_of": "2026-01-01",
                    "research": {"sources": [], "contradiction_matrix": {}},
                    "valuation": {"status": "INSUFFICIENT_DATA"}, "risk": {"x": 1},
                    "financial_history": [1], "sector_model": {"key": "general"},
                    "claims": [], "fundamental_data_quality": {"score": 80},
                    "official_classification": {"status": "INSUFFICIENT_DATA"},
                },
            }

    signal = PrometheusPointInTimeSignalProvider(Engine())(
        "CURY3", datetime.date(2026, 1, 1), {"recent_returns": []},
    )
    assert signal["forecast"] == "no_trade"
    assert "VALUATION_INCOMPLETE" in signal["abstention_reasons"]
    assert "SECTOR_CLASSIFICATION_UNAVAILABLE_POINT_IN_TIME" in signal["abstention_reasons"]


def test_prometheus_signal_provider_runs_point_in_time_peer_valuation(monkeypatch):
    calls = []
    reconciled = []

    class Decision:
        action = "evidence_favorable"
        confidence = 0.9

    class Adapter:
        cvm = object()
        market = object()

    class Engine:
        adapter = Adapter()

        def evaluate(self, *args, **kwargs):
            return {
                "overall_score": 90, "state": "STRONG", "decision_result": Decision(),
                "report": {"ticker": "CURY3", "research": {"sources": []}},
            }

    def enrich(report, adapter, cutoff):
        calls.append(cutoff)
        report["valuation"] = {"status": "AVAILABLE"}
        return report

    def reconcile(self, report):
        reconciled.append((report.get("valuation") or {}).get("status"))
        return {"valuation_reconciliation": {"status": "CONSISTENT"}}

    monkeypatch.setattr("prometheus.automatic_peers.enrich_automatic_peers", enrich)
    monkeypatch.setattr("prometheus.business_quality.BusinessQualityEngine.evaluate", reconcile)
    monkeypatch.setattr("prometheus.backtest_engine.EditorialGate.evaluate", lambda self, report: {
        "status": "APPROVAL_REQUIRED", "blockers": [],
    })
    signal = PrometheusPointInTimeSignalProvider(Engine())(
        "CURY3", datetime.date(2026, 1, 2), {"recent_returns": []},
    )

    assert signal["forecast"] == "positive_return"
    assert signal["decision_action"] == "evidence_favorable"
    assert signal["valuation_status"] == "AVAILABLE"
    assert calls == [datetime.datetime(2026, 1, 2, 23, 59, 59)]
    assert reconciled == ["AVAILABLE"]


def test_backtest_fetches_resolution_window_beyond_analysis_end(monkeypatch):
    requested = []
    history = pd.DataFrame(
        {"Open": [10.0, 11.0], "Close": [10.0, 11.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-12"]),
    )

    def fetch(self, ticker, start_date, end_date):
        requested.append(end_date)
        return {"status": "OK", "history": history}

    monkeypatch.setattr(BacktestEngine, "fetch_history", fetch)
    result = BacktestEngine().run("CURY3", "2024-01-01", "2024-01-01", horizon_days=10)
    assert requested[0] > "2024-01-01"
    assert result["metrics"]["resolved_count"] == 1


def test_portfolio_simulation_orders_dates_and_handles_benchmark():
    engine = PortfolioBacktestEngine(initial_capital=100000.0, brokerage=0.0, slippage=0.0)
    signal_map = {
        "A": [{"date": "2024-01-01", "score": 80.0}, {"date": "2024-01-02", "score": 75.0}],
        "B": [{"date": "2024-01-02", "score": 60.0}],
    }
    prices = {
        "A": {"2024-01-01": 100.0, "2024-01-02": 110.0, "2024-01-03": 120.0},
        "B": {"2024-01-01": 50.0, "2024-01-02": 55.0, "2024-01-03": 60.0},
    }
    benchmark_prices = {
        "IBOV": {"2024-01-01": 100.0, "2024-01-02": 105.0, "2024-01-03": 108.0},
    }

    result = engine.simulate_from_signals(
        signal_map=signal_map,
        prices=prices,
        dates=["2024-01-03", "2024-01-01", "2024-01-02"],
        benchmark_prices=benchmark_prices,
    )

    assert [entry["date"] for entry in result["equity_curve"]] == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert abs(result["portfolio_metrics"]["benchmark_return"] - 0.08) < 1e-9
