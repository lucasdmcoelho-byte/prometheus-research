"""Coverage-regression detection between consecutive research cuts."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class CoverageRegressionMonitor:
    """Compare publishability inputs without changing analytical scores."""

    POINT_DROP = 30.0

    @classmethod
    def snapshot(cls, report: Dict[str, Any]) -> Dict[str, Any]:
        quality = report.get("research_quality") or {}
        peers = ((report.get("research") or {}).get("peer_analysis") or {})
        operational = ((report.get("operational_kpis") or {}).get("metrics") or {})
        traced_kpis = sum(
            1 for metric in operational.values()
            if isinstance(metric, dict) and metric.get("value") is not None
            and metric.get("source_sha256") and metric.get("period")
        )
        return {
            "overall_research_confidence": float(quality.get("overall_research_confidence") or 0.0),
            "research_coverage": float(quality.get("research_coverage") or 0.0),
            "valuation_confidence": float(quality.get("valuation_confidence") or 0.0),
            "traceable_operational_kpis": traced_kpis,
            "eligible_peers": int(peers.get("eligible_multiple_count") or 0),
        }

    @classmethod
    def previous_for(cls, entries: Iterable[Dict[str, Any]], ticker: str) -> Optional[Dict[str, Any]]:
        candidates = [
            entry for entry in entries
            if str(entry.get("ticker") or "").upper() == ticker.upper()
            and isinstance((entry.get("metadata") or {}).get("coverage_snapshot"), dict)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda entry: str(entry.get("point_in_time") or ""))

    @classmethod
    def compare(cls, current: Dict[str, Any], previous_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not previous_entry:
            return {"status": "NOT_APPLICABLE", "alerts": [], "current": current}
        previous = (previous_entry.get("metadata") or {}).get("coverage_snapshot") or {}
        alerts = []
        for name in ("overall_research_confidence", "research_coverage", "valuation_confidence"):
            before, after = float(previous.get(name) or 0.0), float(current.get(name) or 0.0)
            if before - after >= cls.POINT_DROP:
                alerts.append({"metric": name, "previous": before, "current": after, "drop": round(before - after, 2)})
        for name in ("traceable_operational_kpis", "eligible_peers"):
            before, after = int(previous.get(name) or 0), int(current.get(name) or 0)
            if before > 0 and after == 0:
                alerts.append({"metric": name, "previous": before, "current": after, "drop": before})
        return {
            "status": "REGRESSION_ALERT" if alerts else "PASS",
            "alerts": alerts,
            "current": current,
            "previous": previous,
            "previous_point_in_time": previous_entry.get("point_in_time"),
        }
