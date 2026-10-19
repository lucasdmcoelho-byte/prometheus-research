"""CSV ingestion and quality checks for intraday OHLCV data."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import pandas as pd
REQUIRED = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
PRICE_COLS = ["open", "high", "low", "close"]
@dataclass
class QualityReport:
    rows: int
    symbols: int
    duplicate_symbol_timestamps: int
    missing_values_required: int
    invalid_ohlc_rows: int
    nonpositive_prices: int
    negative_volume_rows: int
    timestamp_timezone: str
    start: str | None
    end: str | None
    def to_dict(self): return asdict(self)
def load_ohlcv_csv(path: str | Path, *, naive_timezone: str | None = None) -> pd.DataFrame:
    """Load and normalize OHLCV CSV. Naive timestamps require explicit timezone."""
    df = pd.read_csv(path)
    missing = sorted(set(REQUIRED) - set(df.columns))
    if missing: raise ValueError(f"Missing required columns: {missing}")
    ts = pd.to_datetime(df["timestamp"], errors="raise")
    if getattr(ts.dt, "tz", None) is None:
        if naive_timezone is None: raise ValueError("Naive timestamps found; pass naive_timezone explicitly")
        ts = ts.dt.tz_localize(naive_timezone, ambiguous="raise", nonexistent="raise")
    df["timestamp"] = ts.dt.tz_convert("UTC")
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    for c in PRICE_COLS + ["volume"]: df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values(["symbol", "timestamp"], kind="stable").reset_index(drop=True)
def quality_report(df: pd.DataFrame) -> QualityReport:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing: raise ValueError(f"Missing required columns: {missing}")
    dupes = int(df.duplicated(["symbol", "timestamp"]).sum())
    missing_count = int(df[REQUIRED].isna().sum().sum())
    invalid_ohlc = int(((df["high"] < df[["open", "close", "low"]].max(axis=1)) | (df["low"] > df[["open", "close", "high"]].min(axis=1))).sum())
    nonpositive = int((df[PRICE_COLS] <= 0).any(axis=1).sum())
    negative_volume = int((df["volume"] < 0).sum())
    tz = str(df["timestamp"].dt.tz) if hasattr(df["timestamp"].dt, "tz") else "unknown"
    return QualityReport(len(df), int(df["symbol"].nunique()), dupes, missing_count, invalid_ohlc, nonpositive, negative_volume, tz,
      df["timestamp"].min().isoformat() if len(df) else None, df["timestamp"].max().isoformat() if len(df) else None)
def add_returns(df: pd.DataFrame, horizons=(1, 3, 5, 10)) -> pd.DataFrame:
    """Add close-to-close absolute and fractional returns by symbol and bar horizon."""
    out = df.sort_values(["symbol", "timestamp"]).copy()
    grouped = out.groupby("symbol", sort=False)["close"]
    for h in horizons:
        prior = grouped.shift(h)
        out[f"delta_{h}"] = out["close"] - prior
        out[f"return_{h}"] = out["close"] / prior - 1.0
    return out
def check_regular_intervals(df: pd.DataFrame, expected_minutes: int = 1) -> pd.DataFrame:
    """Report gaps; does not infer bars during auctions, halts, or session breaks."""
    rows, expected = [], pd.Timedelta(minutes=expected_minutes)
    for symbol, g in df.sort_values("timestamp").groupby("symbol"):
        diffs = g["timestamp"].diff()
        for idx in g.index[diffs > expected]:
            rows.append({"symbol":symbol,"timestamp":g.loc[idx,"timestamp"],"gap_minutes":diffs.loc[idx].total_seconds()/60,"expected_minutes":expected_minutes})
    return pd.DataFrame(rows, columns=["symbol","timestamp","gap_minutes","expected_minutes"])
