"""Control-event construction for rebound hypothesis tests."""
from __future__ import annotations
import pandas as pd

def detect_drawdown_controls(df: pd.DataFrame, *, lookback_bars: int = 5,
                             drawdown_threshold: float = 0.004,
                             max_bounce: float = 0.0005,
                             cooldown_bars: int = 5) -> pd.DataFrame:
    """Find drawdown events without the rebound threshold; signals use past/current bars only."""
    if lookback_bars < 2 or cooldown_bars < 0:
        raise ValueError("lookback_bars >= 2 and cooldown_bars >= 0 required")
    x = df.sort_values("timestamp").reset_index(drop=True).copy()
    session_dates = x["timestamp"].dt.tz_convert("America/Sao_Paulo").dt.date
    peak = x.groupby(session_dates)["close"].transform(lambda s: s.shift(1).rolling(lookback_bars, min_periods=lookback_bars).max())
    previous = x.groupby(session_dates)["close"].shift(1)
    dd = x["close"] / peak - 1
    bounce = x["close"] / previous - 1
    flags = ((dd <= -abs(drawdown_threshold)) & (bounce < max_bounce)).fillna(False).to_numpy()
    chosen, last = [], -10**9
    for i, flag in enumerate(flags):
        if flag and i > last:
            chosen.append(i)
            last = i + cooldown_bars
    return pd.DataFrame({"timestamp": x.loc[chosen, "timestamp"].to_list(),
                         "signal_index": chosen,
                         "drawdown_from_peak": dd.iloc[chosen].to_numpy(),
                         "bounce_return": bounce.iloc[chosen].to_numpy()})

def forward_event_outcomes(df: pd.DataFrame, events: pd.DataFrame, *, horizon_bars: int = 5,
                           event_type: str = "event") -> pd.DataFrame:
    """Return next-bar-open to horizon-close return plus MFE/MAE for event/control rows."""
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be >= 1")
    x = df.sort_values("timestamp").reset_index(drop=True)
    session_dates = x["timestamp"].dt.tz_convert("America/Sao_Paulo").dt.date
    rows = []
    for event in events.itertuples(index=False):
        signal_i = int(event.signal_index)
        entry_i = signal_i + 1
        if entry_i >= len(x) or session_dates.iloc[entry_i] != session_dates.iloc[signal_i]:
            continue
        end = min(entry_i + horizon_bars, len(x))
        while end > entry_i and session_dates.iloc[end - 1] != session_dates.iloc[entry_i]:
            end -= 1
        entry = float(x.loc[entry_i, "open"])
        future = x.iloc[entry_i:end]
        if entry <= 0 or future.empty:
            continue
        exit_price = float(future.iloc[-1]["close"])
        rows.append({"event_type": event_type, "signal_timestamp": event.timestamp,
                     "entry_timestamp": x.loc[entry_i, "timestamp"], "entry_price": entry,
                     "exit_timestamp": future.iloc[-1]["timestamp"], "horizon_return": exit_price / entry - 1,
                     "mfe": float(future["high"].max() / entry - 1),
                     "mae": float(future["low"].min() / entry - 1), "bars_observed": len(future)})
    return pd.DataFrame(rows)
