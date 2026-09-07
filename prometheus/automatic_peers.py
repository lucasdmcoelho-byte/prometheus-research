from __future__ import annotations

import datetime as dt
import math
import statistics
from typing import Any, Dict, List

from prometheus.cvm_client import CVMFundamentalSnapshotBuilder
from prometheus.editorial_gate import EditorialGate
from prometheus.peer_universe import identity_for, peers_for
from prometheus.peer_universe import PeerIdentity
from prometheus.valuation_engine import ValuationEngine
from prometheus.evidence_engine import EvidenceEngine


def enrich_automatic_peers(report: Dict[str, Any], adapter: Any, as_of: dt.datetime, limit: int = 6) -> Dict[str, Any]:
    """Select period-compatible peers and rebuild the sector-appropriate valuation."""
    sector_key = (report.get("sector_model") or {}).get("key", "general")
    capital_intensive = {"mining", "oil_gas", "utilities", "materials", "transport_logistics", "industrial"}
    multiple_method = "P/B" if sector_key == "financial" else "EV/EBIT" if sector_key in capital_intensive else "P/E"
    target_roe = _metric({"metrics": report.get("official_metrics") or {}}, "roe")
    candidate_provider = getattr(adapter, "peer_candidates", None)
    activity_sector = (report.get("official_classification") or {}).get("sector")
    # A wider pool avoids letting alphabetical ticker order decide the result
    # before comparable period and issuer scale are evaluated.
    candidate_limit = max(limit * 6, 36)
    dynamic_candidates = candidate_provider(str(report.get("ticker")), activity_sector, as_of, candidate_limit) if callable(candidate_provider) and activity_sector else []
    target_ticker = str(report.get("ticker"))
    maintained = peers_for(target_ticker, sector_key, limit=candidate_limit if dynamic_candidates else limit)
    target_identity = identity_for(target_ticker)
    dynamic_by_ticker = {item["ticker"]: item for item in dynamic_candidates}
    maintained_dynamic = [item for item in maintained if item.ticker in dynamic_by_ticker]
    if target_identity and target_identity.sector_key == sector_key and maintained and (not dynamic_candidates or len(maintained_dynamic) >= 2):
        identities = maintained_dynamic if dynamic_candidates else maintained
        selection_method = "maintained_economic_model_and_exact_cvm_activity" if dynamic_candidates else "maintained_sector_universe"
    else:
        identities = [
            PeerIdentity(item["ticker"], item["cvm_code"], sector_key, item["company"])
            for item in dynamic_candidates
        ] or maintained
        selection_method = "exact_cvm_activity_sector_unique_issuer" if dynamic_candidates else "maintained_sector_universe"
    prefetched = adapter.cvm.load_rows_many(
        [item.cvm_code for item in identities], as_of, filing_types=("ITR", "DFP"),
        years=range(max(2011, as_of.year - 1), as_of.year + 1),
    ) if identities and hasattr(adapter.cvm, "load_rows_many") else {}
    rows: List[Dict[str, Any]] = []
    for identity in identities:
        try:
            filings = prefetched.get(identity.cvm_code.lstrip("0")) or adapter.cvm.load_rows(
                identity.cvm_code, as_of, filing_types=("ITR", "DFP"),
                years=range(max(2011, as_of.year - 1), as_of.year + 1),
            )
            snapshot = CVMFundamentalSnapshotBuilder().build(filings)
            market_record = _market_cap_record(adapter, identity.ticker, as_of)
            price_record = _price_record(adapter, identity.ticker, as_of)
            market_cap = market_record.get("value")
            peer_ttm = CVMFundamentalSnapshotBuilder().build_ttm(filings)
            ttm_income_metric = (peer_ttm.get("metrics") or {}).get("net_income") or {}
            ttm_income = ttm_income_metric.get("normalized")
            if ttm_income is not None:
                net_income, annualization, income_method = float(ttm_income), None, "TTM: current YTD + prior FY - prior YTD"
                income_sources = ttm_income_metric.get("source_rows") or []
            else:
                net_income, annualization = _annualized_net_income(snapshot)
                income_method = "linear YTD annualization fallback"
                income_sources = ((snapshot.get("metrics") or {}).get("net_income") or {}).get("source_rows") or []
            equity = _metric(snapshot, "equity")
            equity_sources = ((snapshot.get("metrics") or {}).get("equity") or {}).get("source_rows") or []
            total_assets = _metric(snapshot, "total_assets")
            pb = market_cap / equity if market_cap and equity and equity > 0 else None
            pb_formula = "market_cap / equity"
            equity_value_proxy = None
            capital = {}
            market_basis_record = market_record
            capital_loader = getattr(adapter.cvm, "load_capital_composition", None)
            if market_cap is None and callable(capital_loader):
                capital = capital_loader(
                    identity.cvm_code, as_of, filing_types=("ITR", "DFP"),
                    years=range(max(2011, as_of.year - 1), as_of.year + 1),
                ) or {}
            shares = (
                capital.get("shares_outstanding")
                if capital.get("status") == "AVAILABLE" and capital.get("quantity_scale_status") == "VERIFIED"
                else None
            )
            class_price = price_record.get("value")
            if (
                market_cap is None and capital.get("single_class") is True
                and isinstance(class_price, (int, float)) and class_price > 0
                and isinstance(shares, (int, float)) and shares > 0
            ):
                market_cap = float(class_price) * float(shares)
                market_basis_record = {
                    **price_record,
                    "value": market_cap,
                    "source": "B3 price × official CVM capital",
                    "formula": "price * shares_outstanding",
                }
            pe = market_cap / net_income if market_cap and net_income and net_income > 0 else None
            pb = market_cap / equity if market_cap and equity and equity > 0 else None
            if multiple_method == "P/B" and pb is None and equity and equity > 0:
                if not capital and callable(capital_loader):
                    capital = capital_loader(
                        identity.cvm_code, as_of, filing_types=("ITR", "DFP"),
                        years=range(max(2011, as_of.year - 1), as_of.year + 1),
                    ) or {}
                    shares = (
                        capital.get("shares_outstanding")
                        if capital.get("status") == "AVAILABLE" and capital.get("quantity_scale_status") == "VERIFIED"
                        else None
                    )
                if isinstance(class_price, (int, float)) and class_price > 0 and isinstance(shares, (int, float)) and shares > 0:
                    equity_value_proxy = float(class_price) * float(shares)
                    pb = equity_value_proxy / float(equity)
                    pb_formula = "price / (equity / shares_outstanding)"
                    market_basis_record = price_record
            ttm_ebit_metric = (peer_ttm.get("metrics") or {}).get("operating_income") or {}
            ttm_ebit = ttm_ebit_metric.get("normalized")
            ttm_ebit_sources = ttm_ebit_metric.get("source_rows") or []
            net_debt_metric = (snapshot.get("metrics") or {}).get("net_debt") or {}
            peer_net_debt = net_debt_metric.get("normalized")
            net_debt_sources = net_debt_metric.get("source_rows") or []
            calculated_ev = market_cap + peer_net_debt if market_cap is not None and peer_net_debt is not None else None
            ev_ebit = calculated_ev / ttm_ebit if calculated_ev and calculated_ev > 0 and ttm_ebit and ttm_ebit > 0 else None
            multiple_sources = (
                [*equity_sources, *income_sources] if multiple_method == "P/B"
                else [*ttm_ebit_sources, *net_debt_sources] if multiple_method == "EV/EBIT"
                else income_sources
            )
            financial_publication_date, financial_source_urls, financial_source_hashes = _source_availability(multiple_sources)
            if capital.get("status") == "AVAILABLE":
                financial_publication_date = _latest_publication(financial_publication_date, capital.get("received_at"))
                if capital.get("source_url"):
                    financial_source_urls = sorted(set([*financial_source_urls, str(capital["source_url"])]))
                if isinstance(capital.get("source_sha256"), str) and len(capital["source_sha256"]) == 64:
                    financial_source_hashes = sorted(set([*financial_source_hashes, capital["source_sha256"]]))
            rows.append({
                "ticker": identity.ticker, "company": identity.company, "cvm_code": identity.cvm_code,
                "trailing_pe": float(pe) if isinstance(pe, (int, float)) and pe > 0 else None,
                "price_to_book": float(pb) if isinstance(pb, (int, float)) and pb > 0 else None,
                "ev_to_ebit": float(ev_ebit) if isinstance(ev_ebit, (int, float)) and ev_ebit > 0 else None,
                "enterprise_value_calculated": calculated_ev, "equity_value_proxy": equity_value_proxy,
                "ttm_ebit": ttm_ebit,
                "net_debt": peer_net_debt,
                "market_cap": market_cap, "total_assets": total_assets, "annualized_net_income": net_income,
                "market_cap_formula": market_basis_record.get("formula"),
                "price": price_record.get("value"),
                "shares_outstanding": capital.get("shares_outstanding"),
                "capital_quantity_scale_status": capital.get("quantity_scale_status"),
                "capital_quantity_scale_multiplier": capital.get("quantity_scale_multiplier"),
                "market_source": market_basis_record.get("source"), "market_source_url": market_basis_record.get("source_url"),
                "market_source_sha256": market_basis_record.get("source_sha256"),
                "market_publication_date": _iso_datetime(market_basis_record.get("publication_date")),
                "financial_publication_date": financial_publication_date,
                "financial_source_urls": financial_source_urls,
                "financial_source_hashes": financial_source_hashes,
                "multiple_publication_date": _latest_publication(
                    market_basis_record.get("publication_date"), financial_publication_date,
                ),
                "multiple_formula": (
                    pb_formula if multiple_method == "P/B"
                    else "(market_cap + net_debt) / TTM_operating_income" if multiple_method == "EV/EBIT"
                    else "market_cap / TTM_net_income" if income_method.startswith("TTM")
                    else "market_cap / annualized_net_income"
                ),
                "annualization_factor": annualization,
                "income_method": income_method,
                "profit_margin": _metric(snapshot, "profit_margin"), "roe": _metric(snapshot, "roe"),
                "debt_to_equity": _metric(snapshot, "debt_to_equity"),
                "reference_date": snapshot.get("reference_date"), "source": "CVM + point-in-time market observation" if market_cap else "CVM",
                "selection_reason": (next((item.get("selection_reason") for item in dynamic_candidates if item["ticker"] == identity.ticker), None) or f"Mesmo modelo setorial mantido: {sector_key}"),
            })
        except Exception as error:
            rows.append({
                "ticker": identity.ticker, "company": identity.company, "cvm_code": identity.cvm_code,
                "status": "UNAVAILABLE", "reason": type(error).__name__,
                "error_detail": _safe_error_detail(error),
                "selection_reason": (next((item.get("selection_reason") for item in dynamic_candidates if item["ticker"] == identity.ticker), None) or f"Mesmo modelo setorial mantido: {sector_key}"),
            })
    target_period = _target_period(report)
    target_market_cap = report.get("market_cap")
    target_assets = ((report.get("official_metrics") or {}).get("total_assets") or {}).get("normalized")
    asset_scale_sectors = {"financial", "real_estate", *capital_intensive}
    preferred_scale_basis = "total_assets" if sector_key in asset_scale_sectors else "market_cap"
    for row in rows:
        use_market_cap = bool(
            preferred_scale_basis == "market_cap" and target_market_cap and row.get("market_cap")
        )
        peer_scale = row.get("market_cap") if use_market_cap else row.get("total_assets")
        target_scale = target_market_cap if use_market_cap else target_assets
        row["scale_basis"] = "market_cap" if use_market_cap else "total_assets" if peer_scale and target_scale else None
        row["scale_distance_log"] = abs(math.log(float(peer_scale) / float(target_scale))) if peer_scale and target_scale and peer_scale > 0 and target_scale > 0 else None
        row["period_compatible"] = bool(target_period and row.get("reference_date") == target_period)
        peer_roe = row.get("roe")
        if multiple_method == "P/B" and row.get("price_to_book") and target_roe and peer_roe and peer_roe > 0:
            row["roe_adjusted_price_to_book"] = float(row["price_to_book"]) * float(target_roe) / float(peer_roe)
            row["roe_adjustment_formula"] = "peer_PB * target_annualized_ROE / peer_annualized_ROE"
            row["target_annualized_roe"] = target_roe
        else:
            row["roe_adjusted_price_to_book"] = None
    rows.sort(key=lambda row: (
        not row.get("period_compatible"), row.get("scale_distance_log") is None,
        row.get("scale_distance_log") or float("inf"), row.get("ticker") or "",
    ))
    multiple_field = "roe_adjusted_price_to_book" if multiple_method == "P/B" else "ev_to_ebit" if multiple_method == "EV/EBIT" else "trailing_pe"
    for row in rows:
        exclusion_reasons = []
        if not row.get("period_compatible"):
            exclusion_reasons.append("INCOMPATIBLE_PERIOD")
        if row.get(multiple_field) is None:
            exclusion_reasons.append("MULTIPLE_UNAVAILABLE")
        if row.get("scale_distance_log") is not None and row["scale_distance_log"] > math.log(4.0):
            exclusion_reasons.append("INCOMPARABLE_SCALE_OVER_4X")
        if multiple_method == "P/E" and not str(row.get("income_method") or "").startswith("TTM"):
            exclusion_reasons.append("NON_TTM_EARNINGS")
        if multiple_method == "EV/EBIT" and row.get("ttm_ebit") is None:
            exclusion_reasons.append("NON_TTM_OPERATING_INCOME")
        if not row.get("market_publication_date"):
            exclusion_reasons.append("MARKET_AVAILABILITY_MISSING")
        if not row.get("financial_publication_date"):
            exclusion_reasons.append("FINANCIAL_AVAILABILITY_MISSING")
        row["multiple_eligible"] = not exclusion_reasons
        row["exclusion_reasons"] = exclusion_reasons
    # Unusable close-scale issuers must not crowd out slightly less similar but
    # fully auditable peers. Eligibility is determined on the wider pool before
    # applying the presentation/valuation limit.
    rows.sort(key=lambda row: (
        not row.get("multiple_eligible"), not row.get("period_compatible"),
        row.get("scale_distance_log") is None,
        row.get("scale_distance_log") or float("inf"), row.get("ticker") or "",
    ))
    rows = rows[:limit]
    compatible = [row for row in rows if row.get("period_compatible")]
    eligible = [row for row in rows if row.get("multiple_eligible")]
    multiples = [row[multiple_field] for row in eligible]
    multiple_median = statistics.median(multiples) if multiples else None
    for row in rows:
        value = row.get(multiple_field)
        row["multiple_outlier"] = bool(
            multiple_median and value and (float(value) > multiple_median * 3.0 or float(value) < multiple_median / 3.0)
        )
        row["quality_comparison"] = {
            "profit_margin": row.get("profit_margin"),
            "roe": row.get("roe"),
            "debt_to_equity": row.get("debt_to_equity"),
        }
    valuation_multiples = multiples if len(multiples) >= 2 else []
    report.setdefault("research", {})["peer_analysis"] = {
        "status": "AVAILABLE" if len(eligible) >= 2 else "INSUFFICIENT_DATA", "sector_key": sector_key,
        "selection_method": selection_method, "target_activity_sector": activity_sector,
        "scale_policy": preferred_scale_basis,
        "multiple_method": "P/B adjusted by annualized ROE" if multiple_method == "P/B" else multiple_method,
        "target_period": target_period,
        "peers": rows, "compatible_period_count": len(compatible),
        "eligible_multiple_count": len(eligible),
        "quality_comparison_available": sum(
            1 for row in eligible if row.get("profit_margin") is not None and row.get("roe") is not None
        ) >= 2,
        "outlier_tickers": [row.get("ticker") for row in rows if row.get("multiple_outlier")],
        "minimum_eligible_multiple_count": 2,
        "limitations": [
            "A classificação setorial é mantida e revisável; não implica negócios idênticos.",
            "Valuation aceita somente períodos idênticos; P/L exige lucro TTM e EV/EBIT exige EBIT TTM e dívida líquida, sem substituir EBIT por EBITDA.",
            "Para bancos, o P/VP observado é ajustado linearmente pela razão entre ROE anualizado do alvo e do peer; isso não substitui um modelo explícito de custo de capital e crescimento.",
            "Peers com diferença de escala superior a 4x em valor de mercado ou ativos totais são excluídos do valuation.",
        ],
    }
    research_sources = report.setdefault("research", {}).setdefault("sources", [])
    peer_source_ids = []
    for row in eligible:
        source_id = f"PEER-{row['ticker']}-{row.get('reference_date') or 'NA'}"
        peer_source_ids.append(source_id)
        research_sources.append({
            "source_id": source_id, "metric": "roe_adjusted_price_to_book" if multiple_method == "P/B" else "ev_to_ebit" if multiple_method == "EV/EBIT" else "ttm_pe", "value": row[multiple_field], "unit": "x",
            "period": row.get("reference_date") or "latest", "reference_date": row.get("reference_date") or "not_provided",
            "publication_date": row.get("multiple_publication_date"),
            "source": row["source"], "source_type": "calculated", "confidence": "medium", "source_tier": "TIER_2",
            "source_url": row.get("market_source_url") or f"https://finance.yahoo.com/quote/{row['ticker']}.SA",
            "financial_source_urls": row.get("financial_source_urls"),
            "source_sha256": row.get("market_source_sha256"),
            "source_sha256_components": row.get("financial_source_hashes") or [],
            "formula": row.get("roe_adjustment_formula") if multiple_method == "P/B" else row.get("multiple_formula"),
            "observed_peer_multiple": row.get("price_to_book") if multiple_method == "P/B" else None,
            "peer_annualized_roe": row.get("roe") if multiple_method == "P/B" else None,
            "target_annualized_roe": target_roe if multiple_method == "P/B" else None,
            "annualization_factor": row.get("annualization_factor"),
        })
    metrics = report.get("official_metrics") or {}
    target_income_source_ids = [
        str(source.get("source_id")) for source in research_sources
        if source.get("metric") == "ttm_net_income" and source.get("source_id")
    ]
    target_ebit_source_ids = [
        str(source.get("source_id")) for source in research_sources
        if source.get("metric") == "ttm_operating_income" and source.get("source_id")
    ]
    target_income = ((((report.get("ttm") or {}).get("metrics") or {}).get("net_income") or {}).get("normalized"))
    target_factor = None
    target_income_method = "TTM: current YTD + prior FY - prior YTD"
    if target_income is None:
        target_income_method = "INSUFFICIENT_DATA: target TTM unavailable"
    if multiple_method == "P/B":
        valuation = ValuationEngine().evaluate_book_value(
            price=report.get("price"), shares=report.get("shares_outstanding"),
            equity=(metrics.get("equity") or {}).get("normalized"), peer_multiples=valuation_multiples,
            assumptions={
                "assumption_source": "mediana do P/VP dos peers ajustado pela razão de ROE anualizado",
                "roe_adjustment_formula": "peer_PB * target_annualized_ROE / peer_annualized_ROE",
                "target_annualized_roe": target_roe,
            } if valuation_multiples else None,
        )
    elif multiple_method == "EV/EBIT":
        target_ttm_ebit = ((((report.get("ttm") or {}).get("metrics") or {}).get("operating_income") or {}).get("normalized"))
        valuation = ValuationEngine().evaluate_ev_ebit(
            price=report.get("price"), shares=report.get("shares_outstanding"),
            ttm_ebit=target_ttm_ebit, net_debt=(metrics.get("net_debt") or {}).get("normalized"),
            peer_multiples=valuation_multiples,
            assumptions={"assumption_source": "mediana EV/EBIT dos peers elegíveis; EBIT não tratado como EBITDA"} if valuation_multiples else None,
        )
    else:
        target_ttm_operating_cash_flow = ((((report.get("ttm") or {}).get("metrics") or {}).get("operating_cash_flow") or {}).get("normalized"))
        valuation = ValuationEngine().evaluate(
            price=report.get("price"), shares=report.get("shares_outstanding"), net_income=target_income,
            operating_cash_flow=target_ttm_operating_cash_flow,
            net_debt=(metrics.get("net_debt") or {}).get("normalized"), peer_multiples=valuation_multiples,
            assumptions={"earnings_growth": 0.0, "horizon_years": 1,
                         "assumption_source": "mediana P/L TTM observado dos peers elegíveis; lucro por ação constante no caso-base"} if valuation_multiples else None,
        )
    if valuation.get("status") == "AVAILABLE":
        valuation["peer_observations"] = len(valuation_multiples)
        valuation["peer_median_check"] = statistics.median(valuation_multiples)
        valuation["target_basis_formula"] = (
            "equity / shares"
            if multiple_method == "P/B"
            else "TTM operating income: current YTD + prior FY - prior YTD"
            if multiple_method == "EV/EBIT"
            else target_income_method
        )
        if multiple_method == "P/E":
            valuation["target_income_annualization_factor"] = target_factor
            valuation["target_income_formula"] = target_income_method
            valuation["cash_conversion_formula"] = "TTM operating_cash_flow / TTM net_income"
        if multiple_method == "P/B":
            valuation["metrics"]["peer_median_roe_adjusted_pb"] = statistics.median(valuation_multiples)
            observed_pb = [row["price_to_book"] for row in eligible if row.get("price_to_book")]
            valuation["metrics"]["peer_median_observed_pb"] = statistics.median(observed_pb) if observed_pb else None
            valuation.setdefault("limitations", []).append(
                "O ajuste relativo de ROE é linear e não modela separadamente custo de capital, crescimento sustentável ou qualidade da carteira."
            )
    report["valuation"] = valuation
    if valuation.get("status") == "AVAILABLE":
        claim_engine = EvidenceEngine()
        median_key = "peer_median_pb" if multiple_method == "P/B" else "peer_median_ev_ebit" if multiple_method == "EV/EBIT" else "peer_median_pe"
        label = "P/VP ajustado por ROE" if multiple_method == "P/B" else "EV/EBIT" if multiple_method == "EV/EBIT" else "P/L TTM"
        report.setdefault("claims", []).append(claim_engine.build_claim(
            section="valuation", text=f"Mediana {label} dos peers: {valuation['metrics'][median_key]:.2f}x",
            claim_type="CALCULATION", source_ids=peer_source_ids, value=valuation["metrics"][median_key], unit="x",
            confidence="medium", materiality="high", formula=f"median({multiple_field})",
        ))
        for scenario, values in valuation["scenarios"].items():
            report["claims"].append(claim_engine.build_claim(
                section="valuation", text=f"Cenário {scenario}: valor implícito por ação de R$ {values['implied_value_per_share']:.2f}",
                claim_type="ESTIMATE", source_ids=[
                    *peer_source_ids,
                    *(target_ebit_source_ids if multiple_method == "EV/EBIT" else target_income_source_ids),
                ], value=values["implied_value_per_share"], unit="BRL/share",
                confidence="low", materiality="high",
                assumptions=[
                    f"{label} {values['multiple']:.4f}x",
                    f"base operacional/patrimonial conforme inputs {values.get('input_values')}",
                    "faixa bear/bull de ±20% sobre a mediana",
                ],
            ))
    report["editorial_gate"] = EditorialGate().evaluate(report)
    return report


