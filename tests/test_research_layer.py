from prometheus.research import ResearchEngine


def test_research_engine_builds_structured_sources():
    engine = ResearchEngine()
    source = engine.build_source_record(
        metric="revenue_growth",
        value=0.32,
        unit="percentage",
        period="TTM",
        reference_date="2026-06-30",
        publication_date="2026-08-14",
        source="yfinance",
        source_type="secondary",
        confidence="medium",
    )

    assert source["metric"] == "revenue_growth"
    assert source["value"] == 0.32
    assert source["source_type"] == "secondary"
    assert source["reference_date"] == "2026-06-30"
    assert source["publication_date"] == "2026-08-14"


def test_research_engine_builds_sector_profile_and_trace():
    engine = ResearchEngine()
    profile = engine.build_sector_profile("Real Estate")
    assert "drivers" in profile
    assert "macro" in profile

    trace = engine.build_research_trace(
        ticker="CURY3",
        metric="revenue_growth",
        value=0.32,
        source="yfinance",
        calculation="Revenue growth = 32%",
        conclusion="Crescimento operacional relevante para o setor imobiliário.",
    )
    assert trace[0]["metric"] == "revenue_growth"
    assert trace[0]["source"] == "yfinance"


def test_company_research_contract():
    engine = ResearchEngine()
    company = engine.build_company_research("CURY3", sector="Real Estate")

    assert company["ticker"] == "CURY3"
    assert company["sector"] == "Real Estate"
    assert "business_model" in company
    assert "geographic_exposure" in company
    assert "kpis" in company
    assert isinstance(company["limitations"], list)


def test_unknown_sector_never_inherits_real_estate_assumptions():
    company = ResearchEngine().build_company_research("EGIE3", sector="Unknown")
    serialized = str(company).lower()
    assert "landbank" not in serialized
    assert "vso" not in serialized
    assert company["thesis_monitors"] == ["receita", "margem", "ROIC", "caixa", "alavancagem"]


def test_sector_kpi_profile_real_estate():
    engine = ResearchEngine()
    profile = engine.build_sector_kpi_profile("Real Estate")

    assert profile["sector"] == "Real Estate"
    assert "kpis" in profile
    assert any("vso" in item.lower() or "venda" in item.lower() for item in profile["kpis"])
    assert "drivers" in profile
    assert "risks" in profile
    assert profile["benchmark"] == "XFIX11"
    assert "P/L" in profile["valuation_methods"]


def test_narrative_sector_profile_uses_the_shared_utilities_model():
    profile = ResearchEngine().build_sector_kpi_profile("Energia Elétrica")
    assert profile["sector_model_key"] == "utilities"
    assert profile["benchmark"] == "UTIL11"
    assert "RAP" in profile["kpis"]
    assert "regulação" in profile["risks"]
    assert "DCF" in profile["valuation_methods"]


def test_broad_energy_label_uses_oil_and_gas_model_without_hydrology_leakage():
    profile = ResearchEngine().build_sector_profile("Energy")
    assert profile["sector_model_key"] == "oil_gas"
    assert "lifting cost" in profile["kpis"]
    assert "hidrologia" not in " ".join(profile["drivers"] + profile["risks"]).lower()


def test_recent_operating_developments_and_fact_classification():
    engine = ResearchEngine()
    changes = engine.build_recent_operating_developments(
        ticker="CURY3",
        items=[
            {
                "metric": "VSO",
                "current_value": 132000,
                "previous_value": 120000,
                "unit": "unidades",
                "period": "2T26 vs 2T25",
                "reference_date": "2026-06-30",
                "source": "company_release",
                "direction": "up",
                "interpretation": "VSO mostrou avanço relevante.",
            }
        ],
    )
    assert changes[0]["metric"] == "VSO"
    assert changes[0]["change"] == 12000

    fact = engine.classify_evidence("VSO cresceu de 120 mil para 132 mil unidades, conforme release.")
    assert fact["classification"] in {"FACT", "INTERPRETATION", "INFERENCE", "ESTIMATE", "UNAVAILABLE"}


def test_materiality_and_contradiction_matrix():
    engine = ResearchEngine()
    ranked = engine.rank_materiality([
        {"metric": "VSO", "importance": 0.9, "magnitude": 0.7, "direction": "up"},
        {"metric": "distrato", "importance": 0.8, "magnitude": 0.3, "direction": "down"},
    ])
    assert ranked[0]["metric"] in {"VSO", "distrato"}

    contradiction = engine.build_contradiction_matrix(
        supporting_evidence=["Vendas cresceram", "margem melhorou"],
        contradicting_evidence=["distrato aumentou", "alavancagem subiu"],
    )
    assert contradiction["net_interpretation"]
    assert contradiction["supporting_evidence"]
    assert contradiction["contradicting_evidence"]


def test_peer_analysis_graceful_degradation_and_research_report_serialization():
    engine = ResearchEngine()
    peer = engine.build_peer_analysis(ticker="CURY3", peers=[])
    assert peer["status"] == "INSUFFICIENT_DATA"

    report = engine.build_research_report(ticker="CURY3", sector="Real Estate")
    assert report["ticker"] == "CURY3"
    assert report["sector"] == "Real Estate"
    assert "executive_summary" in report
    assert "evidence_chain" in report
    assert report["valuation_scenarios"]["status"] == "INSUFFICIENT_DATA"


def test_source_tier_and_valuation_scenarios():
    engine = ResearchEngine()
    source = engine.build_source_record(
        metric="vso",
        value=132000,
        unit="unidades",
        period="2T26",
        reference_date="2026-06-30",
        publication_date="2026-08-15",
        source="Fato relevante",
        source_type="primary",
        source_tier="TIER_1",
        confidence="high",
    )
    assert source["source_tier"] == "TIER_1"

    scenarios = engine.build_valuation_scenarios(
        base_value=5.0,
        bear_multiple=8.0,
        bull_multiple=12.0,
        earnings_base=1.0,
    )
    assert set(scenarios.keys()) >= {"bear", "base", "bull"}
    assert scenarios["base"]["implied_value"] == 5.0
