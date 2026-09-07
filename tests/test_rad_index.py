import datetime as dt

from prometheus.rad_index import parse_rad_query_html


def test_rad_index_accepts_only_structured_dfp_and_itr_rows():
    rows = """
    <table>
      <tr><td>01732-9</td><td>ENGIE BRASIL ENERGIA S.A.</td><td>DFP - Demonstrações Financeiras Padronizadas</td><td>-</td><td>-</td><td>31/12/2025</td><td>06/03/2026 14:19</td><td>Ativo</td><td>2</td><td>RE</td><td><i onclick="OpenPopUpVer('frmGerenciaPaginaFRE.aspx?NumeroSequencialDocumento=155137&amp;CodigoTipoInstituicao=1')"></i><i onclick="OpenDownloadDocumentos('155137','2','017329DFP311220250200155137-61','DFP')"></i></td></tr>
      <tr><td>01732-9</td><td>ENGIE BRASIL ENERGIA S.A.</td><td>ITR - Informações Trimestrais</td><td>-</td><td>-</td><td>31/03/2026</td><td>07/05/2026 18:01</td><td>Ativo</td><td>1</td><td>RE</td><td><i onclick="OpenPopUpVer('frmGerenciaPaginaFRE.aspx?NumeroSequencialDocumento=156000&amp;CodigoTipoInstituicao=1')"></i><i onclick="OpenDownloadDocumentos('156000','1','017329ITR310320260100156000-00','ITR')"></i></td></tr>
      <tr><td>01732-9</td><td>ENGIE BRASIL ENERGIA S.A.</td><td>Fato Relevante</td><td>-</td><td>-</td><td>01/01/2026</td><td>01/01/2026 12:00</td><td>Ativo</td><td>1</td><td>AP</td><td><i onclick="OpenDownloadDocumentos('1','1','protocol','IPE')"></i></td></tr>
    </table>
    """.encode()
    result = parse_rad_query_html(rows, "https://www.rad.cvm.gov.br/query", dt.datetime(2026, 8, 16, 12))
    assert [item["filing_type"] for item in result["documents"]] == ["DFP", "ITR"]
    assert result["documents"][0]["cvm_code"] == "17329"
    assert result["documents"][0]["sequence"] == "155137"
    assert result["documents"][0]["protocol"] == "017329DFP311220250200155137-61"
    assert result["source_sha256"]


def test_rad_index_rejects_rows_without_protocol_or_valid_dates():
    payload = b"<table><tr><td>1</td><td>X</td><td>DFP - X</td><td>-</td><td>-</td><td>invalid</td><td>invalid</td><td>Ativo</td><td>1</td><td>RE</td><td></td></tr></table>"
    assert parse_rad_query_html(payload, "url", dt.datetime(2026, 1, 1))["documents"] == []
