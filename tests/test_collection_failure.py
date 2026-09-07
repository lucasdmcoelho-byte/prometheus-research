import datetime

from main import build_collection_failure_report


def test_collection_failure_payload_is_explicitly_not_a_research_report():
    result = build_collection_failure_report(
        ["CURY3"], datetime.datetime(2026, 8, 30, 23, 59, 59),
        [{"ticker": "CURY3", "error_type": "OSError", "detail": "network unavailable"}],
    )

    assert result["schema"] == "prometheus.collection_failure.v1"
    assert result["status"] == "DATA_COLLECTION_FAILED"
    assert result["data_source_status"] == "UNAVAILABLE"
    assert result["deliverable"] is False
    assert "tickers" not in result
    assert result["failures"][0]["ticker"] == "CURY3"
