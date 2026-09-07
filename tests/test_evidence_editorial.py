import pytest

from prometheus.editorial_gate import EditorialGate
from prometheus.evidence_engine import EvidenceEngine


def test_calculation_claim_requires_formula_and_source():
    engine = EvidenceEngine()
    claim = engine.build_claim(section="valuation", text="Valor justo 20", claim_type="CALCULATION")
    audit = engine.audit_claims([claim])
    assert audit["status"] == "FAIL"
    assert {item["reason"] for item in audit["issues"]} == {"missing_source", "missing_formula"}


def test_metric_sources_become_verified_claims():
    sources = [{"metric": "revenue", "value": 100, "unit": "BRL", "period": "2025", "confidence": "high"}]
    claims = EvidenceEngine().build_metric_claims(sources)
    assert claims[0]["verified"] is True
    assert sources[0]["source_id"] == "SRC-0001"


def test_reenriched_sources_receive_unique_ids_instead_of_corrupting_claim_lineage():
    sources = [
        {"source_id": "SRC-0001", "metric": "revenue", "value": 100, "unit": "BRL", "period": "2025", "publication_date": "2026-03-01", "source": "CVM"},
        {"source_id": "SRC-0001", "metric": "cash", "value": 50, "unit": "BRL", "period": "2025", "publication_date": "2026-03-01", "source": "CVM"},
    ]
    claims = EvidenceEngine().build_metric_claims(sources)
    assert len({source["source_id"] for source in sources}) == 2
    assert all(claim["verified"] for claim in claims)


def test_claim_source_ids_must_resolve_to_complete_numeric_sources():
    engine = EvidenceEngine()
    claim = engine.build_claim(
        section="fundamentals", text="Receita de 100", claim_type="FACT",
        source_ids=["SRC-MISSING"], value=100, unit="BRL",
    )
    audit = engine.audit_claims(
        [claim],
        sources=[{
            "source_id": "SRC-OTHER", "metric": "revenue", "value": 100,
            "source": "CVM", "publication_date": "2025-03-01",
        }],
        cutoff="2025-03-31T23:59:59Z",
    )
    reasons = {item["reason"] for item in audit["issues"]}
    assert "unresolved_source:SRC-MISSING" in reasons
    assert "numeric_source_missing_unit" in reasons
    assert "numeric_source_missing_period" in reasons


def test_claim_audit_blocks_future_source_even_when_stored_verified():
    engine = EvidenceEngine()
    claim = engine.build_claim(
        section="fundamentals", text="Receita de 100", claim_type="FACT",
        source_ids=["SRC-1"], value=100, unit="BRL",
    )
    claim["verified"] = True
    audit = engine.audit_claims(
        [claim],
        sources=[{
            "source_id": "SRC-1", "metric": "revenue", "value": 100,
            "unit": "BRL", "period": "2024", "source": "CVM",
            "publication_date": "2025-04-01",
        }],
        cutoff="2025-03-31T23:59:59Z",
    )
    assert any(item["reason"] == "lookahead_source" for item in audit["issues"])


def test_provenance_sentinels_are_not_treated_as_real_unit_period_or_date():
    audit = EvidenceEngine().audit_claims([], sources=[{
        "source_id": "SRC-1", "metric": "price", "value": 10,
        "unit": "unknown", "period": "latest_available",
        "publication_date": "not_provided", "source": "unknown",
    }], cutoff="2026-01-01")
    reasons = {item["reason"] for item in audit["issues"]}
    assert reasons >= {
        "numeric_source_missing_unit", "numeric_source_missing_period",
        "numeric_source_missing_publication_date", "numeric_source_missing_source",
        "invalid_source_publication_date",
    }


def test_calculated_metric_source_becomes_calculation_claim_with_formula():
    sources = [{
        "metric": "market_cap", "value": 1200, "unit": "BRL", "period": "2026-01-01",
        "source_type": "calculated", "formula": "close * shares_outstanding", "confidence": "high",
    }]
    claim = EvidenceEngine().build_metric_claims(sources)[0]
    assert claim["classification"] == "CALCULATION"
    assert claim["formula"] == "close * shares_outstanding"
    assert EvidenceEngine().audit_claims([claim])["status"] == "PASS"


def test_editorial_gate_blocks_lookahead():
    report = {
        "ticker": "TEST3", "company_name": "Teste", "analysis_as_of": "2025-01-01T23:59:59Z",
        "research": {"sources": [{"source_id": "S1", "metric": "revenue", "value": 1, "unit": "BRL", "period": "2024", "publication_date": "2025-02-01"}]},
        "valuation": {"status": "PARTIAL"}, "risk": {"status": "ok"},
        "financial_history": [{"period": "2024"}], "sector_model": {"name": "general"},
        "claims": [], "fundamental_data_quality": {"score": 80},
    }
    gate = EditorialGate().evaluate(report)
    assert gate["status"] == "BLOCKED"
    assert any(item["code"] == "LOOKAHEAD_SOURCE" for item in gate["blockers"])


