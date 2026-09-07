"""LLM-backed qualitative copy with a deterministic post-generation gate."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from collections import deque
from typing import Any, Callable, Dict, Optional

from prometheus.qualitative_content import (
    PROHIBITED_RECOMMENDATION_PATTERNS,
    QualitativeContentError,
    QualitativeContentGenerator,
)
from prometheus.storyteller_voice import PROCESS_LANGUAGE


INTERNAL_FIELD_NAMES = {
    "selic_target", "kpi_vso", "operational_kpis", "human_review_required",
    "source_id", "valuation_margin", "macro_observations", "point_in_time_eligible",
}
TEMPLATE_CLICHES = (
    "é aí que o contexto ganha importância",
    "não é apenas o nome de um setor: é uma história de",
    "nao e apenas o nome de um setor: e uma historia de",
)


def format_human_number(value: Any, unit: Optional[str] = None) -> str:
    """Format numeric facts once, centrally, for audience-facing text."""
    number = float(value)
    normalized = str(unit or "").lower()
    if "percentage" in normalized or normalized in {"percent", "%"}:
        return f"{number * 100:.1f}%" if abs(number) <= 1 else f"{number:.1f}%"
    if normalized.startswith("brl") or normalized in {"r$", "brl"}:
        absolute = abs(number)
        if absolute >= 1_000_000_000:
            return f"R$ {number / 1_000_000_000:.2f} bilhões".replace(".", ",")
        if absolute >= 1_000_000:
            return f"R$ {number / 1_000_000:.2f} milhões".replace(".", ",")
        return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if number.is_integer():
        return f"{int(number):,}".replace(",", ".")
    return f"{number:.2f}".replace(".", ",")


def build_llm_prompt(context: Dict[str, Any], fmt: str, feedback: str = "") -> str:
    facts = []
    for claim in context.get("public_facts") or []:
        # Give the model atomic facts, not pre-composed prose fragments that
        # can be concatenated into ungrammatical audience copy.
        if claim.get("source_id") == "classification":
            facts.append({"fact_type": "sector_classification", "sector": context.get("sector"), "classification": claim.get("classification"), "source_id": claim.get("source_id")})
        else:
            facts.append({"text": claim.get("text"), "classification": claim.get("classification"), "source_id": claim.get("source_id")})
    kpis = []
    for item in context.get("validated_kpis") or []:
        kpis.append({"metric": item.get("metric"), "value": format_human_number(item.get("value"), item.get("unit")), "unit": item.get("unit"), "period": item.get("period"), "source_id": item.get("source_id")})
    return f"""Você escreve conteúdo Storyteller sobre uma empresa para público geral.
