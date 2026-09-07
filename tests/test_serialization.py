import datetime

from prometheus.pipeline import PrometheusEngine


def test_pipeline_serializes_plain_dates_for_json_delivery():
    payload = {"reference_date": datetime.date(2025, 12, 31)}
    assert PrometheusEngine.__new__(PrometheusEngine)._serialize(payload) == {"reference_date": "2025-12-31"}
