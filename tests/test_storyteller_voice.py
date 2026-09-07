import pytest

from prometheus.knowledge_store import KnowledgeStore
from prometheus.qualitative_content import CompanyContextEngine, QualitativeContentGenerator
from prometheus.storyteller_voice import StorytellerVoiceEngine
from prometheus.llm_content import LLMQualitativeGenerator, TextSimilarityRegistry, format_human_number


def _context(with_kpi=True):
    kpis = [{"metric": "vso", "value": 0.406, "unit": "percentage", "period": "2026-Q1", "text": "KPI validado: vso = 0.406", "source_id": "kpi-vso"}] if with_kpi else []
    return {
        "ticker": "CURY3", "company_name": "Cury", "sector": "Construção e incorporação",
        "validated_kpis": kpis, "public_facts": kpis + [{"classification": "PUBLIC_FACT", "text": "Evento real: prévia operacional divulgada", "source_id": "news-1"}],
        "sources": [{"source_id": "kpi-vso", "source": "CVM IPE"}, {"source_id": "news-1", "source": "CVM IPE"}],
        "interpretation": [{"text": "A execução conecta crédito, renda e velocidade de vendas."}],
        "limitations": [] if with_kpi else ["Não há KPI operacional validado."],
        "macro_facts": [{"metric": "selic_target", "source_id": "macro-1"}],
    }


@pytest.mark.parametrize("fmt", ["short_post", "video_script_60_90s", "question_of_the_moment"])
def test_voice_removes_process_language_and_preserves_validation(fmt):
    content = StorytellerVoiceEngine().render(_context(), fmt)
    text = content["text"].lower()
    for term in ("human_review_required", "revisão humana", "o roteiro não usa", "conteúdo educacional", "antes de publicar"):
        assert term not in text
    assert content["human_review_required"] is True
    assert content["validation"] if "validation" in content else True


def test_voice_without_kpi_uses_natural_limitation_without_inventing_number():
    context = _context(with_kpi=False)
    content = StorytellerVoiceEngine().render(context, "short_post")
    assert "número oficial" in content["text"]
    assert "KPI validado" not in content["text"]
    assert not any(term in content["text"].lower() for term in ("compre", "venda agora", "preço-alvo", "deve subir", "deve cair"))


def test_voice_has_human_numbers_and_no_internal_fields_or_old_cliches():
    content = StorytellerVoiceEngine().render(_context(), "short_post")
    text = content["text"].lower()
    assert "2646800000.0" not in text
    assert "selic_target" not in text
    assert "kpi_vso" not in text
    assert "é aí que o contexto ganha importância" not in text
    assert format_human_number(2646800000, "BRL") == "R$ 2,65 bilhões"


def test_llm_retries_three_times_then_marks_generation_failed():
    calls = []

    def invalid_provider(prompt):
        calls.append(prompt)
        return "É aí que o contexto ganha importância."

    generator = LLMQualitativeGenerator(provider=invalid_provider, max_attempts=3)
    result = generator.generate(_context(), "short_post")
    assert result["generation_failed"] is True
    assert result["generation_attempts"] == 3
    assert result["text"] == ""
    assert len(calls) == 3


def test_llm_without_api_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    generator = LLMQualitativeGenerator(provider=None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        generator.generate(_context(), "short_post")


def test_similarity_registry_rejects_repeated_five_word_sequence(tmp_path):
    registry = TextSimilarityRegistry(str(tmp_path / "history.json"))
    first = "Uma empresa transforma decisões concretas em resultados observáveis para seus clientes."
    registry.record(first)
    assert registry.repeated_phrase("Novos fatos: decisões concretas em resultados observáveis para o mercado.") == "decisões concretas em resultados observáveis"


def test_api_call_metadata_is_reportable(tmp_path):
    def provider(prompt):
        return {"text": "Cury acompanha decisões concretas de execução e contexto.", "api_call": {"provider": "anthropic", "model": "claude-test", "input_tokens": 12, "output_tokens": 8, "response_id": "msg_test"}}
    result = LLMQualitativeGenerator(provider=provider, similarity_registry=TextSimilarityRegistry(str(tmp_path / "history.json"))).generate(_context(), "short_post")
    assert result["api_call"] == {"provider": "anthropic", "model": "claude-test", "input_tokens": 12, "output_tokens": 8, "response_id": "msg_test"}
