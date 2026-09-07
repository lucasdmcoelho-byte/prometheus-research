from prometheus.business_quality import BusinessQualityEngine


def test_business_quality_does_not_claim_moat_from_margin_alone():
    report = {
        "official_metrics": {"profit_margin": {"normalized": .2}},
        "research": {"sources": [{"metric": "profit_margin", "source_id": "S1"}]},
        "reference_form": {"status": "AVAILABLE", "sections": {"management": [{"Nome": "A"}]}},
        "official_disclosures": {"documents": []}, "sector_model": {"kpis": ["margem"]},
    }
    result = BusinessQualityEngine().evaluate(report)
    assert result["moat"]["status"] == "UNPROVEN"
    assert result["interpretations"][0]["classification"] == "INTERPRETATION"
    assert result["interpretations"][0]["source_ids"] == ["S1"]


def test_business_quality_explains_when_all_valuation_scenarios_are_below_price():
    report = {
        "official_metrics": {}, "research": {"sources": []},
        "reference_form": {"status": "INSUFFICIENT_DATA"},
        "official_disclosures": {"documents": []}, "sector_model": {"kpis": []},
        "valuation": {"scenarios": {
            "bear": {"upside_downside": -0.40},
            "base": {"upside_downside": -0.25},
            "bull": {"upside_downside": -0.10},
        }},
    }
    reconciliation = BusinessQualityEngine().evaluate(report)["valuation_reconciliation"]
    assert reconciliation["status"] == "DIVERGENCE_EXPLAINED"
    assert reconciliation["valuation_attractiveness"] == "PRICE_ABOVE_SENSITIVITY_RANGE"
    assert reconciliation["margin_of_safety"] == "NEGATIVE_IN_STATED_MODEL"
