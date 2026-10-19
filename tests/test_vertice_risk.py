import pandas as pd
import pytest
from vertice.risk import position_size_by_risk, portfolio_exposure

def test_position_size_obeys_risk_and_gross_limits():
    x=position_size_by_risk(100000,.005,20,19,max_gross_fraction=.5,lot_size=100)
    assert x["shares"]==500 and x["notional"]==10000 and x["planned_stop_loss"]==500

def test_position_size_rejects_invalid_stop():
    with pytest.raises(ValueError): position_size_by_risk(100000,.01,20,20)

def test_long_short_exposure_does_not_assume_full_hedge():
    x=portfolio_exposure(pd.DataFrame({"market_value":[50000,20000],"side":[1,-1]}))
    assert x["gross_exposure"]==70000 and x["net_exposure"]==30000
