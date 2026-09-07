import datetime as dt

from prometheus.cvm_client import CVMOpenDataClient, CVMStatementRow


def test_load_rows_many_groups_codes_and_parses_archive_once(monkeypatch):
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda url: b"zip")
    calls = []
    def parse(**kwargs):
        calls.append(kwargs["cvm_code"])
        return [
            CVMStatementRow(code, code, "DRE", "3.11", "Lucro", 1, "BRL", "UNIDADE", dt.date(2025,12,31), dt.date(2025,1,1), dt.datetime(2026,3,1), "DFP", "url")
            for code in ("1", "2")
        ]
    monkeypatch.setattr(client, "_parse_archive", parse)
    result = client.load_rows_many(["1", "2"], dt.datetime(2026,4,1), filing_types=["DFP"], years=[2025])
    assert len(calls) == 1
    assert set(result) == {"1", "2"}
