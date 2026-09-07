import json
from pathlib import Path

from pypdf import PdfReader

from prometheus.reporting import generate_report


def test_score_values_have_one_canonical_rendered_representation(tmp_path):
    source = Path("tmp/phase0_20260830/reports.json")
    if not source.exists():
        return
    payload = json.loads(source.read_text(encoding="utf-8"))
    report = next(item["analysis"] for item in payload["tickers"] if item["ticker"] == "CURY3")
    result = generate_report("CURY3", output_dir=str(tmp_path), report_data=report)
    output = result["report"]
    text = "\n".join(page.extract_text() or "" for page in PdfReader(result["metadata"]["report_path"]).pages)
    assert "sector: 50.00" not in text
    assert "valuation_margin: 50.00" not in text
    assert "sector: indisponível" in text
    assert "prometheus_final_score: 63.81" in text
    assert output["final_score"] == output["score_reconciliation"]["reconstructed_final_score"]
    assert not any("score_sector" in str(claim) and claim.get("value") == 50.0 for claim in output.get("claims", []))
