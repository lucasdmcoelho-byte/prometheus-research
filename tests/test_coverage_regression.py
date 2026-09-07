from prometheus.editorial_gate import EditorialGate
from prometheus.regression_monitor import CoverageRegressionMonitor


def _report(*, confidence, coverage, valuation, kpis, peers):
    return {
        "research_quality": {
            "overall_research_confidence": confidence,
            "research_coverage": coverage,
            "valuation_confidence": valuation,
        },
        "operational_kpis": {
            "metrics": {
                f"kpi_{index}": {"value": 1, "source_sha256": "a" * 64, "period": "2026-Q2"}
                for index in range(kpis)
            }
        },
        "research": {"peer_analysis": {"eligible_multiple_count": peers}},
    }


def test_cvm_to_yfinance_coverage_regression_is_warned_by_gate():
    complete = _report(confidence=90, coverage=90, valuation=90, kpis=16, peers=4)
    degraded = _report(confidence=45, coverage=40, valuation=0, kpis=0, peers=0)
    previous_entry = {
        "ticker": "CURY3", "point_in_time": "2026-08-23T23:59:59Z",
        "metadata": {"coverage_snapshot": CoverageRegressionMonitor.snapshot(complete)},
    }
    alert = CoverageRegressionMonitor.compare(
        CoverageRegressionMonitor.snapshot(degraded), previous_entry,
    )

    assert alert["status"] == "REGRESSION_ALERT"
    assert {item["metric"] for item in alert["alerts"]} >= {
        "overall_research_confidence", "research_coverage", "valuation_confidence",
        "traceable_operational_kpis", "eligible_peers",
    }

    gate = EditorialGate().evaluate({
        "data_source_status": "DEGRADED",
        "data_source_degradation": {"reason": "CVMTimeout"},
        "regression_alert": alert,
    })
    codes = {warning["code"] for warning in gate["warnings"]}
    assert {"DATA_SOURCE_DEGRADED", "REGRESSION_ALERT"} <= codes


def test_no_alert_for_small_coverage_change():
    previous = {"ticker": "CURY3", "metadata": {"coverage_snapshot": CoverageRegressionMonitor.snapshot(
        _report(confidence=80, coverage=80, valuation=75, kpis=4, peers=3)
    )}}
    result = CoverageRegressionMonitor.compare(
        CoverageRegressionMonitor.snapshot(_report(confidence=60, coverage=60, valuation=55, kpis=2, peers=2)),
        previous,
    )
    assert result["status"] == "PASS"
