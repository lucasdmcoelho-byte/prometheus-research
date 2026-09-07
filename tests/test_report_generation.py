from io import BytesIO
from pathlib import Path

import prometheus.reporting as reporting
from prometheus.pipeline import PrometheusEngine


def test_score_breakdown_discloses_unavailable_sector_score():
    text = reporting._build_score_breakdown({
        "thesis_scores": {"fundamental": 60.0, "sector": None, "macro": 50.0},
        "score_availability": {
            "unavailable_components": ["sector"],
            "component_status": {"sector": {
                "status": "SECTOR_SCORE_UNAVAILABLE",
                "reason": "Sem histórico point-in-time de margens e ROE dos pares suficiente para calcular o Sector Score.",
            }},
        },
        "final_score": 60.0,
        "final_state": "NEUTRAL",
    })
    assert "sector: indisponível" in text
    assert "histórico point-in-time" in text


def test_generate_report_creates_pdf(tmp_path, monkeypatch, market_data_adapter):
    snapshot = PrometheusEngine(adapter=market_data_adapter).evaluate(
        "CURY3", sentiment_score=50.0, news_items=[], journal_metadata={"source": "test"}
    )["report"]
    monkeypatch.setattr(reporting, "_cached_company_snapshot", lambda ticker: (_ for _ in ()).throw(AssertionError("unexpected refetch")))
    result = reporting.generate_report("CURY3", output_dir=str(tmp_path), report_data=snapshot)

    assert result["metadata"]["ticker"] == "CURY3"
    assert result["metadata"]["report_path"].endswith(".pdf")
    assert Path(result["metadata"]["report_path"]).exists()
    assert Path(result["metadata"]["report_path"]).stat().st_size > 500
    assert "cury3" in result["narrative"]["summary"].lower()
    assert "confian" in result["narrative"]["summary"].lower()
    assert "chart_artifacts" in result
    assert len(result["chart_artifacts"]) >= 1
    assert all(Path(chart).exists() for chart in result["chart_artifacts"])


def test_pdf_footer_is_drawn_only_during_final_page_replay():
    events = []
    canvas_class = reporting._footer_canvas_class({"ticker": "CURY3"})

    class ObservedCanvas(canvas_class):
        def _draw_footer(self):
            events.append(("footer", self._pageNumber))
            super()._draw_footer()

    canvas = ObservedCanvas(BytesIO(), pagesize=reporting.letter)
    canvas.drawString(72, 720, "BODY")
    canvas.showPage()
    assert events == []
    canvas.save()

    # Painting on save puts the footer after all page content, preventing a
    # split table background from visually erasing it.
    assert events == [("footer", 1)]


def test_score_reconciliation_scales_pricing_confidence_like_pipeline():
    keys = ("fundamental", "sector", "macro", "expectation_gap", "momentum_velocity", "valuation_margin", "news_sentiment")
    report = {
        "thesis_scores": {key: 50 for key in keys}, "expectation_result": {"expectation_gap_score": 50},
        "catalyst_result": {"catalyst_score": 50}, "regime_result": {"confidence": .5},
        "pricing_result": {"pricing_confidence": .5}, "final_score": 50,
    }
    assert reporting._score_reconciliation(report)["reconciled"] is True
