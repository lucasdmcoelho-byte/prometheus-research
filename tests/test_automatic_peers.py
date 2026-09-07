import datetime as dt
import pytest

from prometheus.automatic_peers import enrich_automatic_peers


class _Market:
    def fetch(self, ticker, as_of=None):
        return {"info": {"trailingPE": {"DIRR3": 8, "MRVE3": 12}.get(ticker, 10)}}


class _CVM:
    def load_rows(self, *args, **kwargs):
        return []


class _Adapter:
    market = _Market(); cvm = _CVM()
    peer_market_cap = staticmethod(lambda ticker, as_of: {"DIRR3": 800, "MRVE3": 1200}.get(ticker, 1000))
    peer_market_cap_record = staticmethod(lambda ticker, as_of: {
        "value": {"DIRR3": 800, "MRVE3": 1200}.get(ticker, 1000),
        "source": "audited market fixture", "source_url": "https://example.test/market",
        "publication_date": "2026-08-16T00:00:00Z",
        "source_sha256": "a" * 64,
    })


def test_automatic_peers_complete_valuation_from_observed_multiples(monkeypatch):
    class Row:
        reference_date = dt.date(2025, 12, 31); period_start = dt.date(2025, 1, 1)
        received_at = dt.datetime(2026, 3, 1); source_url = "https://example.test/cvm"
        source_sha256 = "b" * 64
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build", lambda self, rows: {
        "reference_date": "2025-12-31", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row()]}}
    })
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: {
        "status": "AVAILABLE", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row()]}}
    })
    report = {
        "ticker": "CURY3", "company_name": "Cury", "analysis_as_of": "2026-08-16T00:00:00Z",
        "sector_model": {"key": "real_estate"}, "price": 20, "shares_outstanding": 100,
        "official_metrics": {"net_income": {"normalized": 200, "source_rows": [{"reference_date": "2026-06-30", "period_start": "2026-01-01"}]}, "operating_cash_flow": {"normalized": 180}, "net_debt": {"normalized": 20}},
        "financial_history": [{"reference_date": "2025-12-31"}], "research": {"sources": []},
        "ttm": {"status": "AVAILABLE", "metrics": {"net_income": {"normalized": 400}, "operating_cash_flow": {"normalized": 300}}},
        "risk": {"status": "ok"}, "claims": [], "fundamental_data_quality": {"score": 90},
    }
    result = enrich_automatic_peers(report, _Adapter(), dt.datetime(2026, 8, 16), limit=2)
    assert result["valuation"]["status"] == "AVAILABLE"
    assert result["valuation"]["metrics"]["peer_median_pe"] == 10
    assert result["valuation"]["metrics"]["cash_conversion"] == 0.75
    assert result["valuation"]["cash_conversion_formula"] == "TTM operating_cash_flow / TTM net_income"
    assert result["research"]["peer_analysis"]["selection_method"] == "maintained_sector_universe"
    assert any(claim["classification"] == "ESTIMATE" for claim in result["claims"])
    assert result["editorial_gate"]["claim_audit"]["status"] == "PASS"
    peer_sources = [source for source in result["research"]["sources"] if source.get("metric") == "ttm_pe"]
    assert all(source["source_sha256"] == "a" * 64 for source in peer_sources)
    assert all(source["source_sha256_components"] == ["b" * 64] for source in peer_sources)
    assert not any(
        blocker["code"] == "CVM_RAW_HASH_MISSING" and blocker["detail"] == "ttm_pe"
        for blocker in result["editorial_gate"]["blockers"]
    )


