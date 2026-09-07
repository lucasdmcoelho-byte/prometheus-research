import datetime as dt

from prometheus.knowledge_store import KnowledgeStore
from prometheus.news_feed import NewsFeed


RSS = b'''<rss><channel><item><title>CURY divulga resultado recorde</title><link>https://news/1</link><pubDate>Fri, 01 Aug 2025 12:00:00 GMT</pubDate><source>Fonte</source></item><item><title>CURY fato relevante futuro</title><link>https://news/2</link><pubDate>Fri, 01 Aug 2027 12:00:00 GMT</pubDate></item></channel></rss>'''


def test_news_cutoff_category_and_materiality(monkeypatch):
    feed = NewsFeed(["CURY3"], KnowledgeStore())
    monkeypatch.setattr(feed, "_fetch_rss", lambda url: RSS)
    rows = feed.collect_ticker("CURY3", as_of=dt.datetime(2026, 1, 1), company_name="Cury")
    assert len(rows) == 1
    assert rows[0]["event_category"] == "results"
    assert rows[0]["materiality"] == "high"
    assert rows[0]["point_in_time_eligible"] is True
    assert rows[0]["event_factual_status"] == "SECONDARY_REPORT_UNVERIFIED"
    assert rows[0]["interpretation"]["kind"] == "DETERMINISTIC_LEXICON_SENTIMENT"
