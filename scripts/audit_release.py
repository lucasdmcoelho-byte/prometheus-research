from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACKAGE_VERSION = str(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
DEFAULT_VALIDATION_ROOT = Path("tmp/rc2_validation/multisector")
DEFAULT_RELEASE_MANIFEST = Path("dist/release_current_a") / f"prometheus-research-{PACKAGE_VERSION}-manifest.json"
DEFAULT_REPRO_MANIFEST = Path("dist/release_current_b") / f"prometheus-research-{PACKAGE_VERSION}-manifest.json"
DEFAULT_REPORT_SPECS = (
    f"ITUB4|{DEFAULT_VALIDATION_ROOT / 'itub4.json'}|{DEFAULT_VALIDATION_ROOT / 'pdf' / 'ITUB4_prometheus_report_20260817.pdf'}",
    f"EGIE3|{DEFAULT_VALIDATION_ROOT / 'egie3.json'}|{DEFAULT_VALIDATION_ROOT / 'pdf' / 'EGIE3_prometheus_report_20260817.pdf'}",
    f"CURY3|{DEFAULT_VALIDATION_ROOT / 'cury3.json'}|{DEFAULT_VALIDATION_ROOT / 'pdf' / 'CURY3_prometheus_report_20260817.pdf'}",
)

from prometheus.delivery_workflow import DeliveryWorkflow
from prometheus.editorial_gate import EditorialGate
from prometheus.evidence_engine import EvidenceEngine

def _date(value: Any):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _latest_orders(ledger: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not ledger.is_file():
        return result
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            result[item["order_id"]] = item
    return result


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file():
        return {}, [f"{label} missing: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {}, [f"{label} invalid: {type(error).__name__}"]
    return payload if isinstance(payload, dict) else {}, ([] if isinstance(payload, dict) else [f"{label} must be a JSON object"])


def audit_report(json_path: Path, pdf_path: Path, expected_ticker: str | None = None) -> dict[str, Any]:
    payload, load_failures = _load_json(json_path, "report JSON")
    if load_failures:
        return {
            "ticker": expected_ticker, "status": "FAIL", "failures": load_failures,
            "pdf_pages": 0, "pdf_sha256": None, "json_sha256": None,
        }
    if len(payload.get("tickers") or []) != 1:
        return {"ticker": expected_ticker, "status": "FAIL", "failures": ["JSON must contain exactly one ticker"]}
    item = payload["tickers"][0]
    report = item.get("analysis") or {}
    cutoff = _date(report.get("analysis_as_of"))
    failures: list[str] = []
    if expected_ticker and str(item.get("ticker") or "").upper() != expected_ticker.upper():
        failures.append(f"ticker mismatch: expected {expected_ticker}, found {item.get('ticker')}")
    if not cutoff:
        failures.append("analysis_as_of missing or invalid")
    for source in ((report.get("research") or {}).get("sources") or []):
        available = _date(source.get("publication_date"))
        if cutoff and available and available > cutoff:
            failures.append(f"look-ahead source: {source.get('metric')} {available}")
        if isinstance(source.get("value"), (int, float)):
            for field in ("unit", "period", "publication_date", "source"):
                if not source.get(field):
                    failures.append(f"numeric source missing {field}: {source.get('metric')}")
    for claim in report.get("claims") or []:
        kind = claim.get("classification")
        if kind == "CALCULATION" and not claim.get("formula"):
            failures.append(f"calculation without formula: {claim.get('claim_id')}")
        if kind == "ESTIMATE" and not claim.get("assumptions"):
            failures.append(f"estimate without assumptions: {claim.get('claim_id')}")
        if kind == "FACT" and not claim.get("source_ids"):
            failures.append(f"fact without source: {claim.get('claim_id')}")
    evidence_audit = EvidenceEngine().audit_claims(
        report.get("claims") or [],
        sources=((report.get("research") or {}).get("sources") or []),
        cutoff=report.get("analysis_as_of"),
    )
    failures.extend(f"claim audit: {item['claim_id']} {item['reason']}" for item in evidence_audit["issues"])
    valuation = report.get("valuation") or {}
    if valuation.get("status") == "AVAILABLE":
        if not valuation.get("scenarios") or not valuation.get("assumptions"):
            failures.append("available valuation without scenarios/assumptions")
    stored_gate = report.get("editorial_gate") or {}
    live_gate = EditorialGate().evaluate(report)
    if live_gate.get("blockers"):
        failures.extend(
            f"live editorial blocker: {item.get('code')} {item.get('detail')}"
            for item in live_gate.get("blockers") or []
        )
    stored_codes = sorted(item.get("code") for item in stored_gate.get("blockers") or [])
    live_codes = sorted(item.get("code") for item in live_gate.get("blockers") or [])
    if stored_codes != live_codes:
        failures.append(f"stored editorial gate is stale: stored={stored_codes} live={live_codes}")
    metadata = item.get("pdf_report") or {}
    if metadata.get("editorial_status") not in {"APPROVAL_REQUIRED", "APPROVED"}:
        failures.append("PDF content is not eligible for human approval")
    if metadata.get("qa_status") not in {"pass", "warning"}:
        failures.append("PDF QA failed")
    if not pdf_path.is_file():
        failures.append("PDF missing")
        pages = 0
    else:
        # ReportLab emits an unambiguous /Type /Page token for every page.
        # Keeping this check dependency-free makes the release auditor runnable
        # before optional PDF tooling is installed.
        pages = len(re.findall(rb"/Type\s*/Page\b", pdf_path.read_bytes()))
        if pages < 8:
            failures.append("PDF unexpectedly short")
    return {
        "ticker": item.get("ticker"),
        "sector_key": (report.get("sector_model") or {}).get("key"),
        "status": "PASS" if not failures else "FAIL",
        "failures": sorted(set(failures)),
        "analysis_as_of": report.get("analysis_as_of"),
        "source_count": len(((report.get("research") or {}).get("sources") or [])),
        "claim_count": len(report.get("claims") or []),
        "live_editorial_status": live_gate.get("status"),
        "valuation_status": valuation.get("status"),
        "pdf_pages": pages,
        "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest() if pdf_path.is_file() else None,
        "json_sha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
    }


def audit_report_portfolio(reports: list[dict[str, Any]], minimum: int = 3) -> dict[str, Any]:
    passing = [item for item in reports if item.get("status") == "PASS"]
    tickers = {str(item.get("ticker") or "").upper() for item in passing if item.get("ticker")}
    sectors = {str(item.get("sector_key") or "") for item in passing if item.get("sector_key")}
    failures: list[str] = []
    if len(passing) < minimum:
        failures.append(f"at least {minimum} passing current reports required; found {len(passing)}")
    if len(tickers) < minimum:
        failures.append(f"at least {minimum} distinct tickers required; found {len(tickers)}")
    if len(sectors) < minimum:
        failures.append(f"at least {minimum} distinct sector models required; found {len(sectors)}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "minimum_required": minimum,
        "passing_report_count": len(passing),
        "distinct_tickers": sorted(tickers),
        "distinct_sector_models": sorted(sectors),
        "failures": failures,
    }


def audit_release_manifests(primary_path: Path, reproducibility_path: Path) -> dict[str, Any]:
    primary, failures = _load_json(primary_path, "release manifest A")
    reproducibility, second_failures = _load_json(reproducibility_path, "release manifest B")
    failures.extend(second_failures)
    verified_artifacts: dict[str, str] = {}
    if not failures:
        if primary.get("version") != reproducibility.get("version"):
            failures.append("release versions differ")
        first_artifacts = {item.get("path"): item for item in primary.get("artifacts") or []}
        second_artifacts = {item.get("path"): item for item in reproducibility.get("artifacts") or []}
        if set(first_artifacts) != set(second_artifacts) or not first_artifacts:
            failures.append("release artifact sets differ or are empty")
        for name, declared in first_artifacts.items():
            first_file = primary_path.parent / str(name)
            second_file = reproducibility_path.parent / str(name)
            first_hash = hashlib.sha256(first_file.read_bytes()).hexdigest() if first_file.is_file() else None
            second_hash = hashlib.sha256(second_file.read_bytes()).hexdigest() if second_file.is_file() else None
            expected = declared.get("sha256")
            if first_hash != expected:
                failures.append(f"manifest A artifact mismatch: {name}")
            if second_hash != (second_artifacts.get(name) or {}).get("sha256"):
                failures.append(f"manifest B artifact mismatch: {name}")
            if first_hash != second_hash:
                failures.append(f"non-reproducible artifact: {name}")
            if first_hash:
                verified_artifacts[str(name)] = first_hash
        if primary.get("source_files") != reproducibility.get("source_files"):
            failures.append("source file manifests differ")
    return {
        "status": "PASS" if not failures else "FAIL",
        "version": primary.get("version"), "release_stage": primary.get("release_stage"),
        "verified_artifacts": verified_artifacts, "failures": sorted(set(failures)),
    }


def audit_rad_validation(json_path: Path, cache_dir: Path) -> dict[str, Any]:
    failures: list[str] = []
    if not json_path.is_file():
        return {"status": "FAIL", "failures": ["RAD validation JSON missing"]}
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    try:
        report = payload["tickers"][0]["analysis"]
    except (KeyError, IndexError, TypeError):
        return {"status": "FAIL", "failures": ["RAD validation JSON structure invalid"]}
    cutoff = _date(report.get("analysis_as_of"))
    ttm = report.get("ttm") or {}
    if ttm.get("status") != "AVAILABLE":
        failures.append("RAD TTM is not AVAILABLE")
    if ttm.get("method") != "rolling_twelve_months" or ttm.get("formula") != "current YTD + prior FY - prior YTD":
        failures.append("RAD TTM method/formula mismatch")
    if ((ttm.get("metrics") or {}).get("revenue") or {}).get("normalized") != 13_255_663_000.0:
        failures.append("EGIE3 RAD TTM revenue reconciliation mismatch")
    source_rows = []
    for metric in (ttm.get("metrics") or {}).values():
        source_rows.extend(metric.get("source_rows") or [])
    protocols = {row.get("protocol") for row in source_rows if row.get("protocol")}
    if "017329DFP311220250200155137-61" not in protocols:
        failures.append("ENGIE DFP v2 protocol missing")
    retained_raw_hashes = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in list(cache_dir.glob("*.zip")) + list(cache_dir.glob("rad/*/*.html"))
        if path.is_file()
    }
    matched_raw_hashes: set[str] = set()
    for row in source_rows:
        publication = _date(row.get("received_at"))
        if cutoff and publication and publication > cutoff:
            failures.append(f"RAD TTM look-ahead: {row.get('statement')} {publication}")
        digest = row.get("source_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            failures.append(f"RAD TTM source hash missing: {row.get('statement')} {row.get('reference_date')}")
        elif digest not in retained_raw_hashes:
            failures.append(f"RAD TTM source hash has no retained raw artifact: {digest}")
        else:
            matched_raw_hashes.add(digest)
    gate = report.get("editorial_gate") or {}
    blocker_codes = {item.get("code") for item in gate.get("blockers") or []}
    if gate.get("status") != "BLOCKED" or blocker_codes != {"VALUATION_INCOMPLETE"}:
        failures.append("RAD validation did not stop solely at incomplete valuation")
    if (gate.get("claim_audit") or {}).get("status") != "PASS":
        failures.append("RAD validation claim audit failed")
    sources = {(item.get("metric"), item.get("source_type"), item.get("formula")) for item in (report.get("research") or {}).get("sources") or []}
    if not any(metric == "revenue_growth" and kind == "calculated" and formula for metric, kind, formula in sources):
        failures.append("derived CVM metric lacks calculation classification/formula")
    if not any(metric == "operating_cash_flow" and kind == "primary" for metric, kind, _ in sources):
        failures.append("reported CVM cash flow is not classified as primary")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failures": sorted(set(failures)),
        "ticker": report.get("ticker"),
        "analysis_as_of": report.get("analysis_as_of"),
        "ttm_revenue_brl": ((ttm.get("metrics") or {}).get("revenue") or {}).get("normalized"),
        "protocols": sorted(protocols),
        "source_row_count": len(source_rows),
        "required_raw_artifact_hash_count": len({row.get("source_sha256") for row in source_rows if row.get("source_sha256")}),
        "matched_raw_artifact_hash_count": len(matched_raw_hashes),
        "editorial_blockers": sorted(blocker_codes),
        "json_sha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit PROMETHEUS commercial release artifacts")
    parser.add_argument("--root", default=str(DEFAULT_VALIDATION_ROOT))
    parser.add_argument("--ledger", default=str(DEFAULT_VALIDATION_ROOT / "orders.jsonl"))
    parser.add_argument("--coverage", default="tmp/e2e/coverage_validation.json")
    parser.add_argument("--instrument-catalog-audit", default="tmp/e2e/instrument_catalog_audit.json")
    parser.add_argument("--backtest", default="validation/backtest_20260824.json")
    parser.add_argument("--rad-validation", default="tmp/e2e/egie/rad_ttm_validation_v3.json")
    parser.add_argument("--cvm-cache", default="tmp/cvm")
    parser.add_argument("--output", default="validation/release_audit_current.json")
    parser.add_argument(
        "--report", action="append",
        help="Report triplet TICKER|path/to/report.json|path/to/report.pdf; repeat for each sector",
    )
    parser.add_argument("--release-manifest", default=str(DEFAULT_RELEASE_MANIFEST))
    parser.add_argument("--repro-manifest", default=str(DEFAULT_REPRO_MANIFEST))
    args = parser.parse_args()
    root = Path(args.root)
    reports = []
    report_specs = args.report or list(DEFAULT_REPORT_SPECS)
    for spec in report_specs:
        parts = str(spec).split("|", 2)
        if len(parts) != 3:
            reports.append({"status": "FAIL", "failures": [f"invalid --report specification: {spec}"]})
            continue
        ticker, json_name, pdf_name = parts
        reports.append(audit_report(Path(json_name), Path(pdf_name), expected_ticker=ticker))
    report_portfolio = audit_report_portfolio(reports)
    ledger_path = Path(args.ledger)
    workflow = DeliveryWorkflow(str(ledger_path))
    ledger_audit = workflow.verify_ledger()
    orders = list(_latest_orders(ledger_path).values())
    order_failures = list(ledger_audit.get("failures") or [])
    if not ledger_path.is_file():
        order_failures.append("commercial ledger missing")
    if not orders:
        order_failures.append("commercial ledger has no orders")
    for order in orders:
        if order.get("state") != "DELIVERED":
            order_failures.append(f"{order.get('order_id')} not delivered")
        verification = workflow.verify_artifacts(order, current_version_only=True)
        order_failures.extend(f"artifact verification: {item}" for item in verification.get("failures") or [])
        bundle_verification = workflow.verify_release_bundle(order)
        order_failures.extend(f"bundle verification: {item}" for item in bundle_verification.get("failures") or [])
    for report_item in reports:
        if report_item.get("ticker") and report_item.get("analysis_as_of"):
            report_cutoff = str(report_item["analysis_as_of"])[:10]
            if not any(
                order.get("state") == "DELIVERED"
                and order.get("ticker") == report_item.get("ticker")
                and order.get("as_of") == report_cutoff
                for order in orders
            ):
                order_failures.append(f"no delivered order for {report_item.get('ticker')} at {report_cutoff}")
    coverage, coverage_failures = _load_json(Path(args.coverage), "coverage audit")
    catalog_audit, catalog_failures = _load_json(Path(args.instrument_catalog_audit), "instrument catalog audit")
    backtest, backtest_failures = _load_json(Path(args.backtest), "backtest")
    backtest_metrics = backtest.get("metrics") or {}
    independent_metrics = backtest_metrics.get("non_overlapping") or {}
    rad_validation = audit_rad_validation(Path(args.rad_validation), Path(args.cvm_cache))
    release_build = audit_release_manifests(Path(args.release_manifest), Path(args.repro_manifest))
    backtest_ok = (
        not backtest_failures
        and backtest.get("status") == "OK"
        and backtest.get("model_name") == "PROMETHEUS_POINT_IN_TIME"
        and backtest_metrics.get("commercial_validation_status") == "PASS"
        and independent_metrics.get("statistical_status") == "SUFFICIENT_SAMPLE"
        and independent_metrics.get("hit_rate_ci_95") is not None
        and independent_metrics.get("benchmark_return") is not None
        and independent_metrics.get("excess_return_vs_benchmark") is not None
    )
    overall = (
        all(item["status"] == "PASS" for item in reports)
        and report_portfolio.get("status") == "PASS"
        and not order_failures
        and not coverage_failures and coverage.get("status") == "PASS"
        and not catalog_failures and catalog_audit.get("status") == "PASS"
        and backtest_ok
        and rad_validation.get("status") == "PASS"
        and release_build.get("status") == "PASS"
    )
    result = {
        "status": "PASS" if overall else "FAIL",
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "reports": reports,
        "report_portfolio": report_portfolio,
        "commercial_flow": {
            "status": "PASS" if not order_failures else "FAIL", "order_count": len(orders),
            "ledger_entries": ledger_audit.get("entry_count"), "ledger_head_hash": ledger_audit.get("head_hash"),
            "failures": sorted(set(order_failures)),
        },
        "coverage": {"status": "FAIL" if coverage_failures else coverage.get("status"), "validated_count": coverage.get("validated_count"), "instrument_count": coverage.get("instrument_count"), "failures": coverage_failures},
        "instrument_catalog": {
            "status": "FAIL" if catalog_failures else catalog_audit.get("status"),
            "instrument_count": catalog_audit.get("research_eligible_count", catalog_audit.get("instrument_count")),
            "all_exact_identity_count": catalog_audit.get("accepted_count", catalog_audit.get("instrument_count")),
            "non_research_eligible_count": catalog_audit.get("non_research_eligible_count", 0),
            "failure_count": len(catalog_audit.get("failures") or (catalog_audit.get("cvm_audit") or {}).get("failures") or []),
            "b3_equity_ticker_count": catalog_audit.get("b3_equity_ticker_count"), "failures": catalog_failures,
        },
        "backtest": {"status": "PASS" if backtest_ok else "FAIL", "model_name": backtest.get("model_name"), "metrics": backtest_metrics, "failures": backtest_failures},
        "rad_point_in_time": rad_validation,
        "release_build": release_build,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
