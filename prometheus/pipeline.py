import dataclasses
import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from prometheus.adapters import YFinanceAdapter
from prometheus.data_engine import validate_ticker
from prometheus.data_quality import calculate_data_quality, calculate_research_quality
from prometheus.decision_engine import DecisionEngine
from prometheus.engines import DataLayer, FeatureEngine, ThesisEngine, NormalizationLayer, PointInTimeLayer
from prometheus.fundamental_engine import calculate_fundamental_score
from prometheus.pricing_engine import PricingEngine
from prometheus.risk_engine import RiskEngine
from prometheus.thesis_engine import calculate_score, evidence_coverage, get_state
from prometheus.thesis_state_engine import ThesisStateEngine
from prometheus.thesis_breaker_engine import ThesisBreakerEngine
from prometheus.catalyst_engine import CatalystEngine
from prometheus.expectation_engine import ExpectationEngine
from prometheus.journal_engine import JournalEngine
from prometheus.prediction_engine import PredictionEngine
from prometheus.outcome_engine import OutcomeEngine
from prometheus.calibration_engine import CalibrationEngine
from prometheus.regime_engine import RegimeEngine
from prometheus.replay_engine import ReplayEngine
from prometheus.models import AssetProfile, FinancialStatement, MarketSnapshot
from prometheus.research import ResearchEngine
from prometheus.sector_models import resolve_sector_model
from prometheus.valuation_engine import ValuationEngine
from prometheus.evidence_engine import EvidenceEngine
from prometheus.editorial_gate import EditorialGate
from prometheus.business_quality import BusinessQualityEngine
from prometheus.operational_kpis import OperationalKPIExtractor
from prometheus.regression_monitor import CoverageRegressionMonitor


