import pytest

from prometheus.adapters import CVMEnrichedAdapter, YFinanceAdapter
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from prometheus.engines import DataLayer, FeatureEngine, NormalizationLayer, PointInTimeLayer
from prometheus.models import AssetProfile, FinancialStatement, MarketSnapshot, SourceMetadata


def test_yfinance_adapter_fetch_returns_info(monkeypatch):
    dummy_info = {"longName": "Test Co", "sector": "Technology"}

    class DummyTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            return dummy_info

    monkeypatch.setattr("yfinance.Ticker", DummyTicker)

    adapter = YFinanceAdapter()
    result = adapter.fetch("TEST")

    assert result["info"] == dummy_info
    assert result["source_metadata"].source == "yfinance live snapshot"
    assert result["source_metadata"].publication_date is not None


def test_yfinance_adapter_rejects_historical_point_in_time_request():
    adapter = YFinanceAdapter()

    with pytest.raises(ValueError, match="historical data adapter"):
        adapter.fetch("TEST", as_of=datetime.utcnow() - timedelta(days=1))


def test_point_in_time_layer_rejects_data_published_after_cutoff():
    cutoff = datetime(2024, 1, 1)
    metadata = SourceMetadata(
        source="test",
        timestamp=cutoff + timedelta(days=1),
        publication_date=None,
        effective_date=None,
        ticker="TEST",
        period=None,
        unit=None,
        confidence=None,
        revision_status=None,
    )

    with pytest.raises(ValueError, match="exceeds point-in-time cutoff"):
        PointInTimeLayer(as_of=cutoff).filter({"source_metadata": metadata})


def test_point_in_time_layer_validates_field_level_metadata():
    cutoff = datetime(2024, 1, 1)
    current = SourceMetadata("market", cutoff, cutoff, cutoff, "TEST", None, None, 1.0, None)
    future = SourceMetadata("CVM", cutoff, cutoff + timedelta(days=1), cutoff, "TEST", None, None, 1.0, None)

    with pytest.raises(ValueError, match="exceeds point-in-time cutoff"):
        PointInTimeLayer(as_of=cutoff).filter({
            "source_metadata": current,
            "field_metadata": {"revenueGrowth": future},
        })


def test_cvm_enriched_adapter_preserves_field_level_provenance(monkeypatch, tmp_path):
    adapter = CVMEnrichedAdapter({"TEST3": "1234"}, cache_dir=str(tmp_path))
    market_metadata = SourceMetadata(
        source="market",
        timestamp=datetime(2025, 8, 1),
        publication_date=datetime(2025, 8, 1),
        effective_date=datetime(2025, 8, 1),
        ticker="TEST3",
        period="2025-08-01",
        unit="BRL",
        confidence=1.0,
        revision_status=None,
    )
    monkeypatch.setattr(adapter.market, "fetch", lambda ticker, as_of=None: {
        "ticker": ticker,
        "info": {"regularMarketPrice": 10.0},
        "source_metadata": market_metadata,
    })
    monkeypatch.setattr(adapter.cvm, "load_rows", lambda **kwargs: [object()])
    source = SimpleNamespace(
        received_at=datetime(2025, 7, 15),
        reference_date=date(2025, 6, 30),
        version="1",
        source_url="https://dados.cvm.gov.br/documento",
    )

    def metric(value):
        return {
            "normalized": value,
            "unit": "ratio",
            "calculation": "reported",
            "source_rows": [source],
        }

    monkeypatch.setattr("prometheus.adapters.CVMFundamentalSnapshotBuilder.build", lambda self, rows: {
        "status": "AVAILABLE",
        "reference_date": "2025-06-30",
        "metrics": {
            "revenue_growth": metric(0.20),
            "earnings_growth": metric(0.15),
            "profit_margin": metric(0.18),
            "roe": metric(0.22),
            "debt_to_equity": metric(0.70),
            "operating_cash_flow": metric(123_000_000.0),
        },
    })
    monkeypatch.setattr("prometheus.adapters.CVMFundamentalSnapshotBuilder.build_history", lambda self, rows, limit=20: [])
    monkeypatch.setattr("prometheus.adapters.CVMFundamentalSnapshotBuilder.build_ttm", lambda self, rows: {"status": "PARTIAL", "metrics": {}})

    raw = adapter.fetch("TEST3", as_of=datetime.utcnow())
    normalized = NormalizationLayer().normalize(raw)
    financials = FeatureEngine().build_financial_statement(normalized)

    assert financials.debt_to_equity["normalized"] == pytest.approx(0.70)
    assert financials.debt_to_equity["source"] == "CVM"
    assert financials.debt_to_equity["source_metadata"].publication_date == datetime(2025, 7, 15)
    assert financials.cash_flow["normalized"] == 123_000_000.0
    assert financials.cash_flow["source"] == "CVM"
    assert normalized["source_metadata"].source == "market"


def test_feature_engine_builds_asset_profile():
    engine = FeatureEngine()
    normalized = {
        "ticker": "TEST",
        "info": {"longName": "Test Co", "sector": "Tech", "industry": "Software", "currency": "BRL", "exchange": "B3"},
        "source_metadata": None,
    }

    asset = engine.build_asset_profile(normalized)
    assert isinstance(asset, AssetProfile)
    assert asset.ticker == "TEST"
    assert asset.sector == "Tech"


def test_feature_engine_builds_financial_statement():
    engine = FeatureEngine()
    normalized = {
        "ticker": "TEST",
        "info": {
            "revenueGrowth": 0.12,
            "earningsGrowth": 0.1,
            "profitMargins": 0.25,
            "returnOnEquity": 0.15,
            "debtToEquity": 40.0,
        },
        "source_metadata": None,
    }

    financials = engine.build_financial_statement(normalized)
    assert isinstance(financials, FinancialStatement)
    assert financials.revenue_growth["normalized"] == pytest.approx(0.12)
    assert financials.debt_to_equity["normalized"] == pytest.approx(0.4)
    assert financials.debt_to_equity["source_field"] == "debtToEquity"
    assert financials.debt_to_equity["status"] == "VALID"


def test_feature_engine_builds_market_snapshot():
    engine = FeatureEngine()
    normalized = {
        "ticker": "TEST",
        "info": {
            "regularMarketPrice": 42.0,
            "previousClose": 40.5,
            "regularMarketChange": 1.5,
            "regularMarketChangePercent": 3.7,
            "marketCap": 25_000_000_000,
            "beta": 1.2,
            "forwardPE": 15.0,
            "trailingPE": 18.0,
            "enterpriseValue": 120_000_000_000,
            "sharesOutstanding": 600_000_000,
            "dividendYield": 0.025,
            "52WeekChange": 0.45,
            "fiftyTwoWeekLow": 30.0,
            "fiftyTwoWeekHigh": 48.0,
        },
        "source_metadata": None,
    }

    snapshot = engine.build_market_snapshot(normalized)
    assert isinstance(snapshot, MarketSnapshot)
    assert snapshot.price == pytest.approx(42.0)
    assert snapshot.beta == pytest.approx(1.2)
    assert snapshot.fifty_two_week_change == pytest.approx(45.0)