def test_dynamic_peers_from_exact_cvm_activity_replace_static_universe(monkeypatch):
    class DynamicAdapter(_Adapter):
        @staticmethod
        def peer_candidates(ticker, activity_sector, as_of, limit):
            assert ticker == "EGIE3"
            assert activity_sector == "Energia Elétrica"
            return [
                {"ticker": "DIRR3", "cvm_code": "21350", "company": "Peer A", "selection_reason": "Mesmo SETOR_ATIV oficial da CVM; emissor único"},
                {"ticker": "MRVE3", "cvm_code": "20915", "company": "Peer B", "selection_reason": "Mesmo SETOR_ATIV oficial da CVM; emissor único"},
            ][:limit]

    class Row:
        reference_date = dt.date(2025, 12, 31); period_start = dt.date(2025, 1, 1)
        received_at = dt.datetime(2026, 3, 1); source_url = "https://example.test/cvm"
        source_sha256 = "b" * 64
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build", lambda self, rows: {
        "reference_date": "2025-12-31", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row()]}}
    })
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: {
        "status": "AVAILABLE", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row()]}}
    })
    report = {
        "ticker": "EGIE3", "company_name": "Engie", "analysis_as_of": "2026-08-16T00:00:00Z",
        "sector_model": {"key": "utilities"},
        "official_classification": {"status": "AVAILABLE", "sector": "Energia Elétrica"},
        "price": 20, "shares_outstanding": 100,
        "official_metrics": {"net_income": {"normalized": 200, "source_rows": []}, "operating_cash_flow": {"normalized": 180}, "net_debt": {"normalized": 20}},
        "financial_history": [{"period": "2025-12-31"}], "research": {"sources": []},
        "ttm": {"status": "AVAILABLE", "metrics": {"net_income": {"normalized": 400}}},
        "risk": {"status": "ok"}, "claims": [], "fundamental_data_quality": {"score": 90},
    }
    result = enrich_automatic_peers(report, DynamicAdapter(), dt.datetime(2026, 8, 16), limit=2)
    analysis = result["research"]["peer_analysis"]
    assert analysis["selection_method"] == "exact_cvm_activity_sector_unique_issuer"
    assert analysis["target_activity_sector"] == "Energia Elétrica"
    assert [item["ticker"] for item in analysis["peers"]] == ["DIRR3", "MRVE3"]


def test_financial_peers_use_class_price_and_official_capital_for_pb(monkeypatch):
    class Row:
        reference_date = dt.date(2026, 3, 31)
        period_start = None
        received_at = dt.datetime(2026, 5, 1)
        source_url = "https://dados.cvm.gov.br/itr.zip"
        source_sha256 = "b" * 64

    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build", lambda self, rows: {
        "reference_date": "2026-03-31",
        "metrics": {
            "equity": {"normalized": 100, "source_rows": [Row()]},
                "total_assets": {"normalized": 5000, "source_rows": [Row()]},
            "roe": {"normalized": 0.10, "source_rows": [Row()]},
        },
    })
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: {
        "status": "PARTIAL", "metrics": {},
    })

    class FinancialCVM(_CVM):
        @staticmethod
        def load_capital_composition(*args, **kwargs):
            return {
                "status": "AVAILABLE", "shares_outstanding": 10,
                "quantity_scale_status": "VERIFIED", "quantity_scale_multiplier": 1,
                "received_at": dt.datetime(2026, 5, 1),
                "source_url": "https://dados.cvm.gov.br/capital.zip",
                "source_sha256": "c" * 64,
            }

    class FinancialAdapter(_Adapter):
        cvm = FinancialCVM()

        @staticmethod
        def peer_candidates(*args):
            return [
                {"ticker": "BANK3", "cvm_code": "1", "company": "Bank A", "selection_reason": "same sector"},
                {"ticker": "BANK4", "cvm_code": "2", "company": "Bank B", "selection_reason": "same sector"},
            ]

        @staticmethod
        def peer_market_cap_record(ticker, as_of):
            return {"value": None}

        @staticmethod
        def peer_price_record(ticker, as_of):
            return {
                "value": {"BANK3": 20, "BANK4": 30}[ticker],
                "source": "audited historical price", "source_url": "https://example.test/price",
                "publication_date": "2026-04-01T00:00:00Z", "source_sha256": "a" * 64,
            }

    report = {
        "ticker": "ITUB4", "company_name": "Itau", "analysis_as_of": "2026-07-29T23:59:59Z",
        "sector_model": {"key": "financial"}, "official_classification": {"sector": "Bancos"},
        "price": 20, "shares_outstanding": 100,
        "official_metrics": {"equity": {"normalized": 1000}, "total_assets": {"normalized": 10_000}, "roe": {"normalized": 0.10}},
        "financial_history": [{"period": "2026-03-31"}], "research": {"sources": []},
        "ttm": {"status": "PARTIAL", "metrics": {"net_income": {"normalized": 100}}},
        "risk": {"status": "ok"}, "claims": [], "fundamental_data_quality": {"score": 90},
    }
    result = enrich_automatic_peers(report, FinancialAdapter(), dt.datetime(2026, 7, 29, 23, 59, 59), limit=2)
    analysis = result["research"]["peer_analysis"]
    assert analysis["multiple_method"] == "P/B adjusted by annualized ROE"
    assert analysis["eligible_multiple_count"] == 2
    assert [row["roe_adjusted_price_to_book"] for row in analysis["peers"]] == pytest.approx([2.0, 3.0])
    assert all(row["multiple_formula"] == "price / (equity / shares_outstanding)" for row in analysis["peers"])
    sources = [source for source in result["research"]["sources"] if source.get("metric") == "price_to_book"]
    assert all(source["source_sha256"] == "a" * 64 for source in sources)
    assert all(source["source_sha256_components"] == ["b" * 64, "c" * 64] for source in sources)
    assert result["valuation"]["status"] == "AVAILABLE"


