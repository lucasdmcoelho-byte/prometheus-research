from datetime import datetime
from typing import Any, Dict, Optional

from prometheus.models import AssetProfile, FinancialStatement, MarketSnapshot, SourceMetadata
from prometheus.adapters import DataAdapter
from prometheus.data_quality import validate_numeric
from prometheus.thesis_engine import calculate_macro_score, calculate_thesis_scores, calculate_valuation_score, get_state


class DataLayer:
    def __init__(self, adapter: DataAdapter):
        self.adapter = adapter

    def load(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        return self.adapter.fetch(ticker, as_of=as_of)


class NormalizationLayer:
    def normalize(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = {}
        normalized["ticker"] = raw_data.get("ticker")
        normalized["source_metadata"] = raw_data.get("source_metadata")
        normalized["field_metadata"] = raw_data.get("field_metadata", {})
        normalized["market_field_metadata"] = raw_data.get("market_field_metadata", {})
        normalized["macro_observations"] = raw_data.get("macro_observations", [])
        normalized["official_metrics"] = raw_data.get("official_metrics", {})
        normalized["financial_history"] = raw_data.get("financial_history", [])
        normalized["reference_form"] = raw_data.get("reference_form", {"status": "INSUFFICIENT_DATA", "sections": {}})
        normalized["technical_context"] = raw_data.get("technical_context", {"status": "INSUFFICIENT_DATA"})
        normalized["ttm"] = raw_data.get("ttm", {"status": "INSUFFICIENT_DATA", "metrics": {}})
        normalized["official_disclosures"] = raw_data.get("official_disclosures", {"status": "INSUFFICIENT_DATA", "documents": []})
        normalized["official_classification"] = raw_data.get("official_classification", {"status": "INSUFFICIENT_DATA"})
        normalized["data_source_status"] = raw_data.get("data_source_status", "PRIMARY")
        normalized["data_source_degradation"] = raw_data.get("data_source_degradation")
        normalized["info"] = raw_data.get("info")
        return normalized


class PointInTimeLayer:
    def __init__(self, as_of: Optional[datetime] = None):
        self.as_of = as_of

    def filter(self, normalized_data: Dict[str, Any]) -> Dict[str, Any]:
        if self.as_of is None:
            return normalized_data

        metadata_items = [normalized_data.get("source_metadata")]
        metadata_items.extend((normalized_data.get("field_metadata") or {}).values())
        metadata_items.extend((normalized_data.get("market_field_metadata") or {}).values())
        for metadata in metadata_items:
            self._validate_metadata(metadata)
        return normalized_data

    def _validate_metadata(self, metadata: Optional[SourceMetadata]) -> None:
        if metadata is None:
            raise ValueError("Point-in-time data must include source metadata.")
        publication_date = getattr(metadata, "publication_date", None)
        effective_date = getattr(metadata, "effective_date", None)
        timestamp = getattr(metadata, "timestamp", None)
        available_at = publication_date or effective_date or timestamp
        if available_at is None:
            raise ValueError("Point-in-time data must include an availability timestamp.")

        cutoff = self.as_of
        if available_at.tzinfo is not None and cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=available_at.tzinfo)
        elif available_at.tzinfo is None and cutoff.tzinfo is not None:
            available_at = available_at.replace(tzinfo=cutoff.tzinfo)
        if available_at > cutoff:
            raise ValueError(
                f"Data available at {available_at.isoformat()} exceeds point-in-time cutoff "
                f"{cutoff.isoformat()}."
            )


class FeatureEngine:
    def build_asset_profile(self, normalized_data: Dict[str, Any]) -> AssetProfile:
        info = normalized_data.get("info", {})
        source_metadata = normalized_data.get("source_metadata")
        return AssetProfile(
            ticker=normalized_data.get("ticker"),
            company_name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            currency=info.get("currency"),
            exchange=info.get("exchange"),
            business_summary=info.get("longBusinessSummary"),
            country=info.get("country"),
            source_metadata=source_metadata,
        )

    def build_financial_statement(self, normalized_data: Dict[str, Any]) -> FinancialStatement:
        info = normalized_data.get("info", {})
        source_metadata = normalized_data.get("source_metadata")
        field_metadata = normalized_data.get("field_metadata", {})
        official_period = next(
            (getattr(metadata, "period", None) for metadata in field_metadata.values() if getattr(metadata, "period", None)),
            None,
        )
        return FinancialStatement(
            revenue_growth=self._build_point(info.get("revenueGrowth"), "percentage", field_metadata.get("revenueGrowth", source_metadata), source_field="revenueGrowth"),
            earnings_growth=self._build_point(info.get("earningsGrowth"), "percentage", field_metadata.get("earningsGrowth", source_metadata), source_field="earningsGrowth"),
            profit_margin=self._build_point(info.get("profitMargins"), "percentage", field_metadata.get("profitMargins", source_metadata), source_field="profitMargins"),
            roe=self._build_point(info.get("returnOnEquity"), "percentage", field_metadata.get("returnOnEquity", source_metadata), source_field="returnOnEquity"),
            # yfinance documents debtToEquity in percentage points (70 == 0.70x).
            debt_to_equity=self._build_point(
                info.get("debtToEquity"), "ratio", field_metadata.get("debtToEquity", source_metadata), scale=0.01,
                source_field="debtToEquity",
            ),
            cash_flow=self._build_point(
                info.get("operatingCashflow"), "monetary",
                field_metadata.get("operatingCashflow", source_metadata), source_field="operatingCashflow",
            ),
            dividend_yield=self._build_point(info.get("dividendYield"), "percentage", source_metadata),
            payout_ratio=self._build_point(info.get("payoutRatio"), "percentage", source_metadata),
            net_debt=self._build_point(info.get("netDebt"), "monetary", source_metadata),
            ebitda_margin=self._build_point(info.get("ebitdaMargins"), "percentage", source_metadata),
            roic=self._build_point(info.get("returnOnInvestment"), "percentage", source_metadata),
            period=official_period or info.get("lastFiscalYearEnd") or info.get("lastQuarter"),
            source_metadata=source_metadata,
        )

    def build_market_snapshot(self, normalized_data: Dict[str, Any]) -> MarketSnapshot:
        info = normalized_data.get("info", {})
        source_metadata = normalized_data.get("source_metadata")
        return MarketSnapshot(
            price=self._safe_float(info.get("regularMarketPrice")),
            previous_close=self._safe_float(info.get("previousClose")),
            price_change=self._safe_float(info.get("regularMarketChange")),
            price_change_percent=self._safe_float(info.get("regularMarketChangePercent")),
            market_cap=self._safe_float(info.get("marketCap")),
            beta=self._safe_float(info.get("beta")),
            forward_pe=self._safe_float(info.get("forwardPE")),
            trailing_pe=self._safe_float(info.get("trailingPE")),
            enterprise_value=self._safe_float(info.get("enterpriseValue")),
            shares_outstanding=self._safe_float(info.get("sharesOutstanding")),
            dividend_yield=self._safe_float(info.get("dividendYield")),
            fifty_two_week_change=self._as_percent(self._safe_float(info.get("52WeekChange"))),
            fifty_two_week_low=self._safe_float(info.get("fiftyTwoWeekLow")),
            fifty_two_week_high=self._safe_float(info.get("fiftyTwoWeekHigh")),
            source_metadata=source_metadata,
            field_metadata=normalized_data.get("market_field_metadata", {}),
        )

    def _safe_float(self, value: Any) -> Optional[float]:
        return validate_numeric(value)

    def _as_percent(self, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return value * 100.0 if abs(value) <= 2.0 else value

    def _build_point(
        self,
        raw_value: Any,
        data_type: str,
        source_metadata: Optional[SourceMetadata],
        scale: float = 1.0,
        source_field: Optional[str] = None,
    ) -> Any:
        normalized = None
        if raw_value is not None:
            try:
                normalized = float(raw_value) * scale
            except Exception:
                normalized = None
        status = "VALID" if normalized is not None else ("MISSING" if raw_value is None else "INVALID")
        return {
            "raw": raw_value,
            "normalized": normalized,
            "unit": data_type,
            "status": status,
            "semantic_status": "VERIFIED" if status == "VALID" else status,
            "source": getattr(source_metadata, "source", None),
            "source_field": source_field,
            "publication_date": getattr(source_metadata, "publication_date", None),
            "effective_date": getattr(source_metadata, "effective_date", None),
            "source_metadata": source_metadata,
        }


class ThesisEngine:
    def __init__(self):
        self.thesis_engine = calculate_thesis_scores

    def evaluate(
        self,
        asset_profile: AssetProfile,
        market_snapshot: MarketSnapshot,
        fundamental_score: float,
        news_sentiment: float = 50.0,
        macro_observations: Optional[list] = None,
    ) -> Dict[str, float]:
        selic_rate = next(
            (
                item.get("value") for item in (macro_observations or [])
                if item.get("metric") == "selic_target"
                and item.get("value") is not None
                and item.get("point_in_time_eligible", True)
            ),
            None,
        )
        data = {
            "fundamental_score": fundamental_score,
            "sector_name": asset_profile.sector,
            "beta": market_snapshot.beta,
            "market_cap": market_snapshot.market_cap,
            "price_change_percent": market_snapshot.price_change_percent,
            "fifty_two_week_change": market_snapshot.fifty_two_week_change,
            "valuation_margin": calculate_valuation_score(market_snapshot.forward_pe),
            "selic_rate": selic_rate,
        }
        scores = self.thesis_engine(data, news_sentiment)
        scores["macro"] = calculate_macro_score(
            market_snapshot.beta,
            market_snapshot.market_cap,
            selic_rate=selic_rate,
            sector_name=asset_profile.sector,
        )
        return scores
