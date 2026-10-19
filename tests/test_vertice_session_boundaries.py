import pandas as pd
from vertice.rebounds import ReboundConfig, evaluate_rebounds
from vertice.controls import detect_drawdown_controls, forward_event_outcomes
from vertice.data_pipeline import add_returns

def bars():
    ts=list(pd.date_range("2026-01-01 16:57",periods=3,freq="min",tz="America/Sao_Paulo"))+list(pd.date_range("2026-01-02 10:00",periods=3,freq="min",tz="America/Sao_Paulo"))
    close=[100,99.8,99.5,50,49.8,49.5]
    return pd.DataFrame({"timestamp":ts,"open":close,"high":[x+.2 for x in close],"low":[x-.2 for x in close],"close":close,"volume":[100]*6})

def test_rebound_window_does_not_cross_sessions():
    x=bars(); cfg=ReboundConfig(lookback_bars=2,drawdown_threshold=.01,min_bounce=.005,horizon_bars=1,cooldown_bars=0)
    s=__import__("vertice.rebounds",fromlist=["detect_rebounds"]).detect_rebounds(x,cfg)
    assert 3 not in s.signal_index.tolist()

def test_control_window_does_not_cross_sessions():
    x=bars(); c=detect_drawdown_controls(x,lookback_bars=2,drawdown_threshold=.01,max_bounce=.005,cooldown_bars=0)
    assert 3 not in c.signal_index.tolist()

def test_control_outcome_skips_signal_at_session_end():
    x=bars(); events=pd.DataFrame([{"timestamp":x.loc[2,"timestamp"],"signal_index":2,"drawdown_from_peak":-.01,"bounce_return":-.01}])
    assert forward_event_outcomes(x,events,horizon_bars=3,event_type="control").empty

def test_rebound_does_not_enter_next_session():
    x=bars(); signals=pd.DataFrame([{"timestamp":x.loc[2,"timestamp"],"close":99.5,"rolling_peak_prev":100,"drawdown_from_peak":-.005,"bounce_return":-.003,"signal_index":2}])
    assert evaluate_rebounds(x,signals,ReboundConfig(lookback_bars=2,horizon_bars=2)).empty

def test_return_lags_reset_between_sessions():
    x=bars(); x["symbol"]="AAA"; out=add_returns(x,horizons=(1,))
    assert pd.isna(out.loc[3,"return_1"])
