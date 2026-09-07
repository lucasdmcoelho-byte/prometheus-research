from prometheus.editorial_gate import EditorialGate
from prometheus.operational_kpis import OperationalKPIExtractor


def _release_document():
    text = """
    Operacional (R$ milhões) 3T25 2T25 % T/T 3T24 % A/A
    VGV lançado ¹ (R$ milhões) 1.986,4 2.225,3 -10,7%
    Vendas Líquidas (R$ milhões) 1.827,0 2.261,4 -19,2%
    VSO Líquida ² 40,6% 47,5%
    Banco de Terrenos (VGV, R$ milhões) 23.343,7* 21.114,4
    Geração de Caixa (R$ milhões) 233,1 103,3
    Lançamentos 3T25 2T25 % T/T 3T24 % A/A
    Número de Unidades 6.813 6.588
    Vendas, %VSO 3T25 2T25 % T/T 3T24 % A/A
    Vendas Brutas (R$ milhões VGV) 2.051,9 2.498,0
    Número de Unidades 6.847 8.067
    Preço Médio/Unid. (R$ mil) 299,7 309,7
    Distratos (R$ milhões) 224,8 236,6
    Margem bruta ajustada ³ 40,2% 39,8%
    Resultado a Apropriar (REF) (R$ milhões)
    Receitas de vendas a apropriar 7.701,1 5.565,3
    Margem Bruta REF 43,4% 43,4%
    VGV Repassado (R$ milhões) 1.487,2 2.149,3
    Estoque (R$ milhões, exceto % e unidades) 3T25 2T25
    Em andamento 2.625,4 2.464,3
    Concluído 52,8 33,4
    Minha Casa Minha Vida é o programa nacional de habitação.
    Produção 4.908 unidades. Unidades concluídas 6.262.
    """
    return {
        "subject": "Release de resultados 3T25 PT-EN",
        "category": "Dados Econômico-Financeiros",
        "reference_date": "2025-09-30",
        "delivered_at": "2025-11-11T00:00:00",
        "protocol": "025100IPE300920250197929108-19",
        "version": 1,
        "source_url": "https://www.rad.cvm.gov.br/document",
        "source_sha256": "a" * 64,
        "raw_document_sha256": "b" * 64,
        "raw_document_cache_path": "cache/document.bin",
        "raw_document_status": "RETAINED",
        "content_scope": "ANALYSIS_INCLUDED",
        "content_extraction_status": "EXTRACTED",
        "extracted_text": text,
    }


def test_real_estate_release_extracts_sixteen_traceable_kpis_without_guessing():
    extractor = OperationalKPIExtractor()
    result = extractor.extract({"documents": [_release_document()]}, "real_estate")

    assert result["available_count"] == 16
    assert result["required_count"] == 18
    assert result["missing"] == ["unidades_entregues", "participação_no_mcmv"]
    assert result["metrics"]["lançamentos"]["value"] == 1_986_400_000
    assert result["metrics"]["vso"]["value"] == 0.406
    assert result["metrics"]["unidades_lançadas"]["value"] == 6813
    assert result["metrics"]["estoque_pronto"]["value"] == 52_800_000
    assert result["metrics"]["unidades_entregues"]["status"] == "INSUFFICIENT_DATA"
    assert result["metrics"]["participação_no_mcmv"]["status"] == "INSUFFICIENT_DATA"

    sources = list(extractor.source_records(result))
    assert len(sources) == 16
    assert all(len(item["source_sha256"]) == 64 for item in sources)
    assert all(item["period"] == "2025-Q3" for item in sources)
    assert all(item["publication_date"] == "2025-11-11T00:00:00" for item in sources)
    assert all(item["protocol"] == "025100IPE300920250197929108-19" for item in sources)


def test_gate_blocks_unparsed_critical_kpis_when_relevant_documents_are_retained():
    report = {
        "sector_model": {"key": "real_estate"},
        "official_disclosures": {"documents": [{
            "subject": "Release de resultados 3T25", "raw_document_status": "RETAINED",
            "content_scope": "ANALYSIS_INCLUDED", "raw_document_sha256": "b" * 64,
        }]},
    }
    gate = EditorialGate().evaluate(report)
    codes = [item["code"] for item in gate["blockers"]]
    assert "SECTOR_KPI_COVERAGE_INCOMPLETE" in codes


def test_gate_releases_sector_coverage_blocker_when_all_critical_kpis_are_available():
    critical = ("lançamentos", "vendas_líquidas", "vso", "distratos", "landbank")
    report = {
        "sector_model": {"key": "real_estate"},
        "operational_kpis": {
            "relevant_document_count": 1,
            "metrics": {name: {"status": "AVAILABLE"} for name in critical},
        },
    }
    gate = EditorialGate().evaluate(report)
    codes = [item["code"] for item in gate["blockers"]]
    assert "SECTOR_KPI_COVERAGE_INCOMPLETE" not in codes


