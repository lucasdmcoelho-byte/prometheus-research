import datetime
import re
from typing import Any, Dict, List, Optional

from prometheus.models import AssetProfile, MarketSnapshot, ThesisEvidence


class CatalystEngine:
    CATALYST_PATTERNS = {
        "earnings": [r"lucro", r"receita", r"earnings", r"guidance", r"forecast"],
        "corporate_action": [r"dividendo", r"split", r"aquisição", r"incorporação", r"compra"],
        "regulatory": [r"investigação", r"denúncia", r"autorização", r"cvm", r"b3"],
        "macro": [r"inflação", r"juros", r"taxa", r"câmbio", r"pib", r"desemprego"],
    }

    def identify(
        self,
        news_items: Optional[List[Dict[str, Any]]],
        asset_profile: AssetProfile,
        market_snapshot: MarketSnapshot,
    ) -> Dict[str, Any]:
        if not news_items:
            return {
                "catalysts": [],
                "catalyst_score": 50.0,
                "evidence": [
                    ThesisEvidence(
                        claim="Nenhum catalisador recente identificado",
                        evidence_type="catalyst",
                        confidence=0.45,
                        details="Não há notícias recentes capazes de alterar expectativas no curto prazo.",
                        timestamp=datetime.datetime.utcnow(),
                    )
                ],
            }

        catalysts: List[Dict[str, Any]] = []
        evidence: List[ThesisEvidence] = []
        accumulator = 0.0

        for item in news_items:
            title = str(item.get("title", "") or "").lower()
            link = item.get("url") or ""
            matched = False
            for category, patterns in self.CATALYST_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, title, flags=re.IGNORECASE):
                        matched = True
                        catalysts.append(
                            {
                                "category": category,
                                "title": item.get("title"),
                                "url": link,
                                "source": item.get("source") or "news",
                                "published_at": item.get("published_at"),
                                "factual_status": item.get("event_factual_status") or (
                                    "PRIMARY_CONFIRMED" if item.get("source_type") == "primary"
                                    else "SECONDARY_REPORT_UNVERIFIED"
                                ),
                                "interpretation": "POTENTIAL_CATALYST",
                            }
                        )
                        primary_confirmed = item.get("source_type") == "primary"
                        materiality_weight = (
                            10.0 if item.get("materiality") == "high" else 5.0
                        ) if primary_confirmed else (
                            2.5 if item.get("materiality") == "high" else 1.0
                        )
                        sentiment = float(item.get("sentiment_score", 50.0) or 50.0)
                        direction = 1.0 if sentiment > 55 else -1.0 if sentiment < 45 else 0.0
                        accumulator += materiality_weight * direction
                        evidence.append(
                            ThesisEvidence(
                                claim=f"Catalisador de {category} detectado",
                                evidence_type="catalyst",
                                confidence=(0.8 if primary_confirmed else 0.45) if item.get("point_in_time_eligible") else 0.3,
                                details=(
                                    "A publicação '"
                                    + str(item.get("title") or "")
                                    + "' é interpretada como catalisador potencial para "
                                    + asset_profile.ticker
                                    + ("; o evento tem fonte primária." if primary_confirmed else "; o evento não foi confirmado por fonte primária.")
                                ),
                                timestamp=datetime.datetime.utcnow(),
                            )
                        )
                        break
                if matched:
                    break

        catalyst_score = max(0.0, min(100.0, 50.0 + accumulator))
        if market_snapshot.price_change_percent is not None and abs(market_snapshot.price_change_percent) > 5.0:
            catalyst_score = min(100.0, catalyst_score + 10.0)
            evidence.append(
                ThesisEvidence(
                    claim="Movimento de preço acentuado reforça catalisador",
                    evidence_type="catalyst",
                    confidence=0.55,
                    details=f"Movimento de preço {market_snapshot.price_change_percent:.2f}% sugere incorporação de novo catalisador.",
                    timestamp=datetime.datetime.utcnow(),
                )
            )

        return {
            "catalysts": catalysts,
            "catalyst_score": round(catalyst_score, 2),
            "evidence": evidence,
        }
