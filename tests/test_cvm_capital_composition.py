import io
import zipfile
from datetime import datetime

from prometheus.cvm_client import CVMOpenDataClient


def _archive(invalid_first_total: bool = False) -> bytes:
    metadata = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
        "02.474.103/0001-19;2026-03-31;1;ENGIE;017329;ITR;1;2026-05-07;https://cvm.example/1\n"
        "02.474.103/0001-19;2026-06-30;1;ENGIE;017329;ITR;2;2026-08-05;https://cvm.example/2\n"
    )
    first_preferred = "1" if invalid_first_total else "0"
    capital = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO\n"
        f"02.474.103/0001-19;2026-03-31;1;ENGIE;1142298836;{first_preferred};1142298836;10;0;10\n"
        "02.474.103/0001-19;2026-06-30;1;ENGIE;1200000000;0;1200000000;0;0;0\n"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("itr_cia_aberta_2026.csv", metadata)
        zipped.writestr("itr_cia_aberta_composicao_capital_2026.csv", capital)
    return output.getvalue()


def _scaled_archive(raw_total: int, profit: float, eps: float) -> bytes:
    metadata = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
        "60.872.504/0001-23;2026-06-30;1;ITAU;019348;ITR;1;2026-08-04;https://cvm.example/1\n"
    )
    ordinary = raw_total // 2
    preferred = raw_total - ordinary
    capital = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO\n"
        f"60.872.504/0001-23;2026-06-30;1;ITAU;{ordinary};{preferred};{raw_total};0;0;0\n"
    )
    dre_header = (
        "CD_CVM;DT_REFER;VERSAO;DENOM_CIA;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA;DT_INI_EXERC;DT_FIM_EXERC;ORDEM_EXERC\n"
    )
    dre = dre_header + (
        f"019348;2026-06-30;1;ITAU;3.11.01;Atribuido a Controladora;{profit};BRL;UNIDADE;2026-01-01;2026-06-30;ULTIMO\n"
        f"019348;2026-06-30;1;ITAU;3.99.01.01;ON;{eps};BRL;MIL;2026-01-01;2026-06-30;ULTIMO\n"
        f"019348;2026-06-30;1;ITAU;3.99.01.02;PN;{eps};BRL;MIL;2026-01-01;2026-06-30;ULTIMO\n"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("itr_cia_aberta_2026.csv", metadata)
        zipped.writestr("itr_cia_aberta_composicao_capital_2026.csv", capital)
        zipped.writestr("itr_cia_aberta_DRE_con_2026.csv", dre)
    return output.getvalue()


def test_capital_composition_is_point_in_time_and_subtracts_treasury(monkeypatch):
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda _: _archive())
    result = client.load_capital_composition(
        "17329", datetime(2026, 7, 29), filing_types=("ITR",), years=(2026,)
    )
    assert result["status"] == "AVAILABLE"
    assert result["reference_date"] == "2026-03-31"
    assert result["received_at"] == datetime(2026, 5, 7)
    assert result["shares_outstanding"] == 1_142_298_826
    assert result["single_class"] is True
    assert result["formula"] == "(QT_ACAO_TOTAL_CAP_INTEGR - QT_ACAO_TOTAL_TESOURO) * quantity_scale_multiplier"
    assert result["quantity_scale_multiplier"] == 1


def test_capital_composition_uses_new_filing_only_after_publication(monkeypatch):
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda _: _archive())
    result = client.load_capital_composition(
        "17329", datetime(2026, 8, 6), filing_types=("ITR",), years=(2026,)
    )
    assert result["reference_date"] == "2026-06-30"
    assert result["shares_outstanding"] == 1_200_000_000


def test_invalid_capital_reconciliation_is_discarded(monkeypatch):
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda _: _archive(invalid_first_total=True))
    result = client.load_capital_composition(
        "17329", datetime(2026, 7, 29), filing_types=("ITR",), years=(2026,)
    )
    assert result["status"] == "INSUFFICIENT_DATA"


def test_small_capital_quantity_is_scaled_only_after_eps_reconciliation(monkeypatch):
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda _: _scaled_archive(11_000_000, 23_540_000_000, 2.14))
    result = client.load_capital_composition(
        "19348", datetime(2026, 8, 17), filing_types=("ITR",), years=(2026,)
    )
    assert result["status"] == "AVAILABLE"
    assert result["reported_total_quantity"] == 11_000_000
    assert result["total_issued_shares"] == 11_000_000_000
    assert result["quantity_scale_multiplier"] == 1000
    assert result["quantity_scale_status"] == "VERIFIED"
    assert result["quantity_scale_reconciliation_error"] < 0.001


def test_large_capital_quantity_reconciles_without_scaling(monkeypatch):
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda _: _scaled_archive(10_000_000_000, 12_000_000_000, 1.2))
    result = client.load_capital_composition(
        "19348", datetime(2026, 8, 17), filing_types=("ITR",), years=(2026,)
    )
    assert result["quantity_scale_multiplier"] == 1
    assert result["quantity_scale_status"] == "VERIFIED"


def test_small_capital_quantity_without_independent_reconciliation_fails_closed(monkeypatch):
    client = CVMOpenDataClient()
    monkeypatch.setattr(client, "_download", lambda _: _scaled_archive(11_000_000, 0, 0))
    result = client.load_capital_composition(
        "19348", datetime(2026, 8, 17), filing_types=("ITR",), years=(2026,)
    )
    assert result == {"status": "INSUFFICIENT_DATA", "reason": "NO_POINT_IN_TIME_CAPITAL_COMPOSITION"}
