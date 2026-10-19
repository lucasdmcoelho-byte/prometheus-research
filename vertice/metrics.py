"""Descriptive metrics for intraday paths and synchronized returns."""
from __future__ import annotations
import numpy as np
import pandas as pd
def intraday_range_pct(df: pd.DataFrame) -> pd.DataFrame:
    """Per symbol/session range: (max(high)-min(low))/first open."""
    x=df.copy(); x["session_date"]=x["timestamp"].dt.tz_convert("America/Sao_Paulo").dt.date
    rows=[]
    for (symbol,date),g in x.groupby(["symbol","session_date"]):
        g=g.sort_values("timestamp"); first=float(g["open"].iloc[0]); hi=float(g["high"].max()); lo=float(g["low"].min())
        rows.append({"symbol":symbol,"session_date":str(date),"high":hi,"low":lo,"range_abs":hi-lo,"range_pct":(hi-lo)/first if first else np.nan})
    return pd.DataFrame(rows)
def path_runs(close: pd.Series) -> dict:
    """Run lengths and counts of positive/negative close changes."""
    signs=np.sign(close.astype(float).diff().dropna().to_numpy()).astype(int)
    def runs_for(sign):
        lens=[]; n=0
        for s in signs:
            if s==sign: n+=1
            elif n: lens.append(n); n=0
        if n: lens.append(n)
        return lens
    up,down,flat=runs_for(1),runs_for(-1),runs_for(0)
    return {"up_run_count":len(up),"up_run_max":max(up,default=0),"down_run_count":len(down),"down_run_max":max(down,default=0),"flat_change_count":int((signs==0).sum()),"changes":len(signs)}
def excursion(entry: float, future_high: pd.Series, future_low: pd.Series) -> tuple[float,float]:
    """Long-side MFE and MAE as fractional returns from entry."""
    if entry<=0 or len(future_high)==0: return (float("nan"),float("nan"))
    return float(future_high.max()/entry-1),float(future_low.min()/entry-1)
def returns_frame(df: pd.DataFrame, price_col: str="close") -> pd.DataFrame:
    px=df.pivot_table(index="timestamp",columns="symbol",values=price_col,aggfunc="last").sort_index()
    return px.pct_change(fill_method=None)
def contemporaneous_corr(returns: pd.DataFrame,min_periods: int=30)->pd.DataFrame:
    return returns.corr(min_periods=min_periods)
def lagged_corr(returns: pd.DataFrame,source: str,target: str,max_lag: int=10,min_periods: int=30)->pd.DataFrame:
    """corr(r_source[t], r_target[t+lag]); positive lag means source leads."""
    if source not in returns or target not in returns: raise KeyError(f"Missing source/target columns: {source}, {target}")
    rows=[]
    for lag in range(-max_lag,max_lag+1):
        aligned=returns[target].shift(-lag); pair=pd.concat([returns[source],aligned],axis=1).dropna()
        corr=pair.iloc[:,0].corr(pair.iloc[:,1]) if len(pair)>=min_periods else np.nan
        rows.append({"source":source,"target":target,"lag_bars":lag,"n":len(pair),"correlation":corr})
    return pd.DataFrame(rows)
def residualize_on_market(returns: pd.DataFrame,asset: str,market: str)->pd.Series:
    """OLS residuals from asset returns regressed on market returns; not causal identification."""
    pair=returns[[asset,market]].dropna()
    if len(pair)<3: return pd.Series(index=returns.index,dtype=float,name=f"{asset}_resid")
    x=np.column_stack([np.ones(len(pair)),pair[market].to_numpy()]); beta=np.linalg.lstsq(x,pair[asset].to_numpy(),rcond=None)[0]
    return pd.Series(pair[asset].to_numpy()-x@beta,index=pair.index,name=f"{asset}_resid")
