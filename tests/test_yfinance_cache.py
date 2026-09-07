from pathlib import Path

import yfinance.cache

from prometheus.adapters import configure_yfinance_cache


def test_yfinance_cache_is_created_and_configured_with_absolute_path(tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(yfinance.cache, "set_cache_location", observed.append)
    configure_yfinance_cache(str(tmp_path))
    expected = (tmp_path / "yfinance").resolve()
    assert expected.is_dir()
    assert observed == [str(expected)]