def _safe_error_detail(error: Exception, limit: int = 240) -> str:
    """Keep peer failures actionable without leaking multiline/internal payloads."""
    detail = " ".join(str(error).split()) or type(error).__name__
    return detail[:limit]


def _metric(snapshot: Dict[str, Any], name: str):
    return ((snapshot.get("metrics") or {}).get(name) or {}).get("normalized")


def _target_period(report: Dict[str, Any]):
    return next((
        item.get("period") or item.get("reference_date")
        for item in reversed(report.get("financial_history") or [])
        if item.get("period") or item.get("reference_date")
    ), None)


def _row_value(row: Any, key: str):
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def _source_availability(source_rows: List[Any]):
    publications = [_row_value(row, "received_at") for row in source_rows]
    urls = sorted({str(_row_value(row, "source_url")) for row in source_rows if _row_value(row, "source_url")})
    hashes = sorted({
        str(_row_value(row, "source_sha256"))
        for row in source_rows
        if isinstance(_row_value(row, "source_sha256"), str) and len(str(_row_value(row, "source_sha256"))) == 64
    })
    return _latest_publication(*publications), urls, hashes


def _parse_datetime(value: Any):
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime.combine(value, dt.datetime.max.time())
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _iso_datetime(value: Any):
    parsed = _parse_datetime(value)
    return parsed.replace(microsecond=0).isoformat() + "Z" if parsed else None


