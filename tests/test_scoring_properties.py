from prometheus.decision_engine import DecisionEngine
from prometheus.risk_engine import RiskEngine
from prometheus.thesis_engine import WEIGHTS, calculate_score, evidence_coverage


def test_weighted_thesis_score_is_bounded_at_domain_corners():
    for value in (0.0, 100.0):
        scores = {key: value for key in WEIGHTS}
        result = calculate_score(scores)
        assert 0.0 <= result <= 100.0


def test_each_positive_thesis_component_is_monotonic():
    baseline = {key: 50.0 for key in WEIGHTS}
    baseline_score = calculate_score(baseline)
    for key in WEIGHTS:
        improved = dict(baseline)
        improved[key] = 60.0
        assert calculate_score(improved) > baseline_score


def test_unavailable_component_is_renormalized_not_scored_as_neutral():
    scores = {key: 50.0 for key in WEIGHTS} | {"valuation_margin": 0.0}
    assert calculate_score(scores, {"valuation_margin"}) == 50.0
    assert evidence_coverage({"valuation_margin"}) == 80.0


def test_risk_score_is_bounded_and_low_beta_is_not_called_elevated():
    engine = RiskEngine()
    low = engine.analyze({"beta": 0.1, "market_cap": 30_000_000_000, "debt_to_equity": 0.2})
    extreme = engine.analyze({"beta": 10.0, "market_cap": 1_000_000, "debt_to_equity": 20.0})

    assert 0.0 <= low["risk_score"] <= 1.0
    assert 0.0 <= extreme["risk_score"] <= 1.0
    assert low["risk_score"] > extreme["risk_score"]
    assert not any("elevated" in item.claim.lower() for item in low["evidence"])
