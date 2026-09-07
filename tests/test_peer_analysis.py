from prometheus.peer_analysis import enrich_peer_analysis


def _report(ticker, sector="Real Estate", period="2026-06-30", margin=0.2, roe=0.18, debt=0.7):
    def field(value):
        return {"normalized": value, "source": "CVM", "source_metadata": {"period": period}}
    return {
        "ticker": ticker,
        "sector_name": sector,
        "fundamental_data": {
            "profit_margin": field(margin),
            "roe": field(roe),
            "debt_to_equity": field(debt),
        },
        "research": {"peer_analysis": {"status": "INSUFFICIENT_DATA", "peers": []}},
    }


def test_peer_analysis_requires_same_sector_and_period():
    target = _report("AAA3")
    different_period = _report("BBB3", period="2026-03-31")
    different_sector = _report("CCC3", sector="Financial")
    enrich_peer_analysis([target, different_period, different_sector])
    assert target["research"]["peer_analysis"]["status"] == "INSUFFICIENT_DATA"


def test_peer_analysis_ranks_normalized_comparable_metrics():
    first = _report("AAA3", margin=0.20, roe=0.15, debt=0.9)
    second = _report("BBB3", margin=0.30, roe=0.22, debt=0.5)
    enrich_peer_analysis([first, second])
    analysis = first["research"]["peer_analysis"]
    assert analysis["status"] == "AVAILABLE"
    margin_rows = [row for row in analysis["peers"] if row["metric"] == "profit_margin"]
    assert next(row for row in margin_rows if row["company"] == "BBB3")["rank"] == 1
    debt_rows = [row for row in analysis["peers"] if row["metric"] == "debt_to_equity"]
    assert next(row for row in debt_rows if row["company"] == "BBB3")["rank"] == 1
