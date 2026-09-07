from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Optional


GENERIC_KPI_SCHEMA = {
    "revenue_by_segment": {"unit": "BRL", "evidence": "official_segment_table"},
    "margin_by_segment": {"unit": "percentage", "evidence": "official_segment_table"},
}


class SectorModule(ABC):
    """Plug-in contract for deterministic, evidence-bound sector extraction."""

    key: str

    @abstractmethod
    def kpi_schema(self) -> Dict[str, Dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def extract(self, official_disclosures: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def validate(self, result: Dict[str, Any]) -> Dict[str, Any]:
        invalid = [name for name, item in (result.get("metrics") or {}).items()
                   if item.get("status") == "AVAILABLE" and not all(item.get(field) for field in ("unit", "period", "raw_document_sha256"))]
        return {"status": "PASS" if not invalid else "FAIL", "invalid_metrics": invalid}


class GenericSectorModule(SectorModule):
    key = "generic"

    def kpi_schema(self) -> Dict[str, Dict[str, str]]:
        return dict(GENERIC_KPI_SCHEMA)

    def extract(self, official_disclosures: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "NOT_APPLICABLE", "sector_key": self.key, "sector_coverage": "GENERIC", "metrics": {}, "available_count": 0, "required_count": 0, "method": "generic module: no sector-specific operational extraction"}


class ExtractorBackedSectorModule(SectorModule):
    def __init__(self, key: str, extractor: "OperationalKPIExtractor", kpis: tuple[str, ...]):
        self.key, self.extractor, self.kpis = key, extractor, kpis

    def kpi_schema(self) -> Dict[str, Dict[str, str]]:
        return {**GENERIC_KPI_SCHEMA, **{name: {"unit": "sector_declared", "evidence": "retained_official_document"} for name in self.kpis}}

    def extract(self, official_disclosures: Dict[str, Any]) -> Dict[str, Any]:
        result = self.extractor._extract_for_sector(official_disclosures, self.key)
        result["sector_coverage"] = "DEDICATED"
        result["validation"] = self.validate(result)
        return result


class SectorRegistry:
    """Central mapping from a resolved CVM sector model to an extractor module."""

    def __init__(self, extractor: "OperationalKPIExtractor"):
        self._modules = {
            "real_estate": ExtractorBackedSectorModule("real_estate", extractor, extractor.REAL_ESTATE_KPIS),
            "healthcare": ExtractorBackedSectorModule("healthcare", extractor, extractor.HEALTHCARE_KPIS),
        }
        self._generic = GenericSectorModule()

    def resolve(self, sector_key: str) -> SectorModule:
        return self._modules.get(str(sector_key or ""), self._generic)


class OperationalKPIExtractor:
    """Extract conservative sector KPIs from retained CVM IPE documents.

    Patterns are anchored to company-labelled tables.  A nearby number is not
    enough: when the label/table cannot be identified exactly, the field stays
    INSUFFICIENT_DATA.
    """

    REAL_ESTATE_KPIS = (
        "lançamentos", "vendas_brutas", "vendas_líquidas", "vso", "distratos",
        "unidades_lançadas", "unidades_vendidas", "ticket_médio", "unidades_entregues",
        "margem_bruta_ajustada", "margem_ref", "receita_a_apropriar", "landbank",
        "geração_de_caixa", "repasses", "estoque_pronto", "estoque_em_construção",
        "participação_no_mcmv",
    )
    HEALTHCARE_KPIS = (
        "beneficiarios_saude", "beneficiarios_odonto", "ticket_medio_mensal_saude",
        "sinistralidade_caixa", "churn", "cancelamentos", "rede_propria", "rede_credenciada",
        # Integrated health groups can be both payer and provider.  These
        # provider metrics deliberately have distinct names from insurer
        # metrics: a hospital occupancy rate must never be presented as a
        # health-plan utilisation or loss-ratio proxy.
        "leitos_totais", "taxa_media_ocupacao_leitos", "pacientes_dia",
        "procedimentos_cirurgicos", "hospitais_operados", "beneficiarios_saude_e_odonto",
        "sinistralidade_consolidada",
    )

    def __init__(self):
        self.registry = SectorRegistry(self)

    def extract(self, disclosures: Dict[str, Any], sector_key: str) -> Dict[str, Any]:
        return self.registry.resolve(sector_key).extract(disclosures)

    def _extract_for_sector(self, disclosures: Dict[str, Any], sector_key: str) -> Dict[str, Any]:
        sector_key = str(sector_key or "")
        required_kpis = {
            "real_estate": self.REAL_ESTATE_KPIS,
            "healthcare": self.HEALTHCARE_KPIS,
        }.get(sector_key)
        if not required_kpis:
            return {
                "status": "NOT_APPLICABLE", "sector_key": sector_key,
                "metrics": {}, "available_count": 0, "required_count": 0,
            }
        candidates = [
            item for item in (disclosures.get("documents") or [])
            if self._is_relevant_retained(item)
        ]
        candidates.sort(key=lambda item: str(item.get("delivered_at") or ""), reverse=True)
        metrics: Dict[str, Dict[str, Any]] = {
            name: {
                "status": "INSUFFICIENT_DATA",
                "reason": "FIELD_NOT_UNAMBIGUOUS_IN_RETAINED_OPERATIONAL_DOCUMENTS",
            }
            for name in required_kpis
        }
        selected_period = None
        used_protocols = []
        # Prefer the latest period, but allow the release and preview for that
        # same period to complement one another.
        latest = next((self._period_token(item) for item in candidates if self._period_token(item)), None)
        for document in candidates:
            token = self._period_token(document)
            if latest and token != latest:
                continue
            selected_period = selected_period or self._period_label(token)
            used_protocols.append(str(document.get("protocol") or ""))
            for name, extracted in self._extract_document(document, token, sector_key).items():
                if metrics[name]["status"] != "AVAILABLE":
                    metrics[name] = extracted
        available_count = sum(item.get("status") == "AVAILABLE" for item in metrics.values())
        return {
            "status": "AVAILABLE" if available_count else "INSUFFICIENT_DATA",
            "sector_key": sector_key,
            "period": selected_period,
            "metrics": metrics,
            "available_count": available_count,
            "required_count": len(required_kpis),
            "missing": [name for name, item in metrics.items() if item.get("status") != "AVAILABLE"],
            "relevant_document_count": len(candidates),
            "selected_protocols": [item for item in used_protocols if item],
            "method": "sector-specific label-anchored deterministic extraction from retained CVM IPE PDF text",
        }

    def source_records(self, result: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
        for metric, item in (result.get("metrics") or {}).items():
            if item.get("status") != "AVAILABLE":
                continue
            yield {
                "metric": metric,
                "value": item["value"],
                "unit": item["unit"],
                "period": item["period"],
                "reference_date": item["reference_date"],
                "publication_date": item["publication_date"],
                "source": item["source"],
                "source_type": "primary",
                "confidence": "high",
                "source_tier": "TIER_1",
                "source_url": item["source_url"],
                "source_sha256": item["raw_document_sha256"],
                "source_sha256_components": item["source_sha256_components"],
                "protocol": item["protocol"],
                "version": item["version"],
                "raw_document_cache_path": item["raw_document_cache_path"],
                "extraction_method": item["extraction_method"],
                "evidence_text": item["evidence_text"],
                "claim_text": item["claim_text"],
            }

    def _extract_document(self, document: Dict[str, Any], token: Optional[str], sector_key: str) -> Dict[str, Dict[str, Any]]:
        text = self._normalize_text(str(document.get("extracted_text") or ""))
        if not text:
            return {}
        period_token = re.escape(token or r"[1-4]T\d{2}")
        real_estate_specs = {
            "lançamentos": (r"VGV lan[çc]ado\s*(?:¹|1)?\s*\(R\$ milh[oõ]es\)\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "vendas_brutas": (r"Vendas Brutas\s*\(R\$ milh[oõ]es VGV\)\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "vendas_líquidas": (r"Vendas L[íi]quidas\s*\(R\$ milh[oõ]es(?: VGV)?\)\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "vso": (r"VSO L[íi]quida\s*(?:²|2)?\s*([\d.,]+)%", "percentage", 0.01),
            "distratos": (r"Distratos\s*\(R\$ milh[oõ]es\)\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "unidades_lançadas": (rf"Lançamentos\s+{period_token}.*?N[uú]mero de Unidades\s+([\d.]+)", "units", 1),
            "unidades_vendidas": (rf"Vendas,\s*%VSO\s+{period_token}.*?Vendas Brutas.*?N[uú]mero de Unidades\s+([\d.]+)", "units", 1),
            "ticket_médio": (rf"Vendas,\s*%VSO\s+{period_token}.*?Pre[çc]o M[ée]dio/Unid\.\s*\(R\$ mil\)\s*([\d.]+,\d+)", "BRL/unit", 1_000),
            "margem_bruta_ajustada": (r"Margem bruta ajustada\s*(?:³|3)?\s*([\d.,]+)%", "percentage", 0.01),
            "margem_ref": (r"Margem Bruta REF\s*([\d.,]+)%", "percentage", 0.01),
            "receita_a_apropriar": (r"Receitas de vendas a apropriar\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "landbank": (r"Banco de Terrenos\s*\(VGV, R\$ milh[oõ]es\)\s*([\d.]+,\d+)\*?", "BRL", 1_000_000),
            "geração_de_caixa": (r"Gera[çc][aã]o de Caixa\s*\(R\$ milh[oõ]es\)\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "repasses": (r"VGV Repassado\s*\(R\$ milh[oõ]es\)\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "estoque_pronto": (rf"Estoque\s*\(R\$ milh[oõ]es, exceto % e unidades\)\s*{period_token}.*?Conclu[íi]do\s*([\d.]+,\d+)", "BRL", 1_000_000),
            "estoque_em_construção": (rf"Estoque\s*\(R\$ milh[oõ]es, exceto % e unidades\)\s*{period_token}.*?Em andamento\s*([\d.]+,\d+)", "BRL", 1_000_000),
        }
        healthcare_specs = {
            "beneficiarios_saude": (r"Benefici[aá]rios de Sa[uú]de\s*\(EoP\)\s*([\d.]+,\d+)\s*k", "beneficiaries", 1_000),
            "beneficiarios_odonto": (r"Benefici[aá]rios de Odonto\s*\(EoP\)\s*([\d.]+,\d+)\s*k", "beneficiaries", 1_000),
            "ticket_medio_mensal_saude": (r"Ticket M[eé]dio Mensal Sa[uú]de\s*R?\$?\s*([\d.]+,\d+)", "BRL/beneficiary/month", 1),
            "sinistralidade_caixa": (r"Sinistralidade\s+Caixa\s*([\d.,]+)%", "percentage", 0.01),
            # Cancellation and network labels vary materially by issuer.  These
            # patterns accept an explicit labelled value only; they never infer
            # a rate from charts, admissions or qualitative prose.
            "churn": (r"\bChurn\s*(?:\([^)]*\))?\s*([\d.,]+)%", "percentage", 0.01),
            "cancelamentos": (r"Cancelamentos\s*(?:\([^)]*\))?\s*([\d.]+,\d+|[\d.]+)\s*(?:mil|k)?", "beneficiaries", 1),
            "rede_propria": (r"Rede Pr[oó]pria\s*(?:com|de)?\s*([\d.]+)\s*(?:unidades|hospitais|cl[ií]nicas)", "units", 1),
            "rede_credenciada": (r"Rede Credenciada\s*(?:com|de)?\s*([\d.]+)\s*(?:prestadores|unidades|hospitais|cl[ií]nicas)", "units", 1),
            # Provider / integrated-care metrics.  The wording in the
            # patterns is the issuer's explicit label or declarative sentence;
            # no chart-series alignment or inferred value is accepted.
            "leitos_totais": (r"somando\s+([\d.]+)\s+leitos\s+totais", "beds", 1),
            "taxa_media_ocupacao_leitos": (r"Taxa\s+m(?:[eé]|�)dia\s+de\s+ocupa(?:[çc]|�)[aã](?:o|�)(?:\s+de\s+leitos)?\s+(?:atinge|atingiu|de)\s*([\d.,]+)%", "percentage", 0.01),
            "pacientes_dia": (r"Volume\s+de\s+pacientes[-\s]?dia\s+(?:recorde\s+de\s+)?([\d.]+)\s*mil", "patient-days", 1_000),
            "procedimentos_cirurgicos": (r"volume\s+cir(?:[úu]|�)rgico.*?(?:com|de)\s+([\d.]+)\s*mil\s+procedimentos", "procedures", 1_000),
            "hospitais_operados": (r"operava\s+([\d.]+)\s+hospitais", "hospitals", 1),
            "beneficiarios_saude_e_odonto": (r"Base\s+de\s+benefici[aá]rios.*?(?:atinge\s+(?:a\s+)?marca\s+de|total(?:iza)?\s+de)\s*([\d.,]+)\s+milh[õo]es", "beneficiaries", 1_000_000),
            "sinistralidade_consolidada": (r"Sinistralidade(?:\s*consolidada)?\s*(?:m(?:[eé]|�)dia)?\s*(?:de)?\s*([\d.,]+)%", "percentage", 0.01),
        }
        specs = real_estate_specs if sector_key == "real_estate" else healthcare_specs if sector_key == "healthcare" else {}
        output: Dict[str, Dict[str, Any]] = {}
        for metric, (pattern, unit, multiplier) in specs.items():
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            raw_value = match.group(1)
            value = self._parse_pt_number(raw_value) * multiplier
            if unit in {"units", "beneficiaries", "beds", "patient-days", "procedures", "hospitals"}:
                value = int(round(value))
            excerpt = self._normalize_text(match.group(0))[:600]
            output[metric] = self._record(
                document=document, metric=metric, value=value, unit=unit,
                period=self._period_label(token), evidence_text=excerpt,
            )
        return output

    @staticmethod
    def _record(
        *, document: Dict[str, Any], metric: str, value: Any, unit: str,
        period: str, evidence_text: str,
    ) -> Dict[str, Any]:
        raw_hash = str(document.get("raw_document_sha256") or "")
        archive_hash = str(document.get("source_sha256") or "")
        return {
            "status": "AVAILABLE", "metric": metric, "value": value, "unit": unit,
            "period": period, "reference_date": str(document.get("reference_date") or ""),
            "publication_date": str(document.get("delivered_at") or ""),
            "source": f"CVM IPE - {document.get('subject') or document.get('category')}",
            "source_url": document.get("source_url"), "protocol": document.get("protocol"),
            "version": document.get("version"), "raw_document_sha256": raw_hash,
            "source_sha256_components": [item for item in (archive_hash, raw_hash) if len(item) == 64],
            "raw_document_cache_path": document.get("raw_document_cache_path"),
            "extraction_method": "operational_kpi.sector_label_anchored_regex.v2",
            "evidence_text": evidence_text,
            "claim_text": f"{metric} no período {period}: {value} {unit}",
        }

    @staticmethod
    def _is_relevant_retained(document: Dict[str, Any]) -> bool:
        subject = str(document.get("subject") or "").lower()
        relevant = any(token in subject for token in (
            "prévia operacional", "previa operacional", "release de resultados", "apresentação de resultados",
        ))
        return (
            relevant
            and document.get("content_scope") == "ANALYSIS_INCLUDED"
            and document.get("raw_document_status") == "RETAINED"
            and document.get("content_extraction_status") == "EXTRACTED"
            and len(str(document.get("raw_document_sha256") or "")) == 64
        )

    @staticmethod
    def _period_token(document: Dict[str, Any]) -> Optional[str]:
        match = re.search(r"([1-4]T\d{2})", str(document.get("subject") or ""), flags=re.IGNORECASE)
        return match.group(1).upper() if match else None

    @staticmethod
    def _period_label(token: Optional[str]) -> str:
        if not token:
            return "INSUFFICIENT_DATA"
        quarter, year = int(token[0]), int(token[-2:])
        return f"20{year:02d}-Q{quarter}"

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(str(value or "").split())

    @staticmethod
    def _parse_pt_number(value: str) -> float:
        return float(str(value).replace(".", "").replace(",", "."))
