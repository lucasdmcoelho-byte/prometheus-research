"""Evidence-labelled qualitative content for visibility channels.

This layer is deliberately downstream and additive: it does not alter a
research score, editorial gate, or sector KPI extraction.  It turns a company
snapshot plus already-collected feed records into human-reviewable copy while
keeping public facts, interpretation, and missing validation separate.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from prometheus.knowledge_store import KnowledgeStore
from prometheus.sector_models import SectorModel, resolve_sector_model


class QualitativeContentError(ValueError):
    """Raised when qualitative content would violate its publication contract."""


# These patterns describe an instruction or directional claim, not the word
# "vendas" when it appears as a validated operational metric.
PROHIBITED_RECOMMENDATION_PATTERNS = (
    r"\bcompre\b", r"\bcomprar\b", r"\bcompren\b", r"\bvenda agora\b",
    r"\bvender\b", r"\bpre[cç]o[- ]alvo\b", r"\balvo de pre[cç]o\b",
    r"\bdeve(?:m)?\s+(?:subir|cair)\b", r"\bvai\s+(?:subir|cair)\b",
    r"\brecomenda[cç][aã]o\s+de\s+(?:compra|venda)\b",
    r"\bentrar\s+na\s+posi[cç][aã]o\b", r"\bretorno\s+esperado\b",
)


@dataclass(frozen=True)
class FactSource:
    source_id: str
    source: str
    date: Optional[str] = None
    period: Optional[str] = None
    url: Optional[str] = None
    sha256: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source": self.source,
            "date": self.date,
            "period": self.period,
            "url": self.url,
            "sha256": self.sha256,
        }


class CompanyContextEngine:
    """Build a source-labelled qualitative context from existing records."""

    def __init__(self, knowledge_store: Optional[KnowledgeStore] = None):
        self.knowledge_store = knowledge_store or KnowledgeStore()

    @staticmethod
    def _source(source_id: str, record: Dict[str, Any], default: str) -> FactSource:
        return FactSource(
            source_id=source_id,
            source=str(record.get("source") or record.get("subject") or default),
            date=str(record.get("published_at") or record.get("publication_date") or record.get("delivered_at") or record.get("date") or "") or None,
            period=str(record.get("period") or record.get("reference_date") or "") or None,
            url=record.get("url") or record.get("source_url"),
            sha256=record.get("source_sha256") or record.get("raw_document_sha256"),
        )

    @staticmethod
    def _source_dict(source: FactSource) -> Dict[str, Any]:
        return source.as_dict()

    def build(
        self,
        ticker: str,
        company_name: str,
        *,
        report: Optional[Dict[str, Any]] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        business_summary: Optional[str] = None,
        as_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        ticker = str(ticker or "").strip().upper()
        company_name = str(company_name or "").strip()
        if not ticker or not company_name:
            raise QualitativeContentError("ticker and company_name are required")
        report = report or {}
        sector = sector or report.get("sector_name") or (report.get("asset_profile") or {}).get("sector")
        industry = industry or report.get("industry_name") or (report.get("asset_profile") or {}).get("industry")
        model = resolve_sector_model(sector, industry)
        cutoff = as_of or report.get("analysis_as_of") or report.get("as_of")

        claims: List[Dict[str, Any]] = []
        sources: Dict[str, FactSource] = {}

        def add_fact(text: str, record: Dict[str, Any], default_source: str, *, source_id: str) -> None:
            source = self._source(source_id, record, default_source)
            sources[source.source_id] = source
            claims.append({"classification": "PUBLIC_FACT", "text": text, "source_id": source.source_id})

        # A supplied research snapshot is an explicit input source.  It is not
        # silently upgraded to an official filing.
        profile_record = {
            "source": "PROMETHEUS company profile input",
            "publication_date": cutoff,
            "source_url": report.get("profile_source_url"),
        }
        summary = business_summary or report.get("business_summary")
        if summary:
            add_fact(f"{company_name}: {str(summary).strip()}", profile_record, "PROMETHEUS company profile input", source_id="profile")
        add_fact(f"{company_name} está classificada publicamente no setor {sector or model.label}.", {
            "source": "CVM/B3 classification in supplied snapshot", "publication_date": cutoff,
            "source_url": report.get("classification_source_url"),
        }, "CVM/B3 classification in supplied snapshot", source_id="classification")

        # The sector model contributes interpretation only; it does not claim
        # an issuer-specific KPI or competitive ranking.
        interpretation = {
            "kind": "QUALITATIVE_CONTEXT",
            "text": (
                f"No contexto de {model.label.lower()}, o modelo de negócio se relaciona a "
                f"{', '.join(model.drivers[:3])}. A exposição relevante inclui "
                f"{', '.join(model.macro_series[:3])}, além dos riscos de "
                f"{', '.join(model.risks[:3])}."
            ),
            "basis": "PROMETHEUS sector taxonomy",
        }

        records = [r for r in self.knowledge_store.get_by_ticker(ticker) if self._before_cutoff(r, cutoff)]
        records.sort(key=lambda r: str(r.get("published_at") or r.get("timestamp_collected") or ""), reverse=True)
        for index, record in enumerate(records[:2], start=1):
            title = str(record.get("title") or record.get("event") or record.get("text") or "").strip()
            if title:
                add_fact(f"Evento reportado: {title}", record, "KnowledgeStore/news feed", source_id=f"news-{index}")

        macro_facts: List[Dict[str, Any]] = []
        for index, observation in enumerate(report.get("macro_observations") or [], start=1):
            if not isinstance(observation, dict) or not observation.get("metric") or not observation.get("point_in_time_eligible", True):
                continue
            # Keep macro context qualitative by default.  If a number is later
            # rendered, this record is still available as its citation.
            macro_facts.append({
                "metric": observation.get("metric"),
                "source_id": f"macro-{index}",
                "text": f"O cenário macro inclui a série oficial {observation.get('metric')}.",
            })
            source = self._source(f"macro-{index}", observation, "Banco Central do Brasil - SGS")
            sources[source.source_id] = source
            claims.append({"classification": "PUBLIC_FACT", "text": macro_facts[-1]["text"], "source_id": source.source_id})

        validated_kpis: List[Dict[str, Any]] = []
        operational = report.get("operational_kpis") or {}
        for metric, item in (operational.get("metrics") or {}).items():
            if not isinstance(item, dict) or item.get("status") != "AVAILABLE" or item.get("value") is None:
                continue
            source = self._source(f"kpi-{metric}", item, "official operational document")
            if not source.sha256 or not source.period:
                continue
            sources[source.source_id] = source
            fact = {
                "metric": metric,
                "value": item.get("value"),
                "unit": item.get("unit"),
                "period": item.get("period"),
                "text": f"KPI validado: {metric} = {item.get('value')} {item.get('unit') or ''} no período {item.get('period')}.",
                "source_id": source.source_id,
            }
            validated_kpis.append(fact)
            claims.append({"classification": "VALIDATED_KPI", "text": fact["text"], "source_id": source.source_id})

        limitations = []
        if not validated_kpis:
            limitations.append("Não há KPI operacional validado e rastreável para esta empresa neste snapshot; o conteúdo não usa números operacionais específicos.")
        return {
            "schema": "prometheus.company_qualitative_context.v1",
            "ticker": ticker,
            "company_name": company_name,
            "sector": sector or model.label,
            "industry": industry,
            "as_of": cutoff,
            "business_model": {
                "text": f"A empresa é descrita pelo perfil fornecido; a forma específica de monetização deve ser confirmada no documento primário citado.",
                "source_id": "profile",
            },
            "public_facts": claims,
            "interpretation": [interpretation],
            "validated_kpis": validated_kpis,
            "macro_facts": macro_facts,
            "limitations": limitations,
            "sources": [self._source_dict(source) for source in sources.values()],
        }

    @staticmethod
    def _before_cutoff(record: Dict[str, Any], cutoff: Optional[str]) -> bool:
        if not cutoff:
            return True
        published = record.get("published_at") or record.get("publication_date") or record.get("date")
        if not published:
            return False
        return str(published)[:10] <= str(cutoff)[:10]


def export_context_package(context: Dict[str, Any], destination: str) -> str:
    """Persist a clean, human-readable evidence package for offline authorship.

    This is intentionally an export-only helper: it does not alter the
    quantitative snapshot or the API-backed generation path.
    """
    payload = {
        "schema": "prometheus.company_qualitative_context_export.v1",
        "ticker": context.get("ticker"),
        "company_name": context.get("company_name"),
        "as_of": context.get("as_of"),
        "facts_with_sources": context.get("public_facts", []),
        "sources": context.get("sources", []),
        "business_model": context.get("business_model", {}),
        "qualitative_context": context.get("interpretation", []),
        "macro_context": context.get("macro_facts", []),
        "validated_kpis": context.get("validated_kpis", []),
        "limitations": context.get("limitations", []),
    }
    path = str(destination)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


class QualitativeContentGenerator:
    """Render short-form formats from one and only one company context."""

    def __init__(self, context_engine: CompanyContextEngine, llm_provider=None, similarity_registry=None):
        self.context_engine = context_engine
        from prometheus.llm_content import LLMQualitativeGenerator
        self.llm_generator = LLMQualitativeGenerator(provider=llm_provider, similarity_registry=similarity_registry)

    @staticmethod
    def _source_tags(context: Dict[str, Any]) -> str:
        return " ".join(f"[{claim['source_id']}]" for claim in context.get("public_facts") or [])

    @classmethod
    def validate(cls, content: Dict[str, Any]) -> Dict[str, Any]:
        text = str(content.get("text") or "")
        lowered = text.lower()
        violations = [pattern for pattern in PROHIBITED_RECOMMENDATION_PATTERNS if re.search(pattern, lowered, re.IGNORECASE)]
        claim_ids = {str(item.get("source_id")) for item in content.get("claims") or []}
        source_ids = {str(item.get("source_id")) for item in content.get("sources") or []}
        missing_sources = sorted(claim_ids - source_ids)
        numeric_claims_without_source = []
        for claim in content.get("claims") or []:
            if re.search(r"\b\d+(?:[.,]\d+)?\b", str(claim.get("text") or "")) and not claim.get("source_id"):
                numeric_claims_without_source.append(claim.get("text"))
        if violations or missing_sources or numeric_claims_without_source:
            raise QualitativeContentError({"recommendation_terms": violations, "missing_sources": missing_sources, "numeric_claims_without_source": numeric_claims_without_source})
        return {"status": "PASS", "recommendation_terms": [], "missing_sources": [], "numeric_claims_without_source": []}

    def _base(self, fmt: str, context: Dict[str, Any], text: str) -> Dict[str, Any]:
        content = {
            "schema": "prometheus.qualitative_content.v1",
            "format": fmt,
            "ticker": context["ticker"],
            "company_name": context["company_name"],
            "text": text,
            "claims": list(context.get("public_facts") or []),
            "sources": list(context.get("sources") or []),
            "interpretation": list(context.get("interpretation") or []),
            "limitations": list(context.get("limitations") or []),
            "human_review_required": True,
        }
        content["validation"] = self.validate(content)
        return content

    def post(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.llm_generator.generate(context, "short_post")

    def video_script(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.llm_generator.generate(context, "video_script_60_90s")

    def question_of_the_moment(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.llm_generator.generate(context, "question_of_the_moment")
