import pytest
from concurrent.futures import ThreadPoolExecutor

from main import run_workflow_action
from prometheus.delivery_workflow import DeliveryWorkflow


def _approvable_report(ticker="CURY3", as_of="2026-08-16"):
    source = {
        "source_id": "SRC-1", "metric": "revenue", "value": 100,
        "unit": "BRL", "period": "2025", "publication_date": "2026-03-01",
        "source": "CVM", "source_url": "https://example.test/cvm", "source_sha256": "a" * 64,
    }
    claim = {
        "claim_id": "CLM-1", "section": "fundamentals", "text": "Receita: 100 BRL",
        "classification": "FACT", "value": 100, "unit": "BRL",
        "source_ids": ["SRC-1"], "formula": None, "assumptions": [],
    }
    scenarios = {
        "bear": {"formula": "EPS * P/E", "multiple": 8, "implied_value_per_share": 8, "upside_downside": -0.2, "input_values": {"future_eps": 1, "scenario_multiple": 8}},
        "base": {"formula": "EPS * P/E", "multiple": 10, "implied_value_per_share": 10, "upside_downside": 0.0, "input_values": {"future_eps": 1, "scenario_multiple": 10}},
        "bull": {"formula": "EPS * P/E", "multiple": 12, "implied_value_per_share": 12, "upside_downside": 0.2, "input_values": {"future_eps": 1, "scenario_multiple": 12}},
    }
    return {
        "ticker": ticker, "company_name": "Companhia Teste", "analysis_as_of": as_of,
        "price": 10, "research": {"sources": [source], "contradiction_matrix": {"net": "balanced"}},
        "valuation": {
            "status": "AVAILABLE", "method": "P/E", "formula": "EPS * P/E",
            "assumptions": {"assumption_source": "Dois peers comparáveis point-in-time"},
            "scenarios": scenarios,
        },
        "risk": {"status": "AVAILABLE"}, "financial_history": [{"period": "2025"}],
        "sector_model": {"key": "general"}, "ttm": {
            "status": "AVAILABLE", "method": "reported_annual", "formula": "reported annual",
            "metrics": {
                name: {"normalized": value, "unit": "BRL", "calculation": "reported annual", "source_rows": [{
                    "received_at": "2026-03-01", "reference_date": "2025-12-31",
                    "source_url": "https://example.test/cvm", "version": "1", "source_sha256": "a" * 64,
                }]}
                for name, value in (("revenue", 100), ("net_income", 10), ("operating_cash_flow", 12))
            },
        },
        "claims": [claim], "fundamental_data_quality": {"score": 90},
    }


def _generate_bundle(flow, order, tmp_path, name="report"):
    pdf = tmp_path / f"{name}.pdf"
    pdf.write_bytes(b"report")
    bundle = flow.write_release_bundle(
        order, _approvable_report(order["ticker"], order["as_of"]), str(pdf),
        {"qa_status": "pass", "editorial_status": "APPROVAL_REQUIRED", "deliverable": False},
    )
    return pdf, bundle


def test_delivery_requires_valid_approval_chain_and_hashes(tmp_path):
    flow = DeliveryWorkflow(str(tmp_path / "ledger.jsonl"))
    order = flow.create_order("cury3", "CLIENT-01", "2026-08-16")
    artifact, bundle = _generate_bundle(flow, order, tmp_path)
    order = flow.transition(order, "GENERATED", "engine", artifacts=[str(artifact), bundle])
    order = flow.transition(order, "IN_REVIEW", "analyst")
    order = flow.transition(
        order, "APPROVED", "Lucas", "Revisão concluída",
        conflict_declaration="Nenhum conflito material declarado",
    )
    order = flow.transition(order, "DELIVERED", "Lucas", "Envio confirmado")
    assert flow.latest(order["order_id"])["state"] == "DELIVERED"
    assert flow.verify_artifacts(order)["status"] == "PASS"
    assert flow.verify_ledger()["status"] == "PASS"


