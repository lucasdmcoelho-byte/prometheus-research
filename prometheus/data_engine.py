import time
from typing import Dict, Optional

import yfinance as yf

from prometheus.data_quality import (
    calculate_data_quality,
    normalize_percentage,
    normalize_ratio,
    validate_numeric,
)
from prometheus.fundamental_engine import calculate_fundamental_score
from prometheus.thesis_engine import (
    calculate_expectation_gap,
    calculate_macro_score,
    calculate_momentum_velocity,
    calculate_sector_score,
)


def validate_ticker(ticker: str) -> str:
    """Normalize and validate a ticker string."""
    if not isinstance(ticker, str):
        raise TypeError("Ticker must be a string")

    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("Ticker cannot be empty")

    return normalized


def _to_b3_symbol(ticker: str) -> str:
    return ticker if ticker.endswith(".SA") else f"{ticker}.SA"


def _safe_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_string(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text else None


def _fetch_ticker_info(ticker_symbol: str, attempts: int = 3, delay_seconds: float = 1.0) -> Dict[str, object]:
    last_exception: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info
            if isinstance(info, dict) and info:
                return info
        except Exception as error:
            last_exception = error
            if attempt < attempts:
                time.sleep(delay_seconds)
    if last_exception is not None:
        raise RuntimeError(
            f"Failed to fetch ticker info for {ticker_symbol}: {last_exception}"
        ) from last_exception
    return {}


def _build_data_field(
    raw_value: Optional[float],
    source_field: str,
    data_type: str,
) -> Dict[str, Optional[object]]:
    entry = {
        "raw": raw_value,
        "normalized": None,
        "status": "MISSING",
        "semantic_status": "MISSING",
        "unit": None,
        "source": "yfinance",
        "field": source_field,
        "interpretation": None,
    }

    numeric_value = validate_numeric(raw_value)
    if numeric_value is None:
        if raw_value is None:
            entry["status"] = "MISSING"
            entry["semantic_status"] = "MISSING"
        else:
            entry["status"] = "INVALID"
            entry["semantic_status"] = "UNVERIFIED"
            entry["interpretation"] = "Non-numeric raw value"
        return entry

    if data_type == "percentage":
        normalized = normalize_percentage(numeric_value)
        if normalized is None:
            entry["status"] = "SUSPICIOUS"
            entry["semantic_status"] = "UNVERIFIED"
            entry["interpretation"] = (
                "Value may be outside expected percentage/ratio scale"
            )
            entry["unit"] = "UNKNOWN"
        else:
            entry["status"] = "VALID"
            if -1.0 <= numeric_value <= 1.0:
                entry["unit"] = "RATIO"
                entry["interpretation"] = "Raw number treated as ratio"
            else:
                entry["unit"] = "PERCENTAGE"
                entry["interpretation"] = "Raw number treated as percent"
            entry["semantic_status"] = "VERIFIED"
        entry["normalized"] = normalized
    elif data_type == "ratio":
        # Yahoo's debtToEquity field is expressed in percentage points.
        provider_value = numeric_value / 100.0 if source_field == "debtToEquity" else numeric_value
        normalized = normalize_ratio(provider_value)
        if normalized is None:
            entry["status"] = "SUSPICIOUS"
            entry["semantic_status"] = "UNVERIFIED"
            entry["unit"] = "UNKNOWN"
            entry["interpretation"] = (
                "Raw ratio outside expected scale"
            )
        else:
            entry["status"] = "VALID"
            entry["unit"] = "RATIO"
            entry["interpretation"] = (
                "Provider percentage points converted to debt/equity ratio"
                if source_field == "debtToEquity"
                else "Raw number treated as ratio"
            )
            entry["semantic_status"] = "VERIFIED"
        entry["normalized"] = normalized
    else:
        entry["status"] = "INVALID"
        entry["semantic_status"] = "UNVERIFIED"
        entry["interpretation"] = "Unsupported data type"

    return entry


def get_fundamental_data(ticker: str) -> Dict[str, Dict[str, Optional[object]]]:
    ticker = validate_ticker(ticker)
    ticker_symbol = _to_b3_symbol(ticker)
    ticker_info = _fetch_ticker_info(ticker_symbol)

    raw_fields = {
        "revenue_growth": "revenueGrowth",
        "earnings_growth": "earningsGrowth",
        "profit_margin": "profitMargins",
        "roe": "returnOnEquity",
        "debt_to_equity": "debtToEquity",
    }

    normalized_data = {}
    for key, source_field in raw_fields.items():
        raw_value = ticker_info.get(source_field)
        data_type = "percentage" if key != "debt_to_equity" else "ratio"
        normalized_data[key] = _build_data_field(raw_value, source_field, data_type)

    return normalized_data


def _calculate_valuation_margin(ticker_info: dict, price: Optional[float]) -> Dict[str, Optional[object]]:
    raw_eps = _safe_float(
        ticker_info.get("trailingEps")
        or ticker_info.get("epsTrailingTwelveMonths")
        or ticker_info.get("earningsPerShare")
    )

    entry = {
        "raw": None,
        "normalized": None,
        "status": "MISSING",
        "semantic_status": "MISSING",
        "unit": "P/E",
        "source": "yfinance",
        "field": "trailingEps",
        "interpretation": None,
    }

    if price is None:
        entry["status"] = "MISSING"
        entry["semantic_status"] = "MISSING"
        entry["interpretation"] = (
            "Current price is unavailable, so P/L cannot be calculated."
        )
        return entry

    if raw_eps is None:
        entry["status"] = "MISSING"
        entry["semantic_status"] = "MISSING"
        entry["interpretation"] = (
            "Earnings per share is unavailable from yfinance, so valuation margin cannot be calculated."
        )
        return entry

    if raw_eps <= 0:
        entry["status"] = "INVALID"
        entry["semantic_status"] = "UNVERIFIED"
        entry["interpretation"] = (
            "Negative or zero EPS cannot produce a meaningful P/L ratio."
        )
        return entry

    pe_ratio = price / raw_eps
    entry["raw"] = pe_ratio

    reference_pe = 14.0
    score = 50.0 + (reference_pe - pe_ratio) / reference_pe * 50.0
    score = max(0.0, min(100.0, score))

    entry["normalized"] = score
    entry["status"] = "VALID"
    entry["semantic_status"] = "VERIFIED"
    entry["interpretation"] = (
        "P/L atual comparado a uma referência histórica de P/L. "
        "Valores mais baixos do que a referência produzem score mais alto."
    )

    return entry


def get_asset_data(ticker: str) -> Dict[str, object]:
    ticker = validate_ticker(ticker)
    ticker_symbol = _to_b3_symbol(ticker)
    ticker_info = _fetch_ticker_info(ticker_symbol)

    price = _safe_float(
        ticker_info.get("regularMarketPrice")
        or ticker_info.get("currentPrice")
        or ticker_info.get("previousClose")
    )
    previous_close = _safe_float(ticker_info.get("previousClose"))
    if price is None and previous_close is not None:
        price = previous_close

    price_change = None
    price_change_percent = _safe_float(ticker_info.get("regularMarketChangePercent"))
    if price is not None and previous_close is not None:
        price_change = round(price - previous_close, 2)
        if previous_close != 0:
            price_change_percent = round((price - previous_close) / previous_close * 100.0, 2)

    market_cap = _safe_float(ticker_info.get("marketCap"))
    beta = _safe_float(ticker_info.get("beta"))
    sector_name = _safe_string(ticker_info.get("sector")) or "Unknown"
    industry_name = _safe_string(ticker_info.get("industry")) or "Unknown"
    currency = _safe_string(ticker_info.get("currency")) or "BRL"
    exchange = _safe_string(ticker_info.get("exchange")) or "Unknown"
    business_summary = _safe_string(ticker_info.get("longBusinessSummary")) or ""
    fifty_two_week_change = _safe_float(
        ticker_info.get("52WeekChange") or ticker_info.get("fiftyTwoWeekChange")
    )
    if fifty_two_week_change is not None and abs(fifty_two_week_change) <= 2.0:
        fifty_two_week_change *= 100.0
    fifty_two_week_low = _safe_float(ticker_info.get("fiftyTwoWeekLow"))
    fifty_two_week_high = _safe_float(ticker_info.get("fiftyTwoWeekHigh"))
    dividend_yield = _safe_float(ticker_info.get("dividendYield"))
    forward_pe = _safe_float(ticker_info.get("forwardPE"))
    trailing_pe = _safe_float(ticker_info.get("trailingPE"))
    enterprise_value = _safe_float(ticker_info.get("enterpriseValue"))
    shares_outstanding = _safe_float(ticker_info.get("sharesOutstanding"))

    fundamental_data = get_fundamental_data(ticker)
    normalized_values = {
        key: field["normalized"] for key, field in fundamental_data.items()
    }
    fundamental_score_data = calculate_fundamental_score(normalized_values)
    data_quality_summary = calculate_data_quality(fundamental_data)
    valuation_margin_data = _calculate_valuation_margin(ticker_info, price)

    sector_score = calculate_sector_score(sector_name if sector_name != "Unknown" else None)
    macro_score = calculate_macro_score(beta, market_cap)
    expectation_gap_score = calculate_expectation_gap(price_change_percent, fundamental_score_data["score"])
    momentum_velocity_score = calculate_momentum_velocity(price_change_percent, fifty_two_week_change)

    return {
        "ticker": ticker,
        "price": price,
        "previous_close": previous_close,
        "price_change": price_change,
        "price_change_percent": price_change_percent,
        "market_cap": market_cap,
        "beta": beta,
        "sector_name": sector_name,
        "industry_name": industry_name,
        "currency": currency,
        "exchange": exchange,
        "business_summary": business_summary,
        "fifty_two_week_change": fifty_two_week_change,
        "fifty_two_week_low": fifty_two_week_low,
        "fifty_two_week_high": fifty_two_week_high,
        "dividend_yield": dividend_yield,
        "forward_pe": forward_pe,
        "trailing_pe": trailing_pe,
        "enterprise_value": enterprise_value,
        "shares_outstanding": shares_outstanding,
        "fundamental_data": fundamental_data,
        "fundamental_score": fundamental_score_data["score"],
        "fundamental_confidence": fundamental_score_data["confidence"],
        "fundamental_data_quality": data_quality_summary,
        "sector": sector_score,
        "macro": macro_score,
        "expectation_gap": expectation_gap_score,
        "momentum_velocity": momentum_velocity_score,
        "valuation_margin": valuation_margin_data["normalized"],
        "valuation_margin_data": valuation_margin_data,
    }
