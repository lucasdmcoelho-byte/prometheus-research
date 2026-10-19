import pandas as pd
from vertice.controls import forward_event_outcomes
from vertice.rebounds import ReboundConfig, evaluate_rebounds

def two_sessions():
    ts=list(pd.date_range("2026-01-01 16:57",periods=3,freq="min",tz="America/Sao_Paulo"))+list(pd.date_range("2026-01-02 10:00",periods=3,freq="min",tz="America/Sao_Paulo"))
    close=[100,99.8,99.5,50,49.8,49.5]
    return pd.DataFrame({"timestamp":ts,"open":close,"high":[x+.2 for x in close],"low":[x-.2 for x in close],"close":close,"volume":[100]*6})

def test_control_outcome_skips_signal_at_session_end():
    x=two_sessions()
    events=pd.DataFrame([{"timestamp":x.loc[2,"timestamp"],"signal_index":2,"drawdown_from_peak":-.01,"bounce_return":-.01}])
    assert forward_event_outcomes(x,events,horizon_bars=3,event_type="control").empty

def test_control_horizon_stays_within_session():
    x=two_sessions()
    events=pd.DataFrame([{"timestamp":x.loc[1,"timestamp"],"signal_index":1,"drawdown_from_peak":-.01,"bounce_return":-.01}])
    out=forward_event_outcomes(x,events,horizon_bars=5,event_type="control")
    assert len(out)==1 and out.iloc[0].exit_timestamp.date()==out.iloc[0].entry_timestamp.date()

def test_rebound_does_not_enter_next_session():
    x=two_sessions()
    signals=pd.DataFrame([{"timestamp":x.loc[2,"timestamp"],"close":99.5,"rolling_peak_prev":100,"drawdown_from_peak":-.005,"bounce_return":-.003,"signal_index":2}])
    assert evaluate_rebounds(x,signals,ReboundConfig(lookback_bars=2,horizon_bars=2)).empty
