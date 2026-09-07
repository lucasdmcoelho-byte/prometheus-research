from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from prometheus.rad_index import parse_rad_query_html


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an auditable DFP/ITR index from an official RAD result-table HTML export")
    parser.add_argument("html", nargs="+", help="One or more complete HTML exports from the official RAD query")
    parser.add_argument("--output", required=True, help="Destination rad_document_index.json")
    parser.add_argument("--source-url", default="https://www.rad.cvm.gov.br/ENETWeb/frmConsultaExternaCVM.aspx")
    parser.add_argument("--captured-at", help="Snapshot timestamp in ISO-8601; defaults to current UTC")
    parser.add_argument("--merge", action="store_true", help="Preserve documents already present in the destination index")
    args = parser.parse_args()

    captured_at = dt.datetime.fromisoformat(args.captured_at.replace("Z", "+00:00")).replace(tzinfo=None) if args.captured_at else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    snapshots = [parse_rad_query_html(Path(path).read_bytes(), args.source_url, captured_at) for path in args.html]
    documents = []
    source_hashes = []
    for snapshot in snapshots:
        documents.extend(snapshot["documents"])
        source_hashes.append(snapshot["source_sha256"])

    output = Path(args.output)
    if args.merge and output.is_file():
        previous = json.loads(output.read_text(encoding="utf-8"))
        documents.extend(previous.get("documents") or [])
        source_hashes.extend(previous.get("source_sha256s") or ([previous["source_sha256"]] if previous.get("source_sha256") else []))
    unique = {
        (item["cvm_code"], item["filing_type"], item["reference_date"], str(item.get("version") or ""), item["sequence"]): item
        for item in documents
    }
    payload = {
        "schema_version": 1,
        "captured_at": captured_at.isoformat(),
        "source_url": args.source_url,
        "source_sha256s": sorted(set(source_hashes)),
        "method": "Official RAD result table; exact document sequence and protocol; no name inference",
        "documents": sorted(unique.values(), key=lambda item: (item["cvm_code"], item["reference_date"], item["received_at"], int(item.get("version") or 0))),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": str(output), "documents": len(payload["documents"]), "source_sha256s": payload["source_sha256s"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
