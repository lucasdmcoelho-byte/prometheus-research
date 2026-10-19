"""Position sizing and portfolio exposure checks for research simulations."""
from __future__ import annotations
import math
import pandas as pd

def position_size_by_risk(capital: float, risk_fraction: float, entry_price: float, stop_price: float, *, max_gross_fraction: float = 1.0, lot_size: int = 1) -> dict:
    """Shares limited by stop risk and gross exposure; no broker execution."""
    if capital <= 0 or entry_price <= 0 or stop_price <= 0:
        raise ValueError("capital and prices must be positive")
    if not 0 < risk_fraction <= 1 or not 0 < max_gross_fraction <= 1:
        raise ValueError("risk_fraction and max_gross_fraction must be in (0, 1]")
    if stop_price == entry_price:
        raise ValueError("stop must differ from entry")
    if lot_size < 1:
        raise ValueError("lot_size must be >= 1")
    risk_budget = capital * risk_fraction
    shares_risk = math.floor(risk_budget / abs(entry_price - stop_price))
    shares_gross = math.floor(capital * max_gross_fraction / entry_price)
    shares = min(shares_risk, shares_gross)
    shares = (shares // lot_size) * lot_size
    return {"shares": shares, "notional": shares * entry_price,
            "planned_stop_loss": shares * abs(entry_price - stop_price),
            "risk_budget": risk_budget, "gross_fraction": shares * entry_price / capital,
            "binding_constraint": "risk" if shares_risk <= shares_gross else "gross_exposure"}

def portfolio_exposure(positions: pd.DataFrame) -> dict:
    """Gross/net exposure from market_value and side (+1 long, -1 short)."""
    if not {"market_value", "side"}.issubset(positions.columns):
        raise ValueError("required columns: market_value and side")
    if positions.empty:
        return {"gross_exposure": 0.0, "net_exposure": 0.0, "largest_position_fraction": 0.0, "n_positions": 0}
    values = pd.to_numeric(positions["market_value"], errors="raise").abs()
    side = pd.to_numeric(positions["side"], errors="raise")
    if not side.isin([-1, 1]).all():
        raise ValueError("side must be +1 (long) or -1 (short)")
    gross = float(values.sum())
    return {"gross_exposure": gross, "net_exposure": float((values * side).sum()),
            "largest_position_fraction": float(values.max()/gross) if gross else 0.0,
            "n_positions": int(len(positions))}
