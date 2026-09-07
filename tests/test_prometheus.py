import datetime
import json
import os
from pathlib import Path

import pytest

from prometheus.data_engine import get_asset_data, validate_ticker
from prometheus.journal_engine import JournalEngine
from prometheus.knowledge_store import KnowledgeStore
from prometheus.pipeline import PrometheusEngine
from prometheus.thesis_engine import (
    WEIGHTS,
    calculate_score,
    calculate_macro_score,
    calculate_thesis_scores,
    calculate_valuation_score,
    get_state,
)
from prometheus.reporting import _build_narrative
from prometheus.thesis_state_engine import ThesisStateEngine
from prometheus.models import DecisionResult, ThesisBreaker, ThesisEvidence, ThesisResult
from prometheus.decision_engine import DecisionEngine
from prometheus.news_feed import NewsFeed


def test_validate_ticker_normalizes_and_raises():
    assert validate_ticker(" cury3 ") == "CURY3"
    with pytest.raises(ValueError):
        validate_ticker("")


def test_knowledge_store_save_load(tmp_path: Path):
    store = KnowledgeStore()
    store.add({"ticker": "CURY3", "source": "test", "value": 1})
    path = tmp_path / "knowledge.json"
    store.save_to_file(str(path))

    loaded = KnowledgeStore()
    loaded.load_from_file(str(path))
    assert loaded.get_all() == store.get_all()


def test_thesis_score_flow():
    asset_data = {
        "fundamental_score": 60.0,
        "sector_name": "Technology",
        "beta": 1.1,
        "market_cap": 120000000000,
        "price_change_percent": 3.0,
        "fifty_two_week_change": 15.0,
        "valuation_margin": 70.0,
    }
    scores = calculate_thesis_scores(asset_data, news_sentiment=55.0)
    assert scores["fundamental"] == 60.0
    assert scores["sector"] is None
    assert 0.0 <= scores["macro"] <= 100.0
    assert 0.0 <= scores["expectation_gap"] <= 100.0
    assert 0.0 <= scores["momentum_velocity"] <= 100.0
    assert 0.0 <= scores["valuation_margin"] <= 100.0
    assert scores["news_sentiment"] == 55.0

    result = calculate_score(scores)
    assert isinstance(result, float)
    assert 0.0 <= result <= 100.0
    assert get_state(result) in {"STRONG BULL", "BULL", "NEUTRAL", "WEAKENING", "BEAR"}


def test_sector_score_without_peer_history_is_excluded_not_treated_as_neutral():
    scores = {key: 50.0 for key in WEIGHTS}
    scores["sector"] = None
    assert calculate_score(scores) == 50.0


def test_central_thesis_is_stateless_and_sector_specific_across_reports():
    base = {
        "financials": {"revenue_growth": {"normalized": 0.1}, "profit_margin": {"normalized": 0.08}},
        "official_metrics": {"net_debt": {"normalized": 1_000_000}},
        "research_quality": {"overall_research_confidence": 70},
        "valuation": {"status": "INSUFFICIENT_DATA"}, "research": {"peer_analysis": {}},
    }
    real_estate = base | {"ticker": "CURY3", "company_name": "Cury", "sector_model": {"key": "real_estate", "label": "Construção e incorporação"}}
    healthcare = base | {"ticker": "HAPV3", "company_name": "Hapvida Participações", "sector_model": {"key": "healthcare", "label": "Saúde"}}
    cury_text = _build_narrative(real_estate)["central_thesis"]
    hapvida_text = _build_narrative(healthcare)["central_thesis"]
    assert "CURY3" in cury_text
    assert "HAPV3" in hapvida_text
    assert "Cury" not in hapvida_text
    assert "terrenos" not in hapvida_text.lower()


def test_valuation_score_rewards_lower_positive_multiples_and_is_neutral_when_missing():
    assert calculate_valuation_score(7.0) > calculate_valuation_score(14.0)
    assert calculate_valuation_score(28.0) < calculate_valuation_score(14.0)
    assert calculate_valuation_score(None) == 50.0


def test_macro_score_penalizes_high_rates_more_for_rate_sensitive_sector():
    neutral = calculate_macro_score(1.0, 10_000_000_000, selic_rate=8.0, sector_name="Real Estate")
    real_estate = calculate_macro_score(1.0, 10_000_000_000, selic_rate=14.0, sector_name="Real Estate")
    financial = calculate_macro_score(1.0, 10_000_000_000, selic_rate=14.0, sector_name="Financial Services")

    assert real_estate < neutral
    assert real_estate < financial


def test_decision_engine_uses_consistent_zero_to_one_scale():
    engine = DecisionEngine()
    weak = type("Thesis", (), {"score": 10.0, "confidence": 0.5, "evidence": []})()
    strong = type("Thesis", (), {"score": 90.0, "confidence": 0.5, "evidence": []})()

    weak_result = engine.decide(weak, {"risk_score": 0.5, "evidence": []}, 50.0)
    strong_result = engine.decide(strong, {"risk_score": 0.5, "evidence": []}, 50.0)

    assert weak_result.action == "evidence_adverse"
    assert strong_result.action == "evidence_favorable"
    assert "não instrui compra, venda ou manutenção" in strong_result.reasoning.lower()
    assert 0.0 <= weak_result.score <= 1.0
    assert 0.0 <= strong_result.score <= 1.0