def _latest_publication(*values: Any):
    parsed = [_parse_datetime(value) for value in values]
    eligible = [value for value in parsed if value is not None]
    return max(eligible).replace(microsecond=0).isoformat() + "Z" if eligible else None


def _market_cap(adapter: Any, ticker: str, as_of: dt.datetime):
    return _market_cap_record(adapter, ticker, as_of).get("value")


def _market_cap_record(adapter: Any, ticker: str, as_of: dt.datetime):
    record_provider = getattr(adapter, "peer_market_cap_record", None)
    if callable(record_provider):
        try:
            record = record_provider(ticker, as_of)
            if record:
                return record
        except (ValueError, KeyError):
            return {"value": None}
    custom = getattr(adapter, "peer_market_cap", None)
    if callable(custom):
        try:
            return {"value": custom(ticker, as_of), "source": "configured point-in-time market adapter"}
        except (ValueError, KeyError):
            return {"value": None}
    if as_of.date() < dt.datetime.utcnow().date():
        return {"value": None, "limitation": "CURRENT_MARKET_CAP_NOT_POINT_IN_TIME"}
    import yfinance as yf
    if getattr(adapter.market, "cache_dir", None):
        from pathlib import Path
        from yfinance.cache import set_cache_location
        cache = (Path(adapter.market.cache_dir) / "yfinance").resolve()
        cache.mkdir(parents=True, exist_ok=True); set_cache_location(str(cache))
    symbol = ticker if ticker.endswith(".SA") else f"{ticker}.SA"
    instrument = yf.Ticker(symbol)
    # Force a bounded price request before FastInfo; this avoids the unbounded
    # full-profile endpoint used by ``Ticker.info``.
    instrument.history(
        start=(as_of.date() - dt.timedelta(days=10)).isoformat(),
        end=(as_of.date() + dt.timedelta(days=1)).isoformat(), period=None, timeout=8,
        auto_adjust=False,
    )
    try:
        value = instrument.fast_info["market_cap"]
    except (KeyError, TypeError):
        value = None
    return {
        "value": float(value) if isinstance(value, (int, float)) and value > 0 else None,
        "source": "yfinance live market capitalization",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}",
        "publication_date": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def _price_record(adapter: Any, ticker: str, as_of: dt.datetime):
    record_provider = getattr(adapter, "peer_price_record", None)
    if callable(record_provider):
        try:
            record = record_provider(ticker, as_of)
            if record:
                return record
        except (ValueError, KeyError):
            return {"value": None}
    return {"value": None, "limitation": "POINT_IN_TIME_PRICE_UNAVAILABLE"}


def _annualized_net_income(snapshot: Dict[str, Any]):
    metric = (snapshot.get("metrics") or {}).get("net_income") or {}
    value = metric.get("normalized")
    source_rows = metric.get("source_rows") or []
    if value is None or not source_rows:
        return value, None
    row = max(source_rows, key=lambda item: item.reference_date)
    if row.period_start and row.reference_date:
        elapsed = (row.reference_date - row.period_start).days + 1
        factor = 365.0 / elapsed if 0 < elapsed < 350 else 1.0
    else:
        factor = 1.0
    return float(value) * factor, factor


def _annualize_report_metric(metric: Dict[str, Any]):
    value = metric.get("normalized")
    rows = metric.get("source_rows") or []
    if value is None or not rows:
        return value, None
    row = rows[0]
    try:
        reference = dt.date.fromisoformat(str(row.get("reference_date"))[:10])
        start = dt.date.fromisoformat(str(row.get("period_start"))[:10])
        elapsed = (reference - start).days + 1
        factor = 365.0 / elapsed if 0 < elapsed < 350 else 1.0
    except (ValueError, TypeError, AttributeError):
        factor = 1.0
    return float(value) * factor, factor
