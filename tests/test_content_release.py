from prometheus.content_release import EducationalContentGate, build_educational_brief


class _PassGate:
    def evaluate(self, _report):
        return {"status": "APPROVAL_REQUIRED", "blockers": [], "claim_audit": {"status": "PASS"}}


class _BlockedGate:
    def evaluate(self, _report):
        return {"status": "BLOCKED", "blockers": [{"code": "VALUATION_INCOMPLETE"}], "claim_audit": {"status": "PASS"}}


def _report():
    return {
        "ticker": "TEST3", "company_name": "Teste", "analysis_as_of": "2026-08-30T23:59:59Z",
        "data_source_status": "PRIMARY",
        "research": {"sources": [{
            "source_id": "SRC-1", "metric": "revenue", "value": 100.0, "unit": "BRL",
            "period": "2026-Q2", "publication_date": "2026-08-15T00:00:00Z", "source": "CVM",
            "source_url": "https://cvm.example/revenue", "source_sha256": "a" * 64,
        }]},
        "claims": [{"classification": "FACT", "text": "Receita no período: 100 BRL", "value": 100.0, "source_ids": ["SRC-1"]}],
    }


def test_educational_content_exports_only_source_backed_facts_after_editorial_eligibility():
    gate = EducationalContentGate(gate_factory=_PassGate)
    brief = build_educational_brief(_report(), gate=gate)
    assert brief["status"] == "READY_FOR_HUMAN_EDITORIAL_REVIEW"
    assert brief["publication_gate"]["eligible"] is True
    assert brief["fact_cards"] == [{
        "metric": "revenue", "claim_text": "Receita no período: 100 BRL", "value": 100.0,
        "unit": "BRL", "period": "2026-Q2", "publication_date": "2026-08-15T00:00:00Z",
        "source": "CVM", "source_url": "https://cvm.example/revenue", "source_sha256": "a" * 64, "source_id": "SRC-1",
    }]
    assert "compra" in brief["prohibited_claims"]


def test_blocked_research_cannot_be_exported_as_educational_content():
    gate = EducationalContentGate(gate_factory=_BlockedGate)
    brief = build_educational_brief(_report(), gate=gate)
    assert brief["status"] == "NOT_ELIGIBLE"
    assert brief["fact_cards"] == []
    assert brief["publication_gate"]["failures"] == ["RESEARCH_EDITORIAL_GATE_BLOCKED"]


def test_degraded_primary_data_blocks_educational_export_even_when_gate_is_clear():
    report = _report() | {"data_source_status": "DEGRADED"}
    brief = build_educational_brief(report, gate=EducationalContentGate(gate_factory=_PassGate))
    assert brief["publication_gate"]["eligible"] is False
    assert "PRIMARY_DATA_SOURCE_DEGRADED" in brief["publication_gate"]["failures"]
