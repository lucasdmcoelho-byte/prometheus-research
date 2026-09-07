import os
import time

from prometheus.cvm_client import CVMOpenDataClient


def test_stale_official_archive_remains_available_when_refresh_fails(tmp_path, monkeypatch):
    client = CVMOpenDataClient(cache_dir=str(tmp_path), cache_ttl_seconds=1)
    url = client.dataset_url("ITR", 2026)
    cached = tmp_path / "itr_cia_aberta_2026.zip"
    cached.write_bytes(b"official-cached-archive")
    old = time.time() - 3600
    os.utime(cached, (old, old))

    attempts = {"count": 0}

    def unavailable(*args, **kwargs):
        attempts["count"] += 1
        raise OSError("network unavailable")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    assert client._download(url) == b"official-cached-archive"
    assert client._download(url) == b"official-cached-archive"
    assert attempts["count"] == 1