class PrometheusEngine:
    def __init__(
        self,
        adapter: Optional[YFinanceAdapter] = None,
        journal_path: Optional[str] = None,
    ):
        self.adapter = adapter if adapter is not None else YFinanceAdapter()
        self.data_layer = DataLayer(self.adapter)
        self.normalization_layer = NormalizationLayer()
        self.feature_engine = FeatureEngine()
        self.thesis_engine = ThesisEngine()
        self.pricing_engine = PricingEngine()
        self.thesis_state_engine = ThesisStateEngine()
        self.thesis_breaker_engine = ThesisBreakerEngine()
        self.prediction_engine = PredictionEngine()
        self.outcome_engine = OutcomeEngine()
        self.calibration_engine = CalibrationEngine()
        self.risk_engine = RiskEngine()
        self.decision_engine = DecisionEngine()
        self.catalyst_engine = CatalystEngine()
        self.expectation_engine = ExpectationEngine()
        self.regime_engine = RegimeEngine()
        self.journal_engine = JournalEngine(journal_path) if journal_path is not None else JournalEngine()
        self.replay_engine = ReplayEngine()
        self.research_engine = ResearchEngine()
        self.valuation_engine = ValuationEngine()
        self.evidence_engine = EvidenceEngine()
        self.editorial_gate = EditorialGate()
        self.business_quality_engine = BusinessQualityEngine()
        self.operational_kpi_extractor = OperationalKPIExtractor()

    def evaluate(
        self,
        ticker: str,
        sentiment_score: float = 50.0,
        news_items: Optional[List[Dict[str, Any]]] = None,
        recent_returns: Optional[List[float]] = None,
        journal_metadata: Optional[Dict[str, Any]] = None,
        as_of: Optional[datetime.datetime] = None,
    ) -> Dict[str, object]:
        ticker = validate_ticker(ticker)
        news_items = self._filter_news_point_in_time(news_items or [], as_of)
        raw_data = self.data_layer.load(ticker, as_of=as_of)
        filtered_data = PointInTimeLayer(as_of=as_of).filter(raw_data)
        normalized = self.normalization_layer.normalize(filtered_data)

        asset_profile = self.feature_engine.build_asset_profile(normalized)
        financials = self.feature_engine.build_financial_statement(normalized)
        market_snapshot = self.feature_engine.build_market_snapshot(normalized)

        fundamental_inputs = {
            "revenue_growth": self._extract_value(financials.revenue_growth),
            "earnings_growth": self._extract_value(financials.earnings_growth),
            "profit_margin": self._extract_value(financials.profit_margin),
            "roe": self._extract_value(financials.roe),
            "debt_to_equity": self._extract_value(financials.debt_to_equity),
        }

        fundamental_summary = calculate_fundamental_score(fundamental_inputs)
        data_quality_summary = calculate_data_quality({
            "revenue_growth": financials.revenue_growth or {},
            "earnings_growth": financials.earnings_growth or {},
            "profit_margin": financials.profit_margin or {},
            "roe": financials.roe or {},
            "debt_to_equity": financials.debt_to_equity or {},
        })

        thesis_scores = self.thesis_engine.evaluate(
            asset_profile=asset_profile,
            market_snapshot=market_snapshot,
            fundamental_score=fundamental_summary["score"],
            news_sentiment=sentiment_score,
            macro_observations=normalized.get("macro_observations", []),
        )

        expectation_result = self.expectation_engine.quantify(
            market_snapshot={
                "price_change_percent": market_snapshot.price_change_percent,
                "beta": market_snapshot.beta,
            },
            fundamental_summary=fundamental_summary,
            sentiment_score=sentiment_score,
        )

        catalyst_result = self.catalyst_engine.identify(
            news_items=news_items,
            asset_profile=asset_profile,
            market_snapshot=market_snapshot,
        )

        regime_result = self.regime_engine.detect(
            asset_data={
                "beta": market_snapshot.beta,
                "market_cap": market_snapshot.market_cap,
                "price_change_percent": market_snapshot.price_change_percent,
            },
            recent_returns=recent_returns,
        )

        pricing_result = self.pricing_engine.assess(
            market_snapshot={
                "price_change_percent": market_snapshot.price_change_percent,
                "beta": market_snapshot.beta,
                "forward_pe": market_snapshot.forward_pe,
            },
            expectation_result=expectation_result,
            thesis_scores=thesis_scores,
        )
        official_metrics = normalized.get("official_metrics", {})
        valuation_result = self.valuation_engine.evaluate(
            price=market_snapshot.price, shares=market_snapshot.shares_outstanding,
            net_income=(official_metrics.get("net_income") or {}).get("normalized"),
            operating_cash_flow=(official_metrics.get("operating_cash_flow") or {}).get("normalized"),
            net_debt=(official_metrics.get("net_debt") or {}).get("normalized"),
        )

        unavailable_components = set()
        if thesis_scores.get("sector") is None:
            unavailable_components.add("sector")
        if valuation_result.get("status") != "AVAILABLE":
            unavailable_components.add("valuation_margin")
        if not any(
            item.get("metric") == "selic_target"
            and item.get("value") is not None
            and item.get("point_in_time_eligible", True)
            for item in normalized.get("macro_observations", [])
        ):
            unavailable_components.add("macro")
        final_score = round(
            calculate_score(thesis_scores, unavailable_components) * 0.60
            + expectation_result["expectation_gap_score"] * 0.15
            + catalyst_result["catalyst_score"] * 0.10
            + regime_result["confidence"] * 100.0 * 0.08
            + pricing_result["pricing_confidence"] * 100.0 * 0.07,
            2,
        )
        final_score = max(0.0, min(100.0, final_score))
        final_state = get_state(final_score)

        combined_evidence: List[Any] = []
        combined_evidence.extend(expectation_result.get("evidence", []))
        combined_evidence.extend(catalyst_result.get("evidence", []))
        combined_evidence.extend(regime_result.get("evidence", []))
        combined_evidence.extend(pricing_result.get("evidence", []))

        risk_result = self.risk_engine.analyze({
            "beta": market_snapshot.beta,
            "market_cap": market_snapshot.market_cap,
            "debt_to_equity": self._extract_value(financials.debt_to_equity),
        })
        combined_evidence.extend(risk_result.get("evidence", []))

        thesis_result = self.thesis_state_engine.evaluate(
            ticker=ticker,
            current_score=final_score,
            confidence=fundamental_summary.get("confidence", 0.0) / 100.0,
            thesis_scores=thesis_scores,
            evidence=combined_evidence,
            pricing_result=pricing_result,
            catalysts=catalyst_result.get("catalysts", []),
            risk_result=risk_result,
        )

        breakers = self.thesis_breaker_engine.identify(
            thesis_result=thesis_result,
            fundamental_summary=fundamental_summary,
            market_snapshot={
                "price_change_percent": market_snapshot.price_change_percent,
                "beta": market_snapshot.beta,
                "market_cap": market_snapshot.market_cap,
                "forward_pe": market_snapshot.forward_pe,
            },
            risk_result=risk_result,
            expectation_result=expectation_result,
            pricing_result=pricing_result,
            catalysts=catalyst_result.get("catalysts", []),
            regime_result=regime_result,
        )
        thesis_result = self.thesis_state_engine.apply_breakers(thesis_result, breakers)

        # generate explicit predictions from the thesis (falsifiable, objective)
        try:
            preds = self.prediction_engine.generate(
                thesis_result=thesis_result,
                thesis_scores=thesis_scores,
                expectation=expectation_result,
                catalysts=catalyst_result.get("catalysts", []),
                regime=regime_result,
            )
        except Exception:
            preds = []

        if preds:
            thesis_result.prediction_ids = [p.prediction_id for p in preds]

        decision_result = self.decision_engine.decide(
            thesis_result=thesis_result,
            risk_result=risk_result,
            news_sentiment=sentiment_score,
        )

        research_result = self._build_research(
            ticker=ticker,
            asset_profile=asset_profile,
            financials=financials,
            market_snapshot=market_snapshot,
            fundamental_summary=fundamental_summary,
            thesis_result=thesis_result,
            risk_result=risk_result,
            macro_observations=normalized.get("macro_observations", []),
            news_items=news_items,
        )
        sector_model = resolve_sector_model(asset_profile.sector, asset_profile.industry)

        report = {
            "ticker": ticker,
            "ticker_display": ticker,
            "company_name": asset_profile.company_name,
            "sector_name": asset_profile.sector,
            "industry_name": asset_profile.industry,
            "currency": asset_profile.currency,
            "exchange": asset_profile.exchange,
            "business_summary": asset_profile.business_summary,
            "price": market_snapshot.price,
            "previous_close": market_snapshot.previous_close,
            "price_change": market_snapshot.price_change,
            "price_change_percent": market_snapshot.price_change_percent,
            "market_cap": market_snapshot.market_cap,
            "beta": market_snapshot.beta,
            "forward_pe": market_snapshot.forward_pe,
            "trailing_pe": market_snapshot.trailing_pe,
            "enterprise_value": market_snapshot.enterprise_value,
            "shares_outstanding": market_snapshot.shares_outstanding,
            "dividend_yield": market_snapshot.dividend_yield,
            "fifty_two_week_change": market_snapshot.fifty_two_week_change,
            "fifty_two_week_low": market_snapshot.fifty_two_week_low,
            "fifty_two_week_high": market_snapshot.fifty_two_week_high,
            "asset_profile": asset_profile,
            "market_snapshot": market_snapshot,
            "financials": financials,
            "fundamental_data": {
                "revenue_growth": financials.revenue_growth,
                "earnings_growth": financials.earnings_growth,
                "profit_margin": financials.profit_margin,
                "roe": financials.roe,
                "debt_to_equity": financials.debt_to_equity,
            },
            "fundamental_inputs": fundamental_inputs,
            "fundamental_summary": fundamental_summary,
            "fundamental_score": fundamental_summary["score"],
            "fundamental_data_quality": data_quality_summary,
            "sector": thesis_scores.get("sector"),
            "macro": thesis_scores.get("macro"),
            "expectation_gap": thesis_scores.get("expectation_gap"),
            "momentum_velocity": thesis_scores.get("momentum_velocity"),
            "valuation_margin": thesis_scores.get("valuation_margin"),
            "news_sentiment": sentiment_score,
            "thesis_scores": thesis_scores,
            "score_availability": {
                "unavailable_components": sorted(unavailable_components),
                "evidence_coverage": evidence_coverage(unavailable_components),
                "component_status": {
                    "sector": {
                        "status": "SECTOR_SCORE_UNAVAILABLE",
                        "reason": "Sem histórico point-in-time de margens e ROE dos pares suficiente para calcular o Sector Score.",
                    }
                } if "sector" in unavailable_components else {},
            },
            "expectation_result": expectation_result,
            "pricing_result": pricing_result,
            "catalyst_result": catalyst_result,
            "regime_result": regime_result,
            "risk": risk_result,
            "thesis_result": thesis_result,
            "decision_result": decision_result,
            "research": research_result,
            "sector_model": sector_model.__dict__,
            "official_classification": normalized.get("official_classification", {"status": "INSUFFICIENT_DATA"}),
            "official_metrics": official_metrics,
            "financial_history": normalized.get("financial_history", []),
            "reference_form": normalized.get("reference_form", {"status": "INSUFFICIENT_DATA", "sections": {}}),
            "technical_context": normalized.get("technical_context", {"status": "INSUFFICIENT_DATA"}),
            "ttm": normalized.get("ttm", {"status": "INSUFFICIENT_DATA", "metrics": {}}),
            "official_disclosures": normalized.get("official_disclosures", {"status": "INSUFFICIENT_DATA", "documents": []}),
            "data_source_status": normalized.get("data_source_status", "PRIMARY"),
            "data_source_degradation": normalized.get("data_source_degradation"),
            "valuation": valuation_result,
            "macro_observations": normalized.get("macro_observations", []),
            "final_score": final_score,
            "final_state": final_state,
            "sentiment_score": sentiment_score,
            "analysis_as_of": (as_of or datetime.datetime.utcnow()).replace(microsecond=0).isoformat() + "Z",
            "timestamp": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        # Some CVM classification payloads omit CNPJ even though the same
        # issuer identity is present in the official disclosure records.
        # Promote that exact CVM value; never infer or fuzzy-match it.
        classification = report.get("official_classification") or {}
        if not classification.get("cnpj"):
            disclosure_cnpj = next(
                (item.get("cnpj") for item in (report.get("official_disclosures") or {}).get("documents", []) if item.get("cnpj")),
                None,
            )
            if disclosure_cnpj:
                classification["cnpj"] = disclosure_cnpj
                report["official_classification"] = classification

        operational_kpis = self.operational_kpi_extractor.extract(
            report.get("official_disclosures") or {}, str((report.get("sector_model") or {}).get("key") or "general"),
        )
        report["operational_kpis"] = operational_kpis
        report["sector_coverage"] = operational_kpis.get("sector_coverage", "GENERIC")
        report.setdefault("research", {}).setdefault("sources", []).extend(
            self.operational_kpi_extractor.source_records(operational_kpis)
        )
        self._append_official_catalysts(report)
        self._append_structured_financial_sources(report)
        self._append_reference_form_sources(report)
        self._append_score_sources(report)

        for document in (report.get("official_disclosures") or {}).get("documents") or []:
            report.setdefault("research", {}).setdefault("sources", []).append(
                self.research_engine.build_source_record(
                    metric="official_disclosure", value=document.get("subject") or document.get("type") or document.get("category"),
                    unit="text", period=document.get("reference_date") or "not_provided",
                    reference_date=document.get("reference_date") or "not_provided",
                    publication_date=document.get("delivered_at") or "not_provided", source="CVM IPE",
                    source_type="primary", confidence="high", source_url=document.get("source_url"),
                    source_sha256=document.get("raw_document_sha256") or document.get("source_sha256"),
                    source_sha256_components=[
                        value for value in (document.get("source_sha256"), document.get("raw_document_sha256")) if value
                    ],
                    category=document.get("category"), version=document.get("version"), protocol=document.get("protocol"),
                    content_extraction_status=document.get("content_extraction_status"),
                )
            )

        report["claims"] = self.evidence_engine.build_metric_claims(
            (report.get("research") or {}).get("sources") or []
        )
        report["business_quality"] = self.business_quality_engine.evaluate(report)
        report["claims"].extend(report["business_quality"].get("interpretations") or [])
        report["research_quality"] = calculate_research_quality(report)
        coverage_snapshot = CoverageRegressionMonitor.snapshot(report)
        prior_entry = CoverageRegressionMonitor.previous_for(self.journal_engine.entries, ticker)
        report["regression_alert"] = CoverageRegressionMonitor.compare(coverage_snapshot, prior_entry)
        if report["regression_alert"].get("status") == "REGRESSION_ALERT":
            logging.getLogger("prometheus.regression").warning(
                "REGRESSION_ALERT %s", json.dumps({"ticker": ticker, **report["regression_alert"]}, ensure_ascii=False, sort_keys=True),
            )
        report["editorial_gate"] = self.editorial_gate.evaluate(report)

        serialized_report = self._serialize(report)
        preds_serialized = []
        if "preds" in locals() and preds:
            import dataclasses as _dataclasses

            preds_serialized = [_dataclasses.asdict(p) for p in preds]

        journal_entry = self.journal_engine.record(
            ticker=ticker,
            asset_profile=serialized_report.get("asset_profile", {}),
            financials=serialized_report.get("financials", {}),
            market_snapshot=serialized_report.get("market_snapshot", {}),
            thesis_scores=serialized_report.get("thesis_scores", {}),
            thesis_result=thesis_result,
            decision_result=decision_result,
            sentiment_score=sentiment_score,
            metadata={**(journal_metadata or {}), "coverage_snapshot": coverage_snapshot},
            predictions=preds_serialized,
        )
        self.replay_engine.record(serialized_report)

        return {
            "report": serialized_report,
            "overall_score": final_score,
            "state": final_state,
            "scores": thesis_scores,
            "decision_result": decision_result,
            "journal_entry": journal_entry,
        }

    def _append_structured_financial_sources(self, report: Dict[str, Any]) -> None:
        """Expose the exact CVM evidence behind every financial point rendered in the PDF."""
        sources = report.setdefault("research", {}).setdefault("sources", [])
        for metric_name, metric in (report.get("official_metrics") or {}).items():
            if not any(source.get("metric") == metric_name for source in sources):
                self._append_cvm_metric_source(
                    sources, metric_name, metric,
                    str(report.get("financials", {}).period if dataclasses.is_dataclass(report.get("financials")) else report.get("financial_history", [{}])[-1].get("period") if report.get("financial_history") else ""),
                )
        history = report.get("financial_history") or []
        annual = [row for row in history if str(row.get("period") or "").endswith("-12-31")][-5:]
        interim = [row for row in history if row not in annual and row.get("period")]
        selected_history = [*annual, *([interim[-1]] if interim else [])]
        for row in selected_history:
            for metric_name in ("revenue", "net_income", "profit_margin", "roe"):
                metric = (row.get("metric_metadata") or {}).get(metric_name) or {}
                self._append_cvm_metric_source(
                    sources, f"history_{metric_name}", metric, str(row.get("period")),
                )
        ttm = report.get("ttm") or {}
        for metric_name, metric in (ttm.get("metrics") or {}).items():
            self._append_cvm_metric_source(
                sources, f"ttm_{metric_name}", metric, str(ttm.get("as_of_period") or ""),
            )

    @staticmethod
    def _append_official_catalysts(report: Dict[str, Any]) -> None:
        """Expose official publications as confirmed monitors without retroactive score changes."""
        catalysts = report.setdefault("catalyst_result", {}).setdefault("catalysts", [])
        existing = {(item.get("url"), item.get("published_at")) for item in catalysts}
        category_map = {
            "Fato Relevante": "official_material_event",
            "Comunicado ao Mercado": "official_market_communication",
            "Dados Econômico-Financeiros": "official_financial_update",
            "Apresentações a analistas/agentes do mercado": "official_presentation",
        }
        for document in (report.get("official_disclosures") or {}).get("documents") or []:
            key = (document.get("source_url"), document.get("delivered_at"))
            if key in existing:
                continue
            catalysts.append({
                "category": category_map.get(document.get("category"), "official_disclosure"),
                "title": document.get("subject") or document.get("type") or document.get("category"),
                "url": document.get("source_url"), "source": "CVM IPE",
                "published_at": document.get("delivered_at"),
                "factual_status": "PRIMARY_CONFIRMED",
                "interpretation": "OFFICIAL_DISCLOSURE_MONITOR",
                "protocol": document.get("protocol"), "version": document.get("version"),
                "content_extraction_status": document.get("content_extraction_status"),
                "score_included": False,
            })
            existing.add(key)

    def _append_reference_form_sources(self, report: Dict[str, Any]) -> None:
        fre = report.get("reference_form") or {}
        if fre.get("status") != "AVAILABLE" or not fre.get("received_at"):
            return
        sections = fre.get("sections") or {}
        sources = report.setdefault("research", {}).setdefault("sources", [])
        period = str(fre.get("reference_date") or "not_provided")
        for section, label in (
            ("management", "fre_management_records"),
            ("related_parties", "fre_related_party_records"),
            ("auditors", "fre_auditor_records"),
            ("capital", "fre_capital_records"),
            ("ownership_distribution", "fre_ownership_distribution_records"),
        ):
            sources.append(self.research_engine.build_source_record(
                metric=label, value=len(sections.get(section) or []), unit="records",
                period=period, reference_date=period,
                publication_date=str(fre["received_at"]), source="CVM FRE",
                source_type="calculated", confidence="high", source_url=fre.get("source_url"),
                source_sha256=fre.get("source_sha256"),
                formula=f"count(reference_form.sections.{section})", version=fre.get("version"),
            ))

    def _append_score_sources(self, report: Dict[str, Any]) -> None:
        """Make every score shown in the PDF an explicit, labelled calculation."""
        sources = report.setdefault("research", {}).setdefault("sources", [])
        period = str(report.get("analysis_as_of") or "")[:10]
        publication = str(report.get("analysis_as_of") or "")
        formulas = {
            "fundamental": "deterministic fundamental score from normalized financial ratios",
            "sector": "neutral 50 until at least two peers have point-in-time historical margin and ROE series; no sector direction is inferred from the sector name",
            "macro": "neutral 50 without point-in-time eligible Selic; otherwise clamp(70 + beta adjustment + market-cap adjustment - Selic sensitivity, 30, 100)",
            "expectation_gap": "deterministic price/fundamental divergence heuristic",
            "momentum_velocity": "clamp(50 + 0.7*price_change_percent + 0.3*52_week_change, 0, 100)",
            "valuation_margin": "clamp(50 + (14 - forward_PE)/14*50, 0, 100); neutral 50 without valid P/E",
            "news_sentiment": "deterministic headline lexicon aggregate; neutral 50 without eligible headlines",
        }
        unavailable = set((report.get("score_availability") or {}).get("unavailable_components") or [])
        for name, value in (report.get("thesis_scores") or {}).items():
            if name in unavailable:
                continue
            if isinstance(value, (int, float)):
                sources.append(self.research_engine.build_source_record(
                    metric=f"score_{name}", value=float(value), unit="score_0_100",
                    period=period, reference_date=period, publication_date=publication,
                    source="PROMETHEUS deterministic scoring", source_type="calculated",
                    confidence="low" if name in {"sector", "valuation_margin", "news_sentiment"} else "medium",
                    formula=formulas.get(name, "documented deterministic scoring rule"),
                    assumptions=["Scores are descriptive heuristics, not probabilities or expected returns."],
                ))
        quality = (report.get("fundamental_data_quality") or {}).get("score")
        if isinstance(quality, (int, float)):
            sources.append(self.research_engine.build_source_record(
                metric="fundamental_data_quality_score", value=float(quality), unit="score_0_100",
                period=period, reference_date=period, publication_date=publication,
                source="PROMETHEUS deterministic data-quality audit", source_type="calculated",
                confidence="high", formula="coverage and semantic-validity score over required fundamental fields",
            ))
        final_score = report.get("final_score")
        if isinstance(final_score, (int, float)):
            sources.append(self.research_engine.build_source_record(
                metric="prometheus_final_score", value=float(final_score), unit="score_0_100",
                period=period, reference_date=period, publication_date=publication,
                source="PROMETHEUS deterministic scoring", source_type="calculated", confidence="low",
                formula="0.60*weighted_thesis + 0.15*expectation_gap + 0.10*catalyst + 0.08*regime_confidence*100 + 0.07*pricing_confidence*100",
                assumptions=["Heuristic evidence summary; not an investment recommendation or return probability."],
            ))

    def _append_cvm_metric_source(
        self, sources: List[Dict[str, Any]], metric_name: str,
        metric: Dict[str, Any], period: str,
    ) -> None:
        value = metric.get("normalized")
        rows = metric.get("source_rows") or []
        if value is None or not rows or not period:
            return
        def row_value(row: Any, name: str):
            return row.get(name) if isinstance(row, dict) else getattr(row, name, None)
        publications = [row_value(row, "received_at") for row in rows if row_value(row, "received_at")]
        parsed_publications = []
        for value_date in publications:
            if isinstance(value_date, datetime.datetime):
                parsed_publications.append(value_date)
            else:
                try:
                    parsed_publications.append(datetime.datetime.fromisoformat(str(value_date).replace("Z", "+00:00")).replace(tzinfo=None))
                except (TypeError, ValueError):
                    continue
        if not parsed_publications:
            return
        urls = sorted({str(row_value(row, "source_url")) for row in rows if row_value(row, "source_url")})
        hashes = sorted({str(row_value(row, "source_sha256")) for row in rows if row_value(row, "source_sha256")})
        formula = metric.get("calculation")
        calculated = bool(formula and str(formula).lower() not in {"reported", "reported annual"})
        sources.append(self.research_engine.build_source_record(
            metric=metric_name, value=value, unit=metric.get("unit") or "BRL",
            period=period, reference_date=period,
            publication_date=max(parsed_publications).replace(microsecond=0).isoformat() + "Z",
            source="CVM ITR/DFP", source_type="calculated" if calculated else "primary",
            confidence="high", source_url=urls[0] if urls else None,
            source_urls=urls, source_sha256=hashes[0] if len(hashes) == 1 else None,
            source_sha256_components=hashes, formula=formula if calculated else None,
            raw_source_rows=rows,
        ))

    def save_replay(self, file_path: str) -> None:
        self.replay_engine.save(file_path)

    def load_replay(self, file_path: str) -> None:
        self.replay_engine.load(file_path)

    def replay_summary(self) -> Dict[str, Any]:
        return self.replay_engine.summarize()

    def _normalize(self, raw_data: Dict[str, object]) -> Dict[str, object]:
        return raw_data

    def _extract_value(self, field: Optional[Dict[str, object]]) -> Optional[float]:
        if not field:
            return None
        value = field.get("normalized")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _serialize(self, payload: Any) -> Any:
        if dataclasses.is_dataclass(payload):
            payload = dataclasses.asdict(payload)

        if isinstance(payload, dict):
            result: Dict[str, Any] = {}
            for key, value in payload.items():
                result[key] = self._serialize(value)
            return result

        if isinstance(payload, list):
            return [self._serialize(item) for item in payload]

        if isinstance(payload, datetime.datetime):
            return payload.replace(microsecond=0).isoformat() + "Z"

        if isinstance(payload, datetime.date):
            return payload.isoformat()

        return payload

    def _build_research(
        self,
        ticker: str,
        asset_profile: AssetProfile,
        financials: FinancialStatement,
        market_snapshot: MarketSnapshot,
        fundamental_summary: Dict[str, Any],
        thesis_result: Any,
        risk_result: Dict[str, Any],
        macro_observations: List[Dict[str, Any]],
        news_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        sources: List[Dict[str, Any]] = []
        fields = {
            "revenue_growth": financials.revenue_growth,
            "earnings_growth": financials.earnings_growth,
            "profit_margin": financials.profit_margin,
            "roe": financials.roe,
            "debt_to_equity": financials.debt_to_equity,
            "operating_cash_flow": financials.cash_flow,
        }
        for metric, field in fields.items():
            if not field or field.get("normalized") is None:
                continue
            metadata = field.get("source_metadata")
            available_at = (
                getattr(metadata, "publication_date", None)
                or getattr(metadata, "effective_date", None)
                or getattr(metadata, "timestamp", None)
            )
            raw_metadata = getattr(metadata, "raw", {}) or {}
            source_name = getattr(metadata, "source", None) or "unknown"
            calculation = raw_metadata.get("calculation")
            is_calculation = bool(calculation and str(calculation).strip().lower() != "reported")
            source_type = "calculated" if is_calculation else "primary" if source_name.upper().startswith("CVM") else "secondary"
            sources.append(self.research_engine.build_source_record(
                metric=metric,
                value=field.get("normalized"),
                unit=field.get("unit") or "unknown",
                period=financials.period or "latest_available",
                reference_date=str(financials.period or "not_provided"),
                publication_date=available_at.isoformat() if available_at else "not_provided",
                source=source_name,
                source_type=source_type,
                confidence="high" if source_name.upper().startswith("CVM") else "medium",
                source_url=raw_metadata.get("url"),
                source_sha256=raw_metadata.get("source_sha256"),
                formula=calculation if is_calculation else None,
                raw_value=field.get("raw"),
                source_field=field.get("source_field"),
            ))

        market_fields = {
            "price": market_snapshot.price,
            "market_cap": market_snapshot.market_cap,
            "shares_outstanding": market_snapshot.shares_outstanding,
            "enterprise_value": market_snapshot.enterprise_value,
        }
        provider_names = {
            "price": "regularMarketPrice", "market_cap": "marketCap",
            "shares_outstanding": "sharesOutstanding", "enterprise_value": "enterpriseValue",
        }
        market_units = {
            "price": "BRL/share", "market_cap": "BRL",
            "shares_outstanding": "shares", "enterprise_value": "BRL",
        }
        for metric, value in market_fields.items():
            if value is None:
                continue
            metadata = market_snapshot.field_metadata.get(provider_names[metric], market_snapshot.source_metadata)
            available_at = getattr(metadata, "publication_date", None) or getattr(metadata, "effective_date", None)
            raw_metadata = getattr(metadata, "raw", {}) or {}
            source_name = getattr(metadata, "source", None) or "unknown"
            formula = raw_metadata.get("formula")
            source_type = "calculated" if formula else "primary" if source_name.startswith("CVM") else "secondary"
            sources.append(self.research_engine.build_source_record(
                metric=metric, value=value, unit=market_units[metric],
                period=getattr(metadata, "period", None) or "not_provided",
                reference_date=getattr(metadata, "period", None) or "not_provided",
                publication_date=available_at.isoformat() if available_at else "not_provided",
                source=source_name, source_type=source_type,
                confidence="high" if (getattr(metadata, "confidence", 0.0) or 0.0) >= 0.9 else "medium",
                source_url=raw_metadata.get("url"), source_sha256=raw_metadata.get("source_sha256"),
                source_sha256_components=raw_metadata.get("source_sha256_components") or [], formula=formula,
            ))

        for observation in macro_observations:
            if observation.get("point_in_time_eligible") is False or observation.get("value") is None:
                continue
            sources.append(self.research_engine.build_source_record(
                metric=observation.get("metric", "macro_observation"),
                value=observation.get("value"),
                unit=observation.get("unit", "unknown"),
                period=observation.get("date", "not_provided"),
                reference_date=observation.get("date", "not_provided"),
                publication_date=observation.get("publication_date", "not_provided"),
                source=observation.get("source", "Banco Central do Brasil"),
                source_type="primary",
                confidence="high",
                source_url=observation.get("source_url"),
                source_sha256=observation.get("source_sha256"),
                series_code=observation.get("series_code"),
            ))

        for item in news_items:
            published_at = item.get("published_at") or item.get("timestamp_collected") or "not_provided"
            publisher = item.get("source") or "news"
            title = item.get("title") or "Sem título"
            sources.append(self.research_engine.build_source_record(
                metric="news_report",
                value=title,
                unit="text",
                period=str(published_at),
                reference_date=str(published_at),
                publication_date=str(published_at),
                source=publisher,
                source_type="secondary",
                confidence="low",
                source_url=item.get("url"),
                source_sha256=item.get("source_sha256"),
                event_factual_status=item.get("event_factual_status") or "SECONDARY_REPORT_UNVERIFIED",
                claim_classification="FACT",
                claim_text=f"{publisher} publicou a manchete: {title}",
            ))
            if isinstance(item.get("sentiment_score"), (int, float)):
                sources.append(self.research_engine.build_source_record(
                    metric="news_sentiment_interpretation",
                    value=float(item["sentiment_score"]), unit="score_0_100",
                    period=str(published_at), reference_date=str(published_at),
                    publication_date=str(published_at), source="PROMETHEUS deterministic headline lexicon",
                    source_type="calculated", confidence="low", source_url=item.get("url"),
                    source_sha256=item.get("source_sha256"),
                    formula="50 + 10 * clamp(positive_tokens - negative_tokens, -5, 5)",
                    claim_classification="CALCULATION",
                    claim_text=f"Sentimento lexical da manchete de {publisher}: {float(item['sentiment_score']):.1f}/100",
                    event_factual_status="INTERPRETATION_NOT_EVENT_CONFIRMATION",
                ))

        supporting = list(getattr(thesis_result, "drivers", []) or [])
        contradicting = [
            getattr(item, "details", str(item))
            for item in (risk_result.get("evidence") or [])
        ]
        quality_score = fundamental_summary.get("confidence", 0.0)
        return self.research_engine.build_research_report(
            ticker=ticker,
            sector=asset_profile.sector or "Unknown",
            business_model=asset_profile.business_summary or "Não confirmado em fonte primária.",
            geographic_exposure=[asset_profile.country] if asset_profile.country else [],
            sources=sources,
            evidence=sources,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            data_quality_status="SUFFICIENT" if quality_score >= 80.0 else "PARTIAL",
            confidence="high" if quality_score >= 80.0 else "medium" if quality_score >= 50.0 else "low",
            executive_summary=(
                f"Research de {ticker} baseado em {len(sources)} métricas rastreáveis; "
                "as limitações de fonte e período devem ser consideradas na interpretação."
            ),
        )

    @staticmethod
    def _filter_news_point_in_time(
        items: List[Dict[str, Any]], as_of: Optional[datetime.datetime]
    ) -> List[Dict[str, Any]]:
        if as_of is None:
            return list(items)
        cutoff = as_of
        if cutoff.tzinfo is not None:
            cutoff = cutoff.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        accepted: List[Dict[str, Any]] = []
        for item in items:
            timestamp = item.get("published_at") or item.get("timestamp_collected")
            if not timestamp:
                continue
            try:
                parsed = datetime.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
            if parsed <= cutoff:
                accepted.append(item)
        return accepted
