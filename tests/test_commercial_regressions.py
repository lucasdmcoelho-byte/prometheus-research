from prometheus.adapters import CVMEnrichedAdapter
from prometheus.reporting import _build_competitors
from prometheus.data_quality import calculate_research_quality
from prometheus.reporting import _build_implicit_expectations_data, _format_source_value, _metric_label, _sector_kpi_status


def test_financial_peer_narrative_uses_price_to_book():
    report = {
        "valuation": {"method": "P/B"},
        "research": {
            "peer_analysis": {
                "target_period": "2026-Q1",
                "peers": [
                    {"ticker": "BBAS3", "price_to_book": 1.1, "trailing_pe": None},
                    {"ticker": "BBDC4", "price_to_book": 1.5, "trailing_pe": None},
                ],
            }
        },
    }

    narrative = _build_competitors(report)

    assert "P/VP" in narrative
    assert "BBAS3 1.1x" in narrative
    assert "Mediana: 1.3x" in narrative


def test_backtest_mode_is_explicit_and_disabled_by_default(tmp_path):
    live = CVMEnrichedAdapter({"TEST3": "1"}, cache_dir=str(tmp_path))
    historical = CVMEnrichedAdapter({"TEST3": "1"}, cache_dir=str(tmp_path), backtest_mode=True)

    assert live.backtest_mode is False
    assert historical.backtest_mode is True


def test_complete_financials_do_not_masquerade_as_complete_research():
    report = {
        "fundamental_data_quality": {"score": 100},
        "research": {"sources": [{
            "metric": "revenue", "value": 10, "unit": "BRL", "period": "2025",
            "publication_date": "2026-03-01", "source": "CVM",
        }], "peer_analysis": {"status": "INSUFFICIENT_DATA"}},
        "financial_history": [{"period": "2025"}],
        "ttm": {"status": "AVAILABLE"},
        "official_disclosures": {"documents": []},
        "reference_form": {"status": "INSUFFICIENT_DATA"},
        "macro_observations": [], "catalyst_result": {"catalysts": []},
        "sector_model": {"kpis": ["VSO"]},
        "valuation": {"status": "INSUFFICIENT_DATA"},
        "business_quality": {"moat": {"status": "UNPROVEN"}, "governance": {"status": "INSUFFICIENT_DATA"}},
    }
    result = calculate_research_quality(report)
    assert result["financial_data_completeness"] == 100
    assert result["qualitative_evidence_coverage"] < 50
    assert result["overall_research_confidence"] < 80


def test_real_estate_kpis_are_explicitly_insufficient_without_official_source():
    report = {
        "sector_model": {"kpis": ["VSO", "lançamentos", "repasses"]},
        "research": {"sources": []},
    }
    rows = _sector_kpi_status(report)
    assert all(row["status"] == "INSUFFICIENT_DATA" for row in rows)
    assert all("document" in row["needed"] or "release" in row["needed"] for row in rows)


def test_combined_health_beneficiaries_never_fill_health_only_kpi_row():
    report = {
        "sector_model": {"kpis": ["beneficiários saúde", "beneficiários saúde e odonto"]},
        "research": {"sources": []},
        "operational_kpis": {"metrics": {
            "beneficiarios_saude": {"status": "INSUFFICIENT_DATA"},
            "beneficiarios_saude_e_odonto": {"status": "AVAILABLE", "value": 5_700_000, "unit": "beneficiaries", "period": "2025-Q3"},
        }},
    }
    rows = _sector_kpi_status(report)
    assert rows[0]["status"] == "INSUFFICIENT_DATA"
    assert rows[1]["status"] == "AVAILABLE"


def test_implicit_expectations_are_mechanical_and_traceable():
    report = {
        "price": 30,
        "valuation": {"method": "P/E", "metrics": {"current_pe": 10, "peer_median_pe": 5, "eps": 3}},
    }
    result = _build_implicit_expectations_data(report)
    assert result["status"] == "AVAILABLE"
    assert result["eps_required_at_peer_median"] == 6
    assert result["required_eps_change"] == 1
    assert "reference_price" in result["formula"]


def test_audit_metric_names_are_human_readable():
    assert _metric_label("history_net_income") == "Histórico - Lucro líquido"
    assert _metric_label("ttm_operating_cash_flow") == "TTM - Fluxo de caixa operacional"
    assert "_" not in _metric_label("net_debt_to_equity")


def test_provider_kpi_units_are_human_readable_in_pdf_tables():
    assert _format_source_value({"value": 13_270, "unit": "beds"}) == "13.270 leitos"
    assert _format_source_value({"value": 784_000, "unit": "patient-days"}) == "784.000 pacientes-dia"
