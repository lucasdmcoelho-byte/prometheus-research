import pandas as pd
from vertice.rebounds import ReboundConfig, detect_rebounds
from vertice.controls import detect_drawdown_controls

def bars():
    ts=list(pd.date_range("2026-01-01 13:00",periods=3,freq="min",tz="America/Sao_Paulo"))+list(pd.date_range("2026-01-02 13:00",periods=3,freq="min",tz="America/Sao_Paulo"))
    close=[100,99,98,50,49,49.5]
    return pd.DataFrame({"timestamp":ts,"open":close,"high":[v+.1 for v in close],"low":[v-.1 for v in close],"close":close,"volume":[100]*6})

def test_rebound_window_does_not_cross_sessions():
    x=bars(); cfg=ReboundConfig(lookback_bars=2,drawdown_threshold=.01,min_bounce=.005,horizon_bars=1,cooldown_bars=0)
    s=detect_rebounds(x,cfg)
    assert 3 not in s.signal_index.tolist()

def test_control_window_does_not_cross_sessions():
    x=bars(); x.loc[5,"close"]=48.5; x.loc[5,"open"]=48.5
    c=detect_drawdown_controls(x,lookback_bars=2,drawdown_threshold=.01,max_bounce=.005,cooldown_bars=0)
    assert 3 not in c.signal_index.tolist()
