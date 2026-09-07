from __future__ import annotations

import csv
import datetime as dt
import html
import hashlib
import http.cookiejar
import io
import json
import re
import time
import urllib.request
import urllib.parse
import zipfile
import unicodedata
from html.parser import HTMLParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class CVMStatementRow:
    cvm_code: str
    company_name: str
    statement: str
    account_code: str
    account_name: str
    value: float
    currency: str
    scale: str
    reference_date: dt.date
    period_start: Optional[dt.date]
    received_at: dt.datetime
    filing_type: str
    source_url: str
    version: Optional[str] = None
    exercise_order: Optional[str] = None
    protocol: Optional[str] = None
    source_sha256: Optional[str] = None

    @property
    def normalized_value(self) -> float:
        scale = self.scale.strip().upper()
        # CVM statement files inherit ESCALA_MOEDA=MIL on the EPS section,
        # although account 3.99 is already expressed in BRL/share. Treating it
        # as a monetary total silently inflates EPS by 1,000x.
        per_share = self.statement == "DRE" and self.account_code.startswith("3.99")
        multiplier = 1_000.0 if scale in {"MIL", "THOUSAND"} and not per_share else 1.0
        return self.value * multiplier


class _RADTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


class CVMRADStatementClient:
    """Read structured DFP/ITR tables from immutable RAD document pages.

    Discovery is supplied by ``rad_document_index.json`` in the cache. The
    index is independently auditable and lets report generation remain a
    ticker-only operation even when an annual aggregate ZIP is unavailable.
    """

    MAIN_URL = "https://www.rad.cvm.gov.br/ENET/frmGerenciaPaginaFRE.aspx?CodigoTipoInstituicao=1&NumeroSequencialDocumento={sequence}"
    STATEMENTS = {"BPA": "2", "BPP": "3", "DRE": "4", "DFC_MI": "99"}

    def __init__(self, cache_dir: Optional[str] = None, timeout_seconds: float = 30.0, transport=None):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.index_path = self.cache_dir / "rad_document_index.json" if self.cache_dir else None
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def load_rows(self, cvm_code: str, as_of: dt.datetime, filing_types: Iterable[str], years: Iterable[int]) -> List[CVMStatementRow]:
        if not self.index_path or not self.index_path.is_file():
            return []
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        allowed_types = {str(item).upper() for item in filing_types}
        allowed_years = {int(item) for item in years}
        cutoff = as_of.replace(tzinfo=None)
        documents = []
        for document in payload.get("documents") or []:
            reference_date = self._date(document.get("reference_date"))
            received_at = self._datetime(document.get("received_at"))
            if str(document.get("cvm_code") or "").lstrip("0") != str(cvm_code).lstrip("0"):
                continue
            if str(document.get("filing_type") or "").upper() not in allowed_types:
                continue
            if not reference_date or reference_date.year not in allowed_years or not received_at or received_at > cutoff:
                continue
            documents.append((document, reference_date, received_at))
        chosen: Dict[tuple, tuple] = {}
        for item in documents:
            document, reference_date, received_at = item
            key = (str(document["filing_type"]).upper(), reference_date)
            previous = chosen.get(key)
            if previous is None or (received_at, int(document.get("version") or 0)) > (previous[2], int(previous[0].get("version") or 0)):
                chosen[key] = item
        rows: List[CVMStatementRow] = []
        for document, reference_date, received_at in chosen.values():
            rows.extend(self._load_document(document, reference_date, received_at))
        return rows

    def _load_document(self, document: Dict[str, Any], reference_date: dt.date, received_at: dt.datetime) -> List[CVMStatementRow]:
        sequence = str(document["sequence"])
        main_url = self.MAIN_URL.format(sequence=urllib.parse.quote(sequence))
        # Signed table URLs depend on cookies created by the main document page.
        # If a partial cache is present, revisit that page before downloading any
        # missing table instead of attempting the signed URL with a cold session.
        statement_cache_missing = bool(self.cache_dir) and any(
            not (self.cache_dir / "rad" / sequence / f"{label}.html").is_file()
            for label in self.STATEMENTS
        )
        main_html = self._fetch(
            main_url, sequence, "main", force_refresh=statement_cache_missing,
        ).decode("utf-8", errors="replace")
        match = re.search(r"window\.frames\[0\]\.location=['\"]([^'\"]+)", main_html, re.I)
        if not match:
            raise ValueError(f"RAD signed statement URL missing for document {sequence}")
        signed_url = urllib.parse.urljoin(main_url, html.unescape(match.group(1)))
        output: List[CVMStatementRow] = []
        for statement, demonstration in self.STATEMENTS.items():
            statement_url = self._statement_url(signed_url, demonstration)
            table_payload = self._fetch(statement_url, sequence, statement, referer=main_url)
            table_html = table_payload.decode("utf-8", errors="replace")
            output.extend(self._parse_statement(
                table_html, statement, document, reference_date, received_at, main_url,
                hashlib.sha256(table_payload).hexdigest(),
            ))
        return output

    def _fetch(
        self, url: str, sequence: str, label: str, referer: Optional[str] = None,
        force_refresh: bool = False,
    ) -> bytes:
        cache_path = self.cache_dir / "rad" / sequence / f"{label}.html" if self.cache_dir else None
        if cache_path and cache_path.is_file() and not force_refresh:
            return cache_path.read_bytes()
        headers = {"User-Agent": "PROMETHEUS/2.0 research@example.invalid"}
        if referer:
            headers["Referer"] = referer
        if self.transport:
            payload = self.transport(url, headers)
        else:
            request = urllib.request.Request(url, headers=headers)
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(payload)
        return payload

    @staticmethod
    def _statement_url(signed_url: str, demonstration: str) -> str:
        parsed = urllib.parse.urlsplit(signed_url)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        query["Informacao"] = "2"
        query["Demonstracao"] = demonstration
        query["Periodo"] = "0"
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))

    def _parse_statement(
        self, payload: str, statement: str, document: Dict[str, Any], reference_date: dt.date,
        received_at: dt.datetime, source_url: str, source_sha256: str,
    ) -> List[CVMStatementRow]:
        parser = _RADTableParser()
        parser.feed(payload)
        if not parser.rows:
            raise ValueError(f"RAD {statement} table missing for document {document.get('sequence')}")
        header = next((row for row in parser.rows if row and row[0].lower() == "conta"), parser.rows[0])
        period_headers = header[2:] or [reference_date.isoformat()]
        rows = []
        for cells in parser.rows:
            if len(cells) < 3 or not re.fullmatch(r"\d+(?:\.\d+)*", cells[0]):
                continue
            for column_index, period_text in enumerate(period_headers, start=2):
                if column_index >= len(cells):
                    continue
                value = self._decimal_br(cells[column_index])
                if value is None:
                    continue
                dates = re.findall(r"\d{2}/\d{2}/\d{4}", period_text)
                period_start = self._date_br(dates[0]) if len(dates) > 1 else None
                period_end = self._date_br(dates[-1]) if dates else reference_date
                rows.append(CVMStatementRow(
                    cvm_code=str(document["cvm_code"]), company_name=str(document.get("company_name") or ""),
                    statement=statement, account_code=cells[0], account_name=cells[1], value=value,
                    currency="REAL", scale="MIL", reference_date=period_end or reference_date,
                    period_start=period_start, received_at=received_at,
                    filing_type=str(document["filing_type"]).upper(), source_url=source_url,
                    version=str(document.get("version") or "") or None,
                    exercise_order="ULTIMO" if column_index == 2 else "PENULTIMO",
                    protocol=str(document.get("protocol") or "") or None,
                    source_sha256=source_sha256,
                ))
        return rows

    @staticmethod
    def _decimal_br(value: Any) -> Optional[float]:
        text = str(value or "").strip().replace("\xa0", "")
        if not text or text in {"-", "—"}:
            return None
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        elif text.count(".") >= 1 and all(len(part) == 3 for part in text.lstrip("-").split(".")[1:]):
            text = text.replace(".", "")
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _date(value: Any) -> Optional[dt.date]:
        try:
            return dt.date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _datetime(value: Any) -> Optional[dt.datetime]:
        try:
            return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _date_br(value: str) -> Optional[dt.date]:
        try:
            return dt.datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            return None


