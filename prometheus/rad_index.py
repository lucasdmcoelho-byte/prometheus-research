from __future__ import annotations

import datetime as dt
import hashlib
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional


class _RADResultsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: List[Dict[str, Any]] = []
        self._row: Optional[Dict[str, Any]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs):
        attributes = dict(attrs)
        if tag.lower() == "tr":
            self._row = {"cells": [], "actions": []}
        elif tag.lower() == "td" and self._row is not None:
            self._cell = []
        elif self._row is not None and attributes.get("onclick"):
            self._row["actions"].append(attributes["onclick"])

    def handle_data(self, data: str):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() == "td" and self._row is not None and self._cell is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row["cells"]:
                self.rows.append(self._row)
            self._row = None


def parse_rad_query_html(payload: bytes, source_url: str, captured_at: dt.datetime) -> Dict[str, Any]:
    """Parse an official RAD result-table export into the immutable local index.

    Only DFP and ITR rows with a structured ENET document sequence and protocol
    are accepted. Unknown or incomplete rows are ignored rather than guessed.
    """
    text = _decode(payload)
    parser = _RADResultsParser()
    parser.feed(text)
    documents = []
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) < 10:
            continue
        filing_type = _filing_type(cells[2])
        if not filing_type:
            continue
        action_text = " ".join(row["actions"])
        sequence_match = re.search(r"(?:NumeroSequencialDocumento=|OpenDownloadDocumentos\(['\"])(\d+)", action_text, re.I)
        protocol_match = re.search(r"OpenDownloadDocumentos\(['\"]\d+['\"]\s*,\s*['\"]\d+['\"]\s*,\s*['\"]([^'\"]+)", action_text, re.I)
        reference_date = _date_br(cells[5])
        received_at = _datetime_br(cells[6])
        if not sequence_match or not protocol_match or not reference_date or not received_at:
            continue
        cvm_code = re.sub(r"\D", "", cells[0]).lstrip("0")
        if not cvm_code:
            continue
        documents.append({
            "cvm_code": cvm_code,
            "company_name": cells[1],
            "filing_type": filing_type,
            "reference_date": reference_date.isoformat(),
            "received_at": received_at.isoformat(),
            "version": cells[8] or None,
            "sequence": sequence_match.group(1),
            "status": cells[7].upper(),
            "modality": cells[9].upper(),
            "protocol": protocol_match.group(1),
        })
    unique = {
        (document["cvm_code"], document["filing_type"], document["reference_date"], document["version"], document["sequence"]): document
        for document in documents
    }
    return {
        "schema_version": 1,
        "captured_at": captured_at.replace(tzinfo=None).isoformat(),
        "source_url": source_url,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "method": "Official RAD result table; exact document sequence and protocol; no name inference",
        "documents": sorted(
            unique.values(),
            key=lambda item: (item["cvm_code"], item["reference_date"], item["received_at"], int(item["version"] or 0)),
        ),
    }


def _filing_type(category: str) -> Optional[str]:
    normalized = " ".join(category.upper().split())
    if normalized.startswith("DFP -"):
        return "DFP"
    if normalized.startswith("ITR -"):
        return "ITR"
    return None


def _date_br(value: str) -> Optional[dt.date]:
    match = re.search(r"\d{2}/\d{2}/\d{4}", value or "")
    try:
        return dt.datetime.strptime(match.group(0), "%d/%m/%Y").date() if match else None
    except ValueError:
        return None


def _datetime_br(value: str) -> Optional[dt.datetime]:
    match = re.search(r"\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?", value or "")
    if not match:
        return None
    text = match.group(0)
    for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")
