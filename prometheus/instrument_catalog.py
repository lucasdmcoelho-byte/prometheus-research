from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


TICKER_PATTERN = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")


def normalize_cnpj(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(character for character in text if not unicodedata.combining(character)).upper().split())


@dataclass(frozen=True)
class InstrumentIdentity:
    ticker: str
    cvm_code: str
    cnpj: str
    company_name: str
    ticker_source: str
    ticker_source_date: str
    validated_at: str
    isin: str = ""
    specification_code: str = ""
    research_eligible: bool = True
    eligibility_reason: str = "PRIMARY_EQUITY"
    b3_issuer_cnpj: str = ""
    identity_match_method: str = "EXACT_CNPJ"


class InstrumentCatalog:
    """Versioned ticker identities whose issuer side is verified against CVM.

    The ticker itself must come from a reviewed B3 instrument source. CVM code,
    CNPJ and legal name are checked atomically; a mismatch rejects the entry.
    """

    def __init__(self, instruments: Iterable[InstrumentIdentity], metadata: Dict[str, Any] | None = None):
        self.instruments = tuple(instruments)
        self.metadata = dict(metadata or {})
        tickers = [item.ticker for item in self.instruments]
        if len(tickers) != len(set(tickers)):
            raise ValueError("Duplicate ticker in instrument catalog")

    @classmethod
    def load(cls, path: str | Path) -> "InstrumentCatalog":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("instruments"), list):
            raise ValueError("Instrument catalog must contain an instruments list")
        records = []
        for raw in payload["instruments"]:
            ticker = str(raw.get("ticker") or "").strip().upper()
            cvm_code = str(raw.get("cvm_code") or "").strip().lstrip("0")
            cnpj = normalize_cnpj(raw.get("cnpj"))
            source = str(raw.get("ticker_source") or "").strip()
            source_date = str(raw.get("ticker_source_date") or "").strip()
            if not TICKER_PATTERN.fullmatch(ticker):
                raise ValueError(f"Invalid B3 ticker in catalog: {ticker!r}")
            if not cvm_code.isdigit() or len(cnpj) != 14 or not source or not source_date:
                raise ValueError(f"Incomplete instrument identity for {ticker}")
            records.append(InstrumentIdentity(
                ticker=ticker, cvm_code=cvm_code, cnpj=cnpj,
                company_name=str(raw.get("company_name") or "").strip(),
                ticker_source=source, ticker_source_date=source_date,
                validated_at=str(raw.get("validated_at") or payload.get("generated_at") or "").strip(),
                isin=str(raw.get("isin") or "").strip().upper(),
                specification_code=str(raw.get("specification_code") or "").strip(),
                research_eligible=bool(raw.get("research_eligible", True)),
                eligibility_reason=str(raw.get("eligibility_reason") or "PRIMARY_EQUITY").strip(),
                b3_issuer_cnpj=normalize_cnpj(raw.get("b3_issuer_cnpj")),
                identity_match_method=str(raw.get("identity_match_method") or "EXACT_CNPJ").strip(),
            ))
        catalog = cls(records, {key: value for key, value in payload.items() if key != "instruments"})
        expected = payload.get("content_sha256")
        if expected and expected != catalog.content_sha256():
            legacy_fields = {"ticker", "cvm_code", "cnpj", "company_name", "ticker_source", "ticker_source_date", "validated_at"}
            legacy = [{key: value for key, value in asdict(item).items() if key in legacy_fields} for item in records]
            legacy_hash = hashlib.sha256(json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            if expected != legacy_hash:
                raise ValueError("Instrument catalog content hash mismatch")
        return catalog

    def mapping(self, eligible_only: bool = True) -> Dict[str, str]:
        return {item.ticker: item.cvm_code for item in self.instruments if item.research_eligible or not eligible_only}

    def content_sha256(self) -> str:
        canonical = json.dumps([asdict(item) for item in self.instruments], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def audit_against_cvm_csv(self, registry_path: str | Path) -> Dict[str, Any]:
        with Path(registry_path).open("r", encoding="latin-1", newline="") as handle:
            issuers = list(csv.DictReader(handle, delimiter=";"))
        by_code = {str(row.get("CD_CVM") or "").strip().lstrip("0"): row for row in issuers}
        failures: List[Dict[str, Any]] = []
        results = []
        for item in self.instruments:
            issuer = by_code.get(item.cvm_code)
            reasons = []
            if not issuer:
                reasons.append("CVM_CODE_NOT_FOUND")
            else:
                if str(issuer.get("SIT") or "").strip().upper() != "ATIVO":
                    reasons.append("ISSUER_NOT_ACTIVE")
                if normalize_cnpj(issuer.get("CNPJ_CIA")) != item.cnpj:
                    reasons.append("CNPJ_MISMATCH")
                if item.company_name and normalize_name(issuer.get("DENOM_SOCIAL")) != normalize_name(item.company_name):
                    reasons.append("COMPANY_NAME_MISMATCH")
            row = {"ticker": item.ticker, "cvm_code": item.cvm_code, "cnpj": item.cnpj, "status": "PASS" if not reasons else "FAIL", "reasons": reasons}
            results.append(row)
            if reasons:
                failures.append(row)
        return {"status": "PASS" if not failures else "FAIL", "instrument_count": len(results), "failures": failures, "instruments": results}

    def dump(self, path: str | Path) -> None:
        generated_at = self.metadata.get("generated_at") or datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        payload = {**self.metadata, "generated_at": generated_at, "content_sha256": self.content_sha256(), "instruments": [asdict(item) for item in self.instruments]}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