def test_incompatible_or_non_ttm_peers_never_enter_valuation(monkeypatch):
    class Row:
        period_start = dt.date(2026, 1, 1)
        received_at = dt.datetime(2026, 8, 1)
        source_url = "https://example.test/cvm"
        source_sha256 = "b" * 64

        def __init__(self, reference_date):
            self.reference_date = reference_date

    class SnapshotBuilder:
        calls = 0

    snapshots = iter([
        {"reference_date": "2026-06-30", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row(dt.date(2026, 6, 30))]}}},
        {"reference_date": "2026-03-31", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row(dt.date(2026, 3, 31))]}}},
    ])
    ttms = iter([
        {"status": "AVAILABLE", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row(dt.date(2026, 6, 30))]}}},
        {"status": "INSUFFICIENT_DATA", "metrics": {}},
    ])
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build", lambda self, rows: next(snapshots))
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: next(ttms))

    class Adapter(_Adapter):
        @staticmethod
        def peer_candidates(*args):
            return [
                {"ticker": "DIRR3", "cvm_code": "21350", "company": "A", "selection_reason": "same sector"},
                {"ticker": "MRVE3", "cvm_code": "20915", "company": "B", "selection_reason": "same sector"},
            ]

    report = {
        "ticker": "CURY3", "company_name": "Cury", "analysis_as_of": "2026-08-16T00:00:00Z",
        "sector_model": {"key": "real_estate"}, "official_classification": {"sector": "Construção"},
        "price": 20, "shares_outstanding": 100, "market_cap": 2000,
        "official_metrics": {"net_income": {"normalized": 100}, "operating_cash_flow": {"normalized": 90}},
        "financial_history": [{"period": "2026-06-30"}], "research": {"sources": []},
        "ttm": {"status": "AVAILABLE", "metrics": {"net_income": {"normalized": 400}}},
        "risk": {"status": "ok"}, "claims": [{"claim_id": "L", "classification": "LIMITATION", "text": "x", "source_ids": []}],
        "fundamental_data_quality": {"score": 90},
    }
    result = enrich_automatic_peers(report, Adapter(), dt.datetime(2026, 8, 16), limit=2)
    analysis = result["research"]["peer_analysis"]
    assert analysis["eligible_multiple_count"] == 1
    assert analysis["status"] == "INSUFFICIENT_DATA"
    assert result["valuation"]["status"] != "AVAILABLE"
    excluded = next(item for item in analysis["peers"] if item["ticker"] == "MRVE3")
    assert "INCOMPATIBLE_PERIOD" in excluded["exclusion_reasons"]
    assert "NON_TTM_EARNINGS" in excluded["exclusion_reasons"]


