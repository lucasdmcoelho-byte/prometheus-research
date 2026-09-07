from __future__ import annotations

import csv
import io
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from prometheus.issuer_registry import CVM_REGISTRY_URL


class CoverageRegistry:
    """Validates maintained ticker identities against CVM's active issuer registry."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_path = Path(cache_dir) / "cad_cia_aberta.csv" if cache_dir else None

    def validate(self, mapping: Dict[str, str]) -> Dict[str, Any]:
        rows = self._rows()
        by_code = {str(row.get("CD_CVM", "")).strip().lstrip("0"): row for row in rows}
        instruments = []
        for ticker, code in sorted(mapping.items()):
            normalized_code = str(code).lstrip("0")
            issuer = by_code.get(normalized_code)
            cnpj = str((issuer or {}).get("CNPJ_CIA") or "").strip() or None
            instruments.append({
                "ticker": ticker, "cvm_code": normalized_code,
                "company_name": issuer.get("DENOM_SOCIAL") if issuer else None,
                "cnpj": cnpj,
                "issuer_status": issuer.get("SIT") if issuer else "NOT_FOUND",
                "validated": bool(issuer and cnpj and str(issuer.get("SIT", "")).upper() == "ATIVO"),
            })
        failures = [item for item in instruments if not item["validated"]]
        return {
            "status": "PASS" if not failures else "FAIL", "instrument_count": len(instruments),
            "validated_count": len(instruments) - len(failures), "failures": failures,
            "instruments": instruments, "source_url": CVM_REGISTRY_URL,
            "coverage_policy": "Maintained explicit ticker mapping validated against exact active CVM code, company and CNPJ; unsupported tickers require reviewed configuration.",
        }

    def _rows(self):
        if self.cache_path and self.cache_path.exists() and time.time() - self.cache_path.stat().st_mtime < 86400:
            payload = self.cache_path.read_bytes()
        else:
            request = urllib.request.Request(CVM_REGISTRY_URL, headers={"User-Agent": "PROMETHEUS/1.0 research@example.invalid"})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True); self.cache_path.write_bytes(payload)
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                text = payload.decode(encoding); break
            except UnicodeDecodeError:
                continue
        return list(csv.DictReader(io.StringIO(text), delimiter=";"))
