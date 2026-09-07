import argparse
import datetime
import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from prometheus.backtest_engine import BacktestEngine, PrometheusPointInTimeSignalProvider
from prometheus.continuous_feed import ContinuousFeed
from prometheus.data_engine import validate_ticker
from prometheus.knowledge_store import KnowledgeStore
from prometheus.news_feed import NewsFeed
from prometheus.peer_analysis import enrich_peer_analysis
from prometheus.automatic_peers import enrich_automatic_peers
from prometheus.delivery_workflow import DeliveryWorkflow
from prometheus.editorial_gate import EditorialGate
from prometheus.pipeline import PrometheusEngine
from prometheus.reporting import generate_report
from prometheus.adapters import B3COTAHISTAdapter, CVMEnrichedAdapter, PointInTimeMarketSnapshotAdapter, YFinanceAdapter
from prometheus.issuer_registry import DEFAULT_CVM_CODES
from prometheus.instrument_catalog import InstrumentCatalog
from prometheus.peer_universe import benchmark_for_ticker
from prometheus.sector_models import MODELS
from prometheus.thesis_engine import WEIGHTS, calculate_score, get_state

DEFAULT_TICKER = "CURY3"
DEFAULT_INTERVAL_SECONDS = 60


def format_price(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"R$ {value:,.2f}".replace(".", ",")


def format_money(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"R$ {value:,.0f}".replace(".", ",")


def format_change(value: Optional[float], percent: Optional[float]) -> str:
    if value is None:
        return "N/A"
    direction = "+" if value >= 0 else ""
    percent_text = "N/A" if percent is None else f"{percent:.2f}%"
    return f"{direction}{value:.2f} ({percent_text})"


def format_field(field: Dict[str, Any]) -> str:
    raw = field.get("raw")
    normalized = field.get("normalized")
    unit = field.get("unit") or "UNKNOWN"
    status = field.get("status") or "UNKNOWN"
    semantic_status = field.get("semantic_status") or "UNKNOWN"
    source = field.get("source") or "UNKNOWN"
    source_field = field.get("field") or "UNKNOWN"

    normalized_text = "N/A" if normalized is None else normalized
    raw_text = "N/A" if raw is None else raw

    return (
        f"Raw: {raw_text}\n"
        f"Normalized: {normalized_text}\n"
        f"Unit: {unit}\n"
        f"Status: {status}\n"
        f"Semantic Status: {semantic_status}\n"
        f"Source: {source}\n"
        f"Field: {source_field}"
    )


def print_section(title: str) -> None:
    print("\n---\n")
    print(f"## {title}")


def print_data_quality_analysis(fundamental_data: Dict[str, Any], quality_score: float) -> None:
    print_section("DATA QUALITY")
    print(f"Data Quality Score: {quality_score:.2f}/100")
    for label, key in [
        ("Revenue Growth", "revenue_growth"),
        ("Earnings Growth", "earnings_growth"),
        ("Profit Margin", "profit_margin"),
        ("ROE", "roe"),
        ("Debt / Equity", "debt_to_equity"),
    ]:
        print(f"\n{label}:")
        print(format_field(fundamental_data.get(key, {})))


def print_fundamental_analysis(fundamental_data: Dict[str, Any], score: float) -> None:
    print_section("FUNDAMENTAL ANALYSIS")
    print(f"Revenue Growth: {format_field(fundamental_data.get('revenue_growth', {}))}")
    print(f"Earnings Growth: {format_field(fundamental_data.get('earnings_growth', {}))}")
    print(f"Profit Margin: {format_field(fundamental_data.get('profit_margin', {}))}")
    print(f"ROE: {format_field(fundamental_data.get('roe', {}))}")
    print(f"Debt / Equity: {format_field(fundamental_data.get('debt_to_equity', {}))}")
    print(f"\nFUNDAMENTAL SCORE: {score:.2f}/100")


def print_market_profile(asset_data: Dict[str, Any]) -> None:
    print_section("MARKET PROFILE")
    print(f"Asset: {asset_data['ticker']}")
    print(f"Sector: {asset_data['sector_name']} | Industry: {asset_data['industry_name']}")
    print(f"Price: {format_price(asset_data['price'])}")
    print(f"Previous Close: {format_price(asset_data.get('previous_close'))}")
    print(f"Price Change: {format_change(asset_data.get('price_change'), asset_data.get('price_change_percent'))}")
    print(f"Market Cap: {format_money(asset_data.get('market_cap'))}")
    print(f"Beta: {asset_data.get('beta') or 'N/A'}")
    if asset_data.get('business_summary'):
        summary = asset_data['business_summary']
        print(f"Summary: {summary[:320]}{'...' if len(summary) > 320 else ''}")


def print_component_scores(scores: Dict[str, float]) -> None:
    print_section("COMPONENT SCORES")
    for key, weight in WEIGHTS.items():
        value = scores.get(key, 0)
        print(f"{key.replace('_', ' ').title()} ({weight * 100:.0f}%): {value}")


def load_tickers_from_file(path: str) -> List[str]:
    candidates: List[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            sanitized = line.strip()
            if sanitized and not sanitized.startswith("#"):
                candidates.append(validate_ticker(sanitized))
    return candidates


def save_knowledge(store: KnowledgeStore, destination: Optional[str]) -> None:
    if not destination:
        return
    store.save_to_file(destination)
    print(f"Knowledge store saved to: {destination}")


def dump_report(report: Dict[str, Any], destination: Optional[str]) -> None:
    if not destination:
        return
    directory = os.path.dirname(destination)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"Report saved to: {destination}")


def build_collection_failure_report(
    tickers: Iterable[str], as_of: Optional[datetime.datetime], failures: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Return an explicit diagnostic, never a research snapshot, when collection fails.

    A zero-ticker output used to resemble a valid empty report to downstream
    tooling.  This payload is intentionally schema-distinct and cannot be
    mistaken for a deliverable research artifact.
    """
    return {
        "schema": "prometheus.collection_failure.v1",
        "status": "DATA_COLLECTION_FAILED",
        "requested_tickers": list(tickers),
        "analysis_as_of": as_of.replace(microsecond=0).isoformat() + "Z" if as_of else None,
        "data_source_status": "UNAVAILABLE",
        "failures": failures,
        "deliverable": False,
        "generated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PROMETHEUS - fundamental asset score, news sentiment, and continuous feed for B3 tickers."
    )
    parser.add_argument("--ticker", type=str, default=DEFAULT_TICKER, help="Ticker to evaluate")
    parser.add_argument("--tickers", nargs="+", help="Multiple tickers to evaluate or multicenario backtest")
    parser.add_argument("--tickers-file", type=str, help="Path to a file containing a list of tickers")
    parser.add_argument("--news", action="store_true", help="Collect news sentiment for tickers")
    parser.add_argument("--continuous", action="store_true", help="Run continuous feed for selected tickers")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS, help="Interval in seconds for continuous feed")
    parser.add_argument("--iterations", type=int, default=0, help="Stop after this many continuous cycles (0 = infinite)")
    parser.add_argument("--save-knowledge", type=str, help="Save collected knowledge or news to a JSON file")
    parser.add_argument("--load-knowledge", type=str, help="Load existing knowledge or news from a JSON file")
    parser.add_argument("--journal-output", type=str, help="Save decision journal entries to a JSON file")
    parser.add_argument("--replay-save", type=str, help="Save replayable asset sessions to a JSON file")
    parser.add_argument("--replay-load", type=str, help="Load a saved replay file for summary or analysis")
    parser.add_argument("--replay-summary", action="store_true", help="Print a summary of a loaded replay file")
    parser.add_argument("--backtest", type=str, help="Run a historical point-in-time backtest for a ticker")
    parser.add_argument("--start", type=str, help="Backtest start date in YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="Backtest end date in YYYY-MM-DD")
    parser.add_argument("--horizon", type=int, default=30, help="Backtest horizon in days")
    parser.add_argument("--horizons", nargs="+", type=int, help="Multiple horizons to evaluate in a multicenario run")
    parser.add_argument("--benchmark", type=str, help="Optional benchmark ticker for backtest comparison")
    parser.add_argument(
        "--backtest-model",
        choices=("prometheus", "momentum-baseline"),
        default="prometheus",
        help="Signal model used by backtest; defaults to the full point-in-time Prometheus pipeline",
    )
    parser.add_argument("--report-json", type=str, help="Save final asset report as JSON")
    parser.add_argument("--report-pdf", type=str, help="Directory to save generated PDF reports for each evaluated ticker")
    parser.add_argument("--as-of", type=str, help="Point-in-time cutoff for research in YYYY-MM-DD format")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")
    parser.add_argument("--cache-dir", type=str, default=".cache/prometheus", help="Cache directory for CVM and market datasets")
    parser.add_argument("--cvm-map", type=str, help="Optional JSON file mapping B3 tickers to validated CVM codes")
    parser.add_argument("--instrument-catalog", type=str, help="Versioned ticker/CVM/CNPJ catalog with integrity hash; preferred for broad B3 coverage")
    parser.add_argument("--market-snapshot", type=str, help="Audited point-in-time market observations JSON for deterministic/offline generation")
    parser.add_argument("--b3-cotahist", type=str, help="Official B3 COTAHIST annual ZIP used to derive point-in-time closes")
    parser.add_argument(
        "--allow-secondary-fundamentals",
        action="store_true",
        help="Use provider fundamentals instead of official CVM filings (explicit opt-out)",
    )
    parser.add_argument("--skip-auto-peers", action="store_true", help="Skip maintained same-sector peer enrichment")
    parser.add_argument("--reviewer", type=str, help="Named human reviewer approving a blocker-free PDF")
    parser.add_argument("--approval-notes", type=str, default="", help="Notes recorded with editorial approval")
    parser.add_argument(
        "--conflict-declaration", type=str, default="",
        help="Required reviewer conflict-of-interest declaration for approval",
    )
    parser.add_argument("--require-deliverable", action="store_true", help="Fail if the generated PDF is not approved for delivery")
    parser.add_argument("--order-ledger", type=str, help="Append-only JSONL commercial order ledger")
    parser.add_argument("--client-reference", type=str, default="INTERNAL", help="Non-sensitive client/order reference")
    parser.add_argument(
        "--workflow-action", choices=("review", "approve", "deliver", "correct", "reject", "regenerate", "verify"),
        help="Operate an existing commercial order without regenerating research",
    )
    parser.add_argument("--order-id", type=str, help="Existing order id for --workflow-action")
    parser.add_argument("--actor", type=str, help="Named person performing --workflow-action")
    parser.add_argument("--workflow-notes", type=str, default="", help="Review, approval, delivery, rejection or correction record")
    parser.add_argument("--artifacts", nargs="+", help="Current-version artifacts for workflow regeneration")
    return parser.parse_args()


def load_cvm_codes(mapping_path: Optional[str], catalog_path: Optional[str] = None) -> Dict[str, str]:
    # An explicit catalog is authoritative. Merging embedded defaults would
    # silently re-enable instruments rejected by the current point-in-time gate.
    cvm_codes = InstrumentCatalog.load(catalog_path).mapping() if catalog_path else dict(DEFAULT_CVM_CODES)
    if mapping_path:
        with open(mapping_path, "r", encoding="utf-8") as handle:
            configured_codes = json.load(handle)
        if not isinstance(configured_codes, dict):
            raise ValueError("CVM map must be a JSON object")
        cvm_codes.update({str(key).strip().upper(): str(value) for key, value in configured_codes.items()})
    return cvm_codes


def build_data_adapter(args: argparse.Namespace, tickers: List[str]):
    cvm_codes = load_cvm_codes(args.cvm_map, getattr(args, "instrument_catalog", None))
    if args.allow_secondary_fundamentals:
        logging.warning("Using secondary provider fundamentals by explicit request.")
        return YFinanceAdapter(cache_dir=args.cache_dir)
    missing_codes = [ticker for ticker in tickers if ticker not in cvm_codes]
    if missing_codes:
        raise ValueError(
            "Missing validated CVM issuer codes for: " + ", ".join(missing_codes)
            + ". Supply --cvm-map or explicitly use --allow-secondary-fundamentals."
        )
    market_adapter = None
    if getattr(args, "market_snapshot", None) and getattr(args, "b3_cotahist", None):
        raise ValueError("Use either --market-snapshot or --b3-cotahist, not both")
    if getattr(args, "market_snapshot", None):
        with open(args.market_snapshot, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        snapshots = payload.get("snapshots") if isinstance(payload, dict) and "snapshots" in payload else payload
        if not isinstance(snapshots, dict):
            raise ValueError("Market snapshot must be an object keyed by ticker")
        market_adapter = PointInTimeMarketSnapshotAdapter(snapshots)
    elif getattr(args, "b3_cotahist", None):
        benchmark_tickers = {model.benchmark for model in MODELS if model.benchmark}
        market_adapter = B3COTAHISTAdapter(
            args.b3_cotahist, tickers=[*cvm_codes.keys(), *sorted(benchmark_tickers)],
        )
    return CVMEnrichedAdapter(cvm_codes=cvm_codes, cache_dir=args.cache_dir, logger=logging.getLogger("prometheus"), market_adapter=market_adapter)


def run_workflow_action(
    ledger_path: str, order_id: str, action: str, actor: Optional[str] = None,
    notes: str = "", artifacts: Optional[List[str]] = None,
    conflict_declaration: str = "",
) -> Dict[str, Any]:
    if not ledger_path:
        raise ValueError("--order-ledger is required for --workflow-action")
    if not order_id:
        raise ValueError("--order-id is required for --workflow-action")
    workflow = DeliveryWorkflow(ledger_path)
    if action == "verify":
        order = workflow.latest(order_id)
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        return {
            "ledger": workflow.verify_ledger(),
            "order_id": order_id, "state": order.get("state"), "version": order.get("version"),
            "artifacts": workflow.verify_artifacts(order, current_version_only=True),
            "release_bundle": workflow.verify_release_bundle(order),
        }
    order = workflow.latest(order_id)
    if not order:
        raise ValueError(f"Order not found: {order_id}")
    target_by_action = {
        "review": "IN_REVIEW", "approve": "APPROVED", "deliver": "DELIVERED",
        "reject": "REJECTED", "regenerate": "GENERATED",
    }
    if action == "correct":
        return workflow.request_correction(order, actor or "", notes)
    return workflow.transition(
        order, target_by_action[action], actor or "", notes, artifacts=artifacts,
        conflict_declaration=conflict_declaration,
    )


def _synchronize_pdf_snapshot(result: Dict[str, Any], pdf_result: Dict[str, Any]) -> Dict[str, Any]:
    """Make CLI JSON and downstream workflow use the exact PDF input snapshot."""
    snapshot = pdf_result.get("report")
    if not isinstance(snapshot, dict):
        raise ValueError("PDF result is missing its audited report snapshot")
    result["report"] = snapshot
    return snapshot


def run_news_collection(tickers: List[str], store: KnowledgeStore) -> Tuple[Dict[str, float], Dict[str, List[Dict[str, Any]]]]:
    news = NewsFeed(tickers, store)
    records = news.collect_once()
    sentiment_by_ticker: Dict[str, List[float]] = {}
    items_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        ticker = record.get('ticker', 'UNKNOWN')
        score = record.get('sentiment_score')
        items_by_ticker.setdefault(ticker, []).append(record)
        if isinstance(score, (int, float)):
            sentiment_by_ticker.setdefault(ticker, []).append(float(score))

    averages: Dict[str, float] = {}
    for ticker in tickers:
        scores = sentiment_by_ticker.get(ticker, [])
        if not scores:
            averages[ticker] = 50.0
        else:
            averages[ticker] = round(sum(scores) / len(scores), 2)

    return averages, items_by_ticker


def run_continuous_feed(
    tickers: List[str],
    interval_seconds: int,
    iterations: int,
    save_destination: Optional[str],
    store: KnowledgeStore,
    engine: PrometheusEngine,
    replay_save: Optional[str] = None,
) -> None:
    feed = ContinuousFeed(
        tickers=tickers,
        data_engine=lambda ticker: engine.evaluate(ticker)["report"],
        knowledge_store=store,
        interval_seconds=interval_seconds,
    )
    try:
        feed.start(iterations=iterations)
    except KeyboardInterrupt:
        print("\nContinuous feed interrupted by user.")
    finally:
        save_knowledge(store, save_destination)
        if replay_save:
            engine.save_replay(replay_save)


def print_ticker_report(
    ticker: str,
    asset_data: Dict[str, Any],
    sentiment_score: float,
    score: float,
    state: str,
) -> None:
    print("# ========================================")
    print(f"PROMETHEUS REPORT FOR {ticker}")
    print("# ========================================")
    print_market_profile(asset_data)
    print_data_quality_analysis(asset_data["fundamental_data"], asset_data["fundamental_data_quality"]["score"])
    print_fundamental_analysis(asset_data["fundamental_data"], asset_data["fundamental_score"])
    print_component_scores({
        "fundamental": asset_data["fundamental_score"],
        "sector": asset_data["sector"],
        "macro": asset_data["macro"],
        "expectation_gap": asset_data["expectation_gap"],
        "momentum_velocity": asset_data["momentum_velocity"],
        "valuation_margin": asset_data["valuation_margin"],
        "news_sentiment": sentiment_score,
    })
    print_section("THESIS")
    print(f"News Sentiment Score: {sentiment_score}")
    print(f"THESIS SCORE: {score}")
    print(f"STATE: {state}")


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if not args.quiet else logging.WARNING,
        format="[%(levelname)s] %(message)s",
    )

    if args.workflow_action:
        result = run_workflow_action(
            args.order_ledger, args.order_id, args.workflow_action,
            actor=args.actor, notes=args.workflow_notes, artifacts=args.artifacts,
            conflict_declaration=args.conflict_declaration,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.require_deliverable:
        raise ValueError(
            "Generation always creates a draft. Use --order-ledger, then the separate "
            "review/approve/deliver actions; verify the delivered order with --workflow-action verify."
        )
    if args.order_ledger and args.reviewer:
        raise ValueError(
            "Commercial generation cannot approve its own output. Generate the draft, then use "
            "--workflow-action review and --workflow-action approve."
        )
    if args.order_ledger and not args.report_pdf:
        raise ValueError("--order-ledger requires --report-pdf so the reviewed PDF and release bundle can be hashed")

    is_multiticker_backtest = bool(args.tickers and (args.start or args.end or args.horizons))
    if args.backtest or is_multiticker_backtest:
        if not args.start or not args.end:
            logging.error("Para rodar backtest real, informe --start e --end em YYYY-MM-DD.")
            return

        assets = [args.backtest] if args.backtest else [validate_ticker(item) for item in args.tickers]
        if args.backtest_model == "prometheus":
            try:
                backtest_adapter = build_data_adapter(args, assets)
            except Exception as error:
                logging.error(str(error))
                raise SystemExit(2) from error
            if isinstance(backtest_adapter, CVMEnrichedAdapter):
                backtest_adapter.backtest_mode = True
            backtest_pipeline = PrometheusEngine(adapter=backtest_adapter)
            backtest_engine = BacktestEngine(
                signal_provider=PrometheusPointInTimeSignalProvider(backtest_pipeline),
                history_provider=getattr(backtest_adapter.market, "history", None),
                cache_dir=args.cache_dir,
            )
        else:
            backtest_engine = BacktestEngine(cache_dir=args.cache_dir)

        if args.horizons:
            result = backtest_engine.run_multicenario(
                tickers=assets,
                start_date=args.start,
                end_date=args.end,
                horizons=args.horizons,
                benchmark_ticker=args.benchmark,
            )
        else:
            if args.backtest:
                auto_benchmark = args.benchmark or benchmark_for_ticker(args.backtest)
                result = backtest_engine.run(
                    args.backtest,
                    args.start,
                    args.end,
                    horizon_days=args.horizon,
                    benchmark_ticker=auto_benchmark,
                )
            else:
                result = backtest_engine.run_multicenario(
                    tickers=assets,
                    start_date=args.start,
                    end_date=args.end,
                    horizons=[args.horizon],
                    benchmark_ticker=args.benchmark,
                )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.report_json:
            dump_report(result, args.report_json)
        return

    tickers: List[str] = [validate_ticker(args.ticker)]
    if args.tickers:
        tickers = [validate_ticker(item) for item in args.tickers]
    elif args.tickers_file:
        tickers = load_tickers_from_file(args.tickers_file)

    if not tickers:
        logging.error("Nenhum ticker válido foi informado.")
        return

    store = KnowledgeStore()
    if args.load_knowledge:
        try:
            store.load_from_file(args.load_knowledge)
            logging.info(f"Loaded existing knowledge from {args.load_knowledge}")
        except Exception as error:
            logging.warning(f"Unable to load knowledge: {error}")

    sentiment_scores: Dict[str, float] = {}
    news_items: Dict[str, List[Dict[str, Any]]] = {}
    if args.news:
        sentiment_scores, news_items = run_news_collection(tickers, store)
        for ticker in tickers:
            logging.info(f"News sentiment for {ticker}: {sentiment_scores.get(ticker, 50.0)}")
        save_knowledge(store, args.save_knowledge)
        if not args.continuous:
            logging.info("News collection completed.")

    try:
        adapter = build_data_adapter(args, tickers)
    except Exception as error:
        logging.error(str(error))
        raise SystemExit(2) from error

    engine = PrometheusEngine(adapter=adapter, journal_path=args.journal_output)
    if args.replay_load:
        try:
            engine.load_replay(args.replay_load)
            logging.info(f"Loaded replay data from {args.replay_load}")
            if args.replay_summary:
                print(json.dumps(engine.replay_summary(), ensure_ascii=False, indent=2))
        except Exception as error:
            logging.warning(f"Unable to load replay file: {error}")

    if args.continuous:
        logging.info("Starting continuous feed. Press Ctrl+C to stop.")
        run_continuous_feed(
            tickers=tickers,
            interval_seconds=args.interval,
            iterations=args.iterations,
            save_destination=args.save_knowledge,
            store=store,
            engine=engine,
            replay_save=args.replay_save,
        )
        return

    report: Dict[str, Any] = {"tickers": []}
    as_of = None
    if args.as_of:
        try:
            as_of = datetime.datetime.strptime(args.as_of, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError as error:
            raise ValueError("--as-of must use YYYY-MM-DD format") from error
    evaluated: List[Tuple[str, float, Dict[str, Any]]] = []
    collection_failures: List[Dict[str, str]] = []
    for ticker in tickers:
        try:
            sentiment_score = 50.0
            if args.news:
                sentiment_score = sentiment_scores.get(ticker, 50.0)

            result = engine.evaluate(
                ticker,
                sentiment_score=sentiment_score,
                news_items=news_items.get(ticker, []),
                journal_metadata={"source": "cli"},
                as_of=as_of,
            )
            evaluated.append((ticker, sentiment_score, result))
        except Exception as error:
            logging.error(f"Failed to retrieve data for {ticker}: {error}")
            collection_failures.append({"ticker": ticker, "error_type": type(error).__name__, "detail": str(error)})
            continue

    if not evaluated:
        diagnostic = build_collection_failure_report(tickers, as_of, collection_failures)
        dump_report(diagnostic, args.report_json)
        logging.error("Nenhum ticker pôde ser coletado; diagnóstico não entregável foi registrado.")
        raise SystemExit(1)

    if not args.skip_auto_peers and hasattr(adapter, "market") and hasattr(adapter, "cvm"):
        peer_cutoff = as_of or datetime.datetime.utcnow()
        for _, _, result in evaluated:
            try:
                enrich_automatic_peers(result["report"], adapter, peer_cutoff)
            except Exception as error:
                logging.warning(f"Automatic peer enrichment failed: {error}")
        if as_of is None:
            live_cutoff = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            for _, _, result in evaluated:
                result["report"]["analysis_as_of"] = live_cutoff
                result["report"]["editorial_gate"] = EditorialGate().evaluate(result["report"])
    enrich_peer_analysis([item[2]["report"] for item in evaluated])

    for ticker, sentiment_score, result in evaluated:
        asset_data = result["report"]
        score = result["overall_score"]
        state = result["state"]

        if not args.quiet:
            print_ticker_report(ticker, asset_data, sentiment_score, score, state)

        pdf_metadata = None
        order = None
        workflow = DeliveryWorkflow(args.order_ledger) if args.order_ledger else None
        if workflow:
            report_cutoff = str(asset_data.get("analysis_as_of") or "")[:10]
            order = workflow.create_order(ticker, args.client_reference, report_cutoff)
        if args.report_pdf:
            try:
                pdf_result = generate_report(
                    ticker, output_dir=args.report_pdf, report_data=asset_data,
                    reviewer=args.reviewer if not workflow else None,
                    approval_notes=args.approval_notes,
                    conflict_declaration=args.conflict_declaration,
                )
                # The JSON, PDF and commercial release bundle must describe the
                # exact same post-QA snapshot. ``generate_report`` deep-copies
                # its input before adding QA, score reconciliation and the live
                # editorial gate, so replace the pre-PDF object here.
                asset_data = _synchronize_pdf_snapshot(result, pdf_result)
                pdf_metadata = pdf_result["metadata"]
                if workflow and order:
                    bundle_path = workflow.write_release_bundle(
                        order, pdf_result["report"], pdf_metadata["report_path"], pdf_metadata,
                    )
                    order = workflow.transition(
                        order, "GENERATED", "prometheus",
                        artifacts=[pdf_metadata["report_path"], bundle_path],
                    )
                print(f"PDF generated for {ticker}: {pdf_metadata['report_path']}")
            except Exception as error:
                logging.warning(f"Unable to generate PDF for {ticker}: {error}")
                if args.require_deliverable:
                    raise

        report["tickers"].append({
            "ticker": ticker,
            "score": score,
            "state": state,
            "component_scores": result["scores"],
            "sentiment_score": sentiment_score,
            "decision": result["decision_result"].action,
            "journal_point_in_time": result["journal_entry"]["point_in_time"],
            "pdf_report": pdf_metadata,
            "order": order,
            "analysis": asset_data,
        })

    dump_report(report, args.report_json)

    if args.save_knowledge:
        save_knowledge(store, args.save_knowledge)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        logging.error(str(error))
        raise SystemExit(2) from None
