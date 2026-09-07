from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List

from prometheus.business_quality import BusinessQualityEngine
from prometheus.evidence_engine import EvidenceEngine
from prometheus.semantic_consistency import normalize_text, sector_contamination


class EditorialGate:
    """Hard release gate. A failed report may be previewed, never delivered."""

    REQUIRED_SECTIONS = ("research", "valuation", "risk", "financial_history", "sector_model")

    def evaluate(self, report: Dict[str, Any]) -> Dict[str, Any]:
        blockers: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []

        if report.get("data_source_status") == "DEGRADED":
            degradation = report.get("data_source_degradation") or {}
            warnings.append({
                "code": "DATA_SOURCE_DEGRADED",
                "detail": str(degradation.get("reason") or "PRIMARY_SOURCE_UNAVAILABLE"),
                "message": "Fonte primária indisponível neste corte; o relatório usa somente dados secundários/mercado.",
            })
        regression = report.get("regression_alert") or {}
        if regression.get("status") == "REGRESSION_ALERT":
            warnings.append({
                "code": "REGRESSION_ALERT",
                "detail": "; ".join(
                    f"{item.get('metric')}:{item.get('previous')}→{item.get('current')}"
                    for item in (regression.get("alerts") or [])
                ),
                "message": "Queda abrupta de cobertura versus o corte anterior; revisão humana obrigatória antes de circulação.",
            })

        for key in ("ticker", "company_name", "analysis_as_of"):
            if not report.get(key):
                blockers.append({"code": "MISSING_IDENTITY", "detail": key})
        for section in self.REQUIRED_SECTIONS:
            if report.get(section) in (None, {}, []):
                blockers.append({"code": "MISSING_SECTION", "detail": section})

        cutoff = self._parse_date(report.get("analysis_as_of"))
        sources = (report.get("research") or {}).get("sources") or []
        for source in sources:
            publication = self._parse_date(source.get("publication_date"))
            if cutoff and publication and publication > cutoff:
                blockers.append({"code": "LOOKAHEAD_SOURCE", "detail": str(source.get("source_id") or source.get("metric"))})
            if source.get("value") is not None:
                missing_fields = [
                    field for field in ("unit", "period", "publication_date", "source")
                    if EvidenceEngine._is_missing_provenance(source.get(field))
                ]
                if missing_fields:
                    blockers.append({
                        "code": "NUMERIC_SOURCE_PROVENANCE",
                        "detail": f"{source.get('metric')}: {','.join(missing_fields)}",
                    })
                if str(source.get("source") or "").upper().startswith("CVM"):
                    hashes = [source.get("source_sha256"), *(source.get("source_sha256_components") or [])]
                    if not any(isinstance(value, str) and len(value) == 64 for value in hashes):
                        blockers.append({"code": "CVM_RAW_HASH_MISSING", "detail": str(source.get("metric"))})
            elif EvidenceEngine._is_missing_provenance(source.get("period")) or EvidenceEngine._is_missing_provenance(source.get("publication_date")):
                warnings.append({
                    "code": "INCOMPLETE_PROVENANCE", "detail": str(source.get("metric")),
                    "message": f"A fonte {source.get('metric')} não possui período ou data de disponibilidade completos.",
                })

        claims = report.get("claims") or []
        if not claims:
            blockers.append({"code": "MISSING_CLAIM_LEDGER", "detail": "claims"})
        sector_key = str((report.get("sector_model") or {}).get("key") or "general")
        claim_audit = EvidenceEngine().audit_claims(
            claims, sources=sources, cutoff=report.get("analysis_as_of"), sector_key=sector_key,
        )
        for item in claim_audit["issues"]:
            code = "SEMANTIC_CONTAMINATION" if str(item["reason"]).startswith("semantic_contamination:") else "CLAIM_AUDIT"
            blockers.append({"code": code, "detail": f"{item['claim_id']}:{item['reason']}"})

        valuation = report.get("valuation") or {}
        if valuation.get("status") == "AVAILABLE" and not valuation.get("assumptions"):
            blockers.append({"code": "VALUATION_WITHOUT_ASSUMPTIONS", "detail": "valuation"})
        if valuation.get("status") != "AVAILABLE":
            blockers.append({"code": "VALUATION_INCOMPLETE", "detail": str(valuation.get("status") or "missing")})
        else:
            if not valuation.get("formula"):
                blockers.append({"code": "VALUATION_FORMULA_MISSING", "detail": "valuation"})
            if not str((valuation.get("assumptions") or {}).get("assumption_source") or "").strip():
                blockers.append({"code": "VALUATION_ASSUMPTION_SOURCE_MISSING", "detail": "valuation"})
            scenarios = valuation.get("scenarios") or {}
            if set(scenarios) != {"bear", "base", "bull"}:
                blockers.append({"code": "VALUATION_SCENARIOS_INCOMPLETE", "detail": ",".join(sorted(scenarios))})
            implied_values = []
            for name in ("bear", "base", "bull"):
                scenario = scenarios.get(name) or {}
                if not scenario.get("formula"):
                    blockers.append({"code": "VALUATION_FORMULA_MISSING", "detail": name})
                inputs = scenario.get("input_values") or {}
                if not inputs:
                    blockers.append({"code": "VALUATION_INPUTS_MISSING", "detail": name})
                implied = scenario.get("implied_value_per_share")
                multiple = scenario.get("multiple")
                if not isinstance(implied, (int, float)) or implied <= 0 or not isinstance(multiple, (int, float)) or multiple <= 0:
                    blockers.append({"code": "VALUATION_SCENARIO_INVALID", "detail": name})
                    continue
                implied_values.append(float(implied))
                price = report.get("price")
                reported_delta = scenario.get("upside_downside")
                if isinstance(price, (int, float)) and price > 0 and isinstance(reported_delta, (int, float)):
                    expected_delta = float(implied) / float(price) - 1.0
                    if abs(expected_delta - float(reported_delta)) > 1e-4:
                        blockers.append({"code": "VALUATION_RECONCILIATION_FAILED", "detail": name})
                if isinstance(implied, (int, float)) and inputs:
                    if "ttm_ebit" in inputs:
                        required = (inputs.get("ttm_ebit"), inputs.get("scenario_multiple"), inputs.get("net_debt"), inputs.get("shares"))
                        expected_implied = (
                            (float(required[0]) * float(required[1]) - float(required[2])) / float(required[3])
                            if all(isinstance(value, (int, float)) for value in required) and float(required[3]) > 0 else None
                        )
                    else:
                        basis = inputs.get("future_eps", inputs.get("book_value_per_share"))
                        input_multiple = inputs.get("scenario_multiple")
                        expected_implied = float(basis) * float(input_multiple) if isinstance(basis, (int, float)) and isinstance(input_multiple, (int, float)) else None
                    if expected_implied is None or abs(expected_implied - float(implied)) > 1e-3:
                        blockers.append({"code": "VALUATION_INPUT_RECONCILIATION_FAILED", "detail": name})
            if len(implied_values) == 3 and implied_values != sorted(implied_values):
                blockers.append({"code": "VALUATION_SCENARIO_ORDER_INVALID", "detail": "bear/base/bull"})

        contradiction = (report.get("research") or {}).get("contradiction_matrix")
        if not contradiction:
            blockers.append({"code": "MISSING_CONTRADICTION_MATRIX", "detail": "research.contradiction_matrix"})
        peer_analysis = (report.get("research") or {}).get("peer_analysis") or {}
        if peer_analysis.get("status") == "AVAILABLE" and peer_analysis.get("compatible_period_count") is not None:
            if int(peer_analysis.get("compatible_period_count") or 0) < 2:
                blockers.append({"code": "INCOMPATIBLE_PEER_PERIODS", "detail": str(peer_analysis.get("compatible_period_count"))})
            if int(peer_analysis.get("eligible_multiple_count") or 0) < 2:
                blockers.append({"code": "INSUFFICIENT_ELIGIBLE_PEERS", "detail": str(peer_analysis.get("eligible_multiple_count"))})
        for document in (report.get("official_disclosures") or {}).get("documents") or []:
            content_scope = document.get("content_scope") or "ANALYSIS_INCLUDED"
            if content_scope == "ANALYSIS_INCLUDED" and (
                document.get("raw_document_status") != "RETAINED" or not document.get("raw_document_sha256")
            ):
                blockers.append({
                    "code": "OFFICIAL_DOCUMENT_NOT_RETAINED",
                    "detail": str(document.get("protocol") or document.get("subject") or "document"),
                })
            elif content_scope in {"METADATA_ONLY_OUT_OF_SCOPE", "METADATA_ONLY_UNAVAILABLE"}:
                unavailable = content_scope == "METADATA_ONLY_UNAVAILABLE"
                warnings.append({
                    "code": "OFFICIAL_DOCUMENT_UNAVAILABLE" if unavailable else "OFFICIAL_DOCUMENT_METADATA_ONLY",
                    "detail": str(document.get("protocol") or document.get("subject") or "document"),
                    "message": (
                        f"Documento oficial {'indisponível para extração' if unavailable else 'fora do escopo de conteúdo'}: {document.get('subject') or document.get('category') or 'sem assunto'} "
                        f"({document.get('reference_date') or document.get('delivered_at') or 'data não informada'})."
                    ),
                })
            if document.get("content_extraction_status") in {"EXTRACTION_ERROR", "NO_MACHINE_READABLE_TEXT"}:
                warnings.append({
                    "code": "OFFICIAL_DOCUMENT_REQUIRES_VISUAL_REVIEW",
                    "detail": str(document.get("protocol") or document.get("subject") or "document"),
                    "message": "O documento oficial foi retido, mas seu conteúdo exige revisão visual humana.",
                })
        operational = report.get("operational_kpis") or {}
        relevant_operational_documents = [
            document for document in (report.get("official_disclosures") or {}).get("documents") or []
            if document.get("raw_document_status") == "RETAINED"
            and any(token in str(document.get("subject") or "").lower() for token in (
                "prévia operacional", "previa operacional", "release de resultados", "apresentação de resultados",
            ))
        ]
        relevant_count = max(
            int(operational.get("relevant_document_count") or 0),
            len(relevant_operational_documents),
        )
        if sector_key == "real_estate" and relevant_count > 0:
            critical = ("lançamentos", "vendas_líquidas", "vso", "distratos", "landbank")
            metrics = operational.get("metrics") or {}
            missing_critical = [
                name for name in critical
                if (metrics.get(name) or {}).get("status") != "AVAILABLE"
            ]
            if missing_critical:
                blockers.append({
                    "code": "SECTOR_KPI_COVERAGE_INCOMPLETE",
                    "detail": ",".join(missing_critical),
                    "message": (
                        "Documentos operacionais oficiais foram retidos, mas o parser não produziu todos os KPIs críticos: "
                        + ", ".join(missing_critical)
                    ),
                })
        ttm = report.get("ttm") or {}
        required_ttm = ("net_income",) if sector_key == "financial" else ("revenue", "net_income", "operating_cash_flow")
        missing_required_ttm = [
            name for name in required_ttm
            if not isinstance((((ttm.get("metrics") or {}).get(name) or {}).get("normalized")), (int, float))
        ]
        if ttm.get("status") == "INSUFFICIENT_DATA" or missing_required_ttm:
            detail = ",".join(missing_required_ttm or ttm.get("missing") or []) or str(ttm.get("status") or "missing")
            blockers.append({"code": "TTM_INCOMPLETE", "detail": detail})
        for name in required_ttm:
            metric = ((ttm.get("metrics") or {}).get(name) or {})
            if isinstance(metric.get("normalized"), (int, float)):
                if not metric.get("unit") or not metric.get("calculation") or not metric.get("source_rows"):
                    blockers.append({"code": "TTM_PROVENANCE_MISSING", "detail": name})
                for index, source_row in enumerate(metric.get("source_rows") or []):
                    row = source_row if isinstance(source_row, dict) else getattr(source_row, "__dict__", {})
                    if not row.get("received_at") or not row.get("reference_date") or not row.get("source_url"):
                        blockers.append({"code": "TTM_SOURCE_ROW_INCOMPLETE", "detail": f"{name}:{index}"})
                    digest = row.get("source_sha256")
                    if not isinstance(digest, str) or len(digest) != 64:
                        blockers.append({"code": "TTM_RAW_HASH_MISSING", "detail": f"{name}:{index}"})
                    received_at = self._parse_date(row.get("received_at"))
                    if cutoff and received_at and received_at > cutoff:
                        blockers.append({"code": "LOOKAHEAD_TTM_SOURCE", "detail": f"{name}:{index}"})
        for row in report.get("financial_history") or []:
            if not isinstance(row, dict):
                continue
            for name in ("revenue", "net_income", "profit_margin", "roe"):
                if not isinstance(row.get(name), (int, float)):
                    continue
                metadata = ((row.get("metric_metadata") or {}).get(name) or {})
                if not metadata.get("unit") or not metadata.get("source_rows"):
                    blockers.append({"code": "HISTORICAL_NUMERIC_PROVENANCE", "detail": f"{row.get('period')}:{name}"})
                if name in {"profit_margin", "roe"} and not metadata.get("calculation"):
                    blockers.append({"code": "HISTORICAL_FORMULA_MISSING", "detail": f"{row.get('period')}:{name}"})
                for index, source_row in enumerate(metadata.get("source_rows") or []):
                    raw = source_row if isinstance(source_row, dict) else getattr(source_row, "__dict__", {})
                    digest = raw.get("source_sha256")
                    if not raw.get("received_at") or not raw.get("reference_date") or not raw.get("source_url"):
                        blockers.append({"code": "HISTORICAL_SOURCE_ROW_INCOMPLETE", "detail": f"{row.get('period')}:{name}:{index}"})
                    if not isinstance(digest, str) or len(digest) != 64:
                        blockers.append({"code": "HISTORICAL_RAW_HASH_MISSING", "detail": f"{row.get('period')}:{name}:{index}"})
                    received_at = self._parse_date(raw.get("received_at"))
                    if cutoff and received_at and received_at > cutoff:
                        blockers.append({"code": "LOOKAHEAD_HISTORICAL_SOURCE", "detail": f"{row.get('period')}:{name}:{index}"})

        quality = float((report.get("fundamental_data_quality") or {}).get("score") or 0.0)
        if quality < 60:
            warnings.append({
                "code": "LOW_DATA_QUALITY", "detail": f"{quality:.1f}",
                "message": f"A completude dos dados financeiros está abaixo de 60/100: {quality:.1f}/100.",
            })
        research_quality = report.get("research_quality") or {}
        overall_research = float(research_quality.get("overall_research_confidence") or 0.0)
        if quality >= 90 and overall_research < 80:
            warnings.append({
                "code": "FINANCIAL_COMPLETE_RESEARCH_PARTIAL",
                "detail": f"financial={quality:.1f}; overall_research={overall_research:.1f}",
                "message": "As demonstrações financeiras estão completas, mas a cobertura global do research permanece parcial.",
            })
        # Recompute this deterministic bridge from the exact valuation being
        # gated. Saved bundles may predate the reconciliation field, and a
        # stale pre-peer snapshot must neither create nor hide a blocker.
        reconciliation = (
            BusinessQualityEngine().evaluate(report).get("valuation_reconciliation") or {}
        )
        scenarios = (report.get("valuation") or {}).get("scenarios") or {}
        scenario_deltas = [
            (scenarios.get(name) or {}).get("upside_downside") for name in ("bear", "base", "bull")
        ]
        if len(scenario_deltas) == 3 and all(isinstance(value, (int, float)) and value < 0 for value in scenario_deltas):
            if reconciliation.get("status") != "DIVERGENCE_EXPLAINED":
                blockers.append({"code": "UNEXPLAINED_SCORE_VALUATION_DIVERGENCE", "detail": "all scenarios below reference"})
            else:
                warnings.append({
                    "code": "PRICE_ABOVE_SENSITIVITY_RANGE", "detail": str(report.get("final_state")),
                    "message": (
                        "O preço de referência está acima de todos os cenários de sensibilidade; "
                        f"o estado agregado permanece {report.get('final_state')} e não constitui recomendação."
                    ),
                })
        for field in ("company_name", "business_summary"):
            if "�" in str(report.get(field) or ""):
                blockers.append({"code": "INVALID_TEXT_ENCODING", "detail": field})
        self._validate_generated_content(report, blockers)
        self._validate_score_consistency(report, blockers)
        pdf_qa = report.get("qa") or {}
        if pdf_qa.get("status") == "error":
            blockers.append({"code": "PDF_QA_ERROR", "detail": "; ".join(pdf_qa.get("errors") or [])})

        return {
            "status": "BLOCKED" if blockers else "APPROVAL_REQUIRED",
            "deliverable": False,
            "requires_human_approval": True,
            "blockers": blockers,
            "warnings": warnings,
            "claim_audit": claim_audit,
        }

    def approve(
        self,
        gate: Dict[str, Any],
        reviewer: str,
        notes: str = "",
        conflict_declaration: str = "",
    ) -> Dict[str, Any]:
        if gate.get("blockers"):
            raise ValueError("A blocked report cannot be approved")
        if not str(reviewer).strip():
            raise ValueError("reviewer is required")
        if not str(notes).strip():
            raise ValueError("approval notes are required")
        if not str(conflict_declaration).strip():
            raise ValueError("conflict declaration is required")
        return {
            **gate,
            "status": "APPROVED",
            "deliverable": True,
            "requires_human_approval": False,
            "approved_by": reviewer.strip(),
            "approval_notes": notes.strip(),
            "conflict_declaration": conflict_declaration.strip(),
            "approved_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

    @staticmethod
    def _parse_date(value: Any):
        if not value or value == "not_provided":
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            try:
                return datetime.strptime(str(value)[:10], "%Y-%m-%d")
            except ValueError:
                return None

    @classmethod
    def _validate_generated_content(cls, report: Dict[str, Any], blockers: List[Dict[str, str]]) -> None:
        """Block publication prose, KPI labels, and risk text from another sector."""
        rendered = report.get("rendered_narratives") or {}
        thesis = str(rendered.get("central_thesis") or "")
        if not thesis:
            return
        text = normalize_text(thesis)
        ticker = normalize_text(report.get("ticker"))
        company = normalize_text(report.get("company_name"))
        sector_key = str((report.get("sector_model") or {}).get("key") or "general")
        if ticker and ticker not in text:
            blockers.append({"code": "THESIS_IDENTITY_MISMATCH", "detail": "ticker_missing_from_central_thesis"})
        company_tokens = [token for token in re.findall(r"[a-z0-9]+", company) if len(token) >= 4]
        if company_tokens and not any(token in text for token in company_tokens):
            blockers.append({"code": "THESIS_IDENTITY_MISMATCH", "detail": "company_missing_from_central_thesis"})
        markers = {
            "healthcare": ("saude", "medic", "farmaceut", "biotecn"),
            "real_estate": ("construcao", "incorpor", "imobili"),
            "financial": ("banco", "finance", "servicos financeiros"),
            "oil_gas": ("petroleo", "gas"),
            "utilities": ("utilit", "infraestrutura", "energia"),
        }
        expected = markers.get(sector_key, ())
        if expected and not any(marker in text for marker in expected):
            blockers.append({"code": "THESIS_SECTOR_MISMATCH", "detail": f"expected={sector_key}"})
        publication_text = "\n".join(str(value) for value in rendered.values())
        publication_text += "\n" + "\n".join(map(str, (report.get("sector_model") or {}).get("kpis") or []))
        publication_text += "\n" + str(report.get("risk") or "")
        for finding in sector_contamination(publication_text, sector_key):
            blockers.append({
                "code": "SEMANTIC_CONTAMINATION",
                "detail": f"{finding['foreign_sector']}:{finding['term']}",
            })

    @staticmethod
    def _validate_score_consistency(report: Dict[str, Any], blockers: List[Dict[str, str]]) -> None:
        scores = report.get("thesis_scores") or {}
        macro_observations = report.get("macro_observations") or []
        macro_available = any(
            item.get("metric") == "selic_target" and isinstance(item.get("value"), (int, float))
            and item.get("point_in_time_eligible", True)
            for item in macro_observations if isinstance(item, dict)
        )
        macro_score = scores.get("macro")
        if not macro_available and isinstance(macro_score, (int, float)) and abs(float(macro_score) - 50.0) > 1e-9:
            blockers.append({"code": "SCORE_DATA_CONTRADICTION", "detail": "macro_score_non_neutral_without_eligible_macro"})
        peers = ((report.get("research") or {}).get("peer_analysis") or {})
        sector_score = scores.get("sector")
        peer_history_available = bool(peers.get("historical_margin_roe_available"))
        if not peer_history_available and isinstance(sector_score, (int, float)) and abs(float(sector_score) - 50.0) > 1e-9:
            blockers.append({"code": "SCORE_DATA_CONTRADICTION", "detail": "sector_score_non_neutral_without_peer_history"})
