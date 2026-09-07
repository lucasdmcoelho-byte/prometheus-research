import datetime as dt
import zipfile
import pytest

from prometheus.b3_cotahist import build_market_snapshots
from prometheus.adapters import B3COTAHISTAdapter
from prometheus.backtest_engine import BacktestEngine


def _record(date: str, ticker: str, close_cents: int, market_type: str = "010") -> str:
    row = list(" " * 245)
    row[0:2] = "01"
    row[2:10] = date
    row[12:24] = f"{ticker:<12}"
    row[24:27] = market_type
    row[56:69] = f"{close_cents - 10:013d}"
    row[69:82] = f"{close_cents + 20:013d}"
    row[82:95] = f"{close_cents - 20:013d}"
    row[108:121] = f"{close_cents:013d}"
    row[152:170] = f"{1000:018d}"
    return "".join(row)


def test_cotahist_builds_latest_and_previous_official_close_without_lookahead(tmp_path):
    archive = tmp_path / "COTAHIST_A2026.ZIP"
    lines = [
        _record("20260813", "ITUB4", 3826),
        _record("20260814", "ITUB4", 3900),
        _record("20260817", "ITUB4", 3950),
        _record("20260814", "ITUB4F", 3901, market_type="020"),
    ]
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("COTAHIST_A2026.TXT", "\r\n".join(lines).encode("latin-1"))

    snapshots = build_market_snapshots(
        archive, dt.datetime(2026, 8, 17, 23, 59, 59), tickers=("ITUB4",),
        captured_at=dt.datetime(2026, 8, 18, 1, 0),
    )
    row = snapshots["ITUB4"]
    assert row["close"] == 39.0
    assert row["previous_close"] == 38.26
    assert row["effective_at"].startswith("2026-08-14")
    assert row["available_at"].startswith("2026-08-15")
    assert row["captured_at"] == "2026-08-18T01:00:00"
    assert len(row["source_sha256"]) == 64
    assert len(row["record_sha256"]) == 64


def test_cotahist_rejects_conflicting_same_day_records(tmp_path):
    archive = tmp_path / "COTAHIST_A2026.ZIP"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("COTAHIST_A2026.TXT", "\r\n".join([
            _record("20260814", "ITUB4", 3900),
            _record("20260814", "ITUB4", 3901),
        ]).encode("latin-1"))
    with pytest.raises(ValueError, match="Conflicting COTAHIST closes"):
        build_market_snapshots(archive, dt.datetime(2026, 8, 17, 23, 59, 59), tickers=("ITUB4",))


def test_cotahist_adapter_reuses_archive_for_historical_fetch_and_backtest(tmp_path):
    archive = tmp_path / "COTAHIST_A2026.ZIP"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("COTAHIST_A2026.TXT", "\r\n".join([
            _record("20260102", "CURY3", 2000),
            _record("20260105", "CURY3", 2100),
            _record("20260108", "CURY3", 2200),
        ]).encode("latin-1"))

    adapter = B3COTAHISTAdapter(str(archive), tickers=("CURY3",))
    point = adapter.fetch("CURY3", as_of=dt.datetime(2026, 1, 6, 23, 59, 59))
    assert point["info"]["regularMarketPrice"] == 21.0
    assert point["info"]["previousClose"] == 20.0

    history = adapter.history("CURY3", "2026-01-01", "2026-01-10")
    assert history["status"] == "OK"
    assert history["history"].iloc[-1]["Close"] == 22.0
    result = BacktestEngine(history_provider=adapter.history).run(
        "CURY3", "2026-01-02", "2026-01-05", horizon_days=2,
    )
    assert result["metrics"]["resolved_count"] == 2
