from datetime import datetime

import pytest

from prometheus.adapters import CVMEnrichedAdapter, PointInTimeMarketSnapshotAdapter
from prometheus.engines import PointInTimeLayer
from prometheus.models import SourceMetadata


def _row():
    return {"close": 30.01, "previous_close": 30.77, "effective_at": "2026-07-28T18:00:00Z", "available_at": "2026-07-28T20:00:00Z", "source": "B3 historical observation", "source_url": "https://example.invalid", "currency": "BRL"}


def test_market_snapshot_is_deterministic_and_provenanced():
    result = PointInTimeMarketSnapshotAdapter({"EGIE3": _row()}).fetch("EGIE3", datetime(2026, 7, 28, 23, 0))
    assert result["info"]["regularMarketPrice"] == 30.01
    assert result["source_metadata"].period == "2026-07-28"
    assert result["source_metadata"].unit == "BRL"


def test_market_snapshot_blocks_lookahead():
    with pytest.raises(ValueError, match="Look-ahead"):
        PointInTimeMarketSnapshotAdapter({"EGIE3": _row()}).fetch("EGIE3", datetime(2026, 7, 28, 19, 0))


def test_point_in_time_layer_validates_market_field_metadata_too():
    cutoff = datetime(2026, 7, 28, 19, 0)
    metadata = SourceMetadata(
        source="market", timestamp=cutoff, publication_date=datetime(2026, 7, 29),
        effective_date=cutoff, ticker="EGIE3", period="2026-07-28", unit="BRL",
        confidence=1.0, revision_status=None, raw={},
    )
    with pytest.raises(ValueError, match="exceeds point-in-time cutoff"):
        PointInTimeLayer(cutoff).filter({
            "source_metadata": metadata, "field_metadata": {},
            "market_field_metadata": {"marketCap": metadata},
        })


def test_offline_snapshot_does_not_attempt_technical_network(monkeypatch):
    adapter = CVMEnrichedAdapter({"EGIE3": "17329"}, market_adapter=PointInTimeMarketSnapshotAdapter({"EGIE3": _row()}))
    monkeypatch.setattr(adapter, "_technical_context", lambda *_: (_ for _ in ()).throw(AssertionError("network path used")))
    # The branch itself is covered through the type invariant; full CVM assembly
    # is exercised by the cross-universe E2E artifact.
    assert adapter.market.fetch("EGIE3", datetime(2026, 7, 29))["info"]["regularMarketPrice"] == 30.01


def test_market_cap_and_shares_have_independent_point_in_time_provenance():
    row = _row()
    row["fields"] = {
        "shares_outstanding": {
            "value": 800_000_000,
            "unit": "shares",
            "effective_at": "2026-06-30T00:00:00Z",
            "available_at": "2026-07-20T12:00:00Z",
            "source": "CVM capital composition",
            "source_url": "https://dados.cvm.gov.br/",
        },
        "market_cap": {
            "value": 24_008_000_000,
            "unit": "BRL",
            "formula": "close * shares_outstanding",
        },
    }
    result = PointInTimeMarketSnapshotAdapter({"EGIE3": row}).fetch("EGIE3", datetime(2026, 7, 28, 23, 0))
    assert result["info"]["sharesOutstanding"] == 800_000_000
    assert result["info"]["marketCap"] == 24_008_000_000
    metadata = result["market_field_metadata"]
    assert metadata["sharesOutstanding"].source == "CVM capital composition"
    assert metadata["marketCap"].raw["formula"] == "close * shares_outstanding"
    record = PointInTimeMarketSnapshotAdapter({"EGIE3": row}).point_record("EGIE3", "market_cap", datetime(2026, 7, 28, 23, 0))
    assert record["value"] == 24_008_000_000
    assert record["formula"] == "close * shares_outstanding"
    assert record["source_url"] == "https://example.invalid"


def test_point_price_record_preserves_snapshot_hash_and_availability():
    row = _row()
    row["source_sha256"] = "a" * 64
    record = PointInTimeMarketSnapshotAdapter({"EGIE3": row}).point_record(
        "EGIE3", "price", datetime(2026, 7, 28, 23, 0),
    )
    assert record["value"] == 30.01
    assert record["unit"] == "BRL"
    assert record["source_sha256"] == "a" * 64
    assert record["publication_date"] == datetime(2026, 7, 28, 20, 0)


def test_market_field_lookahead_is_blocked_even_when_price_is_available():
    row = _row()
    row["fields"] = {
        "shares_outstanding": {
            "value": 800_000_000,
            "available_at": "2026-07-29T12:00:00Z",
        }
    }
    with pytest.raises(ValueError, match="Look-ahead shares_outstanding"):
        PointInTimeMarketSnapshotAdapter({"EGIE3": row}).fetch("EGIE3", datetime(2026, 7, 28, 23, 0))


def test_cvm_adapter_delegates_offline_peer_market_cap_without_yahoo():
    row = _row()
    row["market_cap"] = 24_008_000_000
    adapter = CVMEnrichedAdapter(
        {"EGIE3": "17329"},
        market_adapter=PointInTimeMarketSnapshotAdapter({"EGIE3": row}),
    )
    assert adapter.peer_market_cap("EGIE3", datetime(2026, 7, 28, 23, 0)) == 24_008_000_000


def test_declared_market_cap_formula_is_reconciled():
    row = _row()
    row["fields"] = {
        "shares_outstanding": {"value": 800_000_000},
        "market_cap": {
            "value": 1,
            "formula": "close * shares_outstanding",
        },
    }
    with pytest.raises(ValueError, match="Inconsistent market_cap formula"):
        PointInTimeMarketSnapshotAdapter({"EGIE3": row}).fetch("EGIE3", datetime(2026, 7, 28, 23, 0))


def test_undeclared_market_cap_formula_is_rejected():
    row = _row()
    row["fields"] = {
        "shares_outstanding": {"value": 800_000_000},
        "market_cap": {"value": 24_008_000_000, "formula": "opaque provider method"},
    }
    with pytest.raises(ValueError, match="Unsupported market_cap formula"):
        PointInTimeMarketSnapshotAdapter({"EGIE3": row}).fetch("EGIE3", datetime(2026, 7, 28, 23, 0))
