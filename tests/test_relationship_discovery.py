from prometheus.relationship_discovery import confidence_language, contradiction_analysis, discover_relationships


def _kpis():
    return {"metrics": {
        "vendas_brutas": {"status": "AVAILABLE", "value": 2533900000},
        "vendas_líquidas": {"status": "AVAILABLE", "value": 2304600000},
        "distratos": {"status": "AVAILABLE", "value": 229300000},
        "lançamentos": {"status": "AVAILABLE", "value": 2646800000},
    }}


def test_identity_is_not_insight():
    result = discover_relationships(_kpis(), periods_available=1)
    relation = next(x for x in result["relationships"] if x["id"] == "gross_minus_net_equals_cancellations")
    assert relation["classification"] == "MECHANICAL_IDENTITY"
    assert relation["insight"] is False


def test_single_period_cannot_be_anomalous_or_informative():
    result = discover_relationships(_kpis(), periods_available=1)
    assert all(x["classification"] not in {"ANOMALOUS", "POTENTIALLY_INFORMATIVE"} for x in result["relationships"])


def test_confidence_is_blocked_without_history():
    assert confidence_language(periods_available=1, supporting_evidence_count=0).startswith("Os dados disponíveis ainda não permitem")


def test_contradiction_lists_missing_history_and_peers():
    discovery = discover_relationships(_kpis(), periods_available=1)
    result = contradiction_analysis(discovery, _kpis(), periods_available=1)
    assert result["relationships"]
    assert "histórico dos últimos 4 trimestres" in result["relationships"][0]["missing_evidence"]
