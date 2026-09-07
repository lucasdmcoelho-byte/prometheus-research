from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prometheus.instrument_catalog import InstrumentCatalog, InstrumentIdentity, normalize_cnpj
from prometheus.b3_instruments import audit_reviewed_tickers, parse_bvbg028_zip


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an atomic B3 ticker/CVM/CNPJ catalog")
    parser.add_argument("--instruments", required=True, help="Reviewed CSV: ticker,cvm_code,cnpj,company_name,ticker_source_date")
    parser.add_argument("--cvm-registry", required=True, help="Official cad_cia_aberta.csv used for validation")
    parser.add_argument("--ticker-source", required=True, help="Name or URL of the reviewed B3 instrument source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output")
    parser.add_argument("--b3-instruments-zip", help="Official point-in-time BVBG.028.02 ZIP; when supplied, ticker identity is also audited against B3")
    args = parser.parse_args()
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with Path(args.instruments).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    b3_audit = None
    if args.b3_instruments_zip:
        b3_audit = audit_reviewed_tickers(parse_bvbg028_zip(args.b3_instruments_zip), rows)
        if b3_audit["status"] != "PASS":
            print(json.dumps({"status": "FAIL", "b3_audit": b3_audit}, ensure_ascii=False, indent=2))
            return 2
    instruments = [InstrumentIdentity(
        ticker=str(row.get("ticker") or "").strip().upper(),
        cvm_code=str(row.get("cvm_code") or "").strip().lstrip("0"),
        cnpj=normalize_cnpj(row.get("cnpj")),
        company_name=str(row.get("company_name") or "").strip(),
        ticker_source=args.ticker_source,
        ticker_source_date=str(row.get("ticker_source_date") or "").strip(),
        validated_at=now,
    ) for row in rows]
    catalog = InstrumentCatalog(instruments, {
        "version": 1, "ticker_source": args.ticker_source,
        "cvm_registry_path": str(Path(args.cvm_registry).resolve()),
    })
    audit = catalog.audit_against_cvm_csv(args.cvm_registry)
    audit_path = Path(args.audit_output) if args.audit_output else Path(args.output).with_suffix(".audit.json")
    combined_audit = {**audit, "b3_audit": b3_audit}
    audit_path.write_text(json.dumps(combined_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if audit["status"] != "PASS":
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 2
    catalog.dump(args.output)
    print(json.dumps({"status": "PASS", "instrument_count": len(instruments), "catalog": args.output, "audit": str(audit_path), "content_sha256": catalog.content_sha256()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
