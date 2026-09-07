import datetime as dt
import hashlib
import os
import zipfile

from prometheus.cvm_sector_registry import CVMSectorRegistry
from prometheus.sector_models import resolve_sector_model


def _write_registry(tmp_path):
    path = tmp_path / "cad_cia_aberta.csv"
    path.write_text(
        "CD_CVM;DENOM_SOCIAL;SETOR_ATIV;SIT\n"
        "017329;ENGIE BRASIL ENERGIA S.A.;Energia Elétrica;ATIVO\n"
        "018761;CIA ENERGETICA A;Energia Elétrica;ATIVO\n"
        "019999;CIA ENERGETICA B;Energia Elétrica;ATIVO\n"
        "020000;VAREJISTA;Comércio (Atacado e Varejo);ATIVO\n",
        encoding="latin-1",
    )
    observed = dt.datetime(2026, 7, 30, 12, 0).timestamp()
    os.utime(path, (observed, observed))
    return path


def test_official_sector_registry_is_point_in_time(tmp_path):
    _write_registry(tmp_path)
    registry = CVMSectorRegistry(str(tmp_path), first_history_year=2027)
    before = registry.lookup("17329", dt.datetime(2026, 7, 29))
    after = registry.lookup("17329", dt.datetime(2026, 7, 31))
    assert before["status"] == "INSUFFICIENT_DATA"
    assert before["reason"] == "REGISTRY_SNAPSHOT_AFTER_CUTOFF"
    assert after["sector"] == "Energia Elétrica"
    assert after["classification_method"] == "SETOR_ATIV exact official current-snapshot field"


def _write_fca_archive(tmp_path, year, documents, rows):
    path = tmp_path / f"fca_cia_aberta_{year}.zip"
    metadata_header = "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
    general_header = (
        "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;"
        "Codigo_CVM;Setor_Atividade;Descricao_Atividade\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(
            f"fca_cia_aberta_{year}.csv",
            metadata_header + "".join(";".join(item) + "\n" for item in documents),
        )
        zipped.writestr(
            f"fca_cia_aberta_geral_{year}.csv",
            general_header + "".join(";".join(item) + "\n" for item in rows),
        )
    old = dt.datetime(2026, 8, 20, 12, 0).timestamp()
    os.utime(path, (old, old))
    return path


def test_historical_fca_sector_starts_at_received_date_and_preserves_provenance(tmp_path):
    archive = _write_fca_archive(
        tmp_path,
        2026,
        [
            ("1", "2026-01-01", "1", "CIA A", "017329", "FCA", "100", "2026-03-05", "https://cvm.test/100"),
            ("1", "2026-01-01", "2", "CIA A", "017329", "FCA", "101", "2026-07-10", "https://cvm.test/101"),
        ],
        [
            ("1", "2026-01-01", "1", "100", "CIA A", "017329", "Energia Elétrica", "Geração"),
            ("1", "2026-01-01", "2", "101", "CIA A", "017329", "Petróleo e Gás", "Exploração"),
        ],
    )
    registry = CVMSectorRegistry(
        str(tmp_path), first_history_year=2026, cache_ttl_seconds=10**12,
    )
    before = registry.lookup("17329", dt.datetime(2026, 3, 4, 23, 59, 59))
    first = registry.lookup("17329", dt.datetime(2026, 3, 5, 23, 59, 59))
    second = registry.lookup("17329", dt.datetime(2026, 7, 10, 23, 59, 59))
    assert before["status"] == "INSUFFICIENT_DATA"
    assert first["sector"] == "Energia Elétrica"
    assert first["valid_from"] == "2026-03-05T00:00:00"
    assert first["valid_to"] == "2026-07-10T00:00:00"
    assert first["document_id"] == "100"
    assert first["source_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert second["sector"] == "Petróleo e Gás"
    assert second["version"] == "2"


def test_historical_peer_candidates_use_each_issuers_fca_at_cutoff(tmp_path):
    _write_fca_archive(
        tmp_path,
        2026,
        [
            ("1", "2026-01-01", "1", "ALVO", "017329", "FCA", "100", "2026-02-01", "https://cvm.test/100"),
            ("2", "2026-01-01", "1", "PEER", "018761", "FCA", "200", "2026-02-02", "https://cvm.test/200"),
            ("3", "2026-01-01", "1", "FUTURO", "019999", "FCA", "300", "2026-09-01", "https://cvm.test/300"),
        ],
        [
            ("1", "2026-01-01", "1", "100", "ALVO", "017329", "Energia Elétrica", "Geração"),
            ("2", "2026-01-01", "1", "200", "PEER", "018761", "Energia Elétrica", "Geração"),
            ("3", "2026-01-01", "1", "300", "FUTURO", "019999", "Energia Elétrica", "Geração"),
        ],
    )
    registry = CVMSectorRegistry(
        str(tmp_path), first_history_year=2026, cache_ttl_seconds=10**12,
    )
    peers = registry.peer_candidates(
        "Energia Elétrica",
        {"ALVO3": "17329", "PEER3": "18761", "FUTR3": "19999"},
        "17329",
        dt.datetime(2026, 6, 1),
        target_ticker="ALVO3",
    )
    assert [item["ticker"] for item in peers] == ["PEER3"]
    assert peers[0]["classification_source"] == "CVM Formulário Cadastral (FCA) estruturado"
    assert len(peers[0]["classification_source_sha256"]) == 64


def test_portuguese_cvm_activity_sectors_resolve_to_specific_models():
    cases = {
        "Energia Elétrica": "utilities",
        "Bancos": "financial",
        "Construção Civil, Mat. Constr. e Decoração": "real_estate",
        "Serviços Transporte e Logística": "transport_logistics",
        "Telecomunicações": "telecom",
        "Metalurgia e Siderurgia": "materials",
        "Serviços Médicos": "healthcare",
        "Educação": "education",
        "Comunicação e Informática": "technology_media",
        "Petróleo e Gás": "oil_gas",
        "Petroleo e Gas": "oil_gas",
    }
    assert {sector: resolve_sector_model(sector).key for sector in cases} == cases


def test_peer_candidates_require_exact_activity_and_one_ticker_per_issuer(tmp_path):
    _write_registry(tmp_path)
    registry = CVMSectorRegistry(str(tmp_path))
    candidates = registry.peer_candidates(
        "Energia Elétrica",
        {"EGIE3": "17329", "ENAA4": "18761", "ENAA3": "18761", "ENBB3": "19999", "VARE3": "20000"},
        "17329", dt.datetime(2026, 7, 31), limit=6,
    )
    assert [item["ticker"] for item in candidates] == ["ENAA3", "ENBB3"]
    assert all(item["selection_reason"] == "Mesmo SETOR_ATIV oficial da CVM; emissor único" for item in candidates)


def test_peer_candidates_prefer_target_share_class_before_deduplicating_issuer(tmp_path):
    _write_registry(tmp_path)
    registry = CVMSectorRegistry(str(tmp_path))
    candidates = registry.peer_candidates(
        "Energia Elétrica",
        {"EGIE4": "17329", "ENAA3": "18761", "ENAA4": "18761", "ENBB3": "19999"},
        "17329", dt.datetime(2026, 7, 31), limit=6, target_ticker="EGIE4",
    )
    assert [item["ticker"] for item in candidates] == ["ENAA4", "ENBB3"]
    assert "mesma classe" in candidates[0]["selection_reason"]
