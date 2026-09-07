"""Storyteller voice layer for qualitative content."""
from __future__ import annotations

from typing import Any, Dict

from prometheus.qualitative_content import QualitativeContentError, QualitativeContentGenerator


PROCESS_LANGUAGE = (
    "human_review_required", "revisão humana", "revisao humana",
    "o roteiro não usa", "o roteiro nao usa", "conteúdo educacional",
    "conteudo educacional", "o sistema separa", "antes de publicar",
    "revisão editorial", "revisao editorial",
)


class StorytellerVoiceEngine:
    """Reshape existing claims into audience-facing, company-specific copy."""

    @staticmethod
    def _anchor(context: Dict[str, Any]) -> Dict[str, Any]:
        kpis = context.get("validated_kpis") or []
        if kpis:
            return kpis[0]
        facts = context.get("public_facts") or []
        events = [item for item in facts if str(item.get("source_id", "")).startswith("news-")]
        if events:
            return events[0]
        return next((item for item in facts if item.get("source_id") == "profile"), facts[0] if facts else {"text": "", "source_id": "profile"})

    def _narrative(self, context: Dict[str, Any], fmt: str) -> str:
        company, ticker = context["company_name"], context["ticker"]
        sector = context.get("sector") or "seu mercado"
        anchor = self._anchor(context)
        anchor_text, anchor_id = str(anchor.get("text") or "").strip(), anchor.get("source_id") or "profile"
        if anchor.get("value") is not None:
            from prometheus.llm_content import format_human_number
            anchor_text = f"KPI validado: {anchor.get('metric')} = {format_human_number(anchor.get('value'), anchor.get('unit'))} no período {anchor.get('period')}"
        interpretation = str((context.get("interpretation") or [{"text": ""}])[0].get("text") or "").strip()
        for internal, public in (("selic_target", "juros básicos"), ("credit_growth", "crescimento do crédito"), ("delinquency", "inadimplência"), ("ipca", "inflação"), ("employment", "emprego"),):
            interpretation = interpretation.replace(internal, public)
        has_kpi = bool(context.get("validated_kpis"))
        if has_kpi:
            opening = f"Um número coloca {company} no centro da conversa: {anchor_text}"
        elif anchor_id.startswith("news-") and anchor_text:
            opening = f"{company} entrou no radar por um acontecimento concreto: {anchor_text}"
        else:
            opening = f"Existe uma tensão interessante em {company} ({ticker}): como transformar seu modelo de {sector.lower()} em execução que se sustenta?"
            if anchor_text:
                opening += f" Os registros públicos descrevem a empresa como {anchor_text.rstrip('. ')}."
        bridge = f"O contexto ajuda a ler esse fato: {interpretation}" if interpretation else f"As escolhas de {company} ficam mais interessantes do que a etiqueta do setor."
        if context.get("limitations") and not has_kpi:
            bridge += " Ainda não dá para confirmar por um número oficial quanto dessa dinâmica já virou resultado operacional."
        if fmt == "short_post":
            return f"{opening}\n\n{bridge}\n\n{company} é uma história de decisões, execução e riscos concretos. O que vale acompanhar é como a empresa responde a esse contexto, distinguindo o que foi documentado do que continua sendo uma pergunta aberta."
        if fmt == "video_script_60_90s":
            return (f"[0–10s | FALA] {opening.rstrip('. ')}.\n[10–30s | CORTE] {bridge}\n"
                    f"[30–55s | FALA] Em {company}, a pergunta humana é o que precisa acontecer nos bastidores para essa história continuar fazendo sentido.\n"
                    "[55–75s | CORTE] O que ainda falta entender é quais decisões mudariam essa história na prática.\n"
                    "[75–90s | ENCERRAMENTO] Qual parte dessa história você investigaria primeiro?")
        if fmt == "question_of_the_moment":
            macro = (context.get("macro_facts") or [{}])[0]
            metric = macro.get("metric") or "o cenário econômico"
            metric = {"selic_target": "os juros básicos", "ipca": "a inflação", "employment": "o emprego", "credit_growth": "o crescimento do crédito", "delinquency": "a inadimplência"}.get(metric, metric)
            return (f"O que a história de {company} revela sobre {metric}: por que esta empresa, com seu modelo de {sector.lower()}, enfrenta essa tensão de um jeito próprio?\n\n"
                    "A pergunta não é adivinhar o próximo movimento, mas identificar quais decisões e evidências separariam narrativa de realidade.")
        raise QualitativeContentError(f"unsupported format: {fmt}")

    def render(self, context: Dict[str, Any], fmt: str) -> Dict[str, Any]:
        text = self._narrative(context, fmt)
        if any(term in text.lower() for term in PROCESS_LANGUAGE):
            raise QualitativeContentError("process language leaked into audience text")
        result = {
            "schema": "prometheus.storyteller_content.v1", "format": fmt,
            "ticker": context["ticker"], "company_name": context["company_name"],
            "text": text, "claims": list(context.get("public_facts") or []),
            "sources": list(context.get("sources") or []),
            "interpretation": list(context.get("interpretation") or []),
            "limitations": list(context.get("limitations") or []),
            "human_review_required": True,
        }
        result["validation"] = QualitativeContentGenerator.validate(result)
        return result