Formato: {fmt}. Empresa: {context.get('company_name')} ({context.get('ticker')}).
Use SOMENTE os fatos abaixo. Não invente fato, evento, número, comparação ou posição competitiva.
Comece por uma cena, tensão ou contraste específico desta empresa; nunca comece por classificação burocrática.
Use números apenas na forma humana fornecida (nunca floats crus). Não exiba IDs, nomes de campos internos ou notas de processo.
Não use linguagem direcional de preço, recomendação, compra, venda, alvo ou previsão de alta/queda.
Não use os clichês: "É aí que o contexto ganha importância" ou "não é apenas o nome de um setor: é uma história de...".
Não diga human_review_required, revisão humana, conteúdo educacional ou que o roteiro não usa números.
Tamanho: post 150–300 palavras; roteiro 60–90 segundos; pergunta curta e provocativa.
Fatos com fontes (IDs são apenas metadados e não devem aparecer no texto): {json.dumps(facts, ensure_ascii=False)}
KPIs validados (se vazia, não cite KPI): {json.dumps(kpis, ensure_ascii=False)}
Contexto interpretativo: {json.dumps(context.get('interpretation') or [], ensure_ascii=False)}
Limitações: {json.dumps(context.get('limitations') or [], ensure_ascii=False)}
Feedback de validação anterior: {feedback or 'nenhum'}
Retorne somente o texto final da peça."""


class AnthropicProvider:
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-haiku-latest"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model

    def __call__(self, prompt: str) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        body = json.dumps({"model": self.model, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]}, ensure_ascii=False).encode()
        request = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        usage = payload.get("usage") or {}
        return {
            "text": "".join(str(item.get("text") or "") for item in payload.get("content") or []),
            "api_call": {
                "provider": "anthropic",
                "model": payload.get("model") or self.model,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "response_id": payload.get("id"),
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        }


class TextSimilarityRegistry:
    """Small persistent registry used to reject repeated five-word phrases."""
    def __init__(self, path: Optional[str] = None, max_entries: int = 50):
        self.path = Path(path or ".cache/qualitative_generation_history.json")
        self.max_entries = max(1, int(max_entries))

    @staticmethod
    def _words(text: str):
        return re.findall(r"[\wÀ-ÿ]+", text.lower())

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries[-self.max_entries:], ensure_ascii=False, indent=2), encoding="utf-8")

    def repeated_phrase(self, text: str) -> Optional[str]:
        words = self._words(text)
        if len(words) < 5:
            return None
        previous = self._load()
        for entry in previous:
            old = self._words(str(entry.get("text") or ""))
            old_set = {tuple(old[i:i+5]) for i in range(max(0, len(old)-4))}
            for i in range(len(words)-4):
                phrase = tuple(words[i:i+5])
                if phrase in old_set:
                    return " ".join(phrase)
        return None

    def record(self, text: str, metadata: Optional[Dict[str, Any]] = None):
        entries = self._load()
        entries.append({"text": text, "metadata": metadata or {}, "recorded_at": datetime.now(timezone.utc).isoformat()})
        self._save(entries)


class LLMQualitativeGenerator:
    def __init__(self, provider: Optional[Callable[[str], Any]] = None, max_attempts: int = 3, similarity_registry: Optional[TextSimilarityRegistry] = None):
        self.provider = provider or (AnthropicProvider() if os.getenv("ANTHROPIC_API_KEY") else None)
        self.max_attempts = max(1, min(3, int(max_attempts)))
        self.similarity_registry = similarity_registry or TextSimilarityRegistry()

    def _draft(self, context: Dict[str, Any], fmt: str, prompt: str) -> str:
        if self.provider is None:
            raise RuntimeError("LLM generation unavailable: ANTHROPIC_API_KEY is not configured")
        result = self.provider(prompt)
        if isinstance(result, dict):
            return result
        return {"text": str(result).strip(), "api_call": {"provider": "custom", "model": None, "input_tokens": None, "output_tokens": None, "response_id": None}}

    def _validate_text(self, text: str, context: Dict[str, Any]) -> None:
        lowered = text.lower()
        if any(term in lowered for term in PROCESS_LANGUAGE):
            raise QualitativeContentError("process/compliance language")
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in PROHIBITED_RECOMMENDATION_PATTERNS):
            raise QualitativeContentError("directional recommendation language")
        if any(cliche in lowered for cliche in TEMPLATE_CLICHES):
            raise QualitativeContentError("template cliche")
        if any(name.lower() in lowered for name in INTERNAL_FIELD_NAMES):
            raise QualitativeContentError("internal field name leaked")
        # Any number must correspond to a validated KPI's human-formatted
        # representation or to a source-backed non-KPI fact.
        numeric_text = re.sub(r"20\d{2}-Q\d", "", text)
        numeric_text = re.sub(r"\[\d+[–-]\d+s[^\]]*\]", "", numeric_text)
        numbers = re.findall(r"(?<![A-Za-z_])\d+(?:[.,]\d+)?", numeric_text)
        if numbers:
            allowed = []
            for item in context.get("validated_kpis") or []:
                allowed.extend(re.findall(r"\d+(?:[.,]\d+)?", format_human_number(item.get("value"), item.get("unit"))))
            if not all(number in allowed for number in numbers):
                raise QualitativeContentError("numeric value without matching validated fact")

    def generate(self, context: Dict[str, Any], fmt: str) -> Dict[str, Any]:
        if self.provider is None:
            # Missing credentials are an operational configuration error, not
            # a content-generation failure eligible for a silent retry.
            raise RuntimeError("LLM generation unavailable: ANTHROPIC_API_KEY is not configured")
        feedback = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                draft = self._draft(context, fmt, build_llm_prompt(context, fmt, feedback))
                text = str(draft.get("text") or "").strip()
                self._validate_text(text, context)
                repeated = self.similarity_registry.repeated_phrase(text)
                if repeated:
                    raise QualitativeContentError(f"repeated five-word phrase: {repeated}")
                result = {
                    "schema": "prometheus.llm_qualitative_content.v1", "format": fmt,
                    "ticker": context["ticker"], "company_name": context["company_name"],
                    "text": text, "claims": list(context.get("public_facts") or []),
                    "sources": list(context.get("sources") or []), "interpretation": list(context.get("interpretation") or []),
                    "limitations": list(context.get("limitations") or []), "human_review_required": True,
                    "generation_attempts": attempt, "generation_failed": False,
                    "api_call": draft.get("api_call") or {},
                }
                result["validation"] = QualitativeContentGenerator.validate(result)
                self.similarity_registry.record(text, {"ticker": context.get("ticker"), "format": fmt, "api_call": result["api_call"]})
                return result
            except Exception as error:
                feedback = str(error)
        return {
            "schema": "prometheus.llm_qualitative_content.v1", "format": fmt,
            "ticker": context.get("ticker"), "company_name": context.get("company_name"),
            "text": "", "claims": [], "sources": list(context.get("sources") or []),
            "interpretation": [], "limitations": list(context.get("limitations") or []),
            "human_review_required": True, "generation_attempts": self.max_attempts,
            "generation_failed": True, "generation_failure_reason": feedback,
            "api_call": {},
            "validation": {"status": "FAIL", "reason": feedback},
        }
