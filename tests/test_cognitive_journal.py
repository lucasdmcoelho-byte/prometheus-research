import datetime as dt
import json

import pytest

from prometheus.journal_engine import EventChainError, FutureEventError, JournalEngine
from prometheus.models import (
    COGNITIVE_EVENT_SCHEMA,
    COGNITIVE_EVENT_SCHEMA_VERSION,
    DecisionResult,
    ThesisResult,
)


UTC = dt.timezone.utc


class MutableClock:
    def __init__(self, value: dt.datetime):
        self.value = value

    def __call__(self) -> dt.datetime:
        return self.value


def _append(
    journal: JournalEngine,
    event_type: str,
    effective_as_of: str,
    *,
    case_id: str = "RC-CURY3-20260818",
    payload=None,
    idempotency_key=None,
):
    return journal.record_event(
        event_type=event_type,
        ticker="CURY3",
        payload=payload or {"value": event_type},
        effective_as_of=effective_as_of,
        occurred_at=effective_as_of,
        research_case_id=case_id,
        idempotency_key=idempotency_key,
        producer="test",
        producer_version="1",
    )


def test_journal_appends_without_rewriting_and_versions_each_research_case(tmp_path):
    path = tmp_path / "cognitive.jsonl"
    clock = MutableClock(dt.datetime(2026, 8, 18, 12, 0, tzinfo=UTC))
    journal = JournalEngine(str(path), clock=clock)

    evidence = _append(journal, "EVIDENCE_SNAPSHOT_RECORDED", "2026-08-18T10:00:00Z")
    first_line = path.read_bytes()
    belief = _append(journal, "BELIEF_VERSION_RECORDED", "2026-08-18T11:00:00Z")
    other_case = _append(
        journal,
        "EVIDENCE_SNAPSHOT_RECORDED",
        "2026-08-18T11:30:00Z",
        case_id="RC-EGIE3-20260818",
    )

    lines = path.read_bytes().splitlines(keepends=True)
    assert lines[0] == first_line
    assert len(lines) == 3
    assert evidence["schema"] == COGNITIVE_EVENT_SCHEMA
    assert evidence["schema_version"] == COGNITIVE_EVENT_SCHEMA_VERSION
    assert evidence["ledger_sequence"] == 1
    assert belief["ledger_sequence"] == 2
    assert other_case["ledger_sequence"] == 3
    assert evidence["aggregate_version"] == 1
    assert belief["aggregate_version"] == 2
    assert other_case["aggregate_version"] == 1
    assert evidence["previous_event_hash"] is None
    assert belief["previous_event_hash"] == evidence["event_hash"]
    assert other_case["previous_event_hash"] == belief["event_hash"]
    assert journal.verify_chain()["status"] == "PASS"


