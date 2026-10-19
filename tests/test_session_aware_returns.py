import pandas as pd
from vertice.data_pipeline import add_returns

def test_returns_reset_between_sessions_by_default():
    x=pd.DataFrame({"timestamp":[pd.Timestamp("2026-01-01 12:00",tz="UTC"),pd.Timestamp("2026-01-02 12:00",tz="UTC")],"symbol":["AAA","AAA"],"open":[10,10],"high":[10,10],"low":[10,10],"close":[10,11],"volume":[1,1]})
    assert pd.isna(add_returns(x,horizons=(1,)).iloc[1]["return_1"])

def test_returns_can_explicitly_include_overnight_lag():
    x=pd.DataFrame({"timestamp":[pd.Timestamp("2026-01-01 12:00",tz="UTC"),pd.Timestamp("2026-01-02 12:00",tz="UTC")],"symbol":["AAA","AAA"],"open":[10,11],"high":[10,11],"low":[10,11],"close":[10,11],"volume":[1,1]})
    assert add_returns(x,horizons=(1,),session_aware=False).iloc[1]["return_1"]==0.1