def test_gate_warning_has_human_readable_message():
    report = {
        "official_disclosures": {"documents": [{
            "content_scope": "METADATA_ONLY_OUT_OF_SCOPE",
            "protocol": "PROTO-1", "subject": "Prévia operacional", "reference_date": "2025-09-30",
        }]},
    }
    warning = next(
        item for item in EditorialGate().evaluate(report)["warnings"]
        if item["code"] == "OFFICIAL_DOCUMENT_METADATA_ONLY"
    )
    assert "Prévia operacional" in warning["message"]
    assert "2025-09-30" in warning["message"]


def test_healthcare_release_extracts_traceable_beneficiaries_and_loss_ratio():
    document = _release_document() | {
        "subject": "Apresentação de Resultados 3T25",
        "extracted_text": """
            Beneficiários de Saúde (EoP) 8.868,9k 8.856,3k
            Beneficiários de Odonto (EoP) 7.107,1k 7.032,3k
            Ticket Médio Mensal Saúde R$292,7 R$289,4
            Sinistralidade Caixa 75,2% 73,9%
        """,
    }
    result = OperationalKPIExtractor().extract({"documents": [document]}, "healthcare")

    assert result["available_count"] == 4
    assert result["metrics"]["beneficiarios_saude"]["value"] == 8_868_900
    assert result["metrics"]["sinistralidade_caixa"]["value"] == 0.752
    assert result["metrics"]["ticket_medio_mensal_saude"]["unit"] == "BRL/beneficiary/month"
    assert result["metrics"]["churn"]["status"] == "INSUFFICIENT_DATA"


def test_integrated_healthcare_release_extracts_provider_metrics_without_relabeling_them_as_insurer_metrics():
    document = _release_document() | {
        "subject": "Press-release de Resultados 3T25",
        "extracted_text": """
            Em setembro de 2025, a Companhia operava 79 hospitais, somando 13.270 leitos totais.
            Taxa média de ocupação de leitos atinge 81,6% no 3T25.
            Volume de pacientes-dia recorde de 784 mil no 3T25; volume cirúrgico com 157 mil procedimentos.
            Base de beneficiários de saúde e odonto avança e atinge marca de 5,7 milhões.
            Sinistralidade consolidada média de 80,1% no trimestre.
        """,
    }
    result = OperationalKPIExtractor().extract({"documents": [document]}, "healthcare")
    assert result["metrics"]["leitos_totais"]["value"] == 13_270
    assert result["metrics"]["taxa_media_ocupacao_leitos"]["value"] == 0.816
    assert result["metrics"]["pacientes_dia"]["value"] == 784_000
    assert result["metrics"]["beneficiarios_saude_e_odonto"]["value"] == 5_700_000
    assert result["metrics"]["beneficiarios_saude"]["status"] == "INSUFFICIENT_DATA"


def test_generic_sector_module_never_reuses_real_estate_or_healthcare_kpis():
    result = OperationalKPIExtractor().extract({"documents": [_release_document()]}, "utilities")
    assert result["sector_coverage"] == "GENERIC"
    assert result["metrics"] == {}
    assert result["required_count"] == 0


def test_unavailable_metadata_only_disclosure_warns_without_becoming_a_content_blocker():
    report = {
        "ticker": "TEST3", "company_name": "Teste", "analysis_as_of": "2026-01-01",
        "research": {"sources": [], "contradiction_matrix": {"net": "ok"}},
        "valuation": {"status": "INSUFFICIENT_DATA"}, "risk": {"status": "ok"},
        "financial_history": [{"period": "2025"}], "sector_model": {"key": "general"}, "claims": [],
        "official_disclosures": {"documents": [{"protocol": "P-1", "subject": "Comunicado", "content_scope": "METADATA_ONLY_UNAVAILABLE", "raw_document_status": "UNAVAILABLE"}]},
    }
    gate = EditorialGate().evaluate(report)
    assert not any(item["code"] == "OFFICIAL_DOCUMENT_NOT_RETAINED" for item in gate["blockers"])
    assert any(item["code"] == "OFFICIAL_DOCUMENT_UNAVAILABLE" for item in gate["warnings"])


def test_gate_blocks_rendered_thesis_with_wrong_company_or_sector():
    report = {
        "ticker": "HAPV3", "company_name": "Hapvida Participações", "analysis_as_of": "2026-08-23",
        "sector_model": {"key": "healthcare"}, "thesis_scores": {"sector": 50, "macro": 50},
        "macro_observations": [], "rendered_narratives": {"central_thesis": "CURY (CURY3) é uma incorporadora de terrenos, obras e recebíveis."},
    }
    codes = [item["code"] for item in EditorialGate().evaluate(report)["blockers"]]
    assert "THESIS_IDENTITY_MISMATCH" in codes
    assert "THESIS_SECTOR_MISMATCH" in codes
    assert "SEMANTIC_CONTAMINATION" in codes


def test_gate_blocks_non_neutral_macro_or_sector_without_evidence():
    report = {"thesis_scores": {"macro": 70, "sector": 70}, "macro_observations": [], "research": {"peer_analysis": {}}}
    details = [item["detail"] for item in EditorialGate().evaluate(report)["blockers"]]
    assert "macro_score_non_neutral_without_eligible_macro" in details
    assert "sector_score_non_neutral_without_peer_history" in details