def test_news_feed_sentiment_scoring(monkeypatch):
    store = KnowledgeStore()
    feed = NewsFeed(["CURY3"], store)
    # override network fetch to return a stable RSS feed with positive and negative terms
    monkeypatch.setattr(
        feed,
        "_fetch_rss",
        lambda url: (
            """
            <rss><channel>
                <item>
                    <title>Empresa anuncia aumento e recorde de lucro</title>
                    <link>http://example.com/1</link>
                    <pubDate>Wed, 02 Oct 2024 13:00:00 GMT</pubDate>
                </item>
                <item>
                    <title>Crise e queda de receitas abalam as ações</title>
                    <link>http://example.com/2</link>
                    <pubDate>Wed, 02 Oct 2024 14:00:00 GMT</pubDate>
                </item>
            </channel></rss>
            """.encode("utf-8")
        )
    )
    records = feed.collect_once()
    assert len(records) == 2
    assert "sentiment_score" in records[0]
    assert "sentiment" in records[0]


@pytest.mark.parametrize("headline", [
    "Hapvida lucro cai 96% no trimestre",
    "Ação desaba 33% após resultado",
    "ANS bloqueia rescisão de 947 mil beneficiários",
    "Companhia reporta prejuízo e cancelamentos crescentes",
])
def test_news_sentiment_recognizes_material_negative_portuguese_headlines(headline):
    feed = NewsFeed(["HAPV3"], KnowledgeStore())
    assert feed._score_sentiment(headline) < 45.0


