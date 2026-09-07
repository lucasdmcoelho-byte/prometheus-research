from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import time
import http.client
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class CVMDisclosureClient:
    """Point-in-time metadata for CVM IPE disclosures and downloadable originals."""

    BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.zip"
    MATERIAL_CATEGORIES = {
        "Fato Relevante", "Comunicado ao Mercado", "Dados Econômico-Financeiros",
        "Apresentações a analistas/agentes do mercado", "Aviso aos Acionistas",
        "Política de Negociação", "Política de Divulgação",
    }

    def __init__(self, cache_dir: Optional[str] = None, timeout_seconds: float = 30.0, original_download_attempts: int = 4):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_seconds = timeout_seconds
        self.original_download_attempts = max(1, int(original_download_attempts))

    def load(
        self, cvm_code: str, as_of: dt.datetime, years: Optional[Iterable[int]] = None,
        limit: int = 100, include_content: bool = False, content_limit: int = 12,
    ) -> Dict[str, Any]:
        requested = list(years or range(max(2011, as_of.year - 2), as_of.year + 1))
        records = []
        for year in requested:
            try:
                payload = self._download(year)
            except Exception:
                continue
            records.extend(self._parse(payload, year, cvm_code, as_of))
        latest: Dict[tuple, Dict[str, Any]] = {}
        for record in records:
            key = (record["category"], record["type"], record["reference_date"], record["subject"])
            previous = latest.get(key)
            if previous is None or (record["delivered_at"], record["version"]) > (previous["delivered_at"], previous["version"]):
                latest[key] = record
        ordered = sorted(latest.values(), key=lambda item: item["delivered_at"], reverse=True)[:limit]
        if include_content:
            # A newest-first cap systematically starves quarterly releases when
            # debt, rating and corporate notices happen afterwards. Preserve the
            # public metadata order, but allocate retained-content slots to
            # operational releases/presentations first.
            content_order = sorted(ordered, key=self._content_priority)
            retained_ids = {id(record) for record in content_order[:max(0, int(content_limit))]}
            for record in ordered:
                if id(record) not in retained_ids:
                    record["raw_document_status"] = "NOT_RETAINED_LIMIT"
                    record["content_scope"] = "METADATA_ONLY_OUT_OF_SCOPE"
                    continue
                try:
                    record.update(self._retain_original(record))
                    record["content_scope"] = "ANALYSIS_INCLUDED"
                except Exception as error:
                    record.update({
                        # Metadata remains auditable through the signed IPE
                        # archive, but the unavailable original is explicitly
                        # outside analytical scope.  It can never support an
                        # extracted fact, KPI or claim.
                        "content_scope": "METADATA_ONLY_UNAVAILABLE",
                        "raw_document_status": "UNAVAILABLE",
                        "content_extraction_status": "UNAVAILABLE",
                        "content_error": type(error).__name__,
                    })
        return {
            "status": "AVAILABLE" if ordered else "INSUFFICIENT_DATA", "documents": ordered,
            "document_count": len(ordered), "cutoff": as_of.replace(microsecond=0).isoformat() + "Z",
            "categories": sorted({item["category"] for item in ordered}),
        }

    @staticmethod
    def _content_priority(record: Dict[str, Any]) -> tuple:
        subject = str(record.get("subject") or "").lower()
        operational = any(token in subject for token in (
            "press-release de resultados", "release de resultados", "apresenta", "teleconfer", "pr\u00e9via operacional", "previa operacional",
        ))
        return (0 if operational else 1, -int(str(record.get("delivered_at") or "").replace("-", "").replace("T", "").replace(":", "")[:14] or 0))

    def _retain_original(self, record: Dict[str, Any]) -> Dict[str, Any]:
        url = str(record.get("source_url") or "").strip()
        if not url:
            raise ValueError("document URL missing")
        payload, cache_path = self._download_original(
            url, str(record.get("protocol") or "document"), int(record.get("version") or 0),
        )
        digest = hashlib.sha256(payload).hexdigest()
        media_type = (
            "application/pdf" if payload.startswith(b"%PDF-")
            else "text/html" if b"<html" in payload[:1024].lower()
            else "text/plain"
        )
        text, extraction_status = self._extract_text(payload, media_type)
        maximum = 100_000
        truncated = len(text) > maximum
        retained_text = text[:maximum]
        return {
            "raw_document_status": "RETAINED",
            "raw_document_sha256": digest,
            "raw_document_size": len(payload),
            "raw_document_media_type": media_type,
            "raw_document_cache_path": str(cache_path.resolve()) if cache_path else None,
            "content_extraction_status": extraction_status,
            "extracted_text": retained_text,
            "extracted_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
            "extracted_text_characters": len(text),
            "extracted_text_truncated": truncated,
        }

    def _download_original(self, url: str, protocol: str, version: int) -> tuple[bytes, Optional[Path]]:
        cache_path = None
        if self.cache_dir:
            safe_protocol = re.sub(r"[^A-Za-z0-9_.-]+", "_", protocol).strip("_") or "document"
            url_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
            cache_path = self.cache_dir / "ipe_documents" / f"{safe_protocol}_v{version}_{url_key}.bin"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if cache_path.is_file():
                return cache_path.read_bytes(), cache_path
        payload = self._fetch_original(url)
        if cache_path:
            cache_path.write_bytes(payload)
        return payload, cache_path

    def _fetch_original(self, url: str) -> bytes:
        """Fetch an IPE original without ever retaining a truncated response.

        RAD occasionally closes a long response before ``read`` completes.  A
        raw artifact is only useful if its bytes are whole and hashable, so a
        failed attempt is discarded and retried from the beginning.  We do not
        silently accept a partial file or mark its metadata as retained.
        """
        request = urllib.request.Request(url, headers={"User-Agent": "PROMETHEUS/2.1 research@example.invalid"})
        last_error: Optional[Exception] = None
        for attempt in range(self.original_download_attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = response.read()
                    headers = getattr(response, "headers", None)
                    expected = headers.get("Content-Length") if headers else None
                if expected is not None and int(expected) != len(payload):
                    raise http.client.IncompleteRead(payload, int(expected) - len(payload))
                if not payload:
                    raise OSError("empty official disclosure response")
                return payload
            except (http.client.IncompleteRead, OSError, TimeoutError, ValueError) as error:
                last_error = error
                if attempt + 1 < self.original_download_attempts:
                    time.sleep(min(0.25 * (2 ** attempt), 1.0))
        raise last_error or OSError("official disclosure download failed")

    @staticmethod
    def _extract_text(payload: bytes, media_type: str) -> tuple[str, str]:
        if media_type == "application/pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(payload))
                text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
                return text, "EXTRACTED" if text else "NO_MACHINE_READABLE_TEXT"
            except Exception:
                return "", "EXTRACTION_ERROR"
        decoded = payload.decode("utf-8", errors="replace")
        if media_type == "text/html":
            decoded = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", decoded)
            decoded = re.sub(r"(?s)<[^>]+>", " ", decoded)
        return " ".join(decoded.split()), "EXTRACTED"

    def _download(self, year: int) -> bytes:
        url = self.BASE_URL.format(year=year)
        path = self.cache_dir / f"ipe_cia_aberta_{year}.zip" if self.cache_dir else None
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and time.time() - path.stat().st_mtime < 86400:
                return path.read_bytes()
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "PROMETHEUS/1.0 research@example.invalid"}), timeout=self.timeout_seconds) as response:
            payload = response.read()
        if path:
            path.write_bytes(payload)
        return payload

    def _parse(self, archive: bytes, year: int, cvm_code: str, as_of: dt.datetime) -> List[Dict[str, Any]]:
        archive_sha256 = hashlib.sha256(archive).hexdigest()
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            payload = zipped.read(f"ipe_cia_aberta_{year}.csv")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = payload.decode("latin-1")
        output = []
        cutoff = as_of.replace(tzinfo=None)
        for row in csv.DictReader(io.StringIO(text), delimiter=";"):
            if str(row.get("Codigo_CVM", "")).lstrip("0") != str(cvm_code).lstrip("0"):
                continue
            delivered = self._date(row.get("Data_Entrega"))
            if not delivered or delivered > cutoff:
                continue
            category = str(row.get("Categoria") or "").strip()
            if category not in self.MATERIAL_CATEGORIES:
                continue
            output.append({
                "company_name": row.get("Nome_Companhia"), "cnpj": row.get("CNPJ_Companhia"),
                "cvm_code": str(cvm_code), "reference_date": row.get("Data_Referencia"),
                "category": category, "type": row.get("Tipo"), "species": row.get("Especie"),
                "subject": row.get("Assunto"), "delivered_at": delivered.isoformat(),
                "presentation_type": row.get("Tipo_Apresentacao"), "protocol": row.get("Protocolo_Entrega"),
                "version": int(row.get("Versao") or 0), "source_url": row.get("Link_Download"),
                "source": "CVM IPE", "source_type": "primary",
                "source_sha256": archive_sha256,
            })
        return output

    @staticmethod
    def _date(value: Any) -> Optional[dt.datetime]:
        try:
            return dt.datetime.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None
