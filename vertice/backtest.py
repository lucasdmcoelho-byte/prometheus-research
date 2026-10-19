"""Transparent cost-adjusted backtest helpers; research/simulation only."""
from __future__ import annotations
import pandas as pd
import numpy as np
def apply_round_trip_costs(trades:pd.DataFrame,*,fee_bps:float=0.0,spread_bps:float=0.0,slippage_bps:float=0.0)->pd.DataFrame:
    """Subtract round-trip cost estimates in basis points from gross fractional returns."""
    out=trades.copy(); out["cost_fraction"]=(fee_bps+spread_bps+slippage_bps)/10_000; out["net_return"]=out["gross_return"]-out["cost_fraction"]
    return out
def performance_summary(net_returns:pd.Series)->dict:
    r=pd.Series(net_returns,dtype=float).dropna()
    if r.empty: return {"n":0,"win_rate":np.nan,"expectancy":np.nan,"profit_factor":np.nan,"max_drawdown":np.nan}
    eq=(1+r).cumprod(); pos,neg=r[r>0],r[r<0]
    pf=float(pos.sum()/abs(neg.sum())) if len(neg) and neg.sum() else (np.inf if len(pos) else np.nan)
    return {"n":int(len(r)),"win_rate":float((r>0).mean()),"expectancy":float(r.mean()),"mean_win":float(pos.mean()) if len(pos) else np.nan,"mean_loss":float(neg.mean()) if len(neg) else np.nan,"profit_factor":pf,"max_drawdown":float((eq/eq.cummax()-1).min()),"median_return":float(r.median()),"std_return":float(r.std(ddof=1)) if len(r)>1 else np.nan}
