from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prometheus.b3_instruments import parse_bvbg028_zip
from prometheus.b3_isin_registry import parse_isin_registry_zip
from prometheus.instrument_catalog import InstrumentCatalog, InstrumentIdentity, normalize_cnpj


def main() -> int:
    parser = argparse.ArgumentParser(description="Build broad B3 equity catalog from two official B3 snapshots and CVM registry")
    parser.add_argument("--b3-instruments-zip", required=True)
    parser.add_argument("--b3-isin-zip", required=True)
    parser.add_argument("--cvm-registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-output")
    args = parser.parse_args()

    instruments = parse_bvbg028_zip(args.b3_instruments_zip)
    isin_registry = parse_isin_registry_zip(args.b3_isin_zip)
    with Path(args.cvm_registry).open("r", encoding="latin-1", newline="") as handle:
        cvm_rows = list(csv.DictReader(handle, delimiter=";"))
    cvm_by_cnpj = {}
    cvm_by_root = {}
    for row in cvm_rows:
        cnpj = normalize_cnpj(row.get("CNPJ_CIA"))
        if cnpj and str(row.get("SIT") or "").strip().upper() == "ATIVO":
            cvm_by_cnpj.setdefault(cnpj, []).append(row)
            cvm_by_root.setdefault(cnpj[:8], []).append(row)

    accepted = []
    rejected = []
    by_ticker = {}
    for item in instruments.equities():
        by_ticker.setdefault(item.ticker, []).append(item)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for ticker, b3_items in sorted(by_ticker.items()):
        candidates = []
        reasons = []
        for item in b3_items:
            security = isin_registry.securities.get(item.isin)
            if not security or security.category != "E" or security.status != "A" or security.numbering_agency != "B3":
                continue
            issuer = isin_registry.issuers.get(security.issuer_code)
            if not issuer:
                continue
            exact = cvm_by_cnpj.get(issuer.cnpj, [])
            root_matches = cvm_by_root.get(issuer.cnpj[:8], []) if len(issuer.cnpj) == 14 else []
            matches = exact or (root_matches if len(root_matches) == 1 else [])
            method = "EXACT_CNPJ" if exact else "UNIQUE_CNPJ_ROOT"
            for cvm in matches:
                candidates.append((item, issuer, cvm, method))
        identities = {(normalize_cnpj(cvm.get("CNPJ_CIA")), str(cvm.get("CD_CVM") or "").strip().lstrip("0")) for _, _, cvm, _ in candidates}
        if not candidates:
            reasons.append("NO_ACTIVE_B3_ISIN_CNPJ_CVM_CHAIN")
        elif len(identities) != 1:
            reasons.append("AMBIGUOUS_CNPJ_OR_CVM_IDENTITY")
        if reasons:
            rejected.append({"ticker": ticker, "reasons": reasons, "b3_instrument_count": len(b3_items)})
            continue
        item, issuer, cvm, match_method = candidates[0]
        suffix_match = re.search(r"(\d+)$", ticker)
        suffix = suffix_match.group(1) if suffix_match else ""
        share_kind = item.specification_code.strip().split(maxsplit=1)[0] if item.specification_code.strip() else ""
        eligible = suffix in {"3", "4", "5", "6", "7", "8", "11"} and share_kind in {"ON", "PN", "PNA", "PNB", "PNC", "PND", "UNT"}
        accepted.append(InstrumentIdentity(
            ticker=ticker, cvm_code=str(cvm.get("CD_CVM") or "").strip().lstrip("0"), cnpj=normalize_cnpj(cvm.get("CNPJ_CIA")),
            company_name=str(cvm.get("DENOM_SOCIAL") or "").strip(),
            ticker_source="B3 BVBG.028.02 + B3 ISIN registry",
            ticker_source_date=instruments.reference_date or item.source_member,
            validated_at=now,
            isin=item.isin, specification_code=item.specification_code.strip(), research_eligible=eligible,
            eligibility_reason="PRIMARY_EQUITY" if eligible else "NON_PRIMARY_OR_TEMPORARY_EQUITY_INSTRUMENT",
            b3_issuer_cnpj=issuer.cnpj, identity_match_method=match_method,
        ))
    catalog = InstrumentCatalog(accepted, {
        "version": 2, "generated_at": now,
        "b3_instruments_sha256": instruments.source_sha256,
        "b3_isin_sha256": isin_registry.source_sha256,
        "method": "Exact ISIN -> B3 issuer CNPJ -> active CVM issuer; no fuzzy matching",
    })
    cvm_audit = catalog.audit_against_cvm_csv(args.cvm_registry)
    audit = {
        "status": "PASS" if cvm_audit["status"] == "PASS" and accepted else "FAIL",
        "accepted_count": len(accepted), "research_eligible_count": sum(item.research_eligible for item in accepted),
        "non_research_eligible_count": sum(not item.research_eligible for item in accepted), "rejected_count": len(rejected),
        "b3_equity_ticker_count": len(by_ticker), "rejected": rejected, "cvm_audit": cvm_audit,
        "b3_instruments_sha256": instruments.source_sha256, "b3_isin_sha256": isin_registry.source_sha256,
        "exact_cnpj_count": sum(item.identity_match_method == "EXACT_CNPJ" for item in accepted),
        "unique_cnpj_root_count": sum(item.identity_match_method == "UNIQUE_CNPJ_ROOT" for item in accepted),
    }
    audit_path = Path(args.audit_output) if args.audit_output else Path(args.output).with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if audit["status"] != "PASS":
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 2
    catalog.dump(args.output)
    print(json.dumps({"status": "PASS", "accepted_count": len(accepted), "rejected_count": len(rejected), "output": args.output, "audit": str(audit_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