def test_single_class_peers_derive_market_cap_from_b3_price_and_verified_cvm_shares(monkeypatch):
    class Row:
        reference_date = dt.date(2026, 3, 31)
        period_start = dt.date(2026, 1, 1)
        received_at = dt.datetime(2026, 5, 1)
        source_url = "https://dados.cvm.gov.br/itr.zip"
        source_sha256 = "b" * 64

    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build", lambda self, rows: {
        "reference_date": "2026-03-31",
        "metrics": {
            "total_assets": {"normalized": 1000, "source_rows": [Row()]},
            "net_debt": {"normalized": 20, "source_rows": [Row()]},
        },
    })
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: {
        "status": "AVAILABLE",
        "metrics": {"operating_income": {"normalized": 50, "source_rows": [Row()]}},
    })

    class UtilityCVM(_CVM):
        @staticmethod
        def load_capital_composition(cvm_code, *args, **kwargs):
            return {
                "status": "AVAILABLE", "shares_outstanding": 10, "single_class": True,
                "quantity_scale_status": "CONSERVATIVE_FALLBACK" if cvm_code == "0" else "VERIFIED",
                "quantity_scale_multiplier": 1,
                "received_at": dt.datetime(2026, 5, 1),
                "source_url": "https://dados.cvm.gov.br/capital.zip", "source_sha256": "c" * 64,
            }

    class UtilityAdapter(_Adapter):
        cvm = UtilityCVM()

        @staticmethod
        def peer_candidates(*args):
            return [
                {"ticker": "DEAD3", "cvm_code": "0", "company": "Unavailable", "selection_reason": "same sector"},
                {"ticker": "UTIL3", "cvm_code": "1", "company": "Utility A", "selection_reason": "same sector"},
                {"ticker": "POWR3", "cvm_code": "2", "company": "Utility B", "selection_reason": "same sector"},
            ]

        @staticmethod
        def peer_market_cap_record(ticker, as_of):
            return {"value": None}

        @staticmethod
        def peer_price_record(ticker, as_of):
            return {
                "value": {"DEAD3": 25, "UTIL3": 20, "POWR3": 30}[ticker], "source": "B3 COTAHIST oficial",
                "source_url": "https://b3.example/cotahist.zip", "publication_date": "2026-04-01T00:00:00Z",
                "source_sha256": "a" * 64,
            }

    report = {
        "ticker": "EGIE3", "company_name": "Engie", "analysis_as_of": "2026-07-29T23:59:59Z",
        "sector_model": {"key": "utilities"}, "official_classification": {"sector": "Energia Elétrica"},
        "price": 40, "shares_outstanding": 100,
        "official_metrics": {"total_assets": {"normalized": 1000}, "net_debt": {"normalized": 100}},
        "financial_history": [{"period": "2026-03-31"}], "research": {"sources": []},
        "ttm": {"status": "AVAILABLE", "metrics": {"operating_income": {"normalized": 500}}},
        "risk": {"status": "ok"}, "claims": [], "fundamental_data_quality": {"score": 90},
    }
    result = enrich_automatic_peers(report, UtilityAdapter(), dt.datetime(2026, 7, 29, 23, 59, 59), limit=2)
    peers = result["research"]["peer_analysis"]["peers"]
    assert {row["ticker"]: row["market_cap"] for row in peers} == {"UTIL3": 200.0, "POWR3": 300.0}
    assert all(row["market_cap_formula"] == "price * shares_outstanding" for row in peers)
    assert {row["ticker"]: row["ev_to_ebit"] for row in peers} == pytest.approx({"UTIL3": 4.4, "POWR3": 6.4})
    assert result["valuation"]["status"] == "AVAILABLE"


def test_peer_failure_preserves_sanitized_bounded_diagnostic(monkeypatch):
    report = {
        "ticker": "CURY3", "analysis_as_of": "2026-08-16T00:00:00Z",
        "sector_model": {"key": "real_estate"},
        "official_metrics": {"total_assets": {"normalized": 1000}},
        "research": {"sources": []}, "claims": [],
    }

    class BrokenCVM(_CVM):
        def load_rows_many(self, *args, **kwargs):
            return {}

        def load_rows(self, *args, **kwargs):
            raise ValueError("first line\n" + "x" * 400)

    class BrokenAdapter(_Adapter):
        cvm = BrokenCVM()

    result = enrich_automatic_peers(report, BrokenAdapter(), dt.datetime(2026, 8, 16), limit=2)
    row = result["research"]["peer_analysis"]["peers"][0]

    assert row["status"] == "UNAVAILABLE"
    assert row["reason"] == "ValueError"
    assert row["error_detail"].startswith("first line ")
    assert "\n" not in row["error_detail"]
    assert len(row["error_detail"]) == 240


