import datetime as dt
from types import SimpleNamespace

from prometheus.models import AssetProfile, FinancialStatement, MarketSnapshot, SourceMetadata
from prometheus.pipeline import PrometheusEngine


def _field(value, calculation):
    metadata = SourceMetadata(
        source="CVM", timestamp=dt.datetime(2026, 5, 7), publication_date=dt.datetime(2026, 5, 7),
        effective_date=dt.datetime(2026, 3, 31), ticker="EGIE3", period="2026-03-31", unit="ratio",
        confidence=1.0, revision_status="version 1",
        raw={"url": "https://www.rad.cvm.gov.br/document", "calculation": calculation, "source_sha256": "a" * 64},
    )
    return {"normalized": value, "raw": value, "unit": "ratio", "source_metadata": metadata, "source_field": "test"}


def test_cvm_derived_metrics_are_calculations_with_formula_and_reported_values_are_primary():
    financials = FinancialStatement(
        revenue_growth=_field(0.10, "(current revenue / prior comparable revenue) - 1"),
        earnings_growth=None, profit_margin=None, roe=None, debt_to_equity=None,
        cash_flow=_field(100.0, "reported"), period="2026-03-31",
    )
    market = MarketSnapshot(
        price=None, previous_close=None, price_change=None, price_change_percent=None, market_cap=None,
        beta=None, forward_pe=None, trailing_pe=None, enterprise_value=None, shares_outstanding=None,
        dividend_yield=None, fifty_two_week_change=None, fifty_two_week_low=None, fifty_two_week_high=None,
    )
    research = PrometheusEngine()._build_research(
        ticker="EGIE3",
        asset_profile=AssetProfile("EGIE3", "ENGIE", "Unknown", None, "BRL", "B3", None, "Brazil"),
        financials=financials, market_snapshot=market,
        fundamental_summary={"confidence": 100.0}, thesis_result=SimpleNamespace(drivers=[]),
        risk_result={"evidence": []}, macro_observations=[], news_items=[],
    )
    by_metric = {item["metric"]: item for item in research["sources"]}
    assert by_metric["revenue_growth"]["source_type"] == "calculated"
    assert by_metric["revenue_growth"]["formula"] == "(current revenue / prior comparable revenue) - 1"
    assert by_metric["revenue_growth"]["source_sha256"] == "a" * 64
    assert by_metric["operating_cash_flow"]["source_type"] == "primary"
    assert by_metric["operating_cash_flow"]["formula"] is None