def test_journal_detects_payload_tampering_in_hash_chain(tmp_path):
    path = tmp_path / "cognitive.jsonl"
    clock = MutableClock(dt.datetime(2026, 8, 18, 12, 0, tzinfo=UTC))
    journal = JournalEngine(str(path), clock=clock)
    _append(journal, "EVIDENCE_SNAPSHOT_RECORDED", "2026-08-18T10:00:00Z")
    _append(journal, "BELIEF_VERSION_RECORDED", "2026-08-18T11:00:00Z")

    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["payload"]["value"] = "tampered"
    lines[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(EventChainError, match="event_hash:1"):
        JournalEngine(str(path), clock=clock)


def test_replay_as_of_requires_effective_and_recorded_time():
    clock = MutableClock(dt.datetime(2026, 1, 10, 12, 0, tzinfo=UTC))
    journal = JournalEngine(clock=clock)
    first = _append(
        journal,
        "EVIDENCE_SNAPSHOT_RECORDED",
        "2026-01-09T18:00:00Z",
        case_id="RC-CURY3-202601",
    )

    clock.value = dt.datetime(2026, 1, 12, 12, 0, tzinfo=UTC)
    second = _append(
        journal,
        "BELIEF_VERSION_RECORDED",
        "2026-01-10T18:00:00Z",
        case_id="RC-CURY3-202601",
    )

    # This is a legitimate backfill, effective earlier but only known on Jan 15.
    clock.value = dt.datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    backfill = _append(
        journal,
        "EVIDENCE_SNAPSHOT_RECORDED",
        "2026-01-08T18:00:00Z",
        case_id="RC-CURY3-202601",
    )

    assert [item["event_id"] for item in journal.replay_as_of("2026-01-11")] == [first["event_id"]]
    assert [item["event_id"] for item in journal.replay_as_of("2026-01-13")] == [
        first["event_id"],
        second["event_id"],
    ]
    assert [item["event_id"] for item in journal.replay_as_of("2026-01-16")] == [
        first["event_id"],
        second["event_id"],
        backfill["event_id"],
    ]


def test_future_event_is_rejected_without_touching_ledger(tmp_path):
    path = tmp_path / "cognitive.jsonl"
    clock = MutableClock(dt.datetime(2026, 8, 18, 12, 0, tzinfo=UTC))
    journal = JournalEngine(str(path), clock=clock)

    with pytest.raises(FutureEventError):
        _append(journal, "EVIDENCE_SNAPSHOT_RECORDED", "2026-08-19T00:00:00Z")

    assert journal.events == []
    assert not path.exists() or path.stat().st_size == 0


def test_idempotency_key_is_stable_and_conflicts_are_rejected(tmp_path):
    path = tmp_path / "cognitive.jsonl"
    clock = MutableClock(dt.datetime(2026, 8, 18, 12, 0, tzinfo=UTC))
    journal = JournalEngine(str(path), clock=clock)

    first = _append(
        journal,
        "EVIDENCE_SNAPSHOT_RECORDED",
        "2026-08-18T10:00:00Z",
        payload={"value": 1},
        idempotency_key="same-command",
    )
    repeated = _append(
        journal,
        "EVIDENCE_SNAPSHOT_RECORDED",
        "2026-08-18T10:00:00Z",
        payload={"value": 1},
        idempotency_key="same-command",
    )

    assert repeated["event_id"] == first["event_id"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(ValueError, match="Conflicting idempotency key"):
        _append(
            journal,
            "EVIDENCE_SNAPSHOT_RECORDED",
            "2026-08-18T10:00:00Z",
            payload={"value": 2},
            idempotency_key="same-command",
        )


def test_legacy_json_migrates_with_backup_and_prediction_updates_append(tmp_path):
    path = tmp_path / "journal.json"
    legacy = [{
        "ticker": "CURY3",
        "point_in_time": "2026-08-17T12:00:00Z",
        "thesis_result": {"thesis_id": "T-1", "score": 80.0},
        "predictions": [{"prediction_id": "P-1", "status": "PENDING"}],
    }]
    original = json.dumps(legacy, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(original)
    clock = MutableClock(dt.datetime(2026, 8, 18, 12, 0, tzinfo=UTC))

    journal = JournalEngine(str(path), clock=clock)
    backup = tmp_path / "journal.json.legacy-v0.json"
    initial_lines = path.read_bytes().splitlines(keepends=True)

    assert backup.read_bytes() == original
    assert len(journal.events) == 1
    assert journal.events[0]["schema_version"] == 1
    assert journal.events[0]["payload"]["migration"]["source_format"] == "journal-array-v0"
    assert journal.query("CURY3")[0]["predictions"][0]["status"] == "PENDING"
    assert journal.verify_chain()["status"] == "PASS"

    journal.update_prediction({"prediction_id": "P-1", "status": "CORRECT"})
    updated_lines = path.read_bytes().splitlines(keepends=True)

    assert updated_lines[0] == initial_lines[0]
    assert len(updated_lines) == 2
    assert journal.events[-1]["event_type"] == "PREDICTION_UPDATE_RECORDED"
    assert journal.query("CURY3")[0]["predictions"][0]["status"] == "CORRECT"
    assert backup.read_bytes() == original
    assert journal.verify_chain()["status"] == "PASS"


def test_legacy_record_and_query_api_remain_compatible_after_reload(tmp_path):
    path = tmp_path / "journal.jsonl"
    now = dt.datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    clock = MutableClock(now)
    journal = JournalEngine(str(path), clock=clock)
    thesis = ThesisResult(
        thesis_id="CURY3-2026-08-18-001",
        ticker="CURY3",
        score=80.0,
        state="STABLE",
        direction="BULLISH",
        velocity=0.0,
        acceleration=0.0,
        confidence=0.8,
        age_days=None,
        status="ACTIVE",
        lifecycle="ACTIVE",
        timestamp=now,
    )
    decision = DecisionResult(
        action="evidence_favorable",
        reasoning="fixture",
        score=0.8,
        confidence=0.8,
        factors={},
        evidence=[],
        timestamp=now,
    )

    returned = journal.record(
        ticker="CURY3",
        asset_profile={"ticker": "CURY3"},
        financials={"period": "2026-06-30"},
        market_snapshot={"price": 20.0},
        thesis_scores={"fundamental": 80.0},
        thesis_result=thesis,
        decision_result=decision,
        sentiment_score=50.0,
        metadata={"source": "compatibility-test"},
        predictions=[],
    )
    reloaded = JournalEngine(str(path), clock=clock)

    assert returned["ticker"] == "CURY3"
    assert returned["point_in_time"] == "2026-08-18T12:00:00Z"
    assert reloaded.query("CURY3") == [returned]
    assert reloaded.entries == [returned]
    assert reloaded.events[0]["event_type"] == "JOURNAL_ENTRY_RECORDED"
    assert reloaded.verify_chain()["status"] == "PASS"
