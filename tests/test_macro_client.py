import datetime as dt

from prometheus.macro_client import BCBSeriesClient


def test_bcb_client_filters_observations_after_point_in_time_cutoff(monkeypatch):
    client = BCBSeriesClient()
    monkeypatch.setattr(client, "_download_json", lambda url: [
        {"data": "01/01/2025", "valor": "12,25"},
        {"data": "02/01/2025", "valor": "12.50"},
        {"data": "03/01/2025", "valor": "13.00"},
    ])

    observations = client.fetch(
        432,
        dt.date(2025, 1, 1),
        dt.date(2025, 1, 3),
        as_of=dt.datetime(2025, 1, 2, 23, 59),
    )

    assert [item["value"] for item in observations] == [12.25, 12.5]
    assert all(item["date"] <= "2025-01-02" for item in observations)
    assert observations[0]["source_url"].startswith("https://api.bcb.gov.br/")


def test_bcb_client_reuses_annual_cache(tmp_path, monkeypatch):
    client = BCBSeriesClient(cache_dir=str(tmp_path))
    calls = []

    def download(url):
        calls.append(url)
        return [{"data": "01/01/2024", "valor": "10,00"}]

    monkeypatch.setattr(client, "_download_json", download)
    first = client.fetch(432, dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    second = client.fetch(432, dt.date(2024, 1, 1), dt.date(2024, 1, 2))
    assert first == second
    assert len(calls) == 1


def test_latest_indicators_preserve_series_identity(monkeypatch):
    client = BCBSeriesClient()
    monkeypatch.setattr(client, "fetch", lambda code, start_date, end_date, as_of=None: [{
        "date": "2026-08-01", "value": float(code), "source": "BCB", "source_url": "url",
        "publication_date": "2026-08-01", "series_code": code,
    }])
    rows = client.latest_indicators(dt.datetime(2026, 8, 16), names=["selic_target", "ipca"])
    assert [row["metric"] for row in rows] == ["selic_target", "ipca"]
    assert rows[1]["unit"] == "percent_month"


def test_monthly_macro_without_historical_vintage_is_excluded_from_historical_scoring(monkeypatch):
    client = BCBSeriesClient()
    monkeypatch.setattr(client, "_download_json", lambda url: [
        {"data": "01/01/2025", "valor": "4,50"},
    ])
    rows = client.latest_indicators(dt.datetime(2025, 2, 1), names=["ipca"])
    assert rows[0]["status"] == "INSUFFICIENT_DATA"
    assert rows[0]["point_in_time_eligible"] is False
    assert rows[0]["reference_date"] == "2025-01-01"
    assert "value" not in rows[0]
    assert "historical publication vintage" in rows[0]["reason"]
