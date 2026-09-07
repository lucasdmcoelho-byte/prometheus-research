from __future__ import annotations

import datetime as dt
import hashlib
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


B3_COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"


def load_market_observations(
    archive_path: str | Path,
    tickers: Optional[Iterable[str]] = None,
    captured_at: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Load the official annual archive once for repeatable point-in-time queries."""
    path = Path(archive_path)
    with path.open("rb") as source:
        payload_hash = hashlib.file_digest(source, "sha256").hexdigest()
    wanted = {str(item).strip().upper() for item in tickers} if tickers else None
    records: Dict[str, list[Dict[str, Any]]] = {}
    with zipfile.ZipFile(path) as zipped:
        names = [name for name in zipped.namelist() if name.upper().endswith(".TXT")]
        if len(names) != 1:
            raise ValueError("COTAHIST archive must contain exactly one TXT file")
        with zipped.open(names[0]) as handle:
            for raw in handle:
                line = raw.decode("latin-1").rstrip("\r\n")
                if len(line) < 245 or line[:2] != "01" or line[24:27] != "010":
                    continue
                ticker = line[12:24].strip().upper()
                if wanted is not None and ticker not in wanted:
                    continue
                try:
                    trade_date = dt.datetime.strptime(line[2:10], "%Y%m%d").date()
                    values = {
                        "open": _numeric_field(line[56:69], 100.0),
                        "high": _numeric_field(line[69:82], 100.0),
                        "low": _numeric_field(line[82:95], 100.0),
                        "close": _numeric_field(line[108:121], 100.0),
                        "volume": _numeric_field(line[152:170], 1.0),
                    }
                except ValueError:
                    continue
                if values["close"] <= 0:
                    continue
                row = {
                    "date": trade_date, **values,
                    "record_sha256": hashlib.sha256(line.encode("latin-1")).hexdigest(),
                }
                existing = next((item for item in records.get(ticker, []) if item["date"] == trade_date), None)
                if existing and existing["close"] != row["close"]:
                    raise ValueError(f"Conflicting COTAHIST closes for {ticker} on {trade_date.isoformat()}")
                if not existing:
                    records.setdefault(ticker, []).append(row)
    for rows in records.values():
        rows.sort(key=lambda item: item["date"])
    retrieved = (captured_at or dt.datetime.fromtimestamp(path.stat().st_mtime)).replace(tzinfo=None)
    return {
        "source_sha256": payload_hash,
        "captured_at": retrieved,
        "records": records,
    }


def snapshots_from_observations(observations: Dict[str, Any], as_of: dt.datetime) -> Dict[str, Dict[str, Any]]:
    """Select the latest conservatively available close for an arbitrary cutoff."""
    cutoff = as_of.replace(tzinfo=None)
    snapshots: Dict[str, Dict[str, Any]] = {}
    for ticker, all_rows in (observations.get("records") or {}).items():
        rows = [
            row for row in all_rows
            if dt.datetime.combine(row["date"] + dt.timedelta(days=1), dt.time()) <= cutoff
        ]
        if not rows:
            continue
        latest = rows[-1]
        previous = rows[-2] if len(rows) > 1 else None
        snapshots[ticker] = {
            "effective_at": f"{latest['date'].isoformat()}T18:00:00-03:00",
            "available_at": f"{(latest['date'] + dt.timedelta(days=1)).isoformat()}T00:00:00-03:00",
            "captured_at": observations["captured_at"].isoformat(),
            "close": latest["close"],
            "previous_close": previous["close"] if previous else None,
            "currency": "BRL",
            "source": "B3 COTAHIST oficial",
            "source_url": B3_COTAHIST_URL.format(year=latest["date"].year),
            "source_sha256": observations["source_sha256"],
            "record_sha256": latest["record_sha256"],
            "revision_status": "official annual COTAHIST archive snapshot",
            "confidence": 1.0,
        }
    return snapshots


def build_market_snapshots(
    archive_path: str | Path,
    as_of: dt.datetime,
    tickers: Optional[Iterable[str]] = None,
    captured_at: Optional[dt.datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Derive auditable close observations from an official B3 COTAHIST ZIP."""
    observations = load_market_observations(archive_path, tickers=tickers, captured_at=captured_at)
    return snapshots_from_observations(observations, as_of)


def _numeric_field(value: str, divisor: float) -> float:
    sanitized = value.strip()
    return int(sanitized) / divisor if sanitized else 0.0
