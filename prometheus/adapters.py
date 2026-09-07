from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import hashlib
import json
from typing import Any, Dict, Optional

from prometheus.models import SourceMetadata
from prometheus.cvm_client import CVMFundamentalSnapshotBuilder, CVMOpenDataClient
from prometheus.macro_client import BCBSeriesClient
from prometheus.cvm_documents import CVMReferenceFormClient
from prometheus.technical_engine import TechnicalEngine
from prometheus.cvm_disclosures import CVMDisclosureClient
from prometheus.cvm_sector_registry import CVMSectorRegistry


def configure_yfinance_cache(cache_dir: Optional[str]) -> None:
    if not cache_dir:
        return
    from pathlib import Path
    from yfinance.cache import set_cache_location

    cache_path = (Path(cache_dir) / "yfinance").resolve()
    cache_path.mkdir(parents=True, exist_ok=True)
    set_cache_location(str(cache_path))


class DataAdapter(ABC):
    @abstractmethod
    def fetch(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        raise NotImplementedError


class YFinanceAdapter(DataAdapter):
    def __init__(self, logger=None, cache_dir: Optional[str] = None):
        self.logger = logger
        self.cache_dir = cache_dir

    def fetch(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        import yfinance as yf

        configure_yfinance_cache(self.cache_dir)

        ticker_symbol = ticker if ticker.endswith(".SA") else f"{ticker}.SA"
        if as_of is not None:
            requested_date = as_of.date() if isinstance(as_of, datetime) else as_of
            if requested_date < datetime.utcnow().date():
                raise ValueError(
                    "YFinanceAdapter cannot provide point-in-time fundamentals for "
                    f"{requested_date}. Use a historical data adapter instead."
                )
        try:
            yf_ticker = yf.Ticker(ticker_symbol)
            info = yf_ticker.info
            observed_at = datetime.utcnow().replace(microsecond=0)
            source_url = f"https://finance.yahoo.com/quote/{ticker_symbol}"
            snapshot_sha256 = hashlib.sha256(
                json.dumps(info, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            period = observed_at.date().isoformat()
            field_units = {
                "revenueGrowth": "ratio", "earningsGrowth": "ratio", "profitMargins": "ratio",
                "returnOnEquity": "ratio", "debtToEquity": "percentage_points",
                "operatingCashflow": "BRL",
            }
            market_units = {
                "regularMarketPrice": "BRL/share", "previousClose": "BRL/share",
                "regularMarketChange": "BRL/share", "regularMarketChangePercent": "percent",
                "marketCap": "BRL", "enterpriseValue": "BRL", "sharesOutstanding": "shares",
                "beta": "x", "forwardPE": "x", "trailingPE": "x", "dividendYield": "ratio",
                "52WeekChange": "ratio", "fiftyTwoWeekLow": "BRL/share", "fiftyTwoWeekHigh": "BRL/share",
            }
            def metadata(unit: str) -> SourceMetadata:
                return SourceMetadata(
                    source="yfinance live snapshot", timestamp=observed_at,
                    publication_date=observed_at, effective_date=observed_at,
                    ticker=ticker, period=period, unit=unit, confidence=0.7,
                    revision_status="retrieval-time snapshot",
                    raw={"ticker_symbol": ticker_symbol, "url": source_url, "source_sha256": snapshot_sha256},
                )
            return {
                "ticker": ticker,
                "info": info,
                "data_source_status": "DEGRADED",
                "data_source_degradation": {
                    "primary_source": "CVM",
                    "active_source": "yfinance",
                    "reason": "SECONDARY_SOURCE_SELECTED_OR_REQUIRED",
                    "limitations": ["KPIs operacionais, governança e valuation oficial não estão disponíveis neste snapshot."],
                },
                "source_metadata": metadata("mixed"),
                "field_metadata": {key: metadata(unit) for key, unit in field_units.items() if info.get(key) is not None},
                "market_field_metadata": {key: metadata(unit) for key, unit in market_units.items() if info.get(key) is not None},
            }
        except Exception as error:
            if self.logger:
                self.logger.warning(f"YFinanceAdapter fetch failed for {ticker_symbol}: {error}")
            raise

    def point_record(self, ticker: str, field: str, as_of: datetime) -> Optional[Dict[str, Any]]:
        """Return only live, retrieval-timestamped observations; never backfill history."""
        if field != "market_cap" or as_of.date() < datetime.utcnow().date():
            return None
        import yfinance as yf

        configure_yfinance_cache(self.cache_dir)
        symbol = ticker if ticker.endswith(".SA") else f"{ticker}.SA"
        observed_at = datetime.utcnow().replace(microsecond=0)
        try:
            value = yf.Ticker(symbol).fast_info["market_cap"]
        except (KeyError, TypeError, ValueError):
            return None
        return {
            "value": float(value) if isinstance(value, (int, float)) and value > 0 else None,
            "source": "yfinance live market capitalization",
            "source_url": f"https://finance.yahoo.com/quote/{symbol}",
            "publication_date": observed_at,
            "effective_date": observed_at,
            "unit": "BRL",
            "source_sha256": hashlib.sha256(
                json.dumps({"symbol": symbol, "field": field, "value": value, "observed_at": observed_at.isoformat()}, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    def point_value(self, ticker: str, field: str, as_of: datetime) -> Optional[float]:
        record = self.point_record(ticker, field, as_of)
        return record.get("value") if record else None


class PointInTimeMarketSnapshotAdapter(DataAdapter):
    """Deterministic offline market observations with explicit provenance."""

    def __init__(self, snapshots: Dict[str, Dict[str, Any]]):
        self.snapshots = {str(key).strip().upper(): dict(value) for key, value in snapshots.items()}

    def fetch(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        normalized = ticker.strip().upper()
        row = self.snapshots.get(normalized)
        if not row:
            raise ValueError(f"No point-in-time market snapshot for {normalized}")
        effective = datetime.fromisoformat(str(row["effective_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        available = datetime.fromisoformat(str(row["available_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        cutoff = (as_of or datetime.utcnow()).replace(tzinfo=None)
        if effective > cutoff or available > cutoff:
            raise ValueError(f"Look-ahead market snapshot for {normalized}")
        price = float(row["close"])
        previous = float(row["previous_close"]) if row.get("previous_close") is not None else None
        change = price - previous if previous is not None else None
        field_metadata: Dict[str, SourceMetadata] = {}
        info_fields = {
            "market_cap": "marketCap",
            "shares_outstanding": "sharesOutstanding",
            "enterprise_value": "enterpriseValue",
            "trailing_pe": "trailingPE",
            "forward_pe": "forwardPE",
            "beta": "beta",
            "dividend_yield": "dividendYield",
        }
        info = {
            "regularMarketPrice": price, "previousClose": previous,
            "regularMarketChange": change,
            "regularMarketChangePercent": change / previous * 100.0 if previous else None,
            "currency": row.get("currency") or "BRL", "exchange": "B3",
        }
        for name, provider_name in info_fields.items():
            observation = (row.get("fields") or {}).get(name)
            if observation is None and row.get(name) is not None:
                observation = {"value": row[name]}
            if observation is None:
                continue
            if not isinstance(observation, dict) or observation.get("value") is None:
                raise ValueError(f"Invalid {name} observation for {normalized}")
            field_effective = self._timestamp(observation.get("effective_at") or row["effective_at"])
            field_available = self._timestamp(observation.get("available_at") or row["available_at"])
            if field_effective > cutoff or field_available > cutoff:
                raise ValueError(f"Look-ahead {name} snapshot for {normalized}")
            value = float(observation["value"])
            if value <= 0 and name in {"market_cap", "shares_outstanding", "enterprise_value"}:
                raise ValueError(f"Non-positive {name} observation for {normalized}")
            info[provider_name] = value
            field_metadata[provider_name] = SourceMetadata(
                source=str(observation.get("source") or row["source"]), timestamp=cutoff,
                publication_date=field_available, effective_date=field_effective, ticker=normalized,
                period=str(observation.get("period") or field_effective.date().isoformat()),
                unit=str(observation.get("unit") or ("BRL" if name in {"market_cap", "enterprise_value"} else "shares" if name == "shares_outstanding" else "x")),
                confidence=float(observation.get("confidence", row.get("confidence", 1.0))),
                revision_status=str(observation.get("revision_status") or row.get("revision_status") or "point-in-time snapshot"),
                raw={"url": observation.get("source_url") or row.get("source_url"), "source_sha256": observation.get("source_sha256"), "formula": observation.get("formula")},
            )
        market_cap_meta = field_metadata.get("marketCap")
        market_cap_formula = ((market_cap_meta.raw or {}).get("formula") if market_cap_meta else None)
        if market_cap_formula:
            normalized_formula = "".join(str(market_cap_formula).lower().split())
            if normalized_formula != "close*shares_outstanding":
                raise ValueError(f"Unsupported market_cap formula for {normalized}: {market_cap_formula}")
            shares = info.get("sharesOutstanding")
            if shares is None:
                raise ValueError(f"market_cap formula missing shares_outstanding for {normalized}")
            calculated = price * float(shares)
            tolerance = max(abs(calculated) * 1e-6, 0.01)
            if abs(float(info["marketCap"]) - calculated) > tolerance:
                raise ValueError(f"Inconsistent market_cap formula for {normalized}")
        return {
            "ticker": normalized,
            "info": info,
            "market_field_metadata": field_metadata,
            "source_metadata": SourceMetadata(
                source=str(row["source"]), timestamp=cutoff, publication_date=available,
                effective_date=effective, ticker=normalized, period=effective.date().isoformat(),
                unit=str(row.get("currency") or "BRL"), confidence=float(row.get("confidence", 1.0)),
                revision_status=str(row.get("revision_status") or "point-in-time snapshot"),
                raw={
                    "url": row.get("source_url"),
                    "source_sha256": row.get("source_sha256"),
                    "record_sha256": row.get("record_sha256"),
                    "captured_at": row.get("captured_at"),
                },
            ),
        }

    def point_value(self, ticker: str, field: str, as_of: datetime) -> Optional[float]:
        provider_names = {"market_cap": "marketCap", "shares_outstanding": "sharesOutstanding"}
        return self.fetch(ticker, as_of).get("info", {}).get(provider_names.get(field, field))

    def point_record(self, ticker: str, field: str, as_of: datetime) -> Dict[str, Any]:
        provider_names = {
            "market_cap": "marketCap", "shares_outstanding": "sharesOutstanding",
            "price": "regularMarketPrice", "previous_close": "previousClose",
        }
        provider_name = provider_names.get(field, field)
        payload = self.fetch(ticker, as_of)
        value = payload.get("info", {}).get(provider_name)
        metadata = (payload.get("market_field_metadata") or {}).get(provider_name, payload.get("source_metadata"))
        raw = getattr(metadata, "raw", {}) or {}
        return {
            "value": value, "source": getattr(metadata, "source", None),
            "source_url": raw.get("url"),
            "publication_date": getattr(metadata, "publication_date", None),
            "effective_date": getattr(metadata, "effective_date", None),
            "unit": getattr(metadata, "unit", None), "formula": raw.get("formula"),
            "source_sha256": raw.get("source_sha256"),
        }

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


class B3COTAHISTAdapter(PointInTimeMarketSnapshotAdapter):
    """Reusable official B3 archive adapter for current reports and walk-forward history."""

    def __init__(self, archive_path: str, tickers=None):
        from prometheus.b3_cotahist import load_market_observations

        self.observations = load_market_observations(archive_path, tickers=tickers)
        self.snapshots = {}

    def fetch(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        from prometheus.b3_cotahist import snapshots_from_observations

        normalized = ticker.strip().upper()
        rows = (self.observations.get("records") or {}).get(normalized) or []
        subset = {**self.observations, "records": {normalized: rows}}
        snapshots = snapshots_from_observations(subset, as_of or datetime.utcnow())
        if normalized not in snapshots:
            raise ValueError(f"No point-in-time COTAHIST observation for {normalized}")
        self.snapshots = snapshots
        return super().fetch(normalized, as_of=as_of)

    def history(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
        import pandas as pd

        normalized = ticker.strip().upper()
        aliases = {"IBOV": "^BVSP", "^BVSP": "IBOV"}
        normalized = aliases.get(normalized, normalized)
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        rows = [
            row for row in (self.observations.get("records") or {}).get(normalized, [])
            if start <= row["date"] <= end
        ]
        if not rows:
            return {
                "status": "BACKTEST_PARTIAL", "ticker": normalized, "history": [],
                "notes": "No official B3 COTAHIST history found.",
            }
        frame = pd.DataFrame(
            {
                "Open": [row["open"] for row in rows],
                "High": [row["high"] for row in rows],
                "Low": [row["low"] for row in rows],
                "Close": [row["close"] for row in rows],
                "Volume": [row["volume"] for row in rows],
            },
            index=pd.to_datetime([row["date"] for row in rows]),
        )
        return {
            "status": "OK", "ticker": normalized, "history": frame,
            "notes": "Official B3 COTAHIST daily series loaded.",
            "source_sha256": self.observations.get("source_sha256"),
        }


class B3Adapter(DataAdapter):
    def fetch(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        raise NotImplementedError("B3Adapter is not implemented yet. Use a concrete data source integration.")


class CVMAdapter(DataAdapter):
    def fetch(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        raise NotImplementedError("CVMAdapter is not implemented yet. Use a concrete data source integration.")


class CVMEnrichedAdapter(DataAdapter):
    """Combine point-in-time CVM fundamentals with market observations.

    ``cvm_codes`` is explicit by design: ticker-to-issuer identity must be
    validated instead of guessed from a company name.
    """

    def __init__(self, cvm_codes: Dict[str, str], cache_dir: Optional[str] = None, logger=None, backtest_mode: bool = False, market_adapter: Optional[DataAdapter] = None):
        self.cvm_codes = {key.strip().upper(): str(value) for key, value in cvm_codes.items()}
        self.cvm = CVMOpenDataClient(cache_dir=cache_dir)
        self.market = market_adapter or YFinanceAdapter(logger=logger, cache_dir=cache_dir)
        self.macro = BCBSeriesClient(cache_dir=cache_dir)
        self.reference_forms = CVMReferenceFormClient(cache_dir=cache_dir)
        self.technical = TechnicalEngine()
        self.disclosures = CVMDisclosureClient(cache_dir=cache_dir)
        self.sector_registry = CVMSectorRegistry(cache_dir=cache_dir)
        self.logger = logger
        self.backtest_mode = backtest_mode

    def fetch(self, ticker: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        normalized = ticker.strip().upper()
        cvm_code = self.cvm_codes.get(normalized)
        if cvm_code is None:
            raise ValueError(f"No validated CVM code configured for {normalized}")

        cutoff = as_of or datetime.utcnow()
        if isinstance(self.market, PointInTimeMarketSnapshotAdapter):
            market_data = self.market.fetch(normalized, as_of=cutoff)
        elif cutoff.date() < datetime.utcnow().date():
            market_data = self._fetch_historical_market(normalized, cutoff)
        else:
            market_data = self.market.fetch(normalized, as_of=as_of)

        try:
            rows = self.cvm.load_rows(
                cvm_code=cvm_code,
                as_of=cutoff,
                filing_types=("ITR", "DFP"),
                years=range(max(2011, cutoff.year - 1), cutoff.year + 1),
            )
        except Exception as error:
            if self.logger:
                self.logger.warning(f"CVM ITR/DFP fetch failed at {cutoff.isoformat()}: {error}")
            return self._degraded_market_snapshot(market_data, normalized, cutoff, error)
        snapshot_builder = CVMFundamentalSnapshotBuilder()
        snapshot = snapshot_builder.build(rows)
        if snapshot.get("status") != "AVAILABLE":
            return self._degraded_market_snapshot(
                market_data, normalized, cutoff,
                ValueError(f"No CVM fundamentals available for {normalized} at {cutoff.isoformat()}"),
            )

        info = dict(market_data.get("info") or {})
        official_company_name = next((getattr(row, "company_name", None) for row in rows if getattr(row, "company_name", None)), None)
        if official_company_name:
            info["longName"] = official_company_name
            info["shortName"] = official_company_name
        official_classification = self.sector_registry.lookup(cvm_code, cutoff)
        if official_classification.get("status") == "AVAILABLE":
            info["sector"] = official_classification["sector"]
            info["industry"] = official_classification["sector"]
        if "�" in str(info.get("longBusinessSummary") or ""):
            info["longBusinessSummary"] = None
        field_map = {
            "revenue_growth": "revenueGrowth",
            "earnings_growth": "earningsGrowth",
            "profit_margin": "profitMargins",
            "roe": "returnOnEquity",
            "debt_to_equity": "debtToEquity",
            "operating_cash_flow": "operatingCashflow",
        }
        field_metadata: Dict[str, SourceMetadata] = {}
        for metric_name, provider_field in field_map.items():
            metric = snapshot["metrics"].get(metric_name, {})
            value = metric.get("normalized")
            if value is None:
                continue
            info[provider_field] = value * 100.0 if provider_field == "debtToEquity" else value
            source_rows = metric.get("source_rows") or []
            latest_source = max(source_rows, key=lambda row: row.received_at) if source_rows else None
            field_metadata[provider_field] = SourceMetadata(
                source="CVM",
                timestamp=cutoff,
                publication_date=latest_source.received_at if latest_source else None,
                effective_date=datetime.combine(latest_source.reference_date, datetime.min.time()) if latest_source else None,
                ticker=normalized,
                period=snapshot.get("reference_date"),
                unit=metric.get("unit"),
                confidence=1.0,
                revision_status=f"version {latest_source.version}" if latest_source and latest_source.version else None,
                raw={
                    "cvm_code": cvm_code,
                    "url": latest_source.source_url if latest_source else None,
                    "source_sha256": getattr(latest_source, "source_sha256", None) if latest_source else None,
                    "calculation": metric.get("calculation"),
                },
            )

        market_data["info"] = info
        market_data["field_metadata"] = field_metadata
        market_field_metadata = dict(market_data.get("market_field_metadata") or {})
        capital = self.cvm.load_capital_composition(
            cvm_code, cutoff, filing_types=("ITR", "DFP"),
            years=range(max(2011, cutoff.year - 1), cutoff.year + 1),
        )
        market_data["capital_composition"] = capital
        if capital.get("status") == "AVAILABLE" and capital.get("quantity_scale_status") == "VERIFIED":
            info["sharesOutstanding"] = float(capital["shares_outstanding"])
            capital_metadata = SourceMetadata(
                source="CVM composição do capital", timestamp=cutoff,
                publication_date=capital["received_at"],
                effective_date=datetime.fromisoformat(capital["reference_date"]),
                ticker=normalized, period=capital["reference_date"], unit="shares", confidence=1.0,
                revision_status=f"{capital['filing_type']} version {capital.get('version') or 'unknown'}",
                raw={
                    "cvm_code": cvm_code, "url": capital["source_url"],
                    "dataset_url": capital["source_dataset"], "formula": capital["formula"],
                    "source_sha256": capital.get("source_sha256"),
                    "reported_total_quantity": capital.get("reported_total_quantity"),
                    "quantity_scale_multiplier": capital.get("quantity_scale_multiplier"),
                    "quantity_scale_status": capital.get("quantity_scale_status"),
                    "quantity_scale_method": capital.get("quantity_scale_method"),
                    "quantity_scale_reconciliation_error": capital.get("quantity_scale_reconciliation_error"),
                },
            )
            market_field_metadata["sharesOutstanding"] = capital_metadata
            if info.get("marketCap") is None and info.get("regularMarketPrice") is not None and capital.get("single_class"):
                info["marketCap"] = float(info["regularMarketPrice"]) * float(capital["shares_outstanding"])
                market_field_metadata["marketCap"] = SourceMetadata(
                    source="Cálculo PROMETHEUS: preço observado × ações CVM", timestamp=cutoff,
                    publication_date=max(capital["received_at"], market_data["source_metadata"].publication_date or cutoff),
                    effective_date=cutoff, ticker=normalized, period=cutoff.date().isoformat(), unit="BRL", confidence=1.0,
                    revision_status="deterministic calculation",
                    raw={"url": capital["source_url"], "price_source_url": (market_data["source_metadata"].raw or {}).get("url"), "formula": "regularMarketPrice * sharesOutstanding"},
                )
        market_data["market_field_metadata"] = market_field_metadata
        market_data["cvm_snapshot"] = snapshot
        market_data["official_metrics"] = snapshot.get("metrics", {})
        market_data["official_classification"] = official_classification
        market_data["financial_history"] = snapshot_builder.build_history(rows, limit=20)
        market_data["ttm"] = snapshot_builder.build_ttm(rows)
        if self.backtest_mode:
            # These modules do not enter the historical score. Skipping them keeps
            # walk-forward runs reproducible without weakening point-in-time inputs.
            reason = "OMITTED_FROM_BACKTEST_SIGNAL"
            market_data["technical_context"] = {"status": "INSUFFICIENT_DATA", "reason": reason}
            market_data["reference_form"] = {"status": "INSUFFICIENT_DATA", "sections": {}, "limitations": [reason]}
            market_data["official_disclosures"] = {"status": "INSUFFICIENT_DATA", "documents": [], "limitations": [reason]}
        else:
            if isinstance(self.market, PointInTimeMarketSnapshotAdapter):
                market_data["technical_context"] = {
                    "status": "INSUFFICIENT_DATA",
                    "reason": "OFFLINE_SNAPSHOT_HAS_NO_PRICE_SERIES",
                }
            else:
                try:
                    market_data["technical_context"] = self._technical_context(normalized, cutoff)
                except Exception as error:
                    if self.logger:
                        self.logger.warning(f"Technical context fetch failed at {cutoff.isoformat()}: {error}")
                    market_data["technical_context"] = {"status": "INSUFFICIENT_DATA", "reason": type(error).__name__}
            try:
                market_data["reference_form"] = self.reference_forms.load_company(cvm_code, cutoff)
            except Exception as error:
                if self.logger:
                    self.logger.warning(f"CVM FRE fetch failed at {cutoff.isoformat()}: {error}")
                market_data["reference_form"] = {
                    "status": "INSUFFICIENT_DATA",
                    "sections": {},
                    "limitations": [f"FRE indisponível: {type(error).__name__}"],
                }
            try:
                market_data["official_disclosures"] = self.disclosures.load(
                    cvm_code, cutoff, include_content=True,
                )
            except Exception as error:
                market_data["official_disclosures"] = {"status": "INSUFFICIENT_DATA", "documents": [], "limitations": [type(error).__name__]}
        try:
            macro_observations = self.macro.latest_indicators(cutoff)
        except Exception as error:
            if self.logger:
                self.logger.warning(f"BCB Selic fetch failed at {cutoff.isoformat()}: {error}")
            macro_observations = []
        market_data["macro_observations"] = macro_observations
        market_data["data_source_status"] = "PRIMARY"
        market_data["data_source_degradation"] = None
        return market_data

    @staticmethod
    def _degraded_market_snapshot(market_data: Dict[str, Any], ticker: str, cutoff: datetime, error: Exception) -> Dict[str, Any]:
        """Publish a clearly degraded market-only snapshot when CVM is unavailable."""
        degraded = dict(market_data)
        degraded.update({
            "ticker": ticker,
            "data_source_status": "DEGRADED",
            "data_source_degradation": {
                "primary_source": "CVM ITR/DFP",
                "active_source": "yfinance market snapshot",
                "reason": type(error).__name__,
                "cutoff": cutoff.replace(microsecond=0).isoformat(),
                "limitations": ["KPIs operacionais, governança e valuation oficial não puderam ser calculados."],
            },
            "official_metrics": {}, "financial_history": [],
            "ttm": {"status": "INSUFFICIENT_DATA", "metrics": {}, "reason": "PRIMARY_SOURCE_UNAVAILABLE"},
            "reference_form": {"status": "INSUFFICIENT_DATA", "sections": {}, "limitations": ["PRIMARY_SOURCE_UNAVAILABLE"]},
            "official_disclosures": {"status": "INSUFFICIENT_DATA", "documents": [], "limitations": ["PRIMARY_SOURCE_UNAVAILABLE"]},
            "official_classification": {"status": "INSUFFICIENT_DATA", "reason": "PRIMARY_SOURCE_UNAVAILABLE"},
        })
        return degraded

    def peer_market_cap(self, ticker: str, as_of: datetime) -> Optional[float]:
        point_value = getattr(self.market, "point_value", None)
        if callable(point_value):
            return point_value(ticker, "market_cap", as_of)
        return None

    def peer_market_cap_record(self, ticker: str, as_of: datetime) -> Optional[Dict[str, Any]]:
        point_record = getattr(self.market, "point_record", None)
        if callable(point_record):
            return point_record(ticker, "market_cap", as_of)
        return None

    def peer_price_record(self, ticker: str, as_of: datetime) -> Optional[Dict[str, Any]]:
        point_record = getattr(self.market, "point_record", None)
        if callable(point_record):
            return point_record(ticker, "price", as_of)
        return None

    def peer_candidates(self, ticker: str, activity_sector: str, as_of: datetime, limit: int = 6):
        target_code = self.cvm_codes.get(ticker.strip().upper())
        if not target_code or not activity_sector:
            return []
        return self.sector_registry.peer_candidates(
            activity_sector, self.cvm_codes, target_code, as_of, limit=limit,
            target_ticker=ticker.strip().upper(),
        )

    def _technical_context(self, ticker: str, cutoff: datetime) -> Dict[str, Any]:
        configure_yfinance_cache(getattr(self.market, "cache_dir", None))
        import yfinance as yf

        symbol = ticker if ticker.endswith(".SA") else f"{ticker}.SA"
        history = yf.Ticker(symbol).history(
            start=(cutoff.date() - timedelta(days=420)).isoformat(),
            end=(cutoff.date() + timedelta(days=1)).isoformat(), interval="1d",
            auto_adjust=False,
        )
        rows = [
            {"close": row.get("Close"), "volume": row.get("Volume")}
            for _, row in history.iterrows()
        ] if history is not None and not getattr(history, "empty", True) else []
        return self.technical.evaluate(rows)

    def _fetch_historical_market(self, ticker: str, as_of: datetime) -> Dict[str, Any]:
        configure_yfinance_cache(getattr(self.market, "cache_dir", None))
        import yfinance as yf

        symbol = ticker if ticker.endswith(".SA") else f"{ticker}.SA"
        start = (as_of.date() - timedelta(days=10)).isoformat()
        end = (as_of.date() + timedelta(days=1)).isoformat()
        history = yf.Ticker(symbol).history(start=start, end=end, interval="1d", auto_adjust=False)
        if history is None or getattr(history, "empty", True):
            raise ValueError(f"No historical market data for {ticker} at {as_of.date()}")
        eligible = history[history.index.date <= as_of.date()]
        if eligible.empty:
            raise ValueError(f"No trading observation for {ticker} at {as_of.date()}")
        current = eligible.iloc[-1]
        previous = eligible.iloc[-2] if len(eligible) > 1 else None
        price = float(current["Close"])
        previous_close = float(previous["Close"]) if previous is not None else None
        change = price - previous_close if previous_close is not None else None
        change_percent = change / previous_close * 100.0 if previous_close else None
        return {
            "ticker": ticker,
            "info": {
                "regularMarketPrice": price,
                "previousClose": previous_close,
                "regularMarketChange": change,
                "regularMarketChangePercent": change_percent,
                "currency": "BRL",
                "exchange": "B3",
            },
            "source_metadata": SourceMetadata(
                source="yfinance_historical",
                timestamp=as_of,
                publication_date=as_of,
                effective_date=as_of,
                ticker=ticker,
                period=as_of.date().isoformat(),
                unit="BRL",
                confidence=0.8,
                revision_status=None,
                raw={
                    "ticker_symbol": symbol, "url": f"https://finance.yahoo.com/quote/{symbol}/history",
                    "source_sha256": hashlib.sha256(
                        json.dumps({
                            "ticker": ticker, "as_of": as_of.isoformat(), "price": price,
                            "previous_close": previous_close,
                        }, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                },
            ),
        }
