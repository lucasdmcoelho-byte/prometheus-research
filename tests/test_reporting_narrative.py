from prometheus.reporting import (
    _build_catalysts, _build_competitors, _build_expectation_gap,
    _build_growth_narrative, _build_scenarios, _build_valuation_narrative,
    _sector_profile,
)


def test_missing_catalysts_are_not_presented_as_confirmed_events():
    report = {
        "company_name": "ENGIE", "sector_name": "Energia Elétrica",
        "sector_model": {
            "key": "utilities", "label": "Utilities e infraestrutura",
            "drivers": ["reajustes", "demanda"], "risks": ["regulação"],
            "macro_series": ["selic_target", "ipca"],
        },
        "catalyst_result": {"catalysts": []},
    }
    narrative = _build_catalysts(report)
    assert "Nenhum catalisador factual" in narrative
    assert "não são eventos confirmados" in narrative


def test_secondary_news_is_not_promoted_to_confirmed_event():
    report = {"catalyst_result": {"catalysts": [{
        "category": "earnings", "title": "Companhia pode rever guidance",
        "source": "Portal", "published_at": "2026-08-01T12:00:00Z",
        "factual_status": "SECONDARY_REPORT_UNVERIFIED",
    }]}}
    narrative = _build_catalysts(report)
    assert "Relatos secundários ainda não confirmados" in narrative
    assert "Eventos confirmados em fonte primária" not in narrative


def test_reporting_uses_shared_utilities_context_without_oil_assumptions():
    report = {
        "company_name": "ENGIE", "sector_name": "Energia Elétrica",
        "sector_model": {
            "key": "utilities", "label": "Utilities e infraestrutura",
            "drivers": ["reajustes", "demanda"], "risks": ["regulação", "hidrologia"],
            "macro_series": ["selic_target", "ipca"],
        },
    }
    profile = _sector_profile(report)
    assert "regulação" in profile["risk"]
    assert "Brent" not in str(profile)
    assert "fonte primária" in profile["business_model"]


def test_negative_growth_is_described_as_variation_not_growth():
    report = {"financials": {"revenue_growth": {"normalized": -0.10}, "earnings_growth": {"normalized": -0.20}}}
    narrative = _build_growth_narrative(report)
    assert "receita variou -10,0%" in narrative
    assert "lucro variou -20,0%" in narrative
    assert "cresceu -" not in narrative


def test_expectation_gap_does_not_invent_market_consensus():
    narrative = _build_expectation_gap({"final_score": 55.0, "final_state": "NEUTRAL"})
    assert "não afirma expectativas agregadas" in narrative
    assert "revisão do consenso" not in narrative


def test_ev_ebit_reporting_never_labels_the_multiple_as_pe_or_ebitda():
    report = {
        "price": 20.0,
        "valuation": {
            "status": "AVAILABLE", "method": "EV/EBIT",
            "metrics": {"current_ev_ebit": 10.0, "peer_median_ev_ebit": 10.0},
            "scenarios": {
                "bear": {"method": "enterprise_value_to_ebit", "multiple": 8.0, "enterprise_value": 2000.0, "equity_value": 1500.0, "implied_value_per_share": 15.0, "upside_downside": -0.25},
                "base": {"method": "enterprise_value_to_ebit", "multiple": 10.0, "enterprise_value": 2500.0, "equity_value": 2000.0, "implied_value_per_share": 20.0, "upside_downside": 0.0},
                "bull": {"method": "enterprise_value_to_ebit", "multiple": 12.0, "enterprise_value": 3000.0, "equity_value": 2500.0, "implied_value_per_share": 25.0, "upside_downside": 0.25},
            },
        },
        "research": {
            "peer_analysis": {
                "multiple_method": "EV/EBIT", "target_period": "2025-12-31",
                "peers": [
                    {"ticker": "A", "ev_to_ebit": 8.0},
                    {"ticker": "B", "ev_to_ebit": 12.0},
                ],
            },
            "sources": [],
        },
        "claims": [],
    }
    competitors = _build_competitors(report)
    valuation = _build_valuation_narrative(report)
    scenarios = _build_scenarios(report)
    assert "EV/EBIT TTM" in competitors
    assert "EV/EBIT corrente" in valuation
    assert "P/L" not in competitors + valuation
    assert "EBITDA" not in competitors + valuation
    assert "EV R$" in scenarios and "equity R$" in scenarios


def test_rejected_valuation_is_suppressed_from_blocked_pdf_narrative():
    report = {
        "valuation": {
            "status": "AVAILABLE", "method": "P/E",
            "metrics": {"current_pe": 10.0, "peer_median_pe": 12.0},
            "scenarios": {
                name: {"multiple": multiple, "future_eps": 2.0, "implied_value_per_share": 2.0 * multiple, "upside_downside": 0.0}
                for name, multiple in (("bear", 8.0), ("base", 10.0), ("bull", 12.0))
            },
        },
        "editorial_gate": {"status": "BLOCKED", "blockers": [{"code": "VALUATION_FORMULA_MISSING", "detail": "base"}]},
    }
    assert "Valuation não publicado" in _build_valuation_narrative(report)
    assert "Cenários quantitativos indisponíveis" in _build_scenarios(report)


def test_bank_valuation_narrative_discloses_roe_adjustment():
    report = {
        "price": 39.0,
        "valuation": {
            "status": "AVAILABLE", "method": "P/B",
            "metrics": {"current_pb": 1.89, "peer_median_pb": 1.87, "peer_median_roe_adjusted_pb": 1.87},
            "scenarios": {
                "bear": {"implied_value_per_share": 31.0},
                "base": {"implied_value_per_share": 39.0},
                "bull": {"implied_value_per_share": 47.0},
            },
        },
        "research": {"sources": []}, "claims": [],
    }
    assert "ajustada por ROE anualizado" in _build_valuation_narrative(report)
