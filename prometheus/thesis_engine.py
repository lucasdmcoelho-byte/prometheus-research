from typing import Any, Dict, Optional

WEIGHTS = {
    "fundamental": 0.23,
    "sector": 0.14,
    "macro": 0.10,
    "expectation_gap": 0.14,
    "momentum_velocity": 0.14,
    "valuation_margin": 0.20,
    "news_sentiment": 0.05,
}


def calculate_score(scores: Dict[str, Any], unavailable: Optional[set[str]] = None) -> float:
    """Calculate the weighted thesis score and round to 2 decimals.

    Expects `scores` to be a dict with the same keys as `WEIGHTS`.
    """
    # ``None`` is the canonical value for a component that has no eligible
    # evidence. Treating it as zero or as 50 would invent a conclusion.
    unavailable = set(unavailable or set()) | {
        key for key in WEIGHTS if scores.get(key) is None
    }
    active_weight = sum(weight for key, weight in WEIGHTS.items() if key not in unavailable)
    if active_weight <= 0:
        return 0.0
    total = 0.0
    for key, weight in WEIGHTS.items():
        if key not in unavailable:
            total += float(scores.get(key, 0)) * weight / active_weight

    return round(total, 2)


def evidence_coverage(unavailable: Optional[set[str]] = None) -> float:
    """Return the share of thesis-score weight supported by available evidence."""
    unavailable = unavailable or set()
    return round(100.0 * sum(weight for key, weight in WEIGHTS.items() if key not in unavailable), 2)


def calculate_sector_score(sector_name: Optional[str]) -> None:
    """Return no score until a point-in-time peer-history model exists.

    The sector catalogue describes economic context, but is not score
    evidence. ``None`` is intentionally distinct from a neutral score: callers
    must exclude its weight and disclose the limitation.
    """
    return None


def calculate_macro_score(
    beta: Optional[float],
    market_cap: Optional[float],
    selic_rate: Optional[float] = None,
    sector_name: Optional[str] = None,
) -> float:
    # No current, point-in-time eligible policy-rate observation means there is
    # no macro evidence to score.  A neutral value keeps the weighted score
    # mathematically defined without representing a macro conclusion.
    if selic_rate is None:
        return 50.0
    beta_value = 1.0 if beta is None else max(0.0, beta)
    score = 70.0 + (1.0 - beta_value) * 15.0
    if market_cap and market_cap > 50_000_000_000:
        score += 5.0
    if market_cap and market_cap < 5_000_000_000:
        score -= 5.0

    if selic_rate is not None:
        sector = (sector_name or "").lower()
        if "real estate" in sector or "imobili" in sector or "construction" in sector:
            sensitivity = 2.0
        elif "financial" in sector or "bank" in sector:
            sensitivity = 0.5
        else:
            sensitivity = 1.0
        score -= max(0.0, float(selic_rate) - 8.0) * sensitivity
    return round(max(30.0, min(100.0, score)), 2)


def calculate_expectation_gap(price_change: Optional[float], fundamental_score: float) -> float:
    if price_change is None:
        return 70.0

    if fundamental_score <= 0:
        return 30.0

    gap = abs(price_change) / max(1.0, fundamental_score)
    score = 100.0 - min(75.0, gap * 100.0)
    if price_change > 12 and fundamental_score < 50:
        score = 35.0
    return round(max(25.0, min(100.0, score)), 2)


def calculate_momentum_velocity(
    price_change: Optional[float], year_change: Optional[float]
) -> float:
    if price_change is None and year_change is None:
        return 50.0

    velocity = 50.0
    if price_change is not None:
        velocity += price_change * 0.7
    if year_change is not None:
        velocity += year_change * 0.3

    return round(max(0.0, min(100.0, velocity)), 2)


def calculate_valuation_score(forward_pe: Optional[float], reference_pe: float = 14.0) -> float:
    """Convert a P/E multiple into a 0..100 valuation-attractiveness score."""
    if forward_pe is None or forward_pe <= 0 or reference_pe <= 0:
        return 50.0
    score = 50.0 + (reference_pe - forward_pe) / reference_pe * 50.0
    return round(max(0.0, min(100.0, score)), 2)


def calculate_thesis_scores(asset_data: Dict[str, object], news_sentiment: float = 50.0) -> Dict[str, Any]:
    fundamental = float(asset_data.get("fundamental_score") or 0.0)
    sector = calculate_sector_score(asset_data.get("sector_name") if isinstance(asset_data.get("sector_name"), str) else None)
    macro = calculate_macro_score(
        asset_data.get("beta") if isinstance(asset_data.get("beta"), (int, float)) else None,
        asset_data.get("market_cap") if isinstance(asset_data.get("market_cap"), (int, float)) else None,
    )
    expectation_gap = calculate_expectation_gap(
        asset_data.get("price_change_percent") if isinstance(asset_data.get("price_change_percent"), (int, float)) else None,
        fundamental,
    )
    momentum_velocity = calculate_momentum_velocity(
        asset_data.get("price_change_percent") if isinstance(asset_data.get("price_change_percent"), (int, float)) else None,
        asset_data.get("fifty_two_week_change") if isinstance(asset_data.get("fifty_two_week_change"), (int, float)) else None,
    )
    valuation_margin = float(asset_data.get("valuation_margin") or 0.0)
    return {
        "fundamental": fundamental,
        "sector": sector,
        "macro": macro,
        "expectation_gap": expectation_gap,
        "momentum_velocity": momentum_velocity,
        "valuation_margin": valuation_margin,
        "news_sentiment": float(news_sentiment),
    }


def get_state(score: float) -> str:
    if score >= 85:
        return "STRONG BULL"
    if score >= 70:
        return "BULL"
    if score >= 50:
        return "NEUTRAL"
    if score >= 30:
        return "WEAKENING"
    return "BEAR"
