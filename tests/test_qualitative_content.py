from prometheus.knowledge_store import KnowledgeStore
from prometheus.qualitative_content import CompanyContextEngine, QualitativeContentGenerator, QualitativeContentError


def _report(sector="Construção e incorporação", kpis=None):
    return {
        "sector_name": sector,
        "industry_name": sector,
        "business_summary": "Opera uma plataforma de serviços para clientes e parceiros.",
        "analysis_as_of": "2026-08-30",
        "macro_observations": [{
            "metric": "selic_target", "value": 14.0, "point_in_time_eligible": True,
            "source": "BCB SGS", "publication_date": "2026-08-30",
            "source_url": "https://api.bcb.gov.br", "source_sha256": "a" * 64,
        }],
        "operational_kpis": {"metrics": kpis or {}},
    }


def _kpi():
    return {"vso": {"status": "AVAILABLE", "value": 0.406, "unit": "percentage", "period": "2025-Q3", "source": "CVM IPE", "source_url": "https://cvm.gov.br/doc", "raw_document_sha256": "b" * 64}}


def _provider(prompt):
    if "video_script" in prompt:
        return "Em Cury, decisões concretas de execução encontram um contexto que muda; quais evidências explicam essa trajetória?"
    if "question_of_the_moment" in prompt:
        return "Que evidências mostram como Cury transforma contexto em decisões concretas de execução?"
    return "Cury acompanha decisões concretas de execução e contexto, mantendo abertas as perguntas que os fatos ainda não respondem."


def test_all_formats_are_source_labelled_and_non_directional(tmp_path):
    store = KnowledgeStore()
    store.add({"ticker": "CURY3", "title": "Prévia operacional divulgada", "published_at": "2026-08-01", "source": "CVM IPE", "url": "https://cvm.gov.br/x", "source_sha256": "c" * 64})
    context = CompanyContextEngine(store).build("CURY3", "Cury", report=_report(kpis=_kpi()))
    from prometheus.llm_content import TextSimilarityRegistry
    generator = QualitativeContentGenerator(CompanyContextEngine(store), llm_provider=_provider, similarity_registry=TextSimilarityRegistry(str(tmp_path / "history.json")))
    for content in (generator.post(context), generator.video_script(context), generator.question_of_the_moment(context)):
        assert content["validation"]["status"] == "PASS"
        assert content["human_review_required"] is True
        assert all(claim["source_id"] in {source["source_id"] for source in content["sources"]} for claim in content["claims"])
        assert not any(word in content["text"].lower() for word in ("compre", "venda agora", "preço-alvo", "deve subir", "deve cair"))
    assert "KPI validado" not in generator.post(context)["text"]


def test_unvalidated_sector_does_not_invent_operational_numbers(tmp_path):
    context = CompanyContextEngine().build("ITUB4", "Itaú Unibanco", report=_report("Bancos e serviços financeiros"))
    from prometheus.llm_content import TextSimilarityRegistry
    content = QualitativeContentGenerator(CompanyContextEngine(), llm_provider=_provider, similarity_registry=TextSimilarityRegistry(str(tmp_path / "history.json"))).post(context)
    assert context["validated_kpis"] == []
    assert "números operacionais" in " ".join(content["limitations"])
    assert "KPI validado" not in content["text"]


def test_numeric_fact_requires_a_traceable_source(tmp_path):
    context = CompanyContextEngine().build("CURY3", "Cury", report=_report(kpis=_kpi()))
    from prometheus.llm_content import TextSimilarityRegistry
    content = QualitativeContentGenerator(CompanyContextEngine(), llm_provider=_provider, similarity_registry=TextSimilarityRegistry(str(tmp_path / "history.json"))).post(context)
    content["claims"].append({"classification": "PUBLIC_FACT", "text": "Fato 123", "source_id": None})
    try:
        QualitativeContentGenerator.validate(content)
    except QualitativeContentError as exc:
        assert "numeric_claims_without_source" in str(exc)
    else:
        raise AssertionError("numeric unsourced fact was accepted")
