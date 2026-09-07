from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from prometheus.data_engine import validate_ticker
from prometheus.editorial_gate import EditorialGate


class DeliveryWorkflow:
    """Append-only order and approval ledger for commercial report delivery."""

    VALID_STATES = ("REQUESTED", "GENERATED", "IN_REVIEW", "APPROVED", "DELIVERED", "CORRECTION_REQUESTED", "REJECTED")
    TRANSITIONS = {
        "REQUESTED": {"GENERATED", "REJECTED"}, "GENERATED": {"IN_REVIEW", "REJECTED"},
        "IN_REVIEW": {"APPROVED", "REJECTED"}, "APPROVED": {"DELIVERED"},
        "DELIVERED": {"CORRECTION_REQUESTED"}, "CORRECTION_REQUESTED": {"GENERATED", "REJECTED"}, "REJECTED": set(),
    }
    _process_lock_guard = threading.Lock()
    _process_locks: Dict[str, threading.RLock] = {}

    def __init__(self, ledger_path: str):
        self.ledger_path = Path(ledger_path)

    def create_order(self, ticker: str, client_reference: str, as_of: str, notes: str = "") -> Dict[str, Any]:
        normalized_ticker = validate_ticker(ticker).upper()
        if not str(client_reference).strip():
            raise ValueError("client_reference is required")
        try:
            datetime.strptime(str(as_of), "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("as_of must use YYYY-MM-DD") from error
        order = {
            "order_id": f"ORD-{uuid.uuid4().hex[:12].upper()}", "ticker": normalized_ticker,
            "client_reference": str(client_reference).strip(), "as_of": as_of, "state": "REQUESTED",
            "notes": notes, "created_at": self._now(), "events": [], "artifacts": [],
            "version": 1,
        }
        order["events"].append(self._event(None, "REQUESTED", "system", "Pedido criado"))
        return self._append(order)

    def transition(
        self,
        order: Dict[str, Any],
        state: str,
        actor: str,
        notes: str = "",
        artifacts: Optional[List[str]] = None,
        conflict_declaration: str = "",
    ) -> Dict[str, Any]:
        target = state.upper()
        current = order.get("state")
        if target not in self.TRANSITIONS.get(current, set()):
            raise ValueError(f"Invalid transition: {current} -> {target}")
        latest = self.latest(str(order.get("order_id") or ""))
        if not latest or latest.get("entry_hash") != order.get("entry_hash"):
            raise ValueError("Stale or unverified order snapshot")
        if not str(actor).strip():
            raise ValueError("Named actor is required")
        if target in {"IN_REVIEW", "APPROVED", "DELIVERED", "CORRECTION_REQUESTED"} and not self._is_named_human(actor):
            raise ValueError(f"Named human actor is required for {target}")
        note_labels = {"APPROVED": "Approval", "DELIVERED": "Delivery", "REJECTED": "Rejection"}
        if target in note_labels and not str(notes).strip():
            raise ValueError(f"{note_labels[target]} notes are required")
        if target == "APPROVED" and not str(conflict_declaration).strip():
            raise ValueError("Conflict declaration is required for approval")
        if target == "GENERATED" and not artifacts:
            raise ValueError("Generated state requires at least one artifact")
        updated = json.loads(json.dumps(order))
        updated["state"] = target
        if current == "CORRECTION_REQUESTED" and target == "GENERATED":
            updated["version"] = int(updated.get("version", 1)) + 1
        updated["events"].append(
            self._event(current, target, actor, notes, conflict_declaration=conflict_declaration)
        )
        for artifact in artifacts or []:
            path = Path(artifact)
            if not path.is_file():
                raise ValueError(f"Artifact not found: {artifact}")
            updated["artifacts"].append({
                "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size, "recorded_at": self._now(),
                "version": int(updated.get("version", 1)),
            })
        if target in {"APPROVED", "DELIVERED"}:
            verification = self.verify_artifacts(updated, current_version_only=True)
            if verification["status"] != "PASS":
                raise ValueError("Current-version artifacts are missing or changed")
            bundle_verification = self.verify_release_bundle(updated)
            if bundle_verification["status"] != "PASS":
                raise ValueError(
                    "Research release bundle is not approvable: "
                    + "; ".join(bundle_verification["failures"])
                )
        return self._append(updated)

    def request_correction(self, order: Dict[str, Any], actor: str, reason: str) -> Dict[str, Any]:
        if not str(reason).strip():
            raise ValueError("Correction reason is required")
        return self.transition(order, "CORRECTION_REQUESTED", actor, reason)

    def latest(self, order_id: str) -> Optional[Dict[str, Any]]:
        matches = [item for item in self._read() if item.get("order_id") == order_id]
        return matches[-1] if matches else None

    def verify_artifacts(self, order: Dict[str, Any], current_version_only: bool = False) -> Dict[str, Any]:
        failures = []
        artifacts = order.get("artifacts") or []
        if current_version_only:
            version = int(order.get("version", 1))
            artifacts = [item for item in artifacts if int(item.get("version", 1)) == version]
            if not artifacts:
                failures.append(f"NO_ARTIFACTS_FOR_VERSION_{version}")
        for artifact in artifacts:
            path = Path(artifact["path"])
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            actual_size = path.stat().st_size if path.is_file() else None
            if actual != artifact.get("sha256") or actual_size != artifact.get("size"):
                failures.append(artifact["path"])
        return {"status": "PASS" if not failures else "FAIL", "failures": failures}

    def write_release_bundle(
        self,
        order: Dict[str, Any],
        report: Dict[str, Any],
        pdf_path: str,
        pdf_metadata: Dict[str, Any],
        destination: Optional[str] = None,
    ) -> str:
        """Persist the immutable content snapshot later reviewed by a human.

        The bundle may be created while blocked so an analyst can inspect it, but
        ``APPROVED`` is refused unless a fresh gate evaluation is blocker-free.
        """
        path = Path(pdf_path)
        if not path.is_file():
            raise ValueError(f"PDF artifact not found: {pdf_path}")
        bundle_path = Path(destination) if destination else path.with_suffix(".bundle.json")
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        live_gate = EditorialGate().evaluate(report)
        bundle_version = int(order.get("version", 1)) + (
            1 if order.get("state") == "CORRECTION_REQUESTED" else 0
        )
        payload = {
            "schema": "prometheus.research_release_bundle.v1",
            "order_id": order.get("order_id"),
            "ticker": report.get("ticker"),
            "as_of": str(report.get("analysis_as_of") or "")[:10],
            "version": bundle_version,
            "generated_at": self._now(),
            "pdf": {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
                "metadata": pdf_metadata,
            },
            "editorial_gate_snapshot": live_gate,
            "analysis": report,
        }
        bundle_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return str(bundle_path.resolve())

    def verify_release_bundle(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Recompute editorial eligibility from the exact current-version bundle."""
        failures: List[str] = []
        version = int(order.get("version", 1))
        current_artifacts = [
            item for item in order.get("artifacts") or []
            if int(item.get("version", 1)) == version
        ]
        bundles: List[Dict[str, Any]] = []
        for artifact in current_artifacts:
            path = Path(str(artifact.get("path") or ""))
            if path.suffix.lower() != ".json" or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if payload.get("schema") == "prometheus.research_release_bundle.v1":
                bundles.append(payload)
        if len(bundles) != 1:
            failures.append(f"EXPECTED_ONE_RELEASE_BUNDLE_FOUND_{len(bundles)}")
            return {"status": "FAIL", "failures": failures}

        bundle = bundles[0]
        report = bundle.get("analysis") or {}
        if bundle.get("order_id") != order.get("order_id"):
            failures.append("BUNDLE_ORDER_MISMATCH")
        if bundle.get("ticker") != order.get("ticker") or report.get("ticker") != order.get("ticker"):
            failures.append("BUNDLE_TICKER_MISMATCH")
        report_cutoff = str(report.get("analysis_as_of") or "")[:10]
        if bundle.get("as_of") != order.get("as_of") or report_cutoff != order.get("as_of"):
            failures.append("BUNDLE_CUTOFF_MISMATCH")
        if int(bundle.get("version", 0)) != version:
            failures.append("BUNDLE_VERSION_MISMATCH")

        pdf = bundle.get("pdf") or {}
        pdf_path = Path(str(pdf.get("path") or ""))
        pdf_artifact = next(
            (item for item in current_artifacts if Path(str(item.get("path") or "")).resolve() == pdf_path.resolve()),
            None,
        )
        if not pdf_artifact or not pdf_path.is_file():
            failures.append("BUNDLE_PDF_NOT_RECORDED")
        else:
            actual_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            if actual_hash != pdf.get("sha256") or actual_hash != pdf_artifact.get("sha256"):
                failures.append("BUNDLE_PDF_HASH_MISMATCH")
            if pdf_path.stat().st_size != pdf.get("size"):
                failures.append("BUNDLE_PDF_SIZE_MISMATCH")

        metadata = pdf.get("metadata") or {}
        if metadata.get("qa_status") not in {"pass", "warning"}:
            failures.append("PDF_QA_NOT_PASSED")
        live_gate = EditorialGate().evaluate(report)
        if live_gate.get("blockers"):
            failures.extend(
                f"LIVE_EDITORIAL_BLOCKER:{item.get('code')}" for item in live_gate.get("blockers") or []
            )
        if live_gate.get("status") != "APPROVAL_REQUIRED":
            failures.append(f"LIVE_EDITORIAL_STATUS:{live_gate.get('status')}")
        snapshot_codes = sorted(
            item.get("code") for item in (bundle.get("editorial_gate_snapshot") or {}).get("blockers") or []
        )
        live_codes = sorted(item.get("code") for item in live_gate.get("blockers") or [])
        if snapshot_codes != live_codes:
            failures.append("EDITORIAL_SNAPSHOT_STALE")
        return {
            "status": "PASS" if not failures else "FAIL",
            "failures": sorted(set(failures)),
            "ticker": report.get("ticker"),
            "as_of": report_cutoff,
            "version": version,
            "live_editorial_status": live_gate.get("status"),
        }

    def verify_ledger(self) -> Dict[str, Any]:
        failures: List[str] = []
        entries = self._read()
        previous_hash = None
        latest_by_order: Dict[str, Dict[str, Any]] = {}
        immutable_fields = ("ticker", "client_reference", "as_of", "created_at")
        for index, entry in enumerate(entries, start=1):
            entry_hash = entry.get("entry_hash")
            if entry.get("ledger_sequence") != index:
                failures.append(f"sequence:{index}")
            if entry.get("previous_entry_hash") != previous_hash:
                failures.append(f"previous_hash:{index}")
            if not entry_hash or entry_hash != self._entry_hash(entry):
                failures.append(f"entry_hash:{index}")
            order_id = str(entry.get("order_id") or "")
            previous = latest_by_order.get(order_id)
            if previous is None:
                if entry.get("state") != "REQUESTED" or len(entry.get("events") or []) != 1:
                    failures.append(f"invalid_initial_state:{order_id}")
            else:
                for field in immutable_fields:
                    if entry.get(field) != previous.get(field):
                        failures.append(f"mutated_{field}:{order_id}")
                events = entry.get("events") or []
                previous_events = previous.get("events") or []
                if events[:-1] != previous_events or len(events) != len(previous_events) + 1:
                    failures.append(f"event_history:{order_id}")
                transition = events[-1] if events else {}
                if transition.get("from") != previous.get("state") or transition.get("to") != entry.get("state"):
                    failures.append(f"event_transition:{order_id}")
                if entry.get("state") not in self.TRANSITIONS.get(previous.get("state"), set()):
                    failures.append(f"invalid_transition:{order_id}")
                target = str(entry.get("state") or "")
                actor = str(transition.get("actor") or "")
                if target in {"IN_REVIEW", "APPROVED", "DELIVERED", "CORRECTION_REQUESTED"} and not self._is_named_human(actor):
                    failures.append(f"unnamed_actor:{order_id}:{target}")
                if target in {"APPROVED", "DELIVERED", "REJECTED", "CORRECTION_REQUESTED"} and not str(transition.get("notes") or "").strip():
                    failures.append(f"missing_notes:{order_id}:{target}")
                # Legacy ledgers predate the conflict-declaration field. New
                # approvals are required to record it in ``transition``;
                # historical entries remain verifiable for hash compatibility.
                expected_version = int(previous.get("version", 1)) + (1 if previous.get("state") == "CORRECTION_REQUESTED" and entry.get("state") == "GENERATED" else 0)
                if int(entry.get("version", 0)) != expected_version:
                    failures.append(f"version:{order_id}")
                if len(entry.get("artifacts") or []) < len(previous.get("artifacts") or []):
                    failures.append(f"artifact_history:{order_id}")
            for artifact in entry.get("artifacts") or []:
                if not isinstance(artifact.get("sha256"), str) or len(artifact.get("sha256")) != 64:
                    failures.append(f"artifact_hash:{order_id}")
                if not isinstance(artifact.get("size"), int) or artifact.get("size") < 0:
                    failures.append(f"artifact_size:{order_id}")
                if int(artifact.get("version", 0)) < 1:
                    failures.append(f"artifact_version:{order_id}")
            if not order_id:
                failures.append(f"missing_order_id:{index}")
            latest_by_order[order_id] = entry
            previous_hash = entry_hash
        return {
            "status": "PASS" if not failures else "FAIL",
            "entry_count": len(entries), "order_count": len(latest_by_order),
            "head_hash": previous_hash, "failures": sorted(set(failures)),
        }

    def _append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_lock():
            existing = self._read()
            stored = json.loads(json.dumps(entry))
            stored.pop("entry_hash", None)
            stored["ledger_sequence"] = len(existing) + 1
            stored["previous_entry_hash"] = existing[-1].get("entry_hash") if existing else None
            stored["entry_hash"] = self._entry_hash(stored)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(stored, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return stored

    @contextmanager
    def _ledger_lock(self):
        """Serialize append operations across processes on Windows and POSIX."""
        lock_path = self.ledger_path.with_suffix(self.ledger_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_key = str(lock_path.resolve())
        with self._process_lock_guard:
            process_lock = self._process_locks.setdefault(lock_key, threading.RLock())
        # msvcrt byte-range locks conflict between separate handles in the same
        # Python process.  The process lock serializes threads first; the OS
        # lock still protects independent processes.
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

    def _read(self) -> List[Dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        return [json.loads(line) for line in self.ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _entry_hash(entry: Dict[str, Any]) -> str:
        payload = dict(entry)
        payload.pop("entry_hash", None)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_named_human(actor: str) -> bool:
        normalized = str(actor).strip().lower().replace(" ", "_")
        return bool(normalized) and normalized not in {"system", "prometheus", "pending", "pending_reviewer", "unknown", "n/a"}

    @staticmethod
    def _event(
        previous: Optional[str],
        current: str,
        actor: str,
        notes: str,
        conflict_declaration: str = "",
    ) -> Dict[str, Any]:
        event = {"from": previous, "to": current, "actor": actor, "notes": notes, "at": DeliveryWorkflow._now()}
        if current == "APPROVED":
            event["conflict_declaration"] = str(conflict_declaration).strip()
        return event

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