def test_real_estate_peer_scale_uses_assets_instead_of_circular_market_value(monkeypatch):
    class Row:
        reference_date = dt.date(2026, 6, 30)
        period_start = dt.date(2026, 1, 1)
        received_at = dt.datetime(2026, 8, 1)
        source_url = "https://dados.cvm.gov.br/itr.zip"
        source_sha256 = "b" * 64

    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build", lambda self, rows: {
        "reference_date": "2026-06-30",
        "metrics": {"total_assets": {"normalized": 1100, "source_rows": [Row()]}},
    })
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: {
        "status": "AVAILABLE", "metrics": {"net_income": {"normalized": 100, "source_rows": [Row()]}},
    })

    class Adapter(_Adapter):
        @staticmethod
        def peer_market_cap_record(ticker, as_of):
            return {
                "value": 100, "source": "audited market fixture", "source_url": "https://example.test/market",
                "publication_date": "2026-08-01T00:00:00Z", "source_sha256": "a" * 64,
            }

    report = {
        "ticker": "CURY3", "analysis_as_of": "2026-08-16T00:00:00Z",
        "sector_model": {"key": "real_estate"}, "market_cap": 1000,
        "official_metrics": {
            "total_assets": {"normalized": 1000},
            "net_income": {"normalized": 200, "source_rows": [Row()]},
        },
        "ttm": {"status": "AVAILABLE", "metrics": {"net_income": {"normalized": 200}}},
        "research": {"sources": []}, "claims": [],
    }
    result = enrich_automatic_peers(report, Adapter(), dt.datetime(2026, 8, 16), limit=2)
    analysis = result["research"]["peer_analysis"]

    assert analysis["scale_policy"] == "total_assets"
    assert all(row["scale_basis"] == "total_assets" for row in analysis["peers"])
    assert all("INCOMPARABLE_SCALE_OVER_4X" not in row["exclusion_reasons"] for row in analysis["peers"])


def test_capital_intensive_sector_uses_traceable_ev_ebit(monkeypatch):
    class Row:
        reference_date = dt.date(2025, 12, 31)
        period_start = dt.date(2025, 1, 1)
        received_at = dt.datetime(2026, 3, 1)
        source_url = "https://example.test/cvm"

    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build", lambda self, rows: {
        "reference_date": "2025-12-31",
        "metrics": {
            "net_income": {"normalized": 100, "source_rows": [Row()]},
            "net_debt": {"normalized": 200, "source_rows": [Row()]},
            "total_assets": {"normalized": 2000, "source_rows": [Row()]},
        },
    })
    monkeypatch.setattr("prometheus.automatic_peers.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: {
        "status": "AVAILABLE",
        "metrics": {
            "net_income": {"normalized": 100, "source_rows": [Row()]},
            "operating_income": {"normalized": 100, "source_rows": [Row()]},
        },
    })

    class CapitalAdapter(_Adapter):
        @staticmethod
        def peer_candidates(*args):
            return [
                {"ticker": "DIRR3", "cvm_code": "21350", "company": "Peer A", "selection_reason": "same exact sector"},
                {"ticker": "MRVE3", "cvm_code": "20915", "company": "Peer B", "selection_reason": "same exact sector"},
            ]

    report = {
        "ticker": "EGIE3", "company_name": "Engie", "analysis_as_of": "2026-08-16T00:00:00Z",
        "sector_model": {"key": "utilities"}, "official_classification": {"sector": "Energia Elétrica"},
        "price": 20, "shares_outstanding": 100,
        "official_metrics": {
            "net_debt": {"normalized": 500}, "total_assets": {"normalized": 5000},
        },
        "financial_history": [{"period": "2025-12-31"}], "research": {"sources": []},
        "ttm": {"status": "AVAILABLE", "metrics": {
            "operating_income": {"normalized": 250}, "net_income": {"normalized": 200},
        }},
        "risk": {"status": "ok"}, "claims": [], "fundamental_data_quality": {"score": 90},
    }
    result = enrich_automatic_peers(report, CapitalAdapter(), dt.datetime(2026, 8, 16), limit=2)
    valuation = result["valuation"]
    analysis = result["research"]["peer_analysis"]
    assert analysis["multiple_method"] == "EV/EBIT"
    assert analysis["eligible_multiple_count"] == 2
    assert all(row["multiple_formula"] == "(market_cap + net_debt) / TTM_operating_income" for row in analysis["peers"])
    assert valuation["status"] == "AVAILABLE"
    assert valuation["method"] == "EV/EBIT"
    assert valuation["target_basis_formula"].startswith("TTM operating income")
    assert "target_income_annualization_factor" not in valuation
    assert valuation["scenarios"]["base"]["formula"] == "(ttm_ebit * scenario_multiple - net_debt) / shares"
