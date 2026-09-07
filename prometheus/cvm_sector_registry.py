from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from prometheus.issuer_registry import CVM_REGISTRY_URL


class CVMSectorRegistry:
    """Read the official CVM activity sector without leaking a future registry.

    Historical resolution uses the structured FCA archive. A classification is
    considered knowable only from ``DT_RECEB`` onward; ``Data_Referencia`` is
    retained as the form's reference date but is never used to backdate the
    information. The daily company registry remains a current-snapshot fallback
    and is still rejected when its file timestamp is after the requested cutoff.
    """

    FCA_BASE_URL = (
        "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/"
        "fca_cia_aberta_{year}.zip"
    )

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        timeout_seconds: float = 30.0,
        cache_ttl_seconds: float = 86_400.0,
        first_history_year: int = 2010,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.path = self.cache_dir / "cad_cia_aberta.csv" if self.cache_dir else None
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.first_history_year = int(first_history_year)
        self._parsed_fca: Dict[int, List[Dict[str, Any]]] = {}
        self._failed_refresh_urls: set[str] = set()

    def lookup(self, cvm_code: str, as_of: dt.datetime) -> Dict[str, Any]:
        historical = self._historical_lookup(cvm_code, as_of)
        if historical.get("status") == "AVAILABLE":
            return historical
        current = self._current_snapshot_lookup(cvm_code, as_of)
        if current.get("status") == "AVAILABLE":
            return current
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": current.get("reason") or historical.get("reason") or "SECTOR_CLASSIFICATION_NOT_FOUND",
            "historical_reason": historical.get("reason"),
            "current_snapshot_reason": current.get("reason"),
        }

    def _current_snapshot_lookup(self, cvm_code: str, as_of: dt.datetime) -> Dict[str, Any]:
        if not self.path or not self.path.is_file():
            return {"status": "INSUFFICIENT_DATA", "reason": "CVM_REGISTRY_NOT_CACHED"}
        available_at = dt.datetime.fromtimestamp(self.path.stat().st_mtime)
        cutoff = as_of.replace(tzinfo=None)
        if available_at > cutoff:
            return {
                "status": "INSUFFICIENT_DATA", "reason": "REGISTRY_SNAPSHOT_AFTER_CUTOFF",
                "available_at": available_at.isoformat(),
            }
        with self.path.open("r", encoding="latin-1", newline="") as handle:
            row = next((item for item in csv.DictReader(handle, delimiter=";") if str(item.get("CD_CVM") or "").strip().lstrip("0") == str(cvm_code).strip().lstrip("0")), None)
        if not row or str(row.get("SIT") or "").strip().upper() != "ATIVO":
            return {"status": "INSUFFICIENT_DATA", "reason": "ACTIVE_ISSUER_NOT_FOUND"}
        sector = " ".join(str(row.get("SETOR_ATIV") or "").split())
        if not sector:
            return {"status": "INSUFFICIENT_DATA", "reason": "CVM_ACTIVITY_SECTOR_MISSING"}
        return {
            "status": "AVAILABLE", "sector": sector, "company_name": row.get("DENOM_SOCIAL"),
            "cvm_code": str(cvm_code).strip().lstrip("0"), "available_at": available_at.isoformat(),
            "source": "Cadastro de Companhias Abertas CVM", "source_url": CVM_REGISTRY_URL,
            "classification_method": "SETOR_ATIV exact official current-snapshot field",
        }

    def _historical_lookup(self, cvm_code: str, as_of: dt.datetime) -> Dict[str, Any]:
        if self.cache_dir is None:
            return {"status": "INSUFFICIENT_DATA", "reason": "FCA_CACHE_NOT_CONFIGURED"}
        cutoff = as_of.replace(tzinfo=None)
        normalized_code = str(cvm_code).strip().lstrip("0")
        candidates: List[Dict[str, Any]] = []
        # FCA is periodic and annual; a three-year lookback is deliberately
        # conservative while avoiding a network request for every archive back
        # to 2010 on each newly configured installation.
        first_year = max(self.first_history_year, cutoff.year - 2)
        for year in range(first_year, cutoff.year + 1):
            try:
                candidates.extend(
                    row for row in self._load_fca_year(year)
                    if row["cvm_code"] == normalized_code
                )
            except Exception:
                continue
        eligible = [
            row for row in candidates
            if row["received_at"] <= cutoff
            and row["reference_date"] <= cutoff.date()
            and row.get("sector")
        ]
        if not eligible:
            return {
                "status": "INSUFFICIENT_DATA",
                "reason": "NO_FCA_SECTOR_AVAILABLE_AT_CUTOFF",
            }
        chosen = max(
            eligible,
            key=lambda row: (row["received_at"], row["reference_date"], row["version"]),
        )
        later = sorted(
            {
                row["received_at"] for row in candidates
                if row["received_at"] > chosen["received_at"]
            }
        )
        return {
            "status": "AVAILABLE",
            "sector": chosen["sector"],
            "company_name": chosen.get("company_name"),
            "cvm_code": normalized_code,
            "available_at": chosen["received_at"].isoformat(),
            "valid_from": chosen["received_at"].isoformat(),
            "valid_to": later[0].isoformat() if later else None,
            "reference_date": chosen["reference_date"].isoformat(),
            "version": str(chosen["version"]),
            "document_id": chosen.get("document_id"),
            "source": "CVM Formulário Cadastral (FCA) estruturado",
            "source_url": chosen["source_url"],
            "document_url": chosen.get("document_url"),
            "source_sha256": chosen["source_sha256"],
            "classification_method": (
                "latest official FCA Setor_Atividade with DT_RECEB <= cutoff; "
                "validity starts conservatively at DT_RECEB"
            ),
        }

    def _load_fca_year(self, year: int) -> List[Dict[str, Any]]:
        if year in self._parsed_fca:
            return self._parsed_fca[year]
        url = self.FCA_BASE_URL.format(year=int(year))
        archive = self._download(url)
        archive_hash = hashlib.sha256(archive).hexdigest()
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            metadata_name = self._member(zipped, f"fca_cia_aberta_{year}.csv")
            general_name = self._member(zipped, f"fca_cia_aberta_geral_{year}.csv")
            metadata = {
                str(row.get("ID_DOC") or "").strip(): row
                for row in self._csv_rows(zipped.read(metadata_name))
            }
            parsed: List[Dict[str, Any]] = []
            for row in self._csv_rows(zipped.read(general_name)):
                document_id = str(row.get("ID_Documento") or "").strip()
                document = metadata.get(document_id) or {}
                received_at = self._datetime(document.get("DT_RECEB"))
                reference_date = self._date(row.get("Data_Referencia"))
                if not received_at or not reference_date:
                    continue
                parsed.append({
                    "cvm_code": str(row.get("Codigo_CVM") or "").strip().lstrip("0"),
                    "company_name": " ".join(str(row.get("Nome_Empresarial") or "").split()),
                    "sector": " ".join(str(row.get("Setor_Atividade") or "").split()),
                    "reference_date": reference_date,
                    "received_at": received_at,
                    "version": self._integer(row.get("Versao")),
                    "document_id": document_id,
                    "document_url": document.get("LINK_DOC"),
                    "source_url": url,
                    "source_sha256": archive_hash,
                })
        self._parsed_fca[year] = parsed
        return parsed

    def _download(self, url: str) -> bytes:
        if self.cache_dir is None:
            raise OSError("FCA cache is not configured")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / url.rsplit("/", 1)[-1]
        cache_age = time.time() - cache_path.stat().st_mtime if cache_path.exists() else None
        if cache_age is not None and cache_age <= self.cache_ttl_seconds:
            return cache_path.read_bytes()
        if url in self._failed_refresh_urls:
            if cache_path.is_file():
                return cache_path.read_bytes()
            raise OSError(f"previous refresh failed for {url}")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "PROMETHEUS/2.1 research@example.invalid"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except Exception:
            self._failed_refresh_urls.add(url)
            if cache_path.is_file():
                return cache_path.read_bytes()
            raise
        cache_path.write_bytes(payload)
        return payload

    @staticmethod
    def _member(zipped: zipfile.ZipFile, expected: str) -> str:
        match = next(
            (name for name in zipped.namelist() if name.replace("\\", "/").rsplit("/", 1)[-1].lower() == expected.lower()),
            None,
        )
        if not match:
            raise ValueError(f"FCA archive member missing: {expected}")
        return match

    @staticmethod
    def _csv_rows(payload: bytes) -> csv.DictReader:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = payload.decode("latin-1")
        return csv.DictReader(io.StringIO(text), delimiter=";")

    @staticmethod
    def _datetime(value: Any) -> Optional[dt.datetime]:
        try:
            return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _date(value: Any) -> Optional[dt.date]:
        try:
            return dt.date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value: Any) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    def peer_candidates(
        self, activity_sector: str, ticker_to_cvm: Dict[str, str], target_cvm_code: str,
        as_of: dt.datetime, limit: int = 6, target_ticker: Optional[str] = None,
    ) -> list[Dict[str, str]]:
        normalized_target = str(target_cvm_code).strip().lstrip("0")
        candidates = []
        seen_codes = {normalized_target}
        target_class = self._ticker_class(target_ticker)
        for ticker, code in sorted(
            ticker_to_cvm.items(), key=lambda item: self._ticker_priority(item[0], target_class),
        ):
            normalized_code = str(code).strip().lstrip("0")
            if normalized_code in seen_codes:
                continue
            classification = self.lookup(normalized_code, as_of)
            if classification.get("status") != "AVAILABLE":
                continue
            if " ".join(str(classification.get("sector") or "").split()) != activity_sector:
                continue
            seen_codes.add(normalized_code)
            same_class = bool(target_class and self._ticker_class(ticker) == target_class)
            candidates.append({
                "ticker": ticker, "cvm_code": normalized_code,
                "company": " ".join(str(classification.get("company_name") or "").split()),
                "activity_sector": activity_sector,
                "classification_source": classification.get("source"),
                "classification_source_sha256": classification.get("source_sha256"),
                "classification_valid_from": classification.get("valid_from"),
                "classification_valid_to": classification.get("valid_to"),
                "selection_reason": (
                    "Mesmo SETOR_ATIV oficial da CVM; emissor único; mesma classe de instrumento"
                    if same_class else "Mesmo SETOR_ATIV oficial da CVM; emissor único"
                ),
            })
            if len(candidates) >= max(1, int(limit)):
                break
        return candidates

    @staticmethod
    def _ticker_class(ticker: Optional[str]) -> Optional[str]:
        match = re.search(r"(11|3|4)$", str(ticker or "").upper())
        return match.group(1) if match else None

    @classmethod
    def _ticker_priority(cls, ticker: str, target_class: Optional[str] = None) -> tuple:
        suffix = cls._ticker_class(ticker)
        same_class_priority = 0 if target_class and suffix == target_class else 1
        class_priority = {"3": 0, "4": 1, "11": 2}.get(suffix, 3)
        return same_class_priority, class_priority, str(ticker)
