import csv
import io
import zipfile
from datetime import datetime

from prometheus.cvm_documents import CVMReferenceFormClient


def _archive():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        for name, rows in {
            "fre_cia_aberta_2025.csv": [
                {"CD_CVM": "025100", "DENOM_CIA": "CIA TESTE", "DT_REFER": "2025-12-31", "DT_RECEB": "2025-04-01", "VERSAO": "2", "ID_DOC": "42", "LINK_DOC": "https://cvm/doc/42"},
            ],
            "fre_cia_aberta_administrador_membro_conselho_fiscal_2025.csv": [
                {"ID_Documento": "42", "Versao": "2", "Nome": "Maria", "CPF": "secret", "Data_Nascimento": "1980-01-01", "Cargo_Eletivo_Ocupado": "Diretora"},
            ],
        }.items():
            fields = sorted({key for row in rows for key in row})
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=fields, delimiter=";", lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
            zipped.writestr(name, text.getvalue().encode("utf-8"))
    return buffer.getvalue()


def test_fre_is_point_in_time_and_private_fields_are_dropped(monkeypatch):
    client = CVMReferenceFormClient()
    monkeypatch.setattr(client, "_download", lambda year: _archive())
    result = client.load_company("25100", datetime(2025, 5, 1), years=[2025])
    assert result["status"] == "AVAILABLE"
    manager = result["sections"]["management"][0]
    assert manager["Nome"] == "Maria"
    assert "CPF" not in manager and "Data_Nascimento" not in manager


def test_fre_rejects_documents_received_after_cutoff(monkeypatch):
    client = CVMReferenceFormClient()
    monkeypatch.setattr(client, "_download", lambda year: _archive())
    result = client.load_company("25100", datetime(2025, 3, 31), years=[2025])
    assert result["status"] == "INSUFFICIENT_DATA"