def test_delivery_cannot_skip_review(tmp_path):
    flow = DeliveryWorkflow(str(tmp_path / "ledger.jsonl"))
    order = flow.create_order("CURY3", "CLIENT-01", "2026-08-16")
    with pytest.raises(ValueError):
        flow.transition(order, "APPROVED", "Lucas")


def test_delivered_report_correction_creates_new_version(tmp_path):
    flow = DeliveryWorkflow(str(tmp_path / "ledger.jsonl"))
    order = flow.create_order("CURY3", "CLIENT", "2026-08-16")
    artifact, bundle = _generate_bundle(flow, order, tmp_path, "v1")
    for state, actor in [("GENERATED","engine"),("IN_REVIEW","analyst"),("APPROVED","Lucas"),("DELIVERED","Lucas")]:
        notes = "Checklist concluído" if state == "APPROVED" else "Envio confirmado" if state == "DELIVERED" else ""
        order = flow.transition(
            order, state, actor, notes=notes,
            artifacts=[str(artifact), bundle] if state == "GENERATED" else None,
            conflict_declaration="Nenhum conflito material declarado" if state == "APPROVED" else "",
        )
    order = flow.request_correction(order, "Lucas", "Fonte retificada")
    artifact_v2, bundle_v2 = _generate_bundle(flow, order, tmp_path, "v2")
    order = flow.transition(order, "GENERATED", "engine", artifacts=[str(artifact_v2), bundle_v2])
    assert order["version"] == 2
    assert any(event["to"] == "CORRECTION_REQUESTED" for event in order["events"])
    assert {item["version"] for item in order["artifacts"]} == {1, 2}


def test_stale_order_snapshot_cannot_fork_ledger(tmp_path):
    artifact = tmp_path / "report.pdf"; artifact.write_bytes(b"report")
    flow = DeliveryWorkflow(str(tmp_path / "ledger.jsonl"))
    original = flow.create_order("CURY3", "CLIENT", "2026-08-16")
    current = flow.transition(original, "GENERATED", "engine", artifacts=[str(artifact)])
    assert current["state"] == "GENERATED"
    with pytest.raises(ValueError, match="Stale"):
        flow.transition(original, "REJECTED", "Analista")


def test_ledger_tampering_is_detected(tmp_path):
    artifact = tmp_path / "report.pdf"; artifact.write_bytes(b"report")
    ledger = tmp_path / "ledger.jsonl"
    flow = DeliveryWorkflow(str(ledger))
    order = flow.create_order("CURY3", "CLIENT", "2026-08-16")
    flow.transition(order, "GENERATED", "engine", artifacts=[str(artifact)])
    lines = ledger.read_text(encoding="utf-8").splitlines()
    changed = lines[0].replace('"ticker": "CURY3"', '"ticker": "PETR4"')
    ledger.write_text("\n".join([changed, *lines[1:]]) + "\n", encoding="utf-8")
    assert flow.verify_ledger()["status"] == "FAIL"


def test_review_requires_named_human_and_approval_notes(tmp_path):
    artifact = tmp_path / "report.pdf"; artifact.write_bytes(b"report")
    flow = DeliveryWorkflow(str(tmp_path / "ledger.jsonl"))
    order = flow.create_order("CURY3", "CLIENT", "2026-08-16")
    order = flow.transition(order, "GENERATED", "engine", artifacts=[str(artifact)])
    with pytest.raises(ValueError, match="Named human"):
        flow.transition(order, "IN_REVIEW", "pending_reviewer")
    order = flow.transition(order, "IN_REVIEW", "Analista")
    with pytest.raises(ValueError, match="Approval notes"):
        flow.transition(order, "APPROVED", "Analista")
    with pytest.raises(ValueError, match="Conflict declaration"):
        flow.transition(order, "APPROVED", "Analista", "Checklist concluído")


