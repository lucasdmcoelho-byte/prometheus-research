"""Reproduce descriptive analysis of manual snapshots; not a candle backtest."""
from pathlib import Path
import json, sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from vertice.manual_observations import load_manual_snapshots,snapshot_returns
source=ROOT/"data"/"manual_observations_2026-10-19.csv"
reports=ROOT/"reports"; reports.mkdir(exist_ok=True)
x=load_manual_snapshots(source); y=snapshot_returns(x)
timed=y[y.timestamp.notna()].copy(); intervals=timed.dropna(subset=["return_pct"]).copy()
pivot=timed.pivot_table(index="timestamp",columns="symbol",values="price",aggfunc="last").sort_index()
rets=pivot.pct_change(fill_method=None); correlations={}
if "IBOV" in rets:
    for symbol in rets.columns:
        if symbol=="IBOV": continue
        pair=rets[[symbol,"IBOV"]].dropna()
        correlations[symbol]={"n_aligned_returns":int(len(pair)),"pearson_corr_with_ibov":float(pair[symbol].corr(pair["IBOV"])) if len(pair)>=3 else None}
summary={"dataset_type":"manual user-reported snapshots; not official OHLCV","source_file":"data/manual_observations_2026-10-19.csv","rows":int(len(y)),"timed_rows":int(y.timestamp.notna().sum()),"untimed_rows":int(y.timestamp.isna().sum()),"symbols":sorted(y.symbol.unique().tolist()),"interval_return_observations":int(len(intervals)),"first_timestamp_local":str(timed.timestamp.min().tz_convert("America/Sao_Paulo")),"last_timestamp_local":str(timed.timestamp.max().tz_convert("America/Sao_Paulo")),"snapshot_return_correlation_with_ibov":correlations,"limitations":["irregular timestamps","no volume per interval","no intrainterval high/low","user-transcribed prices not independently verified","correlations descriptive only; no lead-lag or prediction inference"]}
intervals.to_csv(reports/"manual_snapshot_interval_changes.csv",index=False)
(reports/"manual_snapshot_analysis.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False))
print(json.dumps(summary,indent=2,ensure_ascii=False))
