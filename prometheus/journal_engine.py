from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from prometheus.models import (
    CANONICAL_RESEARCH_EVENT_TYPES,
    COGNITIVE_EVENT_SCHEMA,
    COGNITIVE_EVENT_SCHEMA_VERSION,
    DecisionResult,
    ResearchEvent,
    ThesisResult,
)


class TemporalContractError(ValueError):
    """Raised when a cognitive event violates the canonical time ordering."""


class FutureEventError(TemporalContractError):
    """Raised when an event claims knowledge or occurrence from the future."""


class EventChainError(ValueError):
    """Raised when an existing journal cannot pass integrity verification."""


class JournalEngine:
    """Append-only cognitive history with a legacy journal projection.

    The canonical persistence format is one ``prometheus.cognitive_event`` v1
    JSON object per line. ``entries`` and ``query()`` remain compatible views of
    the old journal records; they are projections and never the audit source of
    truth. Existing array-JSON journals are migrated atomically on first load and
    retained beside the ledger as ``*.legacy-v0.json``.
    """
    _process_lock_guard = threading.Lock()
    _process_locks: Dict[str, threading.RLock] = {}

    def __init__(
        self,
        storage_path: Optional[str] = None,
        clock: Optional[Callable[[], datetime.datetime]] = None,
    ):
        self.storage_path = storage_path
        self._clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.events: List[Dict[str, Any]] = []
        self.entries: List[Dict[str, Any]] = []
        if storage_path and Path(storage_path).is_file() and Path(storage_path).stat().st_size:
            self.load(storage_path)

    def record(
        self,
        ticker: str,
        asset_profile: Dict[str, Any],
        financials: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        thesis_scores: Dict[str, Any],
        thesis_result: ThesisResult,
        decision_result: DecisionResult,
        sentiment_score: float,
        metadata: Optional[Dict[str, Any]] = None,
        predictions: Optional[List[Dict[str, Any]]] = None,
        as_of: Any = None,
    ) -> Dict[str, Any]:
        """Record the current legacy journal payload as an immutable event.

        ``as_of`` is optional for API compatibility. When omitted, the evidence
        cutoff, occurrence, and recording time are the current UTC instant, which
        matches the former live-journal behavior.
        """

        recorded_at = self._clock_utc()
        effective_at = self._coerce_utc(as_of, end_of_day_for_date=True) if as_of is not None else recorded_at
        current_thesis = dataclasses.asdict(thesis_result)
        history = self._build_thesis_history(ticker, current_thesis)
        point_in_time = self._format_utc(effective_at)

        entry = self._json_safe({
            "ticker": ticker,
            "point_in_time": point_in_time,
            "asset_profile": asset_profile,
            "financials": financials,
            "market_snapshot": market_snapshot,
            "thesis_scores": thesis_scores,
            "thesis_result": current_thesis,
            "thesis_history": history,
            "predictions": predictions or [],
            "decision": {
                "action": decision_result.action,
                "reasoning": decision_result.reasoning,
                "score": decision_result.score,
                "confidence": decision_result.confidence,
            },
            "sentiment_score": sentiment_score,
            "metadata": metadata or {},
        })
        self.record_event(
            event_type="JOURNAL_ENTRY_RECORDED",
            ticker=ticker,
            payload={"entry": entry},
            effective_as_of=effective_at,
            occurred_at=effective_at,
            research_case_id=self._default_case_id(ticker, effective_at),
            actor_type="system",
            actor_id="prometheus",
            producer="JournalEngine.record",
            producer_version="1",
        )
        return entry

    def record_event(
        self,
        *,
        event_type: str,
        ticker: str,
        payload: Dict[str, Any],
        effective_as_of: Any,
        occurred_at: Any = None,
        research_case_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        actor_type: str = "system",
        actor_id: str = "prometheus",
        producer: str = "JournalEngine",
        producer_version: str = "1",
        policy_version: Optional[str] = None,
        input_event_ids: Optional[Iterable[str]] = None,
        input_artifact_hashes: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Validate and append one canonical event.

        The recording time is always supplied by the journal clock and cannot be
        forged by callers. Reusing an idempotency key returns the existing event
        only when its identity and payload match; conflicting reuse is rejected.
        """

        normalized_type = str(event_type or "").strip().upper()
        if normalized_type not in CANONICAL_RESEARCH_EVENT_TYPES:
            raise ValueError(f"Unsupported cognitive event type: {event_type}")
        normalized_ticker = str(ticker or "").strip().upper()
        if not normalized_ticker:
            raise ValueError("ticker is required")
        if not isinstance(payload, dict):
            raise TypeError("event payload must be a dictionary")

        recorded = self._clock_utc()
        effective = self._coerce_utc(effective_as_of, end_of_day_for_date=True)
        occurred = self._coerce_utc(occurred_at, end_of_day_for_date=True) if occurred_at is not None else effective
        self._validate_temporal(effective, occurred, recorded, now=recorded)

        case_id = str(research_case_id or self._default_case_id(normalized_ticker, effective)).strip()
        if not case_id:
            raise ValueError("research_case_id is required")
        normalized_payload = self._json_safe(payload)
        artifact_hashes = tuple(str(item).strip().lower() for item in (input_artifact_hashes or []) if str(item).strip())
        invalid_hashes = [item for item in artifact_hashes if not re.fullmatch(r"[0-9a-f]{64}", item)]
        if invalid_hashes:
            raise ValueError("input_artifact_hashes must be SHA-256 hex digests")
        event_inputs = tuple(str(item).strip() for item in (input_event_ids or []) if str(item).strip())
        normalized_actor_type = str(actor_type or "").strip().lower()
        normalized_actor_id = str(actor_id or "").strip()
        normalized_producer = str(producer or "").strip()
        normalized_producer_version = str(producer_version or "").strip()
        if not all((normalized_actor_type, normalized_actor_id, normalized_producer, normalized_producer_version)):
            raise ValueError("actor and producer identity are required")

        event_id = f"EVT-{uuid.uuid4().hex.upper()}"
        key = str(idempotency_key or f"event:{event_id}").strip()
        if not key:
            raise ValueError("idempotency_key cannot be empty")
        specification = {
            "event_type": normalized_type,
            "ticker": normalized_ticker,
            "research_case_id": case_id,
            "effective_as_of": self._format_utc(effective),
            "occurred_at": self._format_utc(occurred),
            "payload": normalized_payload,
        }

        if self.storage_path:
            path = Path(self.storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_lock(path):
                existing = self._read_or_migrate_locked(path)
                self._raise_if_invalid(existing)
                duplicate = self._idempotent_match(existing, key, specification)
                if duplicate is not None:
                    self.events = existing
                    self._rebuild_projection()
                    return dict(duplicate)
                event = self._create_event(
                    existing=existing,
                    event_id=event_id,
                    event_type=normalized_type,
                    ticker=normalized_ticker,
                    payload=normalized_payload,
                    effective=effective,
                    occurred=occurred,
                    recorded=recorded,
                    research_case_id=case_id,
                    causation_id=causation_id,
                    correlation_id=correlation_id or case_id,
                    idempotency_key=key,
                    actor_type=normalized_actor_type,
                    actor_id=normalized_actor_id,
                    producer=normalized_producer,
                    producer_version=normalized_producer_version,
                    policy_version=policy_version,
                    input_event_ids=event_inputs,
                    input_artifact_hashes=artifact_hashes,
                )
                self._append_line(path, event)
                existing.append(event)
        else:
            existing = list(self.events)
            self._raise_if_invalid(existing)
            duplicate = self._idempotent_match(existing, key, specification)
            if duplicate is not None:
                return dict(duplicate)
            event = self._create_event(
                existing=existing,
                event_id=event_id,
                event_type=normalized_type,
                ticker=normalized_ticker,
                payload=normalized_payload,
                effective=effective,
                occurred=occurred,
                recorded=recorded,
                research_case_id=case_id,
                causation_id=causation_id,
                correlation_id=correlation_id or case_id,
                idempotency_key=key,
                actor_type=normalized_actor_type,
                actor_id=normalized_actor_id,
                producer=normalized_producer,
                producer_version=normalized_producer_version,
                policy_version=policy_version,
                input_event_ids=event_inputs,
                input_artifact_hashes=artifact_hashes,
            )
            existing.append(event)

        self.events = existing
        self._rebuild_projection()
        return dict(event)

    def update_prediction(self, prediction_update: Dict[str, Any], as_of: Any = None) -> None:
        """Append a prediction update and refresh the legacy read projection."""

        pid = prediction_update.get("prediction_id")
        if not pid:
            return
        source_event = next(
            (
                event
                for event in reversed(self.events)
                if event.get("event_type") == "JOURNAL_ENTRY_RECORDED"
                and any(
                    prediction.get("prediction_id") == pid
                    for prediction in ((event.get("payload") or {}).get("entry") or {}).get("predictions", [])
                )
            ),
            None,
        )
        if source_event is None:
            return
        effective = self._coerce_utc(as_of, end_of_day_for_date=True) if as_of is not None else self._clock_utc()
        self.record_event(
            event_type="PREDICTION_UPDATE_RECORDED",
            ticker=source_event["ticker"],
            payload={"prediction_update": self._json_safe(prediction_update)},
            effective_as_of=effective,
            occurred_at=effective,
            research_case_id=source_event["research_case_id"],
            causation_id=source_event["event_id"],
            correlation_id=source_event["correlation_id"],
            actor_type="system",
            actor_id="prometheus",
            producer="JournalEngine.update_prediction",
            producer_version="1",
        )

    def verify_chain(self, events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        inspected = self.events if events is None else events
        failures: List[str] = []
        previous_hash = None
        versions: Dict[str, int] = {}
        event_ids = set()
        idempotency_keys = set()
        now = self._clock_utc()

        for index, event in enumerate(inspected, start=1):
            event_id = str(event.get("event_id") or "")
            case_id = str(event.get("research_case_id") or "")
            key = str(event.get("idempotency_key") or "")
            if event.get("schema") != COGNITIVE_EVENT_SCHEMA:
                failures.append(f"schema:{index}")
            if event.get("schema_version") != COGNITIVE_EVENT_SCHEMA_VERSION:
                failures.append(f"schema_version:{index}")
            if event.get("event_type") not in CANONICAL_RESEARCH_EVENT_TYPES:
                failures.append(f"event_type:{index}")
            if event.get("ledger_sequence") != index:
                failures.append(f"ledger_sequence:{index}")
            if event.get("previous_event_hash") != previous_hash:
                failures.append(f"previous_event_hash:{index}")
            if not event.get("event_hash") or event.get("event_hash") != self._event_hash(event):
                failures.append(f"event_hash:{index}")
            if not event_id or event_id in event_ids:
                failures.append(f"event_id:{index}")
            if not key or key in idempotency_keys:
                failures.append(f"idempotency_key:{index}")
            expected_version = versions.get(case_id, 0) + 1
            if not case_id or event.get("aggregate_version") != expected_version:
                failures.append(f"aggregate_version:{index}")
            try:
                effective = self._coerce_utc(event.get("effective_as_of"))
                occurred = self._coerce_utc(event.get("occurred_at"))
                recorded = self._coerce_utc(event.get("recorded_at"))
                self._validate_temporal(effective, occurred, recorded, now=now)
            except (TypeError, ValueError):
                failures.append(f"temporal_contract:{index}")
            if not str(event.get("actor_type") or "").strip() or not str(event.get("actor_id") or "").strip():
                failures.append(f"actor:{index}")
            if not str(event.get("producer") or "").strip() or not str(event.get("producer_version") or "").strip():
                failures.append(f"producer:{index}")

            versions[case_id] = expected_version
            event_ids.add(event_id)
            idempotency_keys.add(key)
            previous_hash = event.get("event_hash")

        return {
            "status": "PASS" if not failures else "FAIL",
            "event_count": len(inspected),
            "research_case_count": len(versions),
            "head_hash": previous_hash,
            "failures": sorted(set(failures)),
        }

    def replay_as_of(
        self,
        as_of: Any,
        ticker: Optional[str] = None,
        event_types: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Replay events that were both effective and recorded by ``as_of``.

        Requiring both timestamps implements a bitemporal “known at the time”
        view. A migrated/backfilled event with an old effective date remains
        absent from a replay that predates its actual recording time.
        """

        cutoff = self._coerce_utc(as_of, end_of_day_for_date=True)
        normalized_ticker = str(ticker or "").strip().upper()
        allowed_types = {str(item).strip().upper() for item in (event_types or []) if str(item).strip()}
        replayed = []
        for event in self.events:
            if normalized_ticker and event.get("ticker") != normalized_ticker:
                continue
            if allowed_types and event.get("event_type") not in allowed_types:
                continue
            effective = self._coerce_utc(event["effective_as_of"])
            recorded = self._coerce_utc(event["recorded_at"])
            if effective <= cutoff and recorded <= cutoff:
                replayed.append(self._json_clone(event))
        return replayed

    def query_events(
        self,
        ticker: Optional[str] = None,
        research_case_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_ticker = str(ticker or "").strip().upper()
        normalized_type = str(event_type or "").strip().upper()
        return [
            self._json_clone(event)
            for event in self.events
            if (not normalized_ticker or event.get("ticker") == normalized_ticker)
            and (not research_case_id or event.get("research_case_id") == research_case_id)
            and (not normalized_type or event.get("event_type") == normalized_type)
        ]

    def save(self, file_path: str) -> None:
        """Clone the canonical event stream to ``file_path``.

        The active ledger is already durable after each append. Saving to that
        same path is therefore a no-op and can never rewrite its history.
        """

        destination = Path(file_path)
        if self.storage_path and destination.resolve() == Path(self.storage_path).resolve():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for event in self.events:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def load(self, file_path: str) -> None:
        path = Path(file_path)
        self.storage_path = str(path)
        if not path.exists() or path.stat().st_size == 0:
            self.events = []
            self.entries = []
            return
        with self._ledger_lock(path):
            events = self._read_or_migrate_locked(path)
            self._raise_if_invalid(events)
        self.events = events
        self._rebuild_projection()

    def query(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        if ticker is None:
            return self._json_clone(self.entries)
        normalized = ticker.strip().upper()
        return self._json_clone([entry for entry in self.entries if entry.get("ticker") == normalized])

    def _build_thesis_history(self, ticker: str, current_thesis: Dict[str, Any]) -> List[Dict[str, Any]]:
        previous_entries = self.query(ticker)
        history: List[Dict[str, Any]] = []
        if not previous_entries:
            return history

        last_entry = previous_entries[-1]
        previous_thesis = last_entry.get("thesis_result", {})
        history.append({
            "previous_thesis_id": previous_thesis.get("thesis_id"),
            "previous_score": previous_thesis.get("score"),
            "current_score": current_thesis.get("score"),
            "score_delta": round(current_thesis.get("score", 0.0) - previous_thesis.get("score", 0.0), 2),
            "previous_status": previous_thesis.get("status"),
            "current_status": current_thesis.get("status"),
            "previous_lifecycle": previous_thesis.get("lifecycle"),
            "current_lifecycle": current_thesis.get("lifecycle"),
            "previous_breakers": [breaker.get("id") for breaker in previous_thesis.get("thesis_breakers", [])],
            "current_breakers": [breaker.get("id") for breaker in current_thesis.get("thesis_breakers", [])],
            "breaker_delta": {
                "added": [breaker.get("id") for breaker in current_thesis.get("thesis_breakers", []) if breaker.get("id") not in {item.get("id") for item in previous_thesis.get("thesis_breakers", [])}],
                "removed": [breaker.get("id") for breaker in previous_thesis.get("thesis_breakers", []) if breaker.get("id") not in {item.get("id") for item in current_thesis.get("thesis_breakers", [])}],
            },
        })
        return history

    def _create_event(
        self,
        *,
        existing: List[Dict[str, Any]],
        event_id: str,
        event_type: str,
        ticker: str,
        payload: Dict[str, Any],
        effective: datetime.datetime,
        occurred: datetime.datetime,
        recorded: datetime.datetime,
        research_case_id: str,
        causation_id: Optional[str],
        correlation_id: str,
        idempotency_key: str,
        actor_type: str,
        actor_id: str,
        producer: str,
        producer_version: str,
        policy_version: Optional[str],
        input_event_ids: tuple[str, ...],
        input_artifact_hashes: tuple[str, ...],
    ) -> Dict[str, Any]:
        aggregate_version = 1 + sum(1 for item in existing if item.get("research_case_id") == research_case_id)
        base = {
            "schema": COGNITIVE_EVENT_SCHEMA,
            "schema_version": COGNITIVE_EVENT_SCHEMA_VERSION,
            "event_id": event_id,
            "event_type": event_type,
            "research_case_id": research_case_id,
            "ticker": ticker,
            "ledger_sequence": len(existing) + 1,
            "aggregate_version": aggregate_version,
            "causation_id": causation_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "effective_as_of": self._format_utc(effective),
            "occurred_at": self._format_utc(occurred),
            "recorded_at": self._format_utc(recorded),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "producer": producer,
            "producer_version": producer_version,
            "policy_version": policy_version,
            "input_event_ids": list(input_event_ids),
            "input_artifact_hashes": list(input_artifact_hashes),
            "payload": payload,
            "previous_event_hash": existing[-1].get("event_hash") if existing else None,
        }
        event_hash = self._event_hash(base)
        return ResearchEvent(
            **{key: value for key, value in base.items() if key not in {"input_event_ids", "input_artifact_hashes"}},
            input_event_ids=input_event_ids,
            input_artifact_hashes=input_artifact_hashes,
            event_hash=event_hash,
        ).to_dict()

    def _idempotent_match(
        self,
        events: List[Dict[str, Any]],
        idempotency_key: str,
        specification: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        existing = next((event for event in events if event.get("idempotency_key") == idempotency_key), None)
        if existing is None:
            return None
        actual = {
            "event_type": existing.get("event_type"),
            "ticker": existing.get("ticker"),
            "research_case_id": existing.get("research_case_id"),
            "effective_as_of": existing.get("effective_as_of"),
            "occurred_at": existing.get("occurred_at"),
            "payload": existing.get("payload"),
        }
        if actual != specification:
            raise ValueError(f"Conflicting idempotency key: {idempotency_key}")
        return existing

    def _read_or_migrate_locked(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists() or path.stat().st_size == 0:
            return []
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        if text.lstrip().startswith("["):
            return self._migrate_legacy_locked(path, raw, text)
        events = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise EventChainError(f"Invalid journal JSONL at line {line_number}") from error
            if not isinstance(event, dict):
                raise EventChainError(f"Journal event at line {line_number} must be an object")
            events.append(event)
        return events

    def _migrate_legacy_locked(self, path: Path, raw: bytes, text: str) -> List[Dict[str, Any]]:
        try:
            legacy_entries = json.loads(text)
        except json.JSONDecodeError as error:
            raise EventChainError("Invalid legacy journal JSON") from error
        if not isinstance(legacy_entries, list) or not all(isinstance(item, dict) for item in legacy_entries):
            raise EventChainError("Legacy journal must contain an array of objects")

        backup = path.with_name(path.name + ".legacy-v0.json")
        if backup.exists():
            if backup.read_bytes() != raw:
                raise EventChainError(f"Legacy backup conflict: {backup}")
        else:
            with backup.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())

        source_hash = hashlib.sha256(raw).hexdigest()
        recorded = self._clock_utc()
        migrated: List[Dict[str, Any]] = []
        for index, original_entry in enumerate(legacy_entries, start=1):
            entry = self._json_safe(original_entry)
            ticker = str(entry.get("ticker") or "UNKNOWN").strip().upper()
            effective = self._coerce_utc(entry.get("point_in_time") or recorded, end_of_day_for_date=True)
            self._validate_temporal(effective, effective, recorded, now=recorded)
            idempotency_key = f"legacy-v0:{source_hash}:{index}"
            event_id = f"EVT-{uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key).hex.upper()}"
            case_id = self._default_case_id(ticker, effective)
            migrated.append(self._create_event(
                existing=migrated,
                event_id=event_id,
                event_type="JOURNAL_ENTRY_RECORDED",
                ticker=ticker,
                payload={
                    "entry": entry,
                    "migration": {
                        "source_format": "journal-array-v0",
                        "source_sha256": source_hash,
                        "legacy_index": index,
                    },
                },
                effective=effective,
                occurred=effective,
                recorded=recorded,
                research_case_id=case_id,
                causation_id=None,
                correlation_id=case_id,
                idempotency_key=idempotency_key,
                actor_type="migration",
                actor_id="journal-v0-migrator",
                producer="JournalEngine.legacy_migration",
                producer_version="1",
                policy_version=None,
                input_event_ids=(),
                input_artifact_hashes=(source_hash,),
            ))

        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.migrating")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for event in migrated:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return migrated

    def _rebuild_projection(self) -> None:
        self.entries = self._project_entries(self.events)

    @staticmethod
    def _project_entries(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for event in events:
            if event.get("event_type") == "JOURNAL_ENTRY_RECORDED":
                entry = ((event.get("payload") or {}).get("entry"))
                if isinstance(entry, dict):
                    entries.append(JournalEngine._json_clone(entry))
            elif event.get("event_type") == "PREDICTION_UPDATE_RECORDED":
                update = ((event.get("payload") or {}).get("prediction_update")) or {}
                prediction_id = update.get("prediction_id")
                for entry in entries:
                    predictions = entry.get("predictions") or []
                    for index, prediction in enumerate(predictions):
                        if prediction.get("prediction_id") == prediction_id:
                            predictions[index] = {**prediction, **update}
                    entry["predictions"] = predictions
        return entries

    def _raise_if_invalid(self, events: List[Dict[str, Any]]) -> None:
        verification = self.verify_chain(events)
        if verification["status"] != "PASS":
            raise EventChainError("Invalid cognitive journal: " + "; ".join(verification["failures"]))

    @staticmethod
    def _append_line(path: Path, event: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @contextmanager
    def _ledger_lock(self, path: Path):
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_key = str(lock_path.resolve())
        with self._process_lock_guard:
            process_lock = self._process_locks.setdefault(lock_key, threading.RLock())
        with process_lock:
            with lock_path.open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _event_hash(event: Dict[str, Any]) -> str:
        payload = dict(event)
        payload.pop("event_hash", None)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _clock_utc(self) -> datetime.datetime:
        value = self._clock()
        if not isinstance(value, datetime.datetime):
            raise TypeError("Journal clock must return datetime")
        return self._as_utc(value).replace(microsecond=0)

    @staticmethod
    def _validate_temporal(
        effective: datetime.datetime,
        occurred: datetime.datetime,
        recorded: datetime.datetime,
        *,
        now: datetime.datetime,
    ) -> None:
        if any(value > now for value in (effective, occurred, recorded)):
            raise FutureEventError("Cognitive events cannot contain future timestamps")
        if effective > occurred:
            raise TemporalContractError("effective_as_of must not exceed occurred_at")
        if occurred > recorded:
            raise TemporalContractError("occurred_at must not exceed recorded_at")

    @classmethod
    def _coerce_utc(cls, value: Any, end_of_day_for_date: bool = False) -> datetime.datetime:
        if isinstance(value, datetime.datetime):
            parsed = value
        elif isinstance(value, datetime.date):
            parsed = datetime.datetime.combine(
                value,
                datetime.time(23, 59, 59) if end_of_day_for_date else datetime.time.min,
            )
        elif isinstance(value, str) and value.strip():
            text = value.strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                parsed = datetime.datetime.combine(
                    datetime.date.fromisoformat(text),
                    datetime.time(23, 59, 59) if end_of_day_for_date else datetime.time.min,
                )
            else:
                try:
                    parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
                except ValueError as error:
                    raise TemporalContractError(f"Invalid event timestamp: {value}") from error
        else:
            raise TemporalContractError("Event timestamp is required")
        return cls._as_utc(parsed).replace(microsecond=0)

    @staticmethod
    def _as_utc(value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc)

    @staticmethod
    def _format_utc(value: datetime.datetime) -> str:
        return JournalEngine._as_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _default_case_id(ticker: str, effective: datetime.datetime) -> str:
        return f"RC-{str(ticker).strip().upper()}-{effective.astimezone(datetime.timezone.utc).strftime('%Y%m%d')}"

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if dataclasses.is_dataclass(value):
            value = dataclasses.asdict(value)
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, datetime.datetime):
            return cls._format_utc(value)
        if isinstance(value, datetime.date):
            return value.isoformat()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def _json_clone(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))