class CVMOpenDataClient:
    """Point-in-time reader for CVM's official ITR and DFP open datasets.

    The client deliberately filters by ``DT_RECEB`` before selecting the latest
    filing. Re-presented statements therefore do not leak into earlier analyses.
    """

    BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{filing}/DADOS/{filing_lower}_cia_aberta_{year}.zip"
    STATEMENTS = ("BPA", "BPP", "DRE", "DFC_MD", "DFC_MI")

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        timeout_seconds: float = 30.0,
        cache_ttl_seconds: float = 86_400.0,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._parsed_cache: Dict[tuple, List[CVMStatementRow]] = {}
        self._failed_refresh_urls: set[str] = set()
        self.rad = CVMRADStatementClient(cache_dir=cache_dir, timeout_seconds=timeout_seconds)

    def dataset_url(self, filing_type: str, year: int) -> str:
        filing = filing_type.strip().upper()
        if filing not in {"ITR", "DFP"}:
            raise ValueError("filing_type must be ITR or DFP")
        return self.BASE_URL.format(filing=filing, filing_lower=filing.lower(), year=int(year))

    def load_rows(
        self,
        cvm_code: str,
        as_of: dt.datetime,
        filing_types: Iterable[str] = ("ITR", "DFP"),
        years: Optional[Iterable[int]] = None,
        consolidated: bool = True,
    ) -> List[CVMStatementRow]:
        requested_years = list(years or range(max(2011, as_of.year - 2), as_of.year + 1))
        rows: List[CVMStatementRow] = []
        for filing_type in filing_types:
            filing = filing_type.strip().upper()
            for year in requested_years:
                url = self.dataset_url(filing, year)
                try:
                    archive = self._download(url)
                except Exception:
                    # A missing current-year archive must not erase valid prior data.
                    continue
                cache_key = (url, str(cvm_code).lstrip("0"), bool(consolidated))
                if cache_key not in self._parsed_cache:
                    self._parsed_cache[cache_key] = self._parse_archive(
                        archive=archive,
                        source_url=url,
                        filing_type=filing,
                        cvm_code=str(cvm_code),
                        as_of=dt.datetime.max,
                        consolidated=consolidated,
                    )
                cutoff = self._coerce_naive(as_of)
                rows.extend(row for row in self._parsed_cache[cache_key] if row.received_at <= cutoff)
        rows.extend(self.rad.load_rows(cvm_code, as_of, filing_types, requested_years))
        return self._latest_versions(rows)

    def load_rows_many(
        self,
        cvm_codes: Iterable[str],
        as_of: dt.datetime,
        filing_types: Iterable[str] = ("ITR", "DFP"),
        years: Optional[Iterable[int]] = None,
        consolidated: bool = True,
    ) -> Dict[str, List[CVMStatementRow]]:
        normalized_codes = tuple(sorted({str(code).strip().lstrip("0") for code in cvm_codes}))
        requested_years = list(years or range(max(2011, as_of.year - 2), as_of.year + 1))
        grouped: Dict[str, List[CVMStatementRow]] = {code: [] for code in normalized_codes}
        cutoff = self._coerce_naive(as_of)
        for filing_type in filing_types:
            filing = filing_type.strip().upper()
            for year in requested_years:
                url = self.dataset_url(filing, year)
                try:
                    archive = self._download(url)
                except Exception:
                    continue
                cache_key = (url, normalized_codes, bool(consolidated))
                if cache_key not in self._parsed_cache:
                    self._parsed_cache[cache_key] = self._parse_archive(
                        archive=archive, source_url=url, filing_type=filing,
                        cvm_code=normalized_codes, as_of=dt.datetime.max,
                        consolidated=consolidated,
                    )
                for row in self._parsed_cache[cache_key]:
                    code = row.cvm_code.lstrip("0")
                    if row.received_at <= cutoff and code in grouped:
                        grouped[code].append(row)
        for code in normalized_codes:
            grouped[code].extend(self.rad.load_rows(code, as_of, filing_types, requested_years))
        return {code: self._latest_versions(rows) for code, rows in grouped.items()}

    def load_capital_composition(
        self,
        cvm_code: str,
        as_of: dt.datetime,
        filing_types: Iterable[str] = ("ITR", "DFP"),
        years: Optional[Iterable[int]] = None,
    ) -> Dict[str, Any]:
        """Return the latest capital composition that was public by ``as_of``."""
        requested_years = list(years or range(max(2011, as_of.year - 2), as_of.year + 1))
        candidates: List[Dict[str, Any]] = []
        normalized_code = str(cvm_code).strip().lstrip("0")
        cutoff = self._coerce_naive(as_of)
        for filing_type in filing_types:
            filing = filing_type.strip().upper()
            for year in requested_years:
                url = self.dataset_url(filing, year)
                try:
                    archive = self._download(url)
                except Exception:
                    continue
                candidates.extend(self._parse_capital_composition(archive, url, filing, normalized_code, cutoff))
        if not candidates:
            return {"status": "INSUFFICIENT_DATA", "reason": "NO_POINT_IN_TIME_CAPITAL_COMPOSITION"}
        chosen = max(candidates, key=lambda row: (row["received_at"], row["reference_date"], int(row.get("version") or 0)))
        return {"status": "AVAILABLE", **chosen}

    def _parse_capital_composition(
        self, archive: bytes, source_url: str, filing_type: str, cvm_code: str, cutoff: dt.datetime,
    ) -> List[Dict[str, Any]]:
        archive_sha256 = hashlib.sha256(archive).hexdigest()
        statement_rows = self._parse_archive(
            archive, source_url, filing_type, cvm_code, cutoff, consolidated=True,
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            metadata = self._read_filing_metadata(zipped, filing_type)
            issuer_records = {
                (str(row.get("CNPJ_CIA") or ""), str(row.get("DT_REFER") or ""), str(row.get("VERSAO") or "")): row
                for row in metadata.values()
                if str(row.get("CD_CVM") or "").strip().lstrip("0") == cvm_code
                and (self._parse_datetime(row.get("DT_RECEB")) or dt.datetime.max) <= cutoff
            }
            capital_name = next((name for name in zipped.namelist() if "composicao_capital" in name.lower() and name.lower().endswith(".csv")), None)
            if not capital_name:
                return []
            payload = zipped.read(capital_name)
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = payload.decode("latin-1")
            output = []
            for row in csv.DictReader(io.StringIO(text), delimiter=";"):
                key = (str(row.get("CNPJ_CIA") or ""), str(row.get("DT_REFER") or ""), str(row.get("VERSAO") or ""))
                filing = issuer_records.get(key)
                if not filing:
                    continue
                ordinary = int(self._parse_decimal(row.get("QT_ACAO_ORDIN_CAP_INTEGR")) or 0)
                preferred = int(self._parse_decimal(row.get("QT_ACAO_PREF_CAP_INTEGR")) or 0)
                total = int(self._parse_decimal(row.get("QT_ACAO_TOTAL_CAP_INTEGR")) or 0)
                treasury = int(self._parse_decimal(row.get("QT_ACAO_TOTAL_TESOURO")) or 0)
                if total <= 0 or total - treasury <= 0 or ordinary + preferred != total:
                    continue
                scale = self._infer_capital_quantity_scale(
                    statement_rows=statement_rows,
                    reference_date=self._parse_date(row.get("DT_REFER")),
                    version=str(row.get("VERSAO") or "") or None,
                    ordinary=ordinary,
                    preferred=preferred,
                    total=total,
                )
                if scale is None:
                    # Small unscaled quantities are unsafe: some issuers report
                    # this table in thousands despite the absence of a scale
                    # column. Fail closed unless EPS reconciles the multiplier.
                    continue
                multiplier = int(scale["multiplier"])
                ordinary_scaled = ordinary * multiplier
                preferred_scaled = preferred * multiplier
                total_scaled = total * multiplier
                treasury_scaled = treasury * multiplier
                outstanding = total_scaled - treasury_scaled
                if outstanding <= 0:
                    continue
                output.append({
                    "cvm_code": cvm_code, "company_name": row.get("DENOM_CIA"),
                    "cnpj": row.get("CNPJ_CIA"), "filing_type": filing_type,
                    "reference_date": str(row.get("DT_REFER")),
                    "received_at": self._parse_datetime(filing.get("DT_RECEB")),
                    "version": str(row.get("VERSAO") or "") or None,
                    "ordinary_shares": ordinary_scaled, "preferred_shares": preferred_scaled,
                    "total_issued_shares": total_scaled, "treasury_shares": treasury_scaled,
                    "shares_outstanding": outstanding,
                    "single_class": ordinary == 0 or preferred == 0,
                    "formula": "(QT_ACAO_TOTAL_CAP_INTEGR - QT_ACAO_TOTAL_TESOURO) * quantity_scale_multiplier",
                    "reported_ordinary_quantity": ordinary,
                    "reported_preferred_quantity": preferred,
                    "reported_total_quantity": total,
                    "reported_treasury_quantity": treasury,
                    "quantity_scale_multiplier": multiplier,
                    "quantity_scale_status": scale["status"],
                    "quantity_scale_method": scale["method"],
                    "quantity_scale_reconciliation_error": scale.get("relative_error"),
                    "quantity_scale_reconciliation_formula": scale.get("formula"),
                    "source_url": str(filing.get("LINK_DOC") or source_url),
                    "source_dataset": source_url,
                    "source_sha256": archive_sha256,
                })
            return output

    @staticmethod
    def _infer_capital_quantity_scale(
        statement_rows: List[CVMStatementRow], reference_date: Optional[dt.date],
        version: Optional[str], ordinary: int, preferred: int, total: int,
    ) -> Optional[Dict[str, Any]]:
        """Infer the capital-table quantity scale from parent profit and EPS.

        The composition CSV has no scale field. Candidate multipliers are kept
        deliberately finite and the selected one must reconcile independently
        reported DRE facts. Large raw counts may safely retain unit scale when
        no EPS fact exists; small counts fail closed.
        """
        relevant = [
            row for row in statement_rows
            if row.reference_date == reference_date
            and (not version or row.version == version)
            and CVMFundamentalSnapshotBuilder._is_current_exercise(row.exercise_order)
        ]

        def cumulative(account: str) -> Optional[CVMStatementRow]:
            candidates = [
                row for row in relevant
                if row.statement == "DRE" and row.account_code == account
            ]
            return min(candidates, key=lambda item: item.period_start or item.reference_date) if candidates else None

        parent_profit = cumulative("3.11.01") or cumulative("3.09.01")
        eps_on = cumulative("3.99.01.01")
        eps_pn = cumulative("3.99.01.02")
        eps_total = cumulative("3.99")
        expected_profit = parent_profit.normalized_value if parent_profit else None

        def predicted(multiplier: int) -> Optional[tuple[float, str]]:
            on = eps_on.normalized_value if eps_on and eps_on.normalized_value > 0 else None
            pn = eps_pn.normalized_value if eps_pn and eps_pn.normalized_value > 0 else None
            if ordinary > 0 and preferred > 0 and on is not None and pn is not None:
                return multiplier * ((ordinary * on) + (preferred * pn)), "EPS_ON * ordinary + EPS_PN * preferred"
            if preferred == 0 and ordinary > 0 and on is not None:
                return multiplier * ordinary * on, "EPS_ON * ordinary"
            if ordinary == 0 and preferred > 0 and pn is not None:
                return multiplier * preferred * pn, "EPS_PN * preferred"
            if eps_total and eps_total.normalized_value > 0:
                return multiplier * total * eps_total.normalized_value, "EPS_total * total"
            return None

        reconciliations = []
        if expected_profit and expected_profit > 0:
            for multiplier in (1, 1000):
                estimate = predicted(multiplier)
                if estimate:
                    value, formula = estimate
                    reconciliations.append((abs(value - expected_profit) / expected_profit, multiplier, formula))
        if reconciliations:
            reconciliations.sort()
            best_error, best_multiplier, formula = reconciliations[0]
            other_error = reconciliations[1][0] if len(reconciliations) > 1 else float("inf")
            if best_error <= 0.05 and other_error >= max(0.25, best_error * 10):
                return {
                    "multiplier": best_multiplier,
                    "status": "VERIFIED",
                    "method": "PARENT_PROFIT_EPS_RECONCILIATION",
                    "relative_error": best_error,
                    "formula": f"{formula}; choose m in {{1,1000}} minimizing |predicted_parent_profit - reported_parent_profit| / reported_parent_profit",
                }
        if total >= 100_000_000:
            return {
                "multiplier": 1,
                "status": "CONSERVATIVE_FALLBACK",
                "method": "RAW_QUANTITY_ABOVE_SMALL_COUNT_GUARD",
                "relative_error": None,
                "formula": "raw total >= 100,000,000; retain reported unit scale",
            }
        return None

    def _download(self, url: str) -> bytes:
        cache_path = None
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = self.cache_dir / url.rsplit("/", 1)[-1]
            cache_age = time.time() - cache_path.stat().st_mtime if cache_path.exists() else None
            if cache_age is not None and cache_age <= self.cache_ttl_seconds:
                return cache_path.read_bytes()
        if url in self._failed_refresh_urls:
            if cache_path is not None and cache_path.is_file():
                return cache_path.read_bytes()
            raise OSError(f"previous refresh failed for {url}")

        request = urllib.request.Request(url, headers={"User-Agent": "PROMETHEUS/1.0 research@example.invalid"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except Exception:
            self._failed_refresh_urls.add(url)
            # Cached official archives remain valid evidence even when refresh
            # is temporarily unavailable. Publication timestamps inside the ZIP
            # still enforce the point-in-time cutoff.
            if cache_path is not None and cache_path.is_file():
                return cache_path.read_bytes()
            raise
        if cache_path is not None:
            cache_path.write_bytes(payload)
        return payload

    def _parse_archive(
        self,
        archive: bytes,
        source_url: str,
        filing_type: str,
        cvm_code: Any,
        as_of: dt.datetime,
        consolidated: bool,
    ) -> List[CVMStatementRow]:
        suffix = "_con_" if consolidated else "_ind_"
        accepted_codes = {
            str(code).strip().lstrip("0") for code in (
                cvm_code if isinstance(cvm_code, (tuple, list, set, frozenset)) else (cvm_code,)
            )
        }
        parsed: List[CVMStatementRow] = []
        archive_sha256 = hashlib.sha256(archive).hexdigest()
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            filing_metadata = self._read_filing_metadata(zipped, filing_type)
            for name in zipped.namelist():
                normalized_name = name.replace("\\", "/").rsplit("/", 1)[-1]
                if suffix not in normalized_name.lower() or not normalized_name.lower().endswith(".csv"):
                    continue
                statement = self._statement_from_filename(normalized_name)
                if statement is None:
                    continue
                payload = zipped.read(name)
                try:
                    text = payload.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = payload.decode("latin-1")
                reader = csv.DictReader(io.StringIO(text), delimiter=";")
                for raw in reader:
                    if str(raw.get("CD_CVM", "")).strip().lstrip("0") not in accepted_codes:
                        continue
                    metadata_key = (
                        str(raw.get("CD_CVM", "")).strip().lstrip("0"),
                        str(raw.get("DT_REFER", "")).strip(),
                        str(raw.get("VERSAO", "")).strip(),
                    )
                    filing_record = filing_metadata.get(metadata_key, {})
                    received_at = self._parse_datetime(raw.get("DT_RECEB") or filing_record.get("DT_RECEB"))
                    if received_at is None or received_at > self._coerce_naive(as_of):
                        continue
                    value = self._parse_decimal(raw.get("VL_CONTA"))
                    reported_reference = self._parse_date(raw.get("DT_REFER"))
                    period_end = self._parse_date(raw.get("DT_FIM_EXERC"))
                    reference_date = period_end if statement in {"DRE", "DFC_MD", "DFC_MI"} and period_end else reported_reference
                    if value is None or reference_date is None:
                        continue
                    parsed.append(CVMStatementRow(
                        cvm_code=str(raw.get("CD_CVM", "")).strip(),
                        company_name=str(raw.get("DENOM_CIA", "")).strip(),
                        statement=statement,
                        account_code=str(raw.get("CD_CONTA", "")).strip(),
                        account_name=str(raw.get("DS_CONTA", "")).strip(),
                        value=value,
                        currency=str(raw.get("MOEDA", "BRL")).strip() or "BRL",
                        scale=str(raw.get("ESCALA_MOEDA", "UNIDADE")).strip() or "UNIDADE",
                        reference_date=reference_date,
                        period_start=self._parse_date(raw.get("DT_INI_EXERC")),
                        received_at=received_at,
                        filing_type=filing_type,
                        source_url=str(filing_record.get("LINK_DOC") or source_url),
                        version=str(raw.get("VERSAO", "")).strip() or None,
                        exercise_order=str(raw.get("ORDEM_EXERC", "")).strip() or None,
                        source_sha256=archive_sha256,
                    ))
        return parsed

    def _read_filing_metadata(self, zipped: zipfile.ZipFile, filing_type: str) -> Dict[tuple, Dict[str, str]]:
        prefix = f"{filing_type.lower()}_cia_aberta_"
        candidates = []
        for name in zipped.namelist():
            basename = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if basename.startswith(prefix) and basename.endswith(".csv"):
                year_part = basename[len(prefix):-4]
                if year_part.isdigit():
                    candidates.append(name)
        if not candidates:
            return {}

        payload = zipped.read(candidates[0])
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = payload.decode("latin-1")
        records: Dict[tuple, Dict[str, str]] = {}
        for raw in csv.DictReader(io.StringIO(text), delimiter=";"):
            key = (
                str(raw.get("CD_CVM", "")).strip().lstrip("0"),
                str(raw.get("DT_REFER", "")).strip(),
                str(raw.get("VERSAO", "")).strip(),
            )
            records[key] = raw
        return records

    def _latest_versions(self, rows: Iterable[CVMStatementRow]) -> List[CVMStatementRow]:
        latest: Dict[tuple, CVMStatementRow] = {}
        for row in rows:
            key = (
                row.filing_type,
                row.statement,
                row.reference_date,
                row.period_start,
                row.account_code,
                row.exercise_order,
            )
            previous = latest.get(key)
            if previous is None or row.received_at > previous.received_at:
                latest[key] = row
        return sorted(latest.values(), key=lambda row: (row.reference_date, row.statement, row.account_code))

    def _statement_from_filename(self, filename: str) -> Optional[str]:
        upper = filename.upper()
        for statement in self.STATEMENTS:
            if f"_{statement}_" in upper:
                return statement
        return None

    @staticmethod
    def _parse_decimal(value: Any) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip()
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_date(value: Any) -> Optional[dt.date]:
        if not value:
            return None
        try:
            return dt.date.fromisoformat(str(value).strip()[:10])
        except ValueError:
            return None

    @classmethod
    def _parse_datetime(cls, value: Any) -> Optional[dt.datetime]:
        if not value:
            return None
        text = str(value).strip().replace("Z", "+00:00")
        try:
            return cls._coerce_naive(dt.datetime.fromisoformat(text))
        except ValueError:
            parsed_date = cls._parse_date(text)
            return dt.datetime.combine(parsed_date, dt.time()) if parsed_date else None

    @staticmethod
    def _coerce_naive(value: dt.datetime) -> dt.datetime:
        if value.tzinfo is not None:
            return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value


class CVMFundamentalSnapshotBuilder:
    """Derive comparable fundamental metrics from official CVM statement rows."""

    REVENUE = ("DRE", "3.01")
    NET_INCOME = ("DRE", "3.11")
    TOTAL_ASSETS = ("BPA", "1")
    CURRENT_ASSETS = ("BPA", "1.01")
    CASH = ("BPA", "1.01.01")
    EQUITY = ("BPP", "2.03")
    CURRENT_LIABILITIES = ("BPP", "2.01")
    CURRENT_DEBT = ("BPP", "2.01.04")
    LONG_TERM_DEBT = ("BPP", "2.02.01")
    GROSS_PROFIT = ("DRE", "3.03")
    OPERATING_INCOME = ("DRE", "3.05")
    OPERATING_CASH_FLOW = ("DFC_MI", "6.01")

    def build(self, rows: Iterable[CVMStatementRow]) -> Dict[str, Any]:
        materialized = list(rows)
        if not materialized:
            return {"status": "INSUFFICIENT_DATA", "metrics": {}, "sources": []}

        latest_date = max(row.reference_date for row in materialized)
        latest = [row for row in materialized if row.reference_date == latest_date]
        revenue = self._flow(latest, *self.REVENUE)
        net_income = self._net_income_flow(latest)
        equity = self._equity_stock(latest)
        total_assets = self._stock(latest, *self.TOTAL_ASSETS)
        current_assets = self._stock(latest, *self.CURRENT_ASSETS)
        cash = self._stock(latest, *self.CASH)
        current_debt = self._stock(latest, *self.CURRENT_DEBT)
        long_term_debt = self._stock(latest, *self.LONG_TERM_DEBT)
        current_liabilities = self._stock(latest, *self.CURRENT_LIABILITIES)
        gross_profit = self._flow(latest, *self.GROSS_PROFIT)
        operating_income = self._flow(latest, *self.OPERATING_INCOME)
        operating_cash_flow = self._flow(latest, *self.OPERATING_CASH_FLOW)

        prior_date = self._prior_year_date(latest_date, materialized)
        prior = [row for row in materialized if row.reference_date == prior_date] if prior_date else []
        prior_revenue = self._flow(prior, *self.REVENUE)
        prior_income = self._net_income_flow(prior)

        debt = None
        debt_sources: List[CVMStatementRow] = []
        debt_parts = [item for item in (current_debt, long_term_debt) if item is not None]
        if debt_parts:
            debt = sum(item.normalized_value for item in debt_parts)
            debt_sources = debt_parts

        annualization = self._annualization_factor(revenue)
        cash_value = cash.normalized_value if cash else None
        net_debt = debt - cash_value if debt is not None and cash_value is not None else None
        metrics = {
            "revenue": self._metric(revenue.normalized_value if revenue else None, "BRL", [revenue] if revenue else []),
            "net_income": self._metric(net_income.normalized_value if net_income else None, "BRL", [net_income] if net_income else []),
            "total_assets": self._metric(total_assets.normalized_value if total_assets else None, "BRL", [total_assets] if total_assets else []),
            "current_assets": self._metric(current_assets.normalized_value if current_assets else None, "BRL", [current_assets] if current_assets else []),
            "cash": self._metric(cash_value, "BRL", [cash] if cash else []),
            "equity": self._metric(equity.normalized_value if equity else None, "BRL", [equity] if equity else []),
            "gross_debt": self._metric(debt, "BRL", debt_sources),
            "net_debt": self._metric(net_debt, "BRL", debt_sources + ([cash] if cash else []), "gross debt - cash"),
            "gross_profit": self._metric(gross_profit.normalized_value if gross_profit else None, "BRL", [gross_profit] if gross_profit else []),
            "operating_income": self._metric(operating_income.normalized_value if operating_income else None, "BRL", [operating_income] if operating_income else []),
            "operating_cash_flow": self._metric(operating_cash_flow.normalized_value if operating_cash_flow else None, "BRL", [operating_cash_flow] if operating_cash_flow else []),
            "revenue_growth": self._ratio_metric(revenue, prior_revenue, "(current revenue / prior comparable revenue) - 1"),
            "earnings_growth": self._ratio_metric(net_income, prior_income, "(current net income / prior comparable net income) - 1"),
            "profit_margin": self._division_metric(net_income, revenue, "ratio", calculation="net income / revenue"),
            "gross_margin": self._division_metric(gross_profit, revenue, "ratio", calculation="gross profit / revenue"),
            "operating_margin": self._division_metric(operating_income, revenue, "ratio", calculation="operating income / revenue"),
            "operating_cash_flow_margin": self._division_metric(operating_cash_flow, revenue, "ratio", calculation="operating cash flow / revenue"),
            "cash_conversion": self._division_metric(operating_cash_flow, net_income, "ratio", calculation="operating cash flow / net income"),
            "roe": self._division_metric(net_income, equity, "ratio", numerator_multiplier=annualization, calculation="annualized net income / equity"),
            "roa": self._division_metric(net_income, total_assets, "ratio", numerator_multiplier=annualization, calculation="annualized net income / total assets"),
            "asset_turnover": self._division_metric(revenue, total_assets, "ratio", numerator_multiplier=annualization, calculation="annualized revenue / total assets"),
            "current_ratio": self._division_metric(current_assets, current_liabilities, "ratio", calculation="current assets / current liabilities"),
            "debt_to_equity": self._value_division_metric(debt, equity, debt_sources, "ratio", calculation="gross debt / equity"),
            "net_debt_to_equity": self._value_division_metric(net_debt, equity, debt_sources + ([cash] if cash else []), "ratio", calculation="net debt / equity"),
        }
        sources = self._unique_sources([source for metric in metrics.values() for source in metric.get("source_rows", [])])
        return {
            "status": "AVAILABLE",
            "reference_date": latest_date.isoformat(),
            "metrics": metrics,
            "sources": sources,
        }

    def build_history(self, rows: Iterable[CVMStatementRow], limit: int = 12) -> List[Dict[str, Any]]:
        materialized = list(rows)
        dates = sorted({row.reference_date for row in materialized})[-max(1, int(limit)):]
        history: List[Dict[str, Any]] = []
        for reference_date in dates:
            eligible = [row for row in materialized if row.reference_date <= reference_date]
            snapshot = self.build(eligible)
            if snapshot.get("status") != "AVAILABLE":
                continue
            values = {
                name: metric.get("normalized")
                for name, metric in snapshot.get("metrics", {}).items()
            }
            history.append({
                "period": snapshot.get("reference_date"),
                **values,
                "sources": snapshot.get("sources", []),
                "metric_metadata": snapshot.get("metrics", {}),
            })
        return history

    def build_ttm(self, rows: Iterable[CVMStatementRow]) -> Dict[str, Any]:
        materialized = list(rows)
        if not materialized:
            return {"status": "INSUFFICIENT_DATA", "metrics": {}, "reason": "no_rows"}
        latest_date = max(row.reference_date for row in materialized)
        definitions = {
            "revenue": self.REVENUE, "net_income": self.NET_INCOME, "gross_profit": self.GROSS_PROFIT,
            "operating_income": self.OPERATING_INCOME, "operating_cash_flow": self.OPERATING_CASH_FLOW,
        }
        metrics: Dict[str, Dict[str, Any]] = {}
        if latest_date.month == 12:
            latest_rows = [row for row in materialized if row.reference_date == latest_date]
            for name, definition in definitions.items():
                row = self._flow_for_metric(name, latest_rows, definition)
                metrics[name] = self._metric(row.normalized_value if row else None, "BRL", [row] if row else [], "reported annual")
            method = "reported_annual"
        else:
            prior_interim_date = self._safe_prior_year(latest_date)
            prior_annual_date = dt.date(latest_date.year - 1, 12, 31)
            current_rows = [row for row in materialized if row.reference_date == latest_date]
            prior_interim_rows = [row for row in materialized if row.reference_date == prior_interim_date]
            prior_annual_rows = [row for row in materialized if row.reference_date == prior_annual_date]
            for name, definition in definitions.items():
                current = self._flow_for_metric(name, current_rows, definition)
                annual = self._flow_for_metric(name, prior_annual_rows, definition)
                prior = self._flow_for_metric(name, prior_interim_rows, definition)
                sources = [row for row in (current, annual, prior) if row]
                value = None
                if current and annual and prior:
                    value = current.normalized_value + annual.normalized_value - prior.normalized_value
                metrics[name] = self._metric(value, "BRL", sources, "current YTD + prior FY - prior YTD")
            method = "rolling_twelve_months"
        revenue = metrics["revenue"].get("normalized")
        net_income = metrics["net_income"].get("normalized")
        operating_cash_flow = metrics["operating_cash_flow"].get("normalized")
        metrics["profit_margin"] = self._numeric_division(
            net_income, revenue, "net_income / revenue",
            (metrics["net_income"].get("source_rows") or []) + (metrics["revenue"].get("source_rows") or []),
        )
        metrics["cash_conversion"] = self._numeric_division(
            operating_cash_flow, net_income, "operating_cash_flow / net_income",
            (metrics["operating_cash_flow"].get("source_rows") or []) + (metrics["net_income"].get("source_rows") or []),
        )
        missing = [name for name, metric in metrics.items() if metric.get("normalized") is None]
        core_available = metrics["revenue"].get("normalized") is not None and metrics["net_income"].get("normalized") is not None
        return {
            "status": "AVAILABLE" if not missing else "PARTIAL" if core_available else "INSUFFICIENT_DATA", "as_of_period": latest_date.isoformat(),
            "method": method, "formula": "current YTD + prior FY - prior YTD" if method == "rolling_twelve_months" else "reported annual",
            "metrics": metrics, "missing": missing,
            "sources": self._unique_sources([source for metric in metrics.values() for source in metric.get("source_rows", [])]),
        }

    @staticmethod
    def _safe_prior_year(value: dt.date) -> dt.date:
        try:
            return value.replace(year=value.year - 1)
        except ValueError:
            return value.replace(year=value.year - 1, day=28)

    def _numeric_division(
        self, numerator: Optional[float], denominator: Optional[float], calculation: str,
        source_rows: Optional[List[CVMStatementRow]] = None,
    ) -> Dict[str, Any]:
        value = numerator / denominator if numerator is not None and denominator not in (None, 0) else None
        return self._metric(value, "ratio", source_rows or [], calculation)

    def _flow(self, rows: List[CVMStatementRow], statement: str, account: str) -> Optional[CVMStatementRow]:
        candidates = self._account_rows(rows, statement, account)
        # DRE/DFC archives contain quarterly and year-to-date views. The earliest
        # period start is the cumulative observation used for margins and ROE.
        return min(candidates, key=lambda row: row.period_start or row.reference_date) if candidates else None

    def _flow_for_metric(
        self, name: str, rows: List[CVMStatementRow], definition: tuple[str, str],
    ) -> Optional[CVMStatementRow]:
        return self._net_income_flow(rows) if name == "net_income" else self._flow(rows, *definition)

    def _net_income_flow(self, rows: List[CVMStatementRow]) -> Optional[CVMStatementRow]:
        # Profit attributable to controlling shareholders is the economically
        # comparable numerator for per-share valuation. Fall back to the
        # consolidated total only when the parent line is absent.
        primary = self._flow(rows, "DRE", "3.11.01") or self._flow(rows, *self.NET_INCOME)
        if primary is not None:
            return primary

        # Financial institutions use a distinct CVM DRE taxonomy. Accept the
        # parent-attributable 3.09.01 only when the 3.09 account proves that the
        # layout represents consolidated period profit. This prevents the
        # ordinary-company 3.09 "before taxes" line from becoming net income.
        consolidated = self._flow(rows, "DRE", "3.09")
        if consolidated is None:
            return None
        account_name = unicodedata.normalize("NFKD", consolidated.account_name).encode("ascii", "ignore").decode("ascii").upper()
        is_financial_layout = (
            "CONSOLIDAD" in account_name
            and ("LUCRO" in account_name or "PREJUIZO" in account_name)
            and "ANTES" not in account_name
        )
        if not is_financial_layout:
            return None
        return self._flow(rows, "DRE", "3.09.01") or consolidated

    def _equity_stock(self, rows: List[CVMStatementRow]) -> Optional[CVMStatementRow]:
        # Financial institutions use 2.07 or 2.08 for consolidated equity,
        # while ordinary issuers normally use 2.03. Account meaning, not the
        # numeric code alone, is the stable discriminator across taxonomies.
        named = []
        for row in rows:
            if row.statement != "BPP":
                continue
            name = unicodedata.normalize("NFKD", row.account_name).encode("ascii", "ignore").decode("ascii").upper()
            if "PATRIMONIO LIQUIDO CONSOLIDADO" in name:
                named.append(row)
        if named:
            current = [row for row in named if self._is_current_exercise(row.exercise_order)] or named
            return sorted(current, key=lambda row: (row.account_code.count("."), -row.received_at.timestamp()))[0]
        equity = self._stock(rows, *self.EQUITY)
        if equity is not None:
            name = unicodedata.normalize("NFKD", equity.account_name).encode("ascii", "ignore").decode("ascii").upper()
            if "PATRIM" in name:
                return equity
        return self._stock(rows, "BPP", "2.08") or self._stock(rows, "BPP", "2.07") or equity

    def _stock(self, rows: List[CVMStatementRow], statement: str, account: str) -> Optional[CVMStatementRow]:
        candidates = self._account_rows(rows, statement, account)
        return candidates[0] if candidates else None

    def _account_rows(self, rows: List[CVMStatementRow], statement: str, account: str) -> List[CVMStatementRow]:
        candidates = [
            row for row in rows
            if row.statement == statement and row.account_code == account
        ]
        current = [row for row in candidates if self._is_current_exercise(row.exercise_order)]
        selected = current or candidates
        return sorted(selected, key=lambda row: (row.received_at, row.period_start or row.reference_date), reverse=True)

    @staticmethod
    def _is_current_exercise(value: Optional[str]) -> bool:
        if not value:
            return True
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").upper().strip()
        return normalized == "ULTIMO"

    @staticmethod
    def _prior_year_date(latest: dt.date, rows: List[CVMStatementRow]) -> Optional[dt.date]:
        candidates = sorted({row.reference_date for row in rows if row.reference_date < latest}, reverse=True)
        exact = [date for date in candidates if date.month == latest.month and date.day == latest.day and date.year == latest.year - 1]
        return exact[0] if exact else None

    @staticmethod
    def _annualization_factor(row: Optional[CVMStatementRow]) -> float:
        if row is None or row.period_start is None:
            return 1.0
        months = max(1, (row.reference_date.year - row.period_start.year) * 12 + row.reference_date.month - row.period_start.month + 1)
        return 12.0 / months

    def _ratio_metric(self, current: Optional[CVMStatementRow], prior: Optional[CVMStatementRow], calculation: str) -> Dict[str, Any]:
        value = None
        if current and prior and prior.normalized_value != 0:
            value = current.normalized_value / prior.normalized_value - 1.0
        return self._metric(value, "ratio", [item for item in (current, prior) if item], calculation)

    def _division_metric(
        self,
        numerator: Optional[CVMStatementRow],
        denominator: Optional[CVMStatementRow],
        unit: str,
        numerator_multiplier: float = 1.0,
        calculation: str = "numerator / denominator",
    ) -> Dict[str, Any]:
        value = None
        if numerator and denominator and denominator.normalized_value != 0:
            value = numerator.normalized_value * numerator_multiplier / denominator.normalized_value
        return self._metric(value, unit, [item for item in (numerator, denominator) if item], calculation)

    def _value_division_metric(
        self,
        numerator: Optional[float],
        denominator: Optional[CVMStatementRow],
        numerator_sources: List[CVMStatementRow],
        unit: str,
        calculation: str = "numerator / denominator",
    ) -> Dict[str, Any]:
        value = None
        if numerator is not None and denominator and denominator.normalized_value != 0:
            value = numerator / denominator.normalized_value
        sources = list(numerator_sources) + ([denominator] if denominator else [])
        return self._metric(value, unit, sources, calculation)

    @staticmethod
    def _metric(value: Optional[float], unit: str, sources: List[CVMStatementRow], calculation: str = "reported") -> Dict[str, Any]:
        return {
            "normalized": value,
            "unit": unit,
            "status": "VALID" if value is not None else "MISSING",
            "semantic_status": "VERIFIED" if value is not None else "MISSING",
            "source": "CVM",
            "calculation": calculation,
            "source_rows": sources,
        }

    @staticmethod
    def _unique_sources(rows: List[CVMStatementRow]) -> List[Dict[str, Any]]:
        unique: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            key = (row.source_url, row.reference_date, row.version)
            unique[key] = {
                "source": "CVM",
                "source_url": row.source_url,
                "reference_date": row.reference_date.isoformat(),
                "publication_date": row.received_at.isoformat(),
                "filing_type": row.filing_type,
                "version": row.version,
                "protocol": row.protocol,
                "source_sha256": row.source_sha256,
            }
        return list(unique.values())
