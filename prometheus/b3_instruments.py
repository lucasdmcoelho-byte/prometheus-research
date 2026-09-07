from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
from xml.etree import ElementTree


TICKER = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(element: ElementTree.Element, *names: str) -> str:
    wanted = set(names)
    for child in element.iter():
        if _local(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


@dataclass(frozen=True)
class B3Instrument:
    ticker: str
    corporation_name: str
    isin: str
    specification_code: str
    market: str
    segment: str
    source_member: str


@dataclass(frozen=True)
class B3InstrumentSnapshot:
    reference_date: str
    source_sha256: str
    instruments: tuple[B3Instrument, ...]

    def equities(self) -> tuple[B3Instrument, ...]:
        return tuple(item for item in self.instruments if TICKER.fullmatch(item.ticker))


def parse_bvbg028_zip(path: str | Path) -> B3InstrumentSnapshot:
    """Parse a point-in-time B3 BVBG.028.02 ZIP without discarding raw identity.

    The B3 file deliberately does not supply CNPJ or CVM code. Those fields must
    be joined from a separately reviewed mapping and verified against CVM.
    """
    source = Path(path)
    raw = source.read_bytes()
    records: List[B3Instrument] = []
    reference_dates: set[str] = set()
    with zipfile.ZipFile(source) as archive:
        xml_sources: list[tuple[str, zipfile.ZipFile, str]] = []
        owned_archives: list[zipfile.ZipFile] = []
        for name in sorted(archive.namelist()):
            if name.lower().endswith(".xml"):
                xml_sources.append((name, archive, name))
            elif name.lower().endswith(".zip"):
                nested = zipfile.ZipFile(io.BytesIO(archive.read(name)))
                owned_archives.append(nested)
                xml_sources.extend((f"{name}!{inner}", nested, inner) for inner in sorted(nested.namelist()) if inner.lower().endswith(".xml"))
        if not xml_sources:
            raise ValueError("BVBG.028.02 archive contains no XML member")
        try:
            for label, container, member in xml_sources:
                with container.open(member) as stream:
                    for event, element in ElementTree.iterparse(stream, events=("end",)):
                        local = _local(element.tag)
                        if local == "Dt" and element.text:
                            reference_dates.add(element.text.strip())
                        if local not in {"EqtyInf", "EquityInformation"}:
                            continue
                        ticker = _first_text(element, "TckrSymb", "TickerSymbol").upper()
                        if ticker:
                            records.append(B3Instrument(
                                ticker=ticker,
                                corporation_name=_first_text(element, "CrpnNm", "CorporationName"),
                                isin=_first_text(element, "ISIN"),
                                specification_code=_first_text(element, "SpcfctnCd", "SpecificationCode"),
                                market="", segment="", source_member=label,
                            ))
                        element.clear()
        finally:
            for nested in owned_archives:
                nested.close()
    if len(reference_dates) > 1:
        raise ValueError("BVBG.028.02 archive mixes reference dates")
    if not records:
        raise ValueError("BVBG.028.02 archive contains no equity instruments")
    return B3InstrumentSnapshot(
        reference_date=next(iter(reference_dates), ""),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        instruments=tuple(dict.fromkeys(records)),
    )


def audit_reviewed_tickers(snapshot: B3InstrumentSnapshot, reviewed: Iterable[dict]) -> dict:
    by_ticker: dict[str, list[B3Instrument]] = {}
    for item in snapshot.equities():
        by_ticker.setdefault(item.ticker, []).append(item)
    results = []
    for row in reviewed:
        ticker = str(row.get("ticker") or "").strip().upper()
        matches = by_ticker.get(ticker, [])
        reasons = []
        if not matches:
            reasons.append("TICKER_NOT_IN_B3_SNAPSHOT")
        if len(matches) > 1:
            identities = {(m.corporation_name, m.isin, m.specification_code) for m in matches}
            if len(identities) > 1:
                reasons.append("AMBIGUOUS_B3_IDENTITY")
        expected_name = str(row.get("b3_corporation_name") or "").strip()
        expected_isin = str(row.get("isin") or "").strip().upper()
        if matches and expected_name and all(m.corporation_name != expected_name for m in matches):
            reasons.append("B3_CORPORATION_NAME_MISMATCH")
        if matches and expected_isin and all(m.isin.upper() != expected_isin for m in matches):
            reasons.append("ISIN_MISMATCH")
        results.append({"ticker": ticker, "status": "PASS" if not reasons else "FAIL", "reasons": reasons})
    failures = [row for row in results if row["status"] == "FAIL"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "reference_date": snapshot.reference_date,
        "source_sha256": snapshot.source_sha256,
        "b3_equity_count": len(snapshot.equities()),
        "reviewed_count": len(results),
        "failures": failures,
        "instruments": results,
    }
