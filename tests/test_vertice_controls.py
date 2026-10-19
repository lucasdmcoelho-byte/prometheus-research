import pandas as pd
from vertice.controls import detect_drawdown_controls, forward_event_outcomes

def bars():
    close=[100,99.8,99.5,99.4,99.2,99.25,99.2,99.3,99.4,99.5,99.6]
    return pd.DataFrame({"timestamp":pd.date_range("2026-01-01 13:00",periods=len(close),freq="min",tz="UTC"),
      "open":close,"high":[v+0.02 for v in close],"low":[v-0.02 for v in close],"close":close,"volume":[100]*len(close)})

def test_controls_require_drawdown_without_bounce():
    x=bars()
    c=detect_drawdown_controls(x,lookback_bars=3,drawdown_threshold=.002,max_bounce=.001,cooldown_bars=1)
    assert len(c)>0
    assert (c.bounce_return < .001).all()

def test_forward_outcomes_enter_after_signal():
    x=bars()
    c=detect_drawdown_controls(x,lookback_bars=3,drawdown_threshold=.002,max_bounce=.001,cooldown_bars=1)
    out=forward_event_outcomes(x,c,horizon_bars=2,event_type="control")
    if len(out):
        idx=int(x.index[x.timestamp==out.iloc[0].signal_timestamp][0])
        assert out.iloc[0].entry_timestamp==x.iloc[idx+1].timestamp
