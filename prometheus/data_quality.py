import unicodedata
from typing import Any, Dict, Optional


def validate_numeric(value: Any) -> Optional[float]:
    """Validate a numeric value and return it as float, or None if invalid."""
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number != number:  # NaN check
        return None

    return number


def normalize_percentage(value: float) -> Optional[float]:
    """Normalize a percentage-like number to a ratio in [-1.0, 1.0]."""
    if value is None:
        return None

    if -1.0 <= value <= 1.0:
        return value

    if -100.0 <= value <= 100.0:
        return value / 100.0

    return None


def normalize_ratio(value: float) -> Optional[float]:
    """Normalize a ratio-like number for metrics such as debt/equity."""
    if value is None:
        return None

    if abs(value) <= 1000.0:
        return value

    return None


def validate_range(value: float, minimum: float, maximum: float) -> bool:
    """Return True if value is within the requested numeric range."""
    if value is None:
        return False

    return minimum <= value <= maximum


def calculate_data_quality(data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate a simple quality score based on data availability and validation.

    The result preserves the original scoring semantics but adds structured factors and
    reasons so the report can explain why a dataset is weak without inventing a new
    methodology beyond the existing evidence-based checks.
    """
    total_fields = len(data)
    total_score = 0.0
    max_per_field = 100.0
    verified_count = 0
    unverified_count = 0
    suspect_count = 0
    missing_count = 0
    invalid_count = 0
    fields_with_value = 0
    fields_with_unit = 0
    fields_with_source = 0
    fields_with_valid_numeric = 0

    reasons: list[str] = []

    for field_name, entry in data.items():
        if not isinstance(entry, dict):
            continue

        presence = 1.0 if entry.get("raw") is not None else 0.0
        numeric = 1.0 if entry.get("status") == "VALID" else 0.0
        unit_known = 1.0 if entry.get("unit") not in (None, "UNKNOWN") else 0.0
        source_known = 1.0 if entry.get("source") is not None else 0.0

        if presence:
            fields_with_value += 1
        if unit_known:
            fields_with_unit += 1
        if source_known:
            fields_with_source += 1
        if numeric:
            fields_with_valid_numeric += 1

        semantic_status = entry.get("semantic_status")
        if semantic_status == "VERIFIED":
            semantic = 1.0
            verified_count += 1
        elif semantic_status == "UNVERIFIED":
            semantic = 0.5
            unverified_count += 1
        elif semantic_status == "SUSPECT":
            semantic = 0.0
            suspect_count += 1
        else:
            semantic = 0.0
            if semantic_status == "MISSING":
                missing_count += 1
            else:
                invalid_count += 1

        field_score = (
            presence * 0.20
            + numeric * 0.25
            + semantic * 0.30
            + unit_known * 0.15
            + source_known * 0.10
        ) * max_per_field
        total_score += field_score

    if total_fields == 0:
        score = 0.0
    else:
        score = round(total_score / total_fields, 2)

    completeness = round((fields_with_value / total_fields) * 100.0, 2) if total_fields else 0.0
    validation = round((fields_with_valid_numeric / total_fields) * 100.0, 2) if total_fields else 0.0
    source_quality = round((fields_with_source / total_fields) * 100.0, 2) if total_fields else 0.0
    semantic_verification = round(((verified_count + 0.5 * unverified_count) / total_fields) * 100.0, 2) if total_fields else 0.0

    if invalid_count:
        reasons.append(f"{invalid_count} campos críticos falharam na validação ou na análise semântica.")
    if missing_count:
        reasons.append(f"{missing_count} campos importantes estavam ausentes.")
    if suspect_count:
        reasons.append(f"{suspect_count} campos apresentaram status suspeito.")
    if invalid_count == 0 and missing_count == 0 and suspect_count == 0:
        reasons.append("Nenhuma falha estrutural foi detectada nos campos avaliados.")

    return {
        "score": score,
        "total_fields": total_fields,
        "verified_count": verified_count,
        "unverified_count": unverified_count,
        "suspect_count": suspect_count,
        "missing_count": missing_count,
        "invalid_count": invalid_count,
        "factors": {
            "completeness": completeness,
            "validation": validation,
            "source_quality": source_quality,
            "semantic_verification": semantic_verification,
        },
        "reasons": reasons,
    }


def calculate_research_quality(report: Dict[str, Any]) -> Dict[str, Any]:
    """Measure report coverage without changing the legacy financial-data score.

    ``fundamental_data_quality`` answers a narrow question: are the normalized
    financial fields present, valid and sourced?  A commercial research report
    also needs qualitative evidence, point-in-time provenance and a defensible
    valuation.  Keeping both measurements prevents a complete financial table
    from being presented as complete research.
    """
    financial = report.get("fundamental_data_quality") or {}
    financial_score = float(financial.get("score") or 0.0)
    sources = list((report.get("research") or {}).get("sources") or [])

    attributable = 0
    for source in sources:
        required = ("source", "period", "publication_date", "unit")
        if source.get("value") is None:
            required = ("source", "period", "publication_date")
        if all(source.get(field) not in (None, "", "not_provided", "unknown") for field in required):
            attributable += 1
    provenance = round(100.0 * attributable / len(sources), 2) if sources else 0.0

    documents = list((report.get("official_disclosures") or {}).get("documents") or [])
    fre = report.get("reference_form") or {}
    peers = (report.get("research") or {}).get("peer_analysis") or {}
    valuation = report.get("valuation") or {}
    business = report.get("business_quality") or {}
    catalysts = list((report.get("catalyst_result") or {}).get("catalysts") or [])
    sector_kpis = list((report.get("sector_model") or {}).get("kpis") or [])
    source_metrics = {_canonical_metric(item.get("metric")) for item in sources}
    covered_kpis = [
        kpi for kpi in sector_kpis
        if any(token in metric for metric in source_metrics for token in _metric_tokens(kpi))
    ]

    coverage_checks = {
        "financial_history": bool(report.get("financial_history")),
        "ttm": (report.get("ttm") or {}).get("status") == "AVAILABLE",
        "comparable_peers": peers.get("status") == "AVAILABLE",
        "official_documents": bool(documents),
        "reference_form": fre.get("status") == "AVAILABLE",
        "macro": bool(report.get("macro_observations")),
        "news_or_events": bool(catalysts),
        "sector_kpis": bool(covered_kpis),
    }
    research_coverage = round(100.0 * sum(coverage_checks.values()) / len(coverage_checks), 2)

    scenario_set = valuation.get("scenarios") or {}
    valuation_checks = {
        "available": valuation.get("status") == "AVAILABLE",
        "formula": bool(valuation.get("formula")),
        "assumptions": bool((valuation.get("assumptions") or {}).get("assumption_source")),
        "three_scenarios": all(name in scenario_set for name in ("bear", "base", "bull")),
        "eligible_peers": int(peers.get("eligible_multiple_count") or 0) >= 3,
        "compatible_periods": int(peers.get("compatible_period_count") or 0) >= 3,
        "current_multiple": any(
            (valuation.get("metrics") or {}).get(name) is not None
            for name in ("current_pe", "current_pb", "current_ev_ebit")
        ),
        "peer_quality_bridge": bool(peers.get("quality_comparison_available")),
    }
    valuation_confidence = round(100.0 * sum(valuation_checks.values()) / len(valuation_checks), 2)

    governance = business.get("governance") or {}
    qualitative_checks = {
        "official_documents": bool(documents),
        "governance": governance.get("status") == "AVAILABLE",
        "management": int(governance.get("management_records") or 0) > 0,
        "moat_evidence": (business.get("moat") or {}).get("status") not in (None, "UNPROVEN", "INSUFFICIENT_DATA"),
        "operating_kpis": bool(covered_kpis),
        "macro": bool(report.get("macro_observations")),
        "company_events": bool(catalysts),
        "business_description": bool(report.get("business_summary")),
    }
    qualitative = round(100.0 * sum(qualitative_checks.values()) / len(qualitative_checks), 2)
    overall = round(
        financial_score * 0.25
        + provenance * 0.20
        + research_coverage * 0.20
        + valuation_confidence * 0.20
        + qualitative * 0.15,
        2,
    )

    missing = [name for name, available in {**coverage_checks, **qualitative_checks}.items() if not available]
    missing = list(dict.fromkeys(missing))
    return {
        "status": "SUFFICIENT" if overall >= 80 else "PARTIAL" if overall >= 50 else "INSUFFICIENT_DATA",
        "financial_data_completeness": round(financial_score, 2),
        "source_provenance": provenance,
        "research_coverage": research_coverage,
        "valuation_confidence": valuation_confidence,
        "qualitative_evidence_coverage": qualitative,
        "overall_research_confidence": overall,
        "weights": {
            "financial_data_completeness": 0.25,
            "source_provenance": 0.20,
            "research_coverage": 0.20,
            "valuation_confidence": 0.20,
            "qualitative_evidence_coverage": 0.15,
        },
        "coverage_checks": coverage_checks,
        "valuation_checks": valuation_checks,
        "qualitative_checks": qualitative_checks,
        "covered_sector_kpis": covered_kpis,
        "missing_areas": missing,
        "limitations": [
            "A nota financeira legada mede campos normalizados; não representa sozinha a completude do research.",
            "Ausência de documento ou KPI reduz cobertura, mas não altera fórmulas analíticas nem o thesis score.",
        ],
    }


def _metric_tokens(label: str) -> tuple[str, ...]:
    normalized = str(label or "").lower()
    aliases = {
        "vso": ("vso", "sales_over_supply"),
        "lançamentos": ("lancamentos", "launches"),
        "vendas brutas": ("vendas_brutas", "gross_sales"),
        "vendas líquidas": ("vendas_liquidas", "net_sales"),
        "distratos": ("distratos", "cancellations"),
        "receita a apropriar": ("receita_a_apropriar", "backlog_revenue"),
        "landbank": ("landbank", "banco_de_terrenos"),
        "repasses": ("repasses", "mortgage_transfers"),
    }
    return tuple(_canonical_metric(item) for item in aliases.get(normalized, (normalized.replace(" ", "_"),)))


def _canonical_metric(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(character for character in text if not unicodedata.combining(character)).replace(" ", "_")
