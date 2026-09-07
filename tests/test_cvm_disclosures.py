import csv
import datetime as dt
import http.client
import io
import zipfile

from prometheus.cvm_disclosures import CVMDisclosureClient


def _zip():
    rows = [
        {"Codigo_CVM":"25100","Nome_Companhia":"Cury","CNPJ_Companhia":"1","Data_Referencia":"2025-01-01","Categoria":"Fato Relevante","Tipo":"FR","Especie":"","Assunto":"Evento","Data_Entrega":"2025-01-02","Tipo_Apresentacao":"AP","Protocolo_Entrega":"P1","Versao":"1","Link_Download":"https://cvm/1"},
        {"Codigo_CVM":"25100","Nome_Companhia":"Cury","CNPJ_Companhia":"1","Data_Referencia":"2027-01-01","Categoria":"Fato Relevante","Tipo":"FR","Especie":"","Assunto":"Futuro","Data_Entrega":"2027-01-02","Tipo_Apresentacao":"AP","Protocolo_Entrega":"P2","Versao":"1","Link_Download":"https://cvm/2"},
    ]
    text=io.StringIO(); writer=csv.DictWriter(text,fieldnames=rows[0],delimiter=';',lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as zipped: zipped.writestr('ipe_cia_aberta_2025.csv',text.getvalue())
    return buffer.getvalue()


def test_ipe_disclosures_are_filtered_point_in_time(monkeypatch):
    client=CVMDisclosureClient(); monkeypatch.setattr(client,'_download',lambda year:_zip())
    result=client.load('25100',dt.datetime(2026,1,1),years=[2025])
    assert result['document_count']==1
    assert result['documents'][0]['subject']=='Evento'


def test_material_disclosure_original_is_retained_hashed_and_extracted(monkeypatch, tmp_path):
    client = CVMDisclosureClient(cache_dir=str(tmp_path))
    monkeypatch.setattr(client, '_download', lambda year: _zip())
    monkeypatch.setattr(
        client, '_download_original',
        lambda url, protocol, version: (b'<html><body>Fato relevante oficial</body></html>', tmp_path / 'doc.bin'),
    )
    result = client.load('25100', dt.datetime(2026, 1, 1), years=[2025], include_content=True)
    document = result['documents'][0]
    assert document['content_scope'] == 'ANALYSIS_INCLUDED'
    assert document['raw_document_status'] == 'RETAINED'
    assert len(document['raw_document_sha256']) == 64
    assert document['content_extraction_status'] == 'EXTRACTED'
    assert document['extracted_text'] == 'Fato relevante oficial'


def test_retained_content_prioritizes_operational_results_over_newer_corporate_notice(monkeypatch, tmp_path):
    client = CVMDisclosureClient(cache_dir=str(tmp_path))
    records = [
        {"delivered_at": "2025-11-07T00:00:00", "subject": "Aviso aos Acionistas", "source_url": "https://cvm/notice", "protocol": "N", "version": 1},
        {"delivered_at": "2025-11-05T00:00:00", "subject": "Press-release de Resultados 3T25", "source_url": "https://cvm/results", "protocol": "R", "version": 1},
    ]
    assert sorted(records, key=client._content_priority)[0]["protocol"] == "R"


def test_original_download_retries_incomplete_response_and_never_caches_partial_bytes(monkeypatch, tmp_path):
    client = CVMDisclosureClient(cache_dir=str(tmp_path), original_download_attempts=3)
    calls = []

    class Response:
        headers = {"Content-Length": "17"}
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b"documento oficial"

    def download(*_, **__):
        calls.append(True)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b"parcial", 15)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", download)
    monkeypatch.setattr("prometheus.cvm_disclosures.time.sleep", lambda *_: None)
    payload, path = client._download_original("https://cvm.test/document", "P1", 1)
    assert payload == b"documento oficial"
    assert len(calls) == 2
    assert path.read_bytes() == b"documento oficial"


def test_unavailable_original_is_metadata_only_and_cannot_be_treated_as_retained_content(monkeypatch, tmp_path):
    client = CVMDisclosureClient(cache_dir=str(tmp_path), original_download_attempts=1)
    monkeypatch.setattr(client, "_download", lambda year: _zip())
    monkeypatch.setattr(client, "_download_original", lambda *_: (_ for _ in ()).throw(OSError("offline")))
    result = client.load("25100", dt.datetime(2026, 1, 1), years=[2025], include_content=True)
    document = result["documents"][0]
    assert document["content_scope"] == "METADATA_ONLY_UNAVAILABLE"
    assert document["raw_document_status"] == "UNAVAILABLE"
