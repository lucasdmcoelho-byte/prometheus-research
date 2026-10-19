"""Analysis for manual snapshots; these are not OHLCV candles."""
from pathlib import Path
import pandas as pd

def load_manual_snapshots(path: str | Path) -> pd.DataFrame:
    x=pd.read_csv(path)
    x["timestamp"]=pd.to_datetime(x["timestamp_local"],utc=True,errors="coerce")
    x["symbol"]=x["symbol"].astype(str).str.upper()
    x["price"]=pd.to_numeric(x["price"],errors="raise")
    return x.sort_values(["symbol","timestamp"],na_position="last").reset_index(drop=True)

def snapshot_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Changes between time-stamped observations only; no prices inferred between snapshots."""
    x=df.sort_values(["symbol","timestamp"],na_position="last").copy()
    timed_price=x["price"].where(x["timestamp"].notna())
    x["previous_price"]=timed_price.groupby(x["symbol"]).ffill().groupby(x["symbol"]).shift()
    x.loc[x["timestamp"].isna(),"previous_price"]=float("nan")
    x["delta"]=x["price"]-x["previous_price"]
    x["return_pct"]=(x["price"]/x["previous_price"]-1)*100
    x["minutes_since_previous"]=x.groupby("symbol")["timestamp"].diff().dt.total_seconds()/60
    return x