def test_human_approval_is_mandatory_and_blockers_cannot_be_overridden():
    gate = {"status": "APPROVAL_REQUIRED", "blockers": [], "warnings": []}
    approved = EditorialGate().approve(
        gate,
        reviewer="Analista",
        notes="Checklist concluído",
        conflict_declaration="Nenhum conflito material declarado",
    )
    assert approved["deliverable"] is True
    assert approved["conflict_declaration"] == "Nenhum conflito material declarado"
    with pytest.raises(ValueError, match="conflict declaration"):
        EditorialGate().approve(gate, reviewer="Analista", notes="Checklist concluído")
    with pytest.raises(ValueError):
        EditorialGate().approve({"blockers": [{"code": "X"}]}, reviewer="Analista")


def test_empty_claim_ledger_cannot_be_approved():
    report = {
        "ticker": "X", "company_name": "X", "analysis_as_of": "2026-01-01",
        "research": {"sources": [], "contradiction_matrix": {"net": "x"}},
        "valuation": {"status": "AVAILABLE", "assumptions": {"base_pe": 8}},
        "risk": {"x": 1}, "financial_history": [1],
        "sector_model": {"key": "general"}, "claims": [],
        "fundamental_data_quality": {"score": 80},
    }
    gate = EditorialGate().evaluate(report)
    assert any(item["code"] == "MISSING_CLAIM_LEDGER" for item in gate["blockers"])


def test_interpretation_claim_with_foreign_sector_vocabulary_is_blocked():
    report = {
        "ticker": "HAPV3", "company_name": "Hapvida", "analysis_as_of": "2026-08-23",
        "sector_model": {"key": "healthcare"}, "claims": [{
            "claim_id": "CLM-SECTOR", "classification": "INTERPRETATION",
            "text": "A incorporadora depende do landbank para sustentar lançamentos.",
            "source_ids": ["S1"], "value": None, "unit": None,
        }],
        "research": {"sources": [{
            "source_id": "S1", "metric": "nota", "value": None, "period": "2025-Q3",
            "publication_date": "2025-11-01", "source": "CVM",
        }], "contradiction_matrix": {"net": "ok"}},
        "valuation": {"status": "INSUFFICIENT_DATA"}, "risk": {"status": "ok"},
        "financial_history": [{"period": "2025-Q3"}],
    }
    gate = EditorialGate().evaluate(report)
    assert gate["deliverable"] is False
    assert any(item["code"] == "SEMANTIC_CONTAMINATION" for item in gate["blockers"])


def test_peer_period_mismatch_is_a_hard_blocker():
    report = {
        "ticker":"X","company_name":"X","analysis_as_of":"2026-01-01","research":{"sources":[],"contradiction_matrix":{},"peer_analysis":{"status":"AVAILABLE","compatible_period_count":1}},
        "valuation":{"status":"PARTIAL"},"risk":{"x":1},"financial_history":[1],"sector_model":{"key":"general"},"claims":[],"fundamental_data_quality":{"score":80},
    }
    gate = EditorialGate().evaluate(report)
    assert any(item["code"] == "INCOMPATIBLE_PEER_PERIODS" for item in gate["blockers"])


def test_broken_unicode_blocks_publication():
    report = {"ticker":"X","company_name":"Ita�","analysis_as_of":"2026-01-01","research":{"sources":[],"contradiction_matrix":{"net":"x"}},"valuation":{"status":"PARTIAL"},"risk":{"x":1},"financial_history":[1],"sector_model":{"key":"financial"},"claims":[],"fundamental_data_quality":{"score":80}}
    assert any(item["code"] == "INVALID_TEXT_ENCODING" for item in EditorialGate().evaluate(report)["blockers"])


@pytest.mark.parametrize(
    ("valuation", "ttm", "expected_code"),
    [
        ({"status": "INSUFFICIENT_DATA"}, {}, "VALUATION_INCOMPLETE"),
        (
            {"status": "AVAILABLE", "assumptions": {"method": "DCF"}},
            {"status": "INSUFFICIENT_DATA", "missing": ["revenue"]},
            "TTM_INCOMPLETE",
        ),
    ],
)
def test_incomplete_valuation_or_ttm_cannot_be_human_overridden(valuation, ttm, expected_code):
    report = {
        "ticker": "X",
        "company_name": "X",
        "analysis_as_of": "2026-01-01",
        "research": {"sources": [], "contradiction_matrix": {"net": "x"}},
        "valuation": valuation,
        "ttm": ttm,
        "risk": {"x": 1},
        "financial_history": [1],
        "sector_model": {"key": "general"},
        "claims": [],
        "fundamental_data_quality": {"score": 80},
    }
    gate = EditorialGate().evaluate(report)
    assert gate["status"] == "BLOCKED"
    assert any(item["code"] == expected_code for item in gate["blockers"])
    with pytest.raises(ValueError):
        EditorialGate().approve(gate, reviewer="Analista")
