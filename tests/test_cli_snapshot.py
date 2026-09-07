import pytest

from main import _synchronize_pdf_snapshot


def test_cli_json_adopts_the_exact_post_qa_pdf_snapshot():
    pre_pdf = {"ticker": "EGIE3", "editorial_gate": {"status": "STALE"}}
    post_qa = {
        "ticker": "EGIE3",
        "qa": {"status": "pass"},
        "editorial_gate": {"status": "APPROVAL_REQUIRED"},
    }
    engine_result = {"report": pre_pdf}
    selected = _synchronize_pdf_snapshot(engine_result, {"report": post_qa})
    assert selected is post_qa
    assert engine_result["report"] is post_qa
    assert engine_result["report"]["qa"]["status"] == "pass"


def test_cli_rejects_pdf_result_without_a_snapshot():
    with pytest.raises(ValueError, match="audited report snapshot"):
        _synchronize_pdf_snapshot({"report": {}}, {"metadata": {}})
