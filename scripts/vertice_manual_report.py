"""Summarize user-reported snapshots; not a continuous-market backtest."""
from pathlib import Path
from vertice.manual_observations import load_manual_snapshots,snapshot_returns
ROOT=Path(__file__).resolve().parents[1]
x=load_manual_snapshots(ROOT/"data"/"manual_observations_2026-10-19.csv")
y=snapshot_returns(x); timed=y[y.timestamp.notna()].dropna(subset=["delta"]).copy()
print(f"rows={len(y)} timed_rows={int(y.timestamp.notna().sum())} symbols={y.symbol.nunique()}")
print(timed.assign(abs_delta=lambda z:z.delta.abs()).nlargest(12,"abs_delta")[["timestamp_local","symbol","previous_price","price","delta","return_pct","minutes_since_previous"]].to_string(index=False))
