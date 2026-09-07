"""Deterministic semantic compatibility checks for research publication text.

The checks deliberately use a small, auditable vocabulary. They are a release
guardrail, not an attempt to infer a company's sector from prose.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List

from prometheus.sector_models import SECTOR_SEMANTIC_TERMS


def normalize_text(value: Any) -> str:
    """Return lowercase, accent-free text suitable for deterministic matching."""
    raw = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(character for character in raw if not unicodedata.combining(character))


def sector_contamination(text: Any, declared_sector: str) -> List[Dict[str, str]]:
    """Return foreign-sector vocabulary found in text for a declared sector."""
    normalized = normalize_text(text)
    sector_key = str(declared_sector or "general")
    if not normalized or sector_key not in SECTOR_SEMANTIC_TERMS:
        return []
    findings: List[Dict[str, str]] = []
    for foreign_sector, terms in SECTOR_SEMANTIC_TERMS.items():
        if foreign_sector == sector_key:
            continue
        for term in terms:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized):
                findings.append({"foreign_sector": foreign_sector, "term": term})
    return findings