def test_get_asset_data_uses_yfinance(monkeypatch):
    fake_info = {
        "regularMarketPrice": 10.0,
        "previousClose": 9.5,
        "marketCap": 120000000000,
        "beta": 1.2,
        "sector": "Technology",
        "industry": "Software",
        "currency": "BRL",
        "longBusinessSummary": "Resumo de teste",
        "revenueGrowth": 0.25,
        "earningsGrowth": 0.2,
        "profitMargins": 0.18,
        "returnOnEquity": 0.22,
        "debtToEquity": 60.0,
        "trailingEps": 2.0,
        "forwardPE": 12.0,
        "trailingPE": 11.5,
        "enterpriseValue": 50000000000,
        "sharesOutstanding": 1000000000,
        "52WeekChange": 0.15,
        "fiftyTwoWeekLow": 7.0,
        "fiftyTwoWeekHigh": 12.0,
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            return fake_info

    import prometheus.data_engine as data_engine

    monkeypatch.setattr(data_engine, "yf", type("YFinanceModule", (), {"Ticker": FakeTicker}))
    asset_data = get_asset_data("CURY3")
    assert asset_data["ticker"] == "CURY3"
    assert asset_data["price"] == 10.0
    assert asset_data["sector_name"] == "Technology"
    assert asset_data["fundamental_score"] >= 0
    assert asset_data["valuation_margin"] >= 0
    assert asset_data["fundamental_data"]["debt_to_equity"]["normalized"] == pytest.approx(0.6)


def test_reporting_uses_real_pipeline_metrics_and_formula(market_data_adapter):
    report = PrometheusEngine(adapter=market_data_adapter).evaluate("CURY3", sentiment_score=51.65, news_items=[], journal_metadata={"source": "test"})["report"]
    narrative = _build_narrative(report)

    assert "receita grew" not in narrative["summary"].lower()
    assert "Fórmula" in narrative["score_breakdown"]
    assert "0.23" in narrative["score_breakdown"]
    assert "0.14" in narrative["score_breakdown"]
    assert "82.45" not in narrative["summary"] or "82.45" in narrative["score_breakdown"]
    assert report["research"]["sources"]
    assert report["research"]["contradiction_matrix"]
    assert all(source.get("publication_date") for source in report["research"]["sources"])
    market_sources = {source["metric"]: source for source in report["research"]["sources"] if source["metric"] in {"price", "market_cap", "shares_outstanding", "enterprise_value"}}
    assert set(market_sources) == {"price", "market_cap", "shares_outstanding", "enterprise_value"}
    assert market_sources["market_cap"]["value"] == 20_000_000_000


def test_pipeline_includes_macro_observation_in_research_sources(market_data_adapter):
    original_fetch = market_data_adapter.fetch

    def fetch_with_macro(ticker, as_of=None):
        raw = original_fetch(ticker, as_of)
        raw["macro_observations"] = [{
            "metric": "selic_target",
            "value": 12.25,
            "unit": "percent_per_year",
            "date": "2025-01-02",
            "publication_date": "2025-01-02",
            "source": "Banco Central do Brasil - SGS",
            "source_url": "https://api.bcb.gov.br/test",
            "series_code": 432,
        }]
        return raw

    market_data_adapter.fetch = fetch_with_macro
    report = PrometheusEngine(adapter=market_data_adapter).evaluate("CURY3")["report"]

    assert report["macro_observations"][0]["value"] == 12.25
    assert any(source["metric"] == "selic_target" for source in report["research"]["sources"])


def test_pipeline_keeps_macro_neutral_when_only_selic_is_not_point_in_time_eligible(market_data_adapter):
    original_fetch = market_data_adapter.fetch

    def fetch_with_future_macro(ticker, as_of=None):
        raw = original_fetch(ticker, as_of)
        raw["macro_observations"] = [{
            "metric": "selic_target", "value": 15.0,
            "unit": "percent_per_year", "date": "2026-08-31",
            "publication_date": "2026-08-31", "source": "Banco Central do Brasil - SGS",
            "point_in_time_eligible": False,
        }]
        return raw

    market_data_adapter.fetch = fetch_with_future_macro
    report = PrometheusEngine(adapter=market_data_adapter).evaluate(
        "CURY3", as_of=datetime.datetime(2026, 8, 30, 23, 59, 59),
    )["report"]
    blocker_details = [item["detail"] for item in report["editorial_gate"]["blockers"]]

    assert report["thesis_scores"]["macro"] == 50.0
    assert report["thesis_scores"]["sector"] is None
    assert "macro" in report["score_availability"]["unavailable_components"]
    assert "sector" in report["score_availability"]["unavailable_components"]
    assert report["score_availability"]["component_status"]["sector"]["status"] == "SECTOR_SCORE_UNAVAILABLE"
    assert "macro_score_non_neutral_without_eligible_macro" not in blocker_details


def test_pipeline_filters_future_news_and_traces_eligible_news(market_data_adapter):
    cutoff = datetime.datetime(2027, 6, 30, 23, 59, 59)
    news = [
        {"title": "Evento conhecido", "published_at": "2027-06-30T12:00:00Z", "source": "Fonte A", "url": "https://example.com/a"},
        {"title": "Evento futuro", "published_at": "2027-07-01T12:00:00Z", "source": "Fonte B", "url": "https://example.com/b"},
        {"title": "Data ausente", "source": "Fonte C"},
    ]
    report = PrometheusEngine(adapter=market_data_adapter).evaluate(
        "CURY3", news_items=news, as_of=cutoff, journal_metadata={"source": "test"}
    )["report"]
    news_sources = [source for source in report["research"]["sources"] if source["metric"] == "news_report"]
    assert [source["value"] for source in news_sources] == ["Evento conhecido"]
    assert news_sources[0]["event_factual_status"] == "SECONDARY_REPORT_UNVERIFIED"
    news_claim = next(claim for claim in report["claims"] if news_sources[0]["source_id"] in claim["source_ids"])
    assert news_claim["classification"] == "FACT"
    assert news_claim["text"] == "Fonte A publicou a manchete: Evento conhecido"


def test_official_disclosure_becomes_confirmed_monitor_without_retroactive_scoring():
    report = {
        "catalyst_result": {"catalysts": [], "catalyst_score": 50},
        "official_disclosures": {"documents": [{
            "category": "Fato Relevante", "subject": "Aquisição concluída",
            "source_url": "https://cvm/doc", "delivered_at": "2026-08-01T12:00:00Z",
            "protocol": "P1", "version": 1, "content_extraction_status": "EXTRACTED",
        }]},
    }
    PrometheusEngine._append_official_catalysts(report)
    catalyst = report["catalyst_result"]["catalysts"][0]
    assert catalyst["factual_status"] == "PRIMARY_CONFIRMED"
    assert catalyst["score_included"] is False
    assert report["catalyst_result"]["catalyst_score"] == 50


def test_thesis_state_engine_advances_lifecycle_with_breakers():
    engine = ThesisStateEngine()
    thesis_result = ThesisResult(
        thesis_id="TEST-2026-08-01-001",
        ticker="TEST",
        score=65.0,
        state="STRENGTHENING",
        direction="BULLISH",
        velocity=2.0,
        acceleration=0.1,
        confidence=0.75,
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
    breakers = [
        ThesisBreaker(
            id="fundamental-weakness",
            name="Fundamental weakness",
            description="Test breaker",
            category="FUNDAMENTAL",
            condition="score<35",
            threshold=35.0,
            current_value=30.0,
            distance_to_threshold=-5.0,
            severity="CRITICAL",
            impact_score=0.75,
            status="TRIGGERED",
            triggered=True,
            evidence=ThesisEvidence(
                claim="Evidence test",
                evidence_type="breaker",
                confidence=0.8,
                details="Details",
                timestamp=datetime.datetime.utcnow(),
            ),
        )
    ]
    updated = engine.apply_breakers(thesis_result, breakers)
    assert updated.lifecycle == "BROKEN"
    assert updated.status == "BROKEN"
    assert updated.thesis_breakers == breakers
