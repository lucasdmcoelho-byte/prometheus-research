from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from prometheus.semantic_consistency import sector_contamination


CLAIM_TYPES = {"FACT", "CALCULATION", "INTERPRETATION", "ESTIMATE", "RISK", "LIMITATION"}


class EvidenceEngine:
    """Creates auditable claims and links every assertion to source records."""

    def build_claim(
        self,
        *,
        section: str,
        text: str,
        claim_type: str,
        source_ids: Optional[Iterable[str]] = None,
        value: Any = None,
        unit: Optional[str] = None,
        confidence: str = "medium",
        materiality: str = "medium",
        formula: Optional[str] = None,
        assumptions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        normalized_type = str(claim_type).upper()
        if normalized_type not in CLAIM_TYPES:
            raise ValueError(f"Unsupported claim type: {claim_type}")
        identifiers = sorted({str(item) for item in (source_ids or []) if item})
        digest = hashlib.sha256(
            f"{section}|{text}|{normalized_type}|{'|'.join(identifiers)}".encode("utf-8")
        ).hexdigest()[:16]
        requires_source = normalized_type in {"FACT", "CALCULATION", "INTERPRETATION", "ESTIMATE"}
        return {
            "claim_id": f"CLM-{digest}",
            "section": section,
            "text": str(text).strip(),
            "classification": normalized_type,
            "value": value,
            "unit": unit,
            "source_ids": identifiers,
            "confidence": confidence,
            "materiality": materiality,
            "formula": formula,
            "assumptions": list(assumptions or []),
            "verified": bool(identifiers) if requires_source else True,
            "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

    def build_metric_claims(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        claims: List[Dict[str, Any]] = []
        used_source_ids: set[str] = set()
        for index, source in enumerate(sources):
            source_id = str(source.get("source_id") or f"SRC-{index + 1:04d}")
            # A report may be re-enriched after it has sources from a prior
            # projection.  Never allow its new sources to reuse a positional
            # identifier and silently corrupt the claim lineage.
            if source_id in used_source_ids:
                source_id = self._deduplicated_source_id(source, source_id, used_source_ids)
            source["source_id"] = source_id
            used_source_ids.add(source_id)
            metric = str(source.get("metric") or "métrica")
            value = source.get("value")
            if value is None:
                continue
            formula = source.get("formula")
            requested_type = str(source.get("claim_classification") or "").upper()
            claim_type = (
                requested_type if requested_type in CLAIM_TYPES
                else "CALCULATION" if source.get("source_type") == "calculated" or formula
                else "FACT"
            )
            claims.append(self.build_claim(
                section="fundamentals",
                text=source.get("claim_text") or f"{metric} no período {source.get('period')}: {value} {source.get('unit') or ''}".strip(),
                claim_type=claim_type,
                source_ids=[source_id],
                value=value,
                unit=source.get("unit"),
                confidence=source.get("confidence", "medium"),
                materiality="high" if metric in {"revenue", "net_income", "operating_cash_flow"} else "medium",
                formula=formula,
                assumptions=source.get("assumptions") or [],
            ))
        return claims

    @staticmethod
    def _deduplicated_source_id(source: Dict[str, Any], original: str, used: set[str]) -> str:
        material = "|".join(str(source.get(field) or "") for field in (
            "metric", "value", "unit", "period", "publication_date", "source", "source_url",
            "source_sha256", "protocol", "version", "formula",
        ))
        candidate = f"{original}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:10]}"
        suffix = 2
        while candidate in used:
            candidate = f"{original}-{hashlib.sha256((material + '|' + str(suffix)).encode('utf-8')).hexdigest()[:10]}"
            suffix += 1
        return candidate

    @staticmethod
    def contains_number(text: str) -> bool:
        return bool(re.search(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?%?", text or ""))

    def audit_claims(
        self,
        claims: List[Dict[str, Any]],
        sources: Optional[List[Dict[str, Any]]] = None,
        cutoff: Any = None,
        sector_key: str = "general",
    ) -> Dict[str, Any]:
        """Audit claims and, when supplied, resolve them against source records.

        A non-empty ``source_ids`` list is not evidence by itself.  Commercial
        review must prove that every identifier resolves to a unique source and
        that numeric source records carry unit, period, publication date and
        publisher.  ``cutoff`` also turns future or malformed availability dates
        into hard failures instead of trusting a previously stored gate result.
        """
        issues: List[Dict[str, str]] = []
        source_index: Dict[str, Dict[str, Any]] = {}
        cutoff_at = self._parse_datetime(cutoff)
        if sources is not None:
            for source in sources:
                source_id = str(source.get("source_id") or "").strip()
                if not source_id:
                    issues.append({"claim_id": "SOURCE-UNKNOWN", "reason": "source_missing_id"})
                    continue
                if source_id in source_index:
                    issues.append({"claim_id": f"SOURCE-{source_id}", "reason": "duplicate_source_id"})
                    continue
                source_index[source_id] = source
                if self._is_number(source.get("value")):
                    for field in ("unit", "period", "publication_date", "source"):
                        if self._is_missing_provenance(source.get(field)):
                            issues.append({"claim_id": f"SOURCE-{source_id}", "reason": f"numeric_source_missing_{field}"})
                publication_value = source.get("publication_date")
                publication_at = self._parse_datetime(publication_value)
                if publication_value and publication_at is None:
                    issues.append({"claim_id": f"SOURCE-{source_id}", "reason": "invalid_source_publication_date"})
                elif cutoff_at and publication_at and publication_at > cutoff_at:
                    issues.append({"claim_id": f"SOURCE-{source_id}", "reason": "lookahead_source"})
        for claim in claims:
            claim_id = str(claim.get("claim_id") or "UNKNOWN")
            classification = claim.get("classification")
            if classification not in CLAIM_TYPES:
                issues.append({"claim_id": claim_id, "reason": "invalid_classification"})
            if not str(claim.get("text") or "").strip():
                issues.append({"claim_id": claim_id, "reason": "empty_text"})
            if classification in {"FACT", "CALCULATION", "INTERPRETATION", "ESTIMATE"} and not claim.get("source_ids"):
                issues.append({"claim_id": claim_id, "reason": "missing_source"})
            if (
                self.contains_number(str(claim.get("text") or ""))
                and not claim.get("source_ids")
                and classification not in {"FACT", "CALCULATION", "INTERPRETATION", "ESTIMATE"}
            ):
                issues.append({"claim_id": claim_id, "reason": "numeric_assertion_missing_source"})
            if self._is_number(claim.get("value")) and self._is_missing_provenance(claim.get("unit")):
                issues.append({"claim_id": claim_id, "reason": "numeric_claim_missing_unit"})
            if classification == "CALCULATION" and not claim.get("formula"):
                issues.append({"claim_id": claim_id, "reason": "missing_formula"})
            if classification == "ESTIMATE" and not claim.get("assumptions"):
                issues.append({"claim_id": claim_id, "reason": "missing_assumptions"})
            if classification == "INTERPRETATION":
                for finding in sector_contamination(claim.get("text"), sector_key):
                    issues.append({
                        "claim_id": claim_id,
                        "reason": "semantic_contamination:%s:%s" % (
                            finding["foreign_sector"], finding["term"],
                        ),
                    })
            if sources is not None:
                for source_id in claim.get("source_ids") or []:
                    if str(source_id) not in source_index:
                        issues.append({"claim_id": claim_id, "reason": f"unresolved_source:{source_id}"})
        issue_claim_ids = {item["claim_id"] for item in issues}
        return {
            "status": "PASS" if not issues else "FAIL",
            "claim_count": len(claims),
            "verified_count": sum(
                1 for item in claims
                if str(item.get("claim_id") or "UNKNOWN") not in issue_claim_ids
            ),
            "source_count": len(source_index) if sources is not None else None,
            "issues": issues,
        }

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _is_missing_provenance(value: Any) -> bool:
        return str(value or "").strip().lower() in {
            "", "unknown", "not_provided", "latest", "latest_available", "n/a", "na", "none",
        }

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value in (None, "", "not_provided"):
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, datetime.max.time())
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                try:
                    parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d")
                except (TypeError, ValueError):
                    return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
