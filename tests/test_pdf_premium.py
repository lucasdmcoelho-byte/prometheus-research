import hashlib
import json
import re
from pathlib import Path

import pytest
from pypdf import PdfReader

import prometheus.reporting as reporting
from prometheus.pipeline import PrometheusEngine


@pytest.fixture()
def premium_report(tmp_path, market_data_adapter):
    snapshot = PrometheusEngine(adapter=market_data_adapter).evaluate(
        "CURY3", sentiment_score=50.0, news_items=[], journal_metadata={"source": "pdf-premium-test"}
    )["report"]
    result = reporting.generate_report("CURY3", output_dir=str(tmp_path), report_data=snapshot)
    return result, PdfReader(result["metadata"]["report_path"])


def test_premium_pdf_is_a4_with_complete_metadata_and_navigation(premium_report):
    result, reader = premium_report
    page = reader.pages[0]
    assert abs(float(page.mediabox.width) - float(reporting.A4[0])) < 1
    assert abs(float(page.mediabox.height) - float(reporting.A4[1])) < 1

    metadata = reader.metadata
    assert metadata.title.startswith("PROMETHEUS Equity Research | CURY3")
    assert metadata.author == "PROMETHEUS Research"
    assert "point-in-time" in metadata.subject
    assert metadata.creator == "PROMETHEUS Research 2.1.0rc2"
    assert "equity research" in metadata.get("/Keywords")
    assert str(reader.root_object.get("/Lang")) == "pt-BR"
    assert reader.outline
    assert len(reader.pages) >= 8


def test_commercial_layer_precedes_audit_and_formulas_stay_in_appendix(premium_report):
    _, reader = premium_report
    pages = [page.extract_text() or "" for page in reader.pages]
    joined = "\n".join(pages)
    audit_page = next(index for index, text in enumerate(pages) if "ANEXO DE AUDITORIA" in text.upper())

    assert "A EMPRESA EM UMA PÁGINA" in joined.upper()
    assert "DASHBOARD FINANCEIRO" in joined.upper()
    assert "TESE E ANTÍTESE" in joined.upper()
    assert "VALUATION E CENÁRIOS" in joined.upper()
    assert "FONTES E DISPONIBILIDADE" in joined.upper()
    assert "REGISTRO DE AFIRMAÇÕES" in joined.upper()
    commercial = re.sub(r"\s+", "", "\n".join(pages[:audit_page]).upper())
    appendix = re.sub(r"\s+", "", "\n".join(pages[audit_page:]).upper())
    assert "0.60*WEIGHTED_THESIS" not in commercial
    assert "0.60*WEIGHTED_THESIS" in appendix


def test_unapproved_report_is_visibly_draft_and_does_not_invent_journal_identity(premium_report):
    result, reader = premium_report
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "HUMAN REVIEW REQUIRED" in text
    assert "APROVADO PARA ENTREGA" not in text
    assert "research_case_id" in text
    assert "INSUFFICIENT_DATA" in text
    assert result["metadata"]["deliverable"] is False


def test_external_manifest_matches_pdf_and_is_not_self_embedded(premium_report):
    result, reader = premium_report
    pdf_path = Path(result["metadata"]["report_path"])
    manifest_path = Path(result["metadata"]["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    assert manifest_path.exists()
    assert manifest["artifacts"][0]["sha256"] == digest
    assert manifest["artifacts"][0]["size"] == pdf_path.stat().st_size
    assert manifest["report_snapshot_sha256"] == result["metadata"]["report_snapshot_sha256"]
    assert manifest["cognitive_identity"]["availability"] == "INSUFFICIENT_DATA"
    assert digest not in "\n".join(page.extract_text() or "" for page in reader.pages)


def test_full_claim_registry_remains_extractable(premium_report):
    result, reader = premium_report
    claims = result["report"].get("claims") or []
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    compact_text = re.sub(r"\s+", "", text)
    assert claims
    assert claims[0]["claim_id"] in compact_text
    assert claims[-1]["claim_id"] in compact_text


def test_complete_audit_export_preserves_unabridged_claims_and_gate(premium_report):
    result, reader = premium_report
    export_path = Path(result["metadata"]["audit_export_path"])
    export = json.loads(export_path.read_text(encoding="utf-8"))
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert export_path.exists()
    assert export["claims"] == result["report"]["claims"]
    assert export["editorial_gate"]["warnings"] == result["report"]["editorial_gate"]["warnings"]
    assert export["report_snapshot_sha256"] == result["metadata"]["report_snapshot_sha256"]
    assert export_path.name in pdf_text


def test_rerender_does_not_include_prior_export_metadata_in_snapshot(premium_report, tmp_path):
    result, _ = premium_report
    rerendered = reporting.generate_report(
        "CURY3", output_dir=str(tmp_path / "rerender"), report_data=result["report"],
    )

    assert rerendered["metadata"]["report_snapshot_sha256"] == result["metadata"]["report_snapshot_sha256"]


def test_sector_chart_accepts_current_wide_peer_records(tmp_path):
    report = {"research": {"peer_analysis": {"peers": [
        {"ticker": "AAA3", "profit_margin": 0.10, "roe": 0.15},
        {"ticker": "BBB3", "profit_margin": 0.08, "roe": 0.12},
    ]}}}
    chart = reporting._build_sector_chart("CURY3", report, tmp_path)
    assert chart is not None
    assert chart.exists()
    assert chart.stat().st_size > 1_000


def test_audit_value_formatting_uses_declared_unit_not_metric_name():
    assert reporting._format_source_value({"metric": "shares_outstanding", "value": 308_054_000, "unit": "shares"}) == "308,05 mi ações"
    assert reporting._format_source_value({"metric": "cash_conversion", "value": 0.4045, "unit": "ratio"}) == "0,40x"
    assert reporting._format_source_value({"metric": "net_income", "value": 573_318_000, "unit": "BRL"}) == "R$ 573,32 mi"


def test_structured_risk_evidence_is_rendered_as_claim_not_raw_json():
    evidence = {"claim": "Smaller capitalization implies idiosyncratic risk", "source_metadata": {"id": "x"}}
    assert reporting._evidence_text(evidence) == "Smaller capitalization implies idiosyncratic risk"


def test_pdf_text_is_searchable_clean_and_every_page_has_content(premium_report):
    _, reader = premium_report
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    assert all(len(re.sub(r"\s+", "", page)) > 100 for page in pages)
    assert "�" not in text
    assert not re.search(r"[A-Za-zÀ-ÿ]\.\.", text)
    assert "CONFIANÇA DO RESEARCH" in text.upper()
    assert "HUMAN REVIEW REQUIRED" in text
