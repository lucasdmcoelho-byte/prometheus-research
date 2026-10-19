import pandas as pd
from vertice.rebounds import ReboundConfig,detect_rebounds,evaluate_rebounds,summarize_trades

def bars():
 close=[100,99.8,99.5,99.4,99.2,99.4,99.7,99.9,100.1,100.2]
 return pd.DataFrame({'timestamp':pd.date_range('2026-01-01 13:00',periods=len(close),freq='min',tz='UTC'),'open':close,'high':[x+0.03 for x in close],'low':[x-0.03 for x in close],'close':close,'volume':[100]*len(close)})
def test_detect_signal_uses_past_and_current_bars():
 cfg=ReboundConfig(lookback_bars=5,drawdown_threshold=.004,min_bounce=.001,horizon_bars=2,cooldown_bars=2); s=detect_rebounds(bars(),cfg); assert len(s)>=1 and (s.signal_index<len(bars())).all()
def test_evaluation_enters_next_bar_open():
 x=bars(); cfg=ReboundConfig(lookback_bars=5,drawdown_threshold=.004,min_bounce=.001,horizon_bars=2,cooldown_bars=2); s=detect_rebounds(x,cfg); t=evaluate_rebounds(x,s,cfg)
 if len(t):
  ix=int(x.index[x.timestamp==t.iloc[0].signal_timestamp][0]); assert t.iloc[0].entry_timestamp==x.iloc[ix+1].timestamp
def test_empty_trade_summary():
 assert summarize_trades(pd.DataFrame())['n']==0
