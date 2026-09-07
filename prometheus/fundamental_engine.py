from typing import Dict, List, Optional

WEIGHTS = {
    "revenue_growth": 20,
    "earnings_growth": 25,
    "profit_margin": 20,
    "roe": 20,
    "debt_to_equity": 15,
}


def _score_growth(value: float, cap: float, max_points: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(value, cap) / cap * max_points


def _score_margin(value: float, cap: float, max_points: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(value, cap) / cap * max_points


def _score_debt_to_equity(value: float) -> float:
    if value is None or value < 0:
        return 0.0
    if value <= 0.5:
        return 15.0
    if value >= 2.0:
        return 0.0
    return (2.0 - value) / (2.0 - 0.5) * 15.0


def calculate_fundamental_score(financial_data: Dict[str, Optional[float]]) -> Dict[str, object]:
    """Heuristic v1 fundamental score from available financial indicators."""
    component_points: Dict[str, float] = {}
    raw_points = 0.0
    available_weight = 0.0
    missing_components: List[str] = []

    for field, weight in WEIGHTS.items():
        value = financial_data.get(field)
        if value is None:
            missing_components.append(field)
            continue

        if field == "revenue_growth":
            points = _score_growth(value, 0.50, weight)
        elif field == "earnings_growth":
            points = _score_growth(value, 0.50, weight)
        elif field == "profit_margin":
            points = _score_margin(value, 0.30, weight)
        elif field == "roe":
            points = _score_margin(value, 0.25, weight)
        elif field == "debt_to_equity":
            points = _score_debt_to_equity(value)
        else:
            points = 0.0

        component_points[field] = round(points, 2)
        raw_points += points
        available_weight += weight

    if available_weight == 0:
        score = 0.0
    else:
        score = round(raw_points / available_weight * 100.0, 2)

    score = max(0.0, min(score, 100.0))
    confidence = round((available_weight / sum(WEIGHTS.values())) * 100, 2)

    return {
        "score": score,
        "component_scores": component_points,
        "missing_components": missing_components,
        "confidence": confidence,
    }
