from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from prometheus.b3_cotahist import load_market_observations
from prometheus.cvm_sector_registry import CVMSectorRegistry


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _fca_index(registry: CVMSectorRegistry, first_year: int, last_year: int):
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    archives = []
    for year in range(first_year, last_year + 1):
        try:
            rows = registry._load_fca_year(year)
        except Exception as error:
            archives.append({"year": year, "status": "UNAVAILABLE", "reason": type(error).__name__})
            continue
        for row in rows:
            by_code[row["cvm_code"]].append(row)
        path = registry.cache_dir / f"fca_cia_aberta_{year}.zip"
        archives.append({
            "year": year,
            "status": "AVAILABLE",
            "path": str(path.resolve()),
            "sha256": _sha256(path),
            "row_count": len(rows),
        })
    for rows in by_code.values():
        rows.sort(key=lambda row: (row["received_at"], row["reference_date"], row["version"]))
    return by_code, archives


def _classification(rows: list[dict[str, Any]], cutoff: dt.datetime):
    eligible = [
        row for row in rows
        if row["received_at"] <= cutoff and row["reference_date"] <= cutoff.date() and row.get("sector")
    ]
    return eligible[-1] if eligible else None


def diagnose(args: argparse.Namespace) -> dict[str, Any]:
    catalog_path = Path(args.instrument_catalog)
    cotahist_path = Path(args.cotahist)
    cache_dir = Path(args.cache_dir)
    output_csv = Path(args.output_csv)
    output_json = Path(args.output_json)
    horizons = sorted({int(value) for value in args.horizons if int(value) > 0})

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    identities = {
        str(item["ticker"]).upper(): str(item["cvm_code"]).lstrip("0")
        for item in catalog.get("instruments") or []
        if item.get("research_eligible") and item.get("ticker") and item.get("cvm_code")
    }
    observations = load_market_observations(cotahist_path, tickers=identities)
    registry = CVMSectorRegistry(str(cache_dir), cache_ttl_seconds=10**12)
    years = [row["date"].year for rows in observations["records"].values() for row in rows]
    first_market_year, last_market_year = min(years), max(years)
    fca_by_code, archives = _fca_index(registry, max(2010, first_market_year - 2), last_market_year)

    snapshot_available_at = (
        dt.datetime.fromtimestamp(registry.path.stat().st_mtime)
        if registry.path and registry.path.is_file() else None
    )
    reason_counts = Counter()
    reason_counts_by_horizon: dict[int, Counter] = {horizon: Counter() for horizon in horizons}
    fca_status_counts = Counter()
    fca_status_by_horizon: dict[int, Counter] = {horizon: Counter() for horizon in horizons}
    window_counts = Counter()
    non_overlapping_counts = Counter()

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "ticker", "cvm_code", "horizon_days", "analysis_date", "future_date",
        "non_overlapping_candidate", "legacy_abstention_reasons",
        "fca_classification_status", "fca_sector", "fca_available_at",
        "fca_reference_date", "fca_version", "fca_document_id", "fca_source_sha256",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for ticker in sorted(identities):
            market_rows = (observations.get("records") or {}).get(ticker) or []
            dates = [row["date"] for row in market_rows]
            if not dates:
                continue
            cvm_code = identities[ticker]
            classifications = fca_by_code.get(cvm_code) or []
            for horizon in horizons:
                last_resolution = None
                for analysis_date in dates:
                    target = analysis_date + dt.timedelta(days=horizon)
                    future_index = bisect.bisect_left(dates, target)
                    if future_index >= len(dates):
                        continue
                    future_date = dates[future_index]
                    cutoff = dt.datetime.combine(analysis_date, dt.time(23, 59, 59))
                    legacy_reasons = []
                    if snapshot_available_at is None or snapshot_available_at > cutoff:
                        legacy_reasons.extend([
                            "SECTOR_CLASSIFICATION_UNAVAILABLE_POINT_IN_TIME",
                            "VALUATION_INCOMPLETE",
                        ])
                    for reason in legacy_reasons:
                        reason_counts[reason] += 1
                        reason_counts_by_horizon[horizon][reason] += 1
                    chosen = _classification(classifications, cutoff)
                    fca_status = "AVAILABLE" if chosen else "INSUFFICIENT_DATA"
                    fca_status_counts[fca_status] += 1
                    fca_status_by_horizon[horizon][fca_status] += 1
                    independent = last_resolution is None or analysis_date >= last_resolution
                    if independent:
                        last_resolution = future_date
                        non_overlapping_counts[horizon] += 1
                    window_counts[horizon] += 1
                    writer.writerow({
                        "ticker": ticker,
                        "cvm_code": cvm_code,
                        "horizon_days": horizon,
                        "analysis_date": analysis_date.isoformat(),
                        "future_date": future_date.isoformat(),
                        "non_overlapping_candidate": str(independent).lower(),
                        "legacy_abstention_reasons": "|".join(legacy_reasons),
                        "fca_classification_status": fca_status,
                        "fca_sector": chosen.get("sector") if chosen else None,
                        "fca_available_at": chosen["received_at"].isoformat() if chosen else None,
                        "fca_reference_date": chosen["reference_date"].isoformat() if chosen else None,
                        "fca_version": chosen.get("version") if chosen else None,
                        "fca_document_id": chosen.get("document_id") if chosen else None,
                        "fca_source_sha256": chosen.get("source_sha256") if chosen else None,
                    })

    total_windows = sum(window_counts.values())
    summary = {
        "schema": "prometheus.backtest_data_gap_diagnostic.v1",
        "generated_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "method": (
            "Exhaustive enumeration of every resolvable COTAHIST ticker/date/horizon window. "
            "Legacy reasons reproduce the pre-FCA resolver: a future daily-registry snapshot "
            "forces general sector, zero exact peers and therefore incomplete valuation. "
            "FCA coverage is measured from DT_RECEB, never Data_Referencia."
        ),
        "limitations": [
            "FCA coverage is exact; post-FCA valuation completeness still requires the full peer/financial engine.",
            "The CSV contains candidate outcome windows, not resolved predictions; editorial and decision gates may still abstain.",
        ],
        "inputs": {
            "instrument_catalog": str(catalog_path.resolve()),
            "instrument_catalog_sha256": _sha256(catalog_path),
            "cotahist": str(cotahist_path.resolve()),
            "cotahist_sha256": observations["source_sha256"],
            "daily_registry": str(registry.path.resolve()) if registry.path and registry.path.is_file() else None,
            "daily_registry_sha256": _sha256(registry.path) if registry.path and registry.path.is_file() else None,
            "daily_registry_available_at": snapshot_available_at.isoformat() if snapshot_available_at else None,
            "fca_archives": archives,
        },
        "universe": {
            "catalog_research_eligible": len(identities),
            "tickers_with_cotahist": len(observations.get("records") or {}),
            "tickers_without_cotahist": sorted(set(identities) - set(observations.get("records") or {})),
            "first_market_date": min(row["date"] for rows in observations["records"].values() for row in rows).isoformat(),
            "last_market_date": max(row["date"] for rows in observations["records"].values() for row in rows).isoformat(),
            "horizons": horizons,
        },
        "windows": {
            "total": total_windows,
            "by_horizon": {str(key): value for key, value in window_counts.items()},
            "non_overlapping_candidates_by_horizon": {
                str(key): value for key, value in non_overlapping_counts.items()
            },
        },
        "pre_fca_legacy_abstentions": {
            "counts": dict(reason_counts),
            "rates": {
                reason: count / total_windows if total_windows else None
                for reason, count in reason_counts.items()
            },
            "by_horizon": {
                str(horizon): dict(counts) for horizon, counts in reason_counts_by_horizon.items()
            },
        },
        "fca_point_in_time_coverage": {
            "counts": dict(fca_status_counts),
            "rates": {
                status: count / total_windows if total_windows else None
                for status, count in fca_status_counts.items()
            },
            "by_horizon": {
                str(horizon): dict(counts) for horizon, counts in fca_status_by_horizon.items()
            },
        },
        "window_table": str(output_csv.resolve()),
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose point-in-time backtest data gates exhaustively")
    parser.add_argument("--instrument-catalog", default="config/instrument_catalog.json")
    parser.add_argument("--cotahist", default="tmp/market/COTAHIST_A2026.ZIP")
    parser.add_argument("--cache-dir", default="tmp/cvm")
    parser.add_argument("--horizons", nargs="+", type=int, default=[5, 15, 30, 60])
    parser.add_argument("--output-csv", default="validation/backtest_abstention_windows.csv")
    parser.add_argument("--output-json", default="validation/backtest_abstention_summary.json")
    args = parser.parse_args()
    print(json.dumps(diagnose(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
