from __future__ import annotations

import statistics
from typing import Any, Dict, Iterable, List


COMPARABLE_METRICS = {
    "profit_margin": True,
    "roe": True,
    "debt_to_equity": False,
}


def enrich_peer_analysis(reports: Iterable[Dict[str, Any]]) -> None:
    """Attach same-sector, same-period comparisons to report dictionaries in place."""
    report_list = list(reports)
    for target in report_list:
        target_sector = target.get("sector_name")
        target_period = _financial_period(target)
        comparable = [
            report for report in report_list
            if report.get("sector_name") == target_sector
            and _financial_period(report) == target_period
            and target_period is not None
        ]
        if len(comparable) < 2:
            continue

        rows: List[Dict[str, Any]] = []
        for metric, higher_is_better in COMPARABLE_METRICS.items():
            observations = []
            for report in comparable:
                field = (report.get("fundamental_data") or {}).get(metric) or {}
                value = field.get("normalized")
                if isinstance(value, (int, float)):
                    observations.append((report, float(value), field))
            if len(observations) < 2:
                continue
            median = statistics.median(value for _, value, _ in observations)
            ordered = sorted(observations, key=lambda row: row[1], reverse=higher_is_better)
            for rank, (report, value, field) in enumerate(ordered, start=1):
                rows.append({
                    "company": report.get("ticker"),
                    "metric": metric,
                    "value": value,
                    "period": target_period,
                    "source": field.get("source") or "unknown",
                    "rank": rank,
                    "sector_median": median,
                    "premium_discount": None if median == 0 else (value / median) - 1.0,
                })
        if rows:
            target["research"]["peer_analysis"] = {
                "ticker": target.get("ticker"),
                "status": "AVAILABLE",
                "peers": rows,
                "summary": "Comparação restrita a empresas do mesmo setor, métricas normalizadas e período contábil idêntico.",
            }


def _financial_period(report: Dict[str, Any]) -> str | None:
    for field in (report.get("fundamental_data") or {}).values():
        if isinstance(field, dict):
            metadata = field.get("source_metadata")
            period = getattr(metadata, "period", None)
            if period is None and isinstance(metadata, dict):
                period = metadata.get("period")
            if period:
                return str(period)
    return None
