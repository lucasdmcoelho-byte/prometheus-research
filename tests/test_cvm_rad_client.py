import datetime as dt
import json
import hashlib
import urllib.parse

import pytest

from prometheus.cvm_client import CVMFundamentalSnapshotBuilder, CVMOpenDataClient, CVMRADStatementClient, CVMStatementRow


def _index(tmp_path):
    payload = {
        "schema_version": 1,
        "documents": [
            {
                "cvm_code": "17329", "company_name": "ENGIE", "filing_type": "DFP",
                "reference_date": "2025-12-31", "received_at": "2026-02-25T18:08:40",
                "version": "1", "sequence": "154900", "status": "INACTIVE",
                "protocol": "017329DFP311220250100154900-79",
            },
            {
                "cvm_code": "17329", "company_name": "ENGIE", "filing_type": "DFP",
                "reference_date": "2025-12-31", "received_at": "2026-03-06T14:19:24",
                "version": "2", "sequence": "155137", "status": "ACTIVE",
                "protocol": "017329DFP311220250200155137-61",
            },
        ],
    }
    (tmp_path / "rad_document_index.json").write_text(json.dumps(payload), encoding="utf-8")


def _table(statement, current):
    accounts = {
        "2": [("1", "Ativo Total", 10_000)],
        "3": [("2.03", "Patrimônio Líquido", 4_000)],
        "4": [
            ("3.01", "Receita de Venda de Bens e/ou Serviços", current),
            ("3.03", "Resultado Bruto", 600),
            ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", 500),
            ("3.11", "Lucro/Prejuízo Consolidado do Período", 300),
        ],
        "99": [("6.01", "Caixa Líquido Atividades Operacionais", 450)],
    }[statement]
    rows = "".join(f"<tr><td>{code}</td><td>{name}</td><td>{value:,}</td><td>0</td></tr>".replace(",", ".") for code, name, value in accounts)
    return ("<table><tr><th>Conta</th><th>Descrição</th><th>01/01/2025 a 31/12/2025</th><th>01/01/2024 a 31/12/2024</th></tr>" + rows + "</table>").encode()


def _transport(url, headers):
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    sequence = query.get("NumeroSequencialDocumento")
    if "frmGerenciaPaginaFRE" in url:
        return (
            "<script>window.frames[0].location='frmDemonstracaoFinanceiraITR.aspx?Informacao=2&amp;Demonstracao=4&amp;Periodo=0&amp;NomeTipoDocumento=DFP&amp;NumeroSequencialDocumento="
            + sequence + "&amp;Hash=signed';</script>"
        ).encode()
    current = 1_000 if sequence == "154900" else 1_200
    return _table(query["Demonstracao"], current)


def test_rad_client_selects_latest_version_available_at_cutoff(tmp_path):
    _index(tmp_path)
    client = CVMRADStatementClient(str(tmp_path), transport=_transport)
    before_revision = client.load_rows("17329", dt.datetime(2026, 3, 1), ("DFP",), (2025,))
    after_revision = client.load_rows("17329", dt.datetime(2026, 3, 7), ("DFP",), (2025,))
    assert next(row for row in before_revision if row.account_code == "3.01").normalized_value == 1_000_000
    assert next(row for row in after_revision if row.account_code == "3.01").normalized_value == 1_200_000
    assert {row.version for row in before_revision} == {"1"}
    assert {row.version for row in after_revision} == {"2"}
    assert {row.protocol for row in after_revision} == {"017329DFP311220250200155137-61"}
    comparative = next(row for row in after_revision if row.account_code == "3.01" and row.exercise_order == "PENULTIMO")
    assert comparative.reference_date == dt.date(2024, 12, 31)
    assert comparative.source_sha256 == hashlib.sha256(_table("4", 1_200)).hexdigest()


def test_rad_rows_feed_the_same_annual_ttm_builder(tmp_path):
    _index(tmp_path)
    rows = CVMRADStatementClient(str(tmp_path), transport=_transport).load_rows(
        "17329", dt.datetime(2026, 3, 7), ("DFP",), (2025,)
    )
    ttm = CVMFundamentalSnapshotBuilder().build_ttm(rows)
    assert ttm["status"] == "AVAILABLE"
    assert ttm["method"] == "reported_annual"
    assert ttm["metrics"]["revenue"]["normalized"] == 1_200_000
    assert ttm["metrics"]["operating_cash_flow"]["normalized"] == 450_000


def test_rad_client_blocks_documents_published_after_cutoff(tmp_path):
    _index(tmp_path)
    rows = CVMRADStatementClient(str(tmp_path), transport=_transport).load_rows(
        "17329", dt.datetime(2026, 2, 20), ("DFP",), (2025,)
    )
    assert rows == []


def test_rad_document_requires_signed_structured_url(tmp_path):
    _index(tmp_path)
    client = CVMRADStatementClient(str(tmp_path), transport=lambda url, headers: b"<html>missing</html>")
    with pytest.raises(ValueError, match="signed statement URL missing"):
        client.load_rows("17329", dt.datetime(2026, 3, 7), ("DFP",), (2025,))


def test_rad_partial_cache_refreshes_main_page_to_establish_signed_session(tmp_path):
    _index(tmp_path)
    cache = tmp_path / "rad" / "155137"
    cache.mkdir(parents=True)
    cache.joinpath("main.html").write_bytes(_transport(
        CVMRADStatementClient.MAIN_URL.format(sequence="155137"), {},
    ))
    calls = []

    def tracking_transport(url, headers):
        calls.append(url)
        return _transport(url, headers)

    CVMRADStatementClient(str(tmp_path), transport=tracking_transport).load_rows(
        "17329", dt.datetime(2026, 3, 7), ("DFP",), (2025,),
    )
    assert calls[0] == CVMRADStatementClient.MAIN_URL.format(sequence="155137")


def test_open_data_client_uses_rad_when_aggregate_archive_is_unavailable(monkeypatch):
    fallback_row = CVMStatementRow(
        cvm_code="17329", company_name="ENGIE", statement="DRE", account_code="3.01",
        account_name="Receita", value=1200, currency="REAL", scale="MIL",
        reference_date=dt.date(2025, 12, 31), period_start=dt.date(2025, 1, 1),
        received_at=dt.datetime(2026, 3, 6, 14, 19, 24), filing_type="DFP",
        source_url="https://www.rad.cvm.gov.br/document/155137", version="2", exercise_order="ULTIMO",
    )
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda url: (_ for _ in ()).throw(OSError("aggregate unavailable")))
    monkeypatch.setattr(client.rad, "load_rows", lambda *args: [fallback_row])
    rows = client.load_rows("17329", dt.datetime(2026, 7, 29), filing_types=("DFP",), years=(2025,))
    assert rows == [fallback_row]
