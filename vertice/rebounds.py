"""Chronological rebound-event detection and outcome evaluation."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import numpy as np
@dataclass(frozen=True)
class ReboundConfig:
    lookback_bars:int=5
    drawdown_threshold:float=0.004
    min_bounce:float=0.0005
    horizon_bars:int=5
    target_return:float=0.002
    stop_return:float=0.002
    cooldown_bars:int=5
def detect_rebounds(df:pd.DataFrame,config:ReboundConfig=ReboundConfig())->pd.DataFrame:
    """Signal uses current/past bars only; entry is scheduled for next-bar open."""
    if config.lookback_bars<2 or config.horizon_bars<1: raise ValueError("lookback_bars >= 2 and horizon_bars >= 1 required")
    x=df.sort_values("timestamp").reset_index(drop=True).copy()
    x["session_date"]=x["timestamp"].dt.tz_convert("America/Sao_Paulo").dt.date
    x["rolling_peak_prev"]=x.groupby("session_date")["close"].transform(lambda s:s.shift(1).rolling(config.lookback_bars,min_periods=config.lookback_bars).max())
    x["previous_close"]=x.groupby("session_date")["close"].shift(1)
    x["drawdown_from_peak"]=x["close"]/x["rolling_peak_prev"]-1
    x["bounce_return"]=x["close"]/x["previous_close"]-1
    flags=((x["drawdown_from_peak"]<=-abs(config.drawdown_threshold))&(x["bounce_return"]>=config.min_bounce)).fillna(False).to_numpy()
    accepted=[]; last=-10**9
    for i,flag in enumerate(flags):
        if flag and i>last: accepted.append(i); last=i+max(config.horizon_bars,config.cooldown_bars)
    return x.loc[accepted,["timestamp","close","rolling_peak_prev","drawdown_from_peak","bounce_return"]].assign(signal_index=accepted).reset_index(drop=True)
def evaluate_rebounds(df:pd.DataFrame,signals:pd.DataFrame,config:ReboundConfig=ReboundConfig(),*,stop_first:bool=True)->pd.DataFrame:
    """Enter at next bar open. If stop and target hit in one OHLC bar, default to stop first."""
    x=df.sort_values("timestamp").reset_index(drop=True); out=[]
    for row in signals.itertuples(index=False):
        i=int(row.signal_index); entry_i=i+1
        if entry_i>=len(x): continue
        end=min(entry_i+config.horizon_bars,len(x))
        session=x.loc[entry_i,"timestamp"].tz_convert("America/Sao_Paulo").date()
        while end>entry_i and x.loc[end-1,"timestamp"].tz_convert("America/Sao_Paulo").date()!=session: end-=1
        entry=float(x.loc[entry_i,"open"]); future=x.iloc[entry_i:end]
        if entry<=0 or future.empty: continue
        target,stop=entry*(1+config.target_return),entry*(1-config.stop_return)
        exit_price,reason,exit_i=float(future.iloc[-1]["close"]),"horizon",end-1
        for j,bar in future.iterrows():
            ht,hs=float(bar["high"])>=target,float(bar["low"])<=stop
            if ht and hs:
                exit_price,reason,exit_i=(stop,"stop_and_target_same_bar_stop_first",j) if stop_first else (target,"stop_and_target_same_bar_target_first",j); break
            if hs: exit_price,reason,exit_i=stop,"stop",j; break
            if ht: exit_price,reason,exit_i=target,"target",j; break
        out.append({"signal_timestamp":row.timestamp,"entry_timestamp":x.loc[entry_i,"timestamp"],"entry_price":entry,"exit_timestamp":x.loc[exit_i,"timestamp"],"exit_price":exit_price,"exit_reason":reason,"gross_return":exit_price/entry-1,"mfe":float(future["high"].max()/entry-1),"mae":float(future["low"].min()/entry-1),"bars_held":int(exit_i-entry_i+1)})
    return pd.DataFrame(out)
def summarize_trades(trades:pd.DataFrame,cost_per_trade:float=0.0)->dict:
    """Summarize fractional-return trades; cost_per_trade is round-trip fraction."""
    if trades.empty: return {"n":0,"win_rate":np.nan,"mean_net_return":np.nan,"profit_factor":np.nan,"max_drawdown":np.nan}
    net=trades["gross_return"].astype(float)-cost_per_trade; wins,losses=net[net>0],net[net<0]; equity=(1+net).cumprod(); dd=equity/equity.cummax()-1
    pf=float(wins.sum()/abs(losses.sum())) if len(losses) and losses.sum()!=0 else (np.inf if len(wins) else np.nan)
    return {"n":int(len(net)),"win_rate":float((net>0).mean()),"mean_net_return":float(net.mean()),"mean_win":float(wins.mean()) if len(wins) else np.nan,"mean_loss":float(losses.mean()) if len(losses) else np.nan,"profit_factor":pf,"max_drawdown":float(dd.min()),"net_returns":net.tolist()}
