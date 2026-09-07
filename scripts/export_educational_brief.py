"""Export a fact-only educational handoff from a PROMETHEUS report JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prometheus.content_release import write_educational_brief


def _report(payload: dict) -> dict:
    if isinstance(payload.get("tickers"), list) and len(payload["tickers"]) == 1:
        return payload["tickers"][0].get("analysis") or {}
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Export fact-only educational content brief")
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-facts", type=int, default=5)
    args = parser.parse_args()
    payload = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
    brief = write_educational_brief(_report(payload), args.output, max_facts=args.max_facts)
    print(json.dumps({"status": brief["status"], "publication_gate": brief["publication_gate"], "path": brief["path"]}, ensure_ascii=False, indent=2))
    return 0 if brief["publication_gate"]["eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
