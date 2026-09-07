import datetime as dt
import io
import hashlib
import zipfile

from prometheus.cvm_client import CVMOpenDataClient, CVMStatementRow


def _archive(*rows: str) -> bytes:
    header = "CD_CVM;DENOM_CIA;DT_REFER;DT_INI_EXERC;DT_FIM_EXERC;DT_RECEB;VERSAO;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("itr_cia_aberta_DRE_con_2024.csv", (header + "\n".join(rows)).encode("latin-1"))
    return output.getvalue()


def test_cvm_client_filters_future_filings_and_keeps_latest_available_version():
    archive = _archive(
        "1234;CIA TESTE;2024-03-31;2024-01-01;2024-03-31;2024-05-01;1;ÚLTIMO;3.01;Receita;10,0;BRL;MIL",
        "1234;CIA TESTE;2024-03-31;2024-01-01;2024-03-31;2024-05-10;2;ÚLTIMO;3.01;Receita;12,0;BRL;MIL",
        "1234;CIA TESTE;2024-03-31;2024-01-01;2024-03-31;2024-06-01;3;ÚLTIMO;3.01;Receita;99,0;BRL;MIL",
    )
    client = CVMOpenDataClient()
    rows = client._parse_archive(
        archive,
        source_url="https://dados.cvm.gov.br/test.zip",
        filing_type="ITR",
        cvm_code="1234",
        as_of=dt.datetime(2024, 5, 15),
        consolidated=True,
    )
    latest = client._latest_versions(rows)

    assert len(latest) == 1
    assert latest[0].value == 12.0
    assert latest[0].normalized_value == 12_000.0
    assert latest[0].version == "2"
    assert latest[0].source_sha256 == hashlib.sha256(archive).hexdigest()


def test_cvm_client_does_not_return_a_filing_before_publication():
    archive = _archive(
        "1234;CIA TESTE;2024-03-31;2024-01-01;2024-03-31;2024-05-01;1;ÚLTIMO;3.01;Receita;10,0;BRL;MIL",
    )
    rows = CVMOpenDataClient()._parse_archive(
        archive,
        source_url="https://dados.cvm.gov.br/test.zip",
        filing_type="ITR",
        cvm_code="1234",
        as_of=dt.datetime(2024, 4, 30, 23, 59),
        consolidated=True,
    )

    assert rows == []


def test_cvm_decimal_parser_handles_official_dot_decimals_and_brazilian_commas():
    assert CVMOpenDataClient._parse_decimal("1216184.0000000000") == 1_216_184.0
    assert CVMOpenDataClient._parse_decimal("1.216.184,50") == 1_216_184.5


def test_latest_versions_preserves_current_and_comparative_exercise_columns():
    common = dict(cvm_code="1", company_name="X", statement="BPP", account_code="2.08", account_name="Equity", currency="BRL", scale="UNIDADE", reference_date=dt.date(2026,6,30), period_start=None, received_at=dt.datetime(2026,8,1), filing_type="ITR", source_url="url", version="1")
    rows = [CVMStatementRow(value=100, exercise_order="ÚLTIMO", **common), CVMStatementRow(value=80, exercise_order="PENÚLTIMO", **common)]
    latest = CVMOpenDataClient()._latest_versions(rows)
    assert len(latest) == 2
    assert {row.exercise_order for row in latest} == {"ÚLTIMO", "PENÚLTIMO"}


def test_flow_rows_use_actual_period_end_instead_of_filing_reference_date():
    archive = _archive(
        "1234;CIA TESTE;2026-03-31;2025-01-01;2025-03-31;2026-05-01;1;PENÚLTIMO;3.01;Receita;50,0;BRL;MIL",
    )
    rows = CVMOpenDataClient()._parse_archive(
        archive, "https://dados.cvm.gov.br/test.zip", "ITR", "1234",
        dt.datetime(2026, 5, 2), True,
    )
    assert len(rows) == 1
    assert rows[0].reference_date == dt.date(2025, 3, 31)
    assert rows[0].period_start == dt.date(2025, 1, 1)
    assert rows[0].exercise_order == "PENÚLTIMO"
    assert len(rows[0].source_sha256) == 64
