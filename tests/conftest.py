import datetime

import pytest

from prometheus.models import SourceMetadata


@pytest.fixture
def market_data_adapter():
    class StaticAdapter:
        def fetch(self, ticker, as_of=None):
            return {
                "ticker": ticker,
                "info": {
                    "longName": "Companhia de Teste",
                    "sector": "Industrials",
                    "industry": "Construction",
                    "currency": "BRL",
                    "exchange": "B3",
                    "longBusinessSummary": "Empresa usada em testes determinísticos.",
                    "regularMarketPrice": 12.0,
                    "previousClose": 11.5,
                    "regularMarketChange": 0.5,
                    "regularMarketChangePercent": 4.35,
                    "marketCap": 20_000_000_000,
                    "beta": 1.1,
                    "forwardPE": 10.0,
                    "trailingPE": 11.0,
                    "enterpriseValue": 22_000_000_000,
                    "sharesOutstanding": 1_000_000_000,
                    "dividendYield": 0.03,
                    "52WeekChange": 0.18,
                    "fiftyTwoWeekLow": 8.0,
                    "fiftyTwoWeekHigh": 13.0,
                    "revenueGrowth": 0.18,
                    "earningsGrowth": 0.15,
                    "profitMargins": 0.20,
                    "returnOnEquity": 0.17,
                    "debtToEquity": 70.0,
                },
                "source_metadata": SourceMetadata(
                    source="test",
                    # Fixed historical availability keeps point-in-time tests
                    # deterministic when they evaluate an older cutoff.
                    timestamp=datetime.datetime(2026, 8, 1, 12, 0, 0),
                    publication_date=None,
                    effective_date=None,
                    ticker=ticker,
                    period=None,
                    unit=None,
                    confidence=1.0,
                    revision_status=None,
                ),
            }

    return StaticAdapter()
