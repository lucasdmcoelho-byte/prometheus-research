from prometheus.sector_models import resolve_sector_model
from prometheus.valuation_engine import ValuationEngine
from prometheus.technical_engine import TechnicalEngine
from prometheus.peer_universe import benchmark_for_ticker


def test_sector_model_resolves_company_context_and_benchmark():
    model = resolve_sector_model("Real Estate", "Development")
    assert model.key == "real_estate"
    assert model.benchmark == "XFIX11"
    assert "VSO" in model.kpis


def test_sector_model_falls_back_without_specialized_claims():
    model = resolve_sector_model("Unknown", "Unknown")
    assert model.key == "general"
    assert model.benchmark == "BOVA11"


def test_healthcare_model_exposes_clinical_and_reimbursement_risks():
    model = resolve_sector_model("Healthcare", "Biotechnology")
    assert model.key == "healthcare"
    assert "validade clínica" in model.risks
    assert model.benchmark is None


def test_technical_indicators_are_deterministic_and_non_prescriptive():
    rows = [{"close": 100 + index, "volume": 1000 + index} for index in range(60)]
    result = TechnicalEngine().evaluate(rows)
    assert result["status"] == "AVAILABLE"
    assert result["trend_context"] == "UP"
    assert "não define entrada" in result["interpretation_policy"]


def test_sector_benchmark_is_automatic_for_known_ticker():
    assert benchmark_for_ticker("CURY3") == "XFIX11"


def test_valuation_requires_explicit_multiple_or_peers():
    result = ValuationEngine().evaluate(20.0, 100.0, 200.0, 180.0, 50.0)
    assert result["status"] == "PARTIAL"
    assert result["scenarios"] == {}


def test_valuation_scenarios_reconcile_to_explicit_assumptions():
    result = ValuationEngine().evaluate(
        price=20.0,
        shares=100.0,
        net_income=200.0,
        operating_cash_flow=180.0,
        net_debt=50.0,
        assumptions={"base_pe": 12.0, "bear_pe": 9.0, "bull_pe": 15.0, "earnings_growth": 0.10, "horizon_years": 1, "assumption_source": "Analyst scenario TEST-1"},
    )
    assert result["status"] == "AVAILABLE"
    assert result["metrics"]["eps"] == 2.0
    assert result["scenarios"]["base"]["implied_value_per_share"] == 26.4
    assert result["assumptions"]["base_pe"] == 12.0
    assert result["scenarios"]["base"]["formula"] == "future_eps * scenario_multiple"


def test_financial_sector_book_value_valuation_is_explicit():
    result = ValuationEngine().evaluate_book_value(20, 100, 1000, peer_multiples=[1.5, 2.0, 2.5])
    assert result["status"] == "AVAILABLE"
    assert result["method"] == "P/B"
    assert result["scenarios"]["base"]["implied_value_per_share"] == 20


def test_valuation_rejects_unordered_or_unattributed_assumptions():
    engine = ValuationEngine()
    missing_source = engine.evaluate(20, 100, 200, 180, 50, assumptions={"base_pe": 10})
    assert missing_source["status"] == "PARTIAL"
    unordered = engine.evaluate(
        20, 100, 200, 180, 50,
        assumptions={"base_pe": 10, "bear_pe": 12, "bull_pe": 8, "assumption_source": "TEST"},
    )
    assert unordered["status"] == "INSUFFICIENT_DATA"


def test_valuation_rejects_non_positive_price_or_ttm_income():
    engine = ValuationEngine()
    assert engine.evaluate(0, 100, 200, 180, 50, assumptions={"base_pe": 10, "assumption_source": "TEST"})["status"] == "INSUFFICIENT_DATA"
    assert engine.evaluate(20, 100, -1, 180, 50, assumptions={"base_pe": 10, "assumption_source": "TEST"})["status"] == "INSUFFICIENT_DATA"


def test_ev_ebit_valuation_reconciles_enterprise_and_equity_values():
    result = ValuationEngine().evaluate_ev_ebit(
        price=20.0,
        shares=100.0,
        ttm_ebit=250.0,
        net_debt=500.0,
        peer_multiples=[8.0, 10.0, 12.0],
        assumptions={"assumption_source": "Eligible point-in-time peer median"},
    )
    assert result["status"] == "AVAILABLE"
    assert result["method"] == "EV/EBIT"
    assert result["metrics"]["current_enterprise_value"] == 2500.0
    assert result["metrics"]["current_ev_ebit"] == 10.0
    base = result["scenarios"]["base"]
    assert base["enterprise_value"] == 2500.0
    assert base["equity_value"] == 2000.0
    assert base["implied_value_per_share"] == 20.0
    assert base["input_values"] == {
        "ttm_ebit": 250.0, "scenario_multiple": 10.0,
        "net_debt": 500.0, "shares": 100.0,
    }
    assert "EV/EBIT não é EV/EBITDA" in result["limitations"][0]


def test_ev_ebit_valuation_requires_two_peers_and_positive_equity_value():
    engine = ValuationEngine()
    one_peer = engine.evaluate_ev_ebit(20, 100, 250, 500, peer_multiples=[10])
    assert one_peer["status"] == "PARTIAL"
    excessive_debt = engine.evaluate_ev_ebit(20, 100, 10, 1000, peer_multiples=[8, 10])
    assert excessive_debt["status"] == "INSUFFICIENT_DATA"
    assert "non_positive_bear_equity_value" in excessive_debt["missing"]


def test_dcf_requires_attributed_multi_year_assumptions_and_reconciles_scenarios():
    engine = ValuationEngine()
    missing = engine.evaluate_dcf(20, 100, 200, 50, [0.1, 0.08, 0.06], 0.12, 0.04)
    assert missing["status"] == "PARTIAL"
    result = engine.evaluate_dcf(
        20, 100, 200, 50, [0.1, 0.08, 0.06], 0.12, 0.04,
        assumptions={"assumption_source": "documented analyst assumptions"},
    )
    assert result["status"] == "AVAILABLE"
    assert set(result["scenarios"]) == {"bear", "base", "bull"}
    assert result["scenarios"]["bear"]["implied_value_per_share"] <= result["scenarios"]["base"]["implied_value_per_share"] <= result["scenarios"]["bull"]["implied_value_per_share"]


def test_multiple_history_statistics_requires_sufficient_observations():
    engine = ValuationEngine()
    assert engine.multiple_history_stats(10, [8, 9])["status"] == "INSUFFICIENT_DATA"
    stats = engine.multiple_history_stats(10, [6, 7, 8, 9, 10, 11, 12, 13])
    assert stats["status"] == "AVAILABLE"
    assert stats["percentile"] == 62.5
