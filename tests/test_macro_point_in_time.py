from prometheus.engines import ThesisEngine
from prometheus.models import AssetProfile, MarketSnapshot


def _asset_profile():
    return AssetProfile(
        ticker="TEST3", company_name="Teste", sector="Utilities", industry="Utilities",
        currency="BRL", exchange="B3", business_summary="", country="BR",
    )


def _market_snapshot():
    return MarketSnapshot(
        price=10.0, previous_close=10.0, price_change=0.0,
        price_change_percent=0.0, market_cap=10_000_000_000.0, beta=0.8,
        forward_pe=10.0, trailing_pe=10.0, enterprise_value=None,
        shares_outstanding=None, dividend_yield=None, fifty_two_week_change=0.0,
        fifty_two_week_low=None, fifty_two_week_high=None,
    )


def test_thesis_macro_score_ignores_selic_not_eligible_at_cutoff():
    scores = ThesisEngine().evaluate(
        _asset_profile(), _market_snapshot(), fundamental_score=50.0,
        macro_observations=[{
            "metric": "selic_target", "value": 15.0,
            "point_in_time_eligible": False,
        }],
    )
    assert scores["macro"] == 50.0


def test_thesis_macro_score_uses_point_in_time_eligible_selic():
    scores = ThesisEngine().evaluate(
        _asset_profile(), _market_snapshot(), fundamental_score=50.0,
        macro_observations=[{
            "metric": "selic_target", "value": 10.0,
            "point_in_time_eligible": True,
        }],
    )
    assert scores["macro"] != 50.0