def test_cli_workflow_actions_support_separate_review_approval_and_delivery(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    flow = DeliveryWorkflow(str(ledger))
    order = flow.create_order("CURY3", "CLIENT", "2026-08-16")
    artifact, bundle = _generate_bundle(flow, order, tmp_path)
    order = flow.transition(order, "GENERATED", "engine", artifacts=[str(artifact), bundle])
    order = run_workflow_action(str(ledger), order["order_id"], "review", actor="Maria")
    assert order["state"] == "IN_REVIEW"
    order = run_workflow_action(
        str(ledger), order["order_id"], "approve", actor="Maria",
        notes="Checklist editorial concluído",
        conflict_declaration="Nenhum conflito material declarado",
    )
    assert order["state"] == "APPROVED"
    order = run_workflow_action(str(ledger), order["order_id"], "deliver", actor="Operação", notes="Envio confirmado")
    assert order["state"] == "DELIVERED"
    verification = run_workflow_action(str(ledger), order["order_id"], "verify")
    assert verification["ledger"]["status"] == "PASS"
    assert verification["artifacts"]["status"] == "PASS"
    assert verification["release_bundle"]["status"] == "PASS"


def test_approval_recomputes_gate_and_rejects_blocked_bundle(tmp_path):
    flow = DeliveryWorkflow(str(tmp_path / "ledger.jsonl"))
    order = flow.create_order("CURY3", "CLIENT", "2026-08-16")
    pdf = tmp_path / "blocked.pdf"; pdf.write_bytes(b"blocked")
    report = _approvable_report()
    report["ttm"] = {"status": "INSUFFICIENT_DATA", "missing": ["net_income"]}
    bundle = flow.write_release_bundle(
        order, report, str(pdf),
        {"qa_status": "pass", "editorial_status": "BLOCKED", "deliverable": False},
    )
    order = flow.transition(order, "GENERATED", "engine", artifacts=[str(pdf), bundle])
    order = flow.transition(order, "IN_REVIEW", "Analista")
    with pytest.raises(ValueError, match="LIVE_EDITORIAL_BLOCKER:TTM_INCOMPLETE"):
        flow.transition(
            order, "APPROVED", "Analista", "Checklist concluído",
            conflict_declaration="Nenhum conflito material declarado",
        )


def test_approval_rejects_modified_pdf_even_if_bundle_is_unchanged(tmp_path):
    flow = DeliveryWorkflow(str(tmp_path / "ledger.jsonl"))
    order = flow.create_order("CURY3", "CLIENT", "2026-08-16")
    pdf, bundle = _generate_bundle(flow, order, tmp_path)
    order = flow.transition(order, "GENERATED", "engine", artifacts=[str(pdf), bundle])
    order = flow.transition(order, "IN_REVIEW", "Analista")
    pdf.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="missing or changed"):
        flow.transition(
            order, "APPROVED", "Analista", "Checklist concluído",
            conflict_declaration="Nenhum conflito material declarado",
        )


def test_concurrent_order_creation_preserves_global_hash_chain(tmp_path):
    ledger = tmp_path / "ledger.jsonl"

    def create(index):
        return DeliveryWorkflow(str(ledger)).create_order(
            "CURY3", f"CLIENT-{index}", "2026-08-16",
        )["order_id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        order_ids = list(pool.map(create, range(12)))
    audit = DeliveryWorkflow(str(ledger)).verify_ledger()
    assert len(set(order_ids)) == 12
    assert audit["status"] == "PASS"
    assert audit["entry_count"] == 12


def test_high_thread_count_preserves_all_orders_without_windows_lock_deadlock(tmp_path):
    ledger = tmp_path / "ledger-high-concurrency.jsonl"

    def create(index):
        return DeliveryWorkflow(str(ledger)).create_order(
            "CURY3", f"CLIENT-{index}", "2026-08-16",
        )["order_id"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        order_ids = list(pool.map(create, range(80)))
    audit = DeliveryWorkflow(str(ledger)).verify_ledger()
    assert len(set(order_ids)) == 80
    assert audit["status"] == "PASS"
    assert audit["entry_count"] == 80
