from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from prometheus.sector_models import resolve_sector_model


class ResearchEngine:
    """Research layer for structured source tracking, sector profiles and traceability."""

    SOURCE_TIERS = {
        "TIER_1": "CVM / RI / DFP / ITR / release / fato relevante",
        "TIER_2": "provedores estruturados e bases confiáveis",
        "TIER_3": "notícias, agregadores e materiais não primários",
    }

    def _infer_source_tier(self, source: str, source_type: str) -> str:
        source_text = (source or "").lower()
        if source_type == "primary" or any(token in source_text for token in ["fato relevante", "ri", "dfp", "itr", "cvm", "release", "apresentacao", "investor"]):
            return "TIER_1"
        if any(token in source_text for token in ["yahoo", "finance", "b3", "factset", "refinitiv", "s&p", "macrotrends"]):
            return "TIER_2"
        return "TIER_3"

    def build_source_record(
        self,
        metric: str,
        value: Any,
        unit: str,
        period: str,
        reference_date: str,
        publication_date: str,
        source: str,
        source_type: str = "secondary",
        confidence: str = "medium",
        source_tier: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        record = {
            "metric": metric,
            "value": value,
            "unit": unit,
            "period": period,
            "reference_date": reference_date,
            "publication_date": publication_date,
            "source": source,
            "source_type": source_type,
            "confidence": confidence,
            "source_tier": source_tier or self._infer_source_tier(source, source_type),
            "retrieved_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        record.update(kwargs)
        return record

    def build_sector_profile(self, sector_name: str) -> Dict[str, Any]:
        normalized = (sector_name or "").strip().lower()
        profiles = {
            "real estate": {
                "drivers": [
                    "vendas de unidades",
                    "entregas",
                    "crédito imobiliário",
                    "juros",
                    "demanda por habitação",
                ],
                "risks": [
                    "queda de demanda",
                    "aumento de juros",
                    "inadimplência",
                    "atraso de obra",
                ],
                "macro": [
                    "Selic",
                    "crédito",
                    "renda",
                    "emprego",
                    "MCMV",
                ],
                "indicators": [
                    "venda por unidade",
                    "margem bruta",
                    "dívida líquida",
                    "caixa",
                    "margem EBITDA",
                ],
                "kpis": [
                    "VSO",
                    "vendas brutas",
                    "vendas líquidas",
                    "distrato",
                    "ticket médio",
                    "margem bruta",
                    "ROE",
                    "alavancagem",
                    "caixa",
                ],
            },
            "financial": {
                "drivers": [
                    "spread",
                    "crédito",
                    "captação",
                    "inadimplência",
                    "volume de operações",
                ],
                "risks": [
                    "inadimplência",
                    "pressão de spread",
                    "risco de crédito",
                    "seguro de risco sistêmico",
                ],
                "macro": [
                    "Selic",
                    "crédito",
                    "inadimplência",
                    "atividade econômica",
                ],
                "indicators": [
                    "NIM",
                    "ROE",
                    "provisões",
                    "carteira de crédito",
                    "dívida líquida",
                ],
                "kpis": [
                    "ROE",
                    "NIM",
                    "carteira",
                    "provisão",
                    "spread",
                ],
            },
            "energy": {
                "drivers": [
                    "demanda",
                    "preço da commodity",
                    "hidrologia",
                    "tarifas",
                    "capacidade de geração",
                ],
                "risks": [
                    "queda de preço",
                    "estrangulamento regulatório",
                    "estresse hidrológico",
                    "custos de expansão",
                ],
                "macro": [
                    "demanda",
                    "hidrologia",
                    "tarifas",
                    "juros",
                    "regulação",
                ],
                "indicators": [
                    "margem EBITDA",
                    "capex",
                    "geração",
                    "custo por MWh",
                    "dívida líquida",
                ],
                "kpis": [
                    "geração",
                    "margem EBITDA",
                    "capex",
                    "dívida líquida",
                ],
            },
            "mining": {
                "drivers": [
                    "preço do minério",
                    "produção",
                    "China",
                    "câmbio",
                    "logística",
                ],
                "risks": [
                    "queda de commodity",
                    "custo energético",
                    "desempenho de demanda",
                    "produção e logística",
                ],
                "macro": [
                    "minério",
                    "China",
                    "câmbio",
                    "produção",
                    "frete",
                ],
                "indicators": [
                    "custo de produção",
                    "volume extraído",
                    "margem bruta",
                    "dívida líquida",
                    "cash cost",
                ],
                "kpis": [
                    "produção",
                    "cash cost",
                    "margem bruta",
                    "dívida líquida",
                ],
            },
            "oil": {
                "drivers": [
                    "Brent",
                    "produção",
                    "demanda global",
                    "câmbio",
                    "refino",
                ],
                "risks": [
                    "queda de Brent",
                    "capex",
                    "produção",
                    "regulação",
                    "custo de operação",
                ],
                "macro": [
                    "Brent",
                    "câmbio",
                    "demanda global",
                    "OPEP",
                    "produção",
                ],
                "indicators": [
                    "lucro líquido",
                    "EBITDA",
                    "produção",
                    "margem operacional",
                    "dívida",
                ],
                "kpis": [
                    "produção",
                    "EBITDA",
                    "margem operacional",
                    "dívida",
                ],
            },
            "industrial": {
                "drivers": [
                    "atividade industrial",
                    "demanda",
                    "capacidade",
                    "preço",
                    "eficiência",
                ],
                "risks": [
                    "queda de demanda",
                    "custos",
                    "competição",
                    "execução de projetos",
                ],
                "macro": [
                    "atividade industrial",
                    "juros",
                    "câmbio",
                    "consumo",
                ],
                "indicators": [
                    "margem EBITDA",
                    "receita",
                    "EBIT",
                    "capex",
                    "dívida líquida",
                ],
                "kpis": [
                    "receita",
                    "EBITDA",
                    "capex",
                    "dívida líquida",
                ],
            },
        }

        model = resolve_sector_model(sector_name)
        legacy_profile = profiles.get(normalized)
        # Yahoo's broad "Energy" sector means oil & gas; the legacy profile
        # mixed power-generation/hydrology concepts and could misdescribe it.
        if normalized == "energy" and model.key == "oil_gas":
            legacy_profile = None
        profile = dict(legacy_profile or {
            "drivers": list(model.drivers),
            "risks": list(model.risks),
            "macro": list(model.macro_series),
            "indicators": list(model.kpis),
            "kpis": list(model.kpis),
        })
        profile["benchmark"] = model.benchmark
        profile["valuation_methods"] = list(model.valuation_methods)
        profile["sector_model_key"] = model.key
        profile["sector"] = sector_name
        return profile

    def build_sector_kpi_profile(self, sector_name: str) -> Dict[str, Any]:
        base = self.build_sector_profile(sector_name)
        return {
            "sector": base.get("sector") or sector_name,
            "drivers": base.get("drivers", []),
            "risks": base.get("risks", []),
            "macro": base.get("macro", []),
            "kpis": base.get("kpis", []),
            "indicators": base.get("indicators", []),
            "benchmark": base.get("benchmark"),
            "valuation_methods": base.get("valuation_methods", []),
            "sector_model_key": base.get("sector_model_key"),
        }

    def build_company_research(self, ticker: str, sector: str = "Unknown", **kwargs: Any) -> Dict[str, Any]:
        sector_profile = self.build_sector_profile(sector)
        company = {
            "ticker": ticker,
            "sector": sector,
            "business_model": kwargs.get(
                "business_model",
                "Modelo de negócio ainda não confirmado por uma fonte primária.",
            ),
            "geographic_exposure": kwargs.get("geographic_exposure", []),
            "revenue_drivers": kwargs.get("revenue_drivers", sector_profile.get("drivers", [])),
            "operating_kpis": kwargs.get("operating_kpis", sector_profile.get("kpis", [])),
            "financial_quality": kwargs.get("financial_quality", {
                "remarks": ["Qualidade financeira deve ser validada por caixa, alavancagem e ROE."],
                "status": "INCOMPLETE",
            }),
            "balance_sheet": kwargs.get("balance_sheet", {
                "debt_profile": "Não informado em detalhe",
                "liquidity": "Não informado em detalhe",
            }),
            "capital_allocation": kwargs.get("capital_allocation", {
                "focus": ["investimentos", "distribuições", "estrutura de capital", "preservação de caixa"],
            }),
            "recent_operating_developments": kwargs.get("recent_operating_developments", []),
            "kpis": kwargs.get("operating_kpis", sector_profile.get("kpis", [])),
            "competitive_position": kwargs.get("competitive_position", "Sem comparação comparável confirmada no momento."),
            "valuation_context": kwargs.get("valuation_context", {
                "status": "INSUFFICIENT_DATA",
                "remarks": ["Valuation depende de múltiplos, geração e consistência dos KPIs do setor."],
            }),
            "catalysts": kwargs.get("catalysts", []),
            "risks": kwargs.get("risks", sector_profile.get("risks", [])),
            "thesis_monitors": kwargs.get("thesis_monitors", sector_profile.get("kpis", [])),
            "evidence": kwargs.get("evidence", []),
            "limitations": kwargs.get("limitations", [
                "Dados específicos de setor podem estar incompletos ou não verificados em fonte primária.",
            ]),
            "data_quality_status": kwargs.get("data_quality_status", "INSUFFICIENT_DATA"),
        }
        return company

    def build_recent_operating_developments(self, ticker: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for item in items:
            current = item.get("current_value")
            previous = item.get("previous_value")
            change = None
            try:
                if current is not None and previous is not None:
                    change = float(current) - float(previous)
            except (TypeError, ValueError):
                change = None
            records.append({
                "ticker": ticker,
                "metric": item.get("metric"),
                "current_value": current,
                "previous_value": previous,
                "change": change,
                "unit": item.get("unit"),
                "period": item.get("period"),
                "reference_date": item.get("reference_date"),
                "source": item.get("source"),
                "direction": item.get("direction"),
                "interpretation": item.get("interpretation"),
                "classification": self.classify_evidence(str(item.get("interpretation") or item.get("metric") or "Sem classificação"))["classification"],
            })
        return records

    def classify_evidence(self, text: str) -> Dict[str, Any]:
        if not text or not str(text).strip():
            return {"classification": "UNAVAILABLE", "reason": "Texto vazio."}
        normalized = str(text).lower()
        if any(token in normalized for token in ["conforme", "segundo", "confirmou", "cresceu de", "fechou em", "foi de", "atingiu", "emitiu", "publicou"]):
            return {"classification": "FACT", "reason": "Afirmativa factual ou quantitativa apoiada por referência explícita."}
        if any(token in normalized for token in ["sugere", "indica", "mostra", "aponta", "pode", "podem", "parece", "interpretação"]):
            return {"classification": "INTERPRETATION", "reason": "Afirmativa qualitativa com interpretação do dado."}
        if any(token in normalized for token in ["poderia", "tende a", "se mantiver", "se confirmar", "espera-se"]):
            return {"classification": "INFERENCE", "reason": "Conclusão deduzida a partir do contexto, ainda não confirmada."}
        if any(token in normalized for token in ["estimado", "estimativa", "assume", "assumindo", "sensibilidade"]):
            return {"classification": "ESTIMATE", "reason": "Baseado em premissa ou sensibilidade, não em dado observado direto."}
        return {"classification": "UNAVAILABLE", "reason": "Não há base suficiente para classificar a afirmação."}

    def rank_materiality(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ranked: List[Dict[str, Any]] = []
        for item in items:
            importance = float(item.get("importance", 0.0) or 0.0)
            magnitude = float(item.get("magnitude", 0.0) or 0.0)
            direction = str(item.get("direction", "neutral")).lower()
            score = importance * magnitude
            if direction == "up":
                score *= 1.0
            elif direction == "down":
                score *= 0.9
            ranked.append({
                **item,
                "materiality_score": round(score, 4),
            })
        ranked.sort(key=lambda i: i["materiality_score"], reverse=True)
        return ranked

    def build_contradiction_matrix(
        self,
        supporting_evidence: Optional[List[str]] = None,
        contradicting_evidence: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        support = supporting_evidence or []
        contradiction = contradicting_evidence or []
        net_interpretation = "Sinais equilibrados" if support and contradiction else "Sem contradição clara"
        if len(support) > len(contradiction):
            net_interpretation = "O conjunto de evidências favorece a tese atual"
        elif len(contradiction) > len(support):
            net_interpretation = "Há sinais de pressão contrária à tese atual"
        return {
            "supporting_evidence": support,
            "contradicting_evidence": contradiction,
            "net_interpretation": net_interpretation,
            "confidence": kwargs.get("confidence", "medium"),
        }

    def build_peer_analysis(self, ticker: str, peers: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> Dict[str, Any]:
        peers = peers or []
        if not peers:
            return {
                "ticker": ticker,
                "status": "INSUFFICIENT_DATA",
                "peers": [],
                "summary": "Dados comparáveis insuficientes para peer analysis confiável.",
            }

        rows = []
        for peer in peers:
            rows.append({
                "company": peer.get("company"),
                "metric": peer.get("metric"),
                "value": peer.get("value"),
                "period": peer.get("period"),
                "source": peer.get("source"),
                "rank": peer.get("rank"),
                "sector_median": peer.get("sector_median"),
                "premium_discount": peer.get("premium_discount"),
            })
        return {
            "ticker": ticker,
            "status": "AVAILABLE",
            "peers": rows,
            "summary": "Comparação feita apenas com métricas comparáveis e períodos compatíveis.",
        }

    def build_research_report(self, ticker: str, sector: str = "Real Estate", **kwargs: Any) -> Dict[str, Any]:
        company = self.build_company_research(ticker=ticker, sector=sector, **kwargs)
        peer_analysis = self.build_peer_analysis(ticker=ticker, peers=kwargs.get("peers") or [])
        valuation_scenarios = kwargs.get("valuation_scenarios")
        valuation_inputs = (
            kwargs.get("base_value"),
            kwargs.get("bear_multiple"),
            kwargs.get("bull_multiple"),
            kwargs.get("earnings_base"),
        )
        if valuation_scenarios is None and all(value is not None for value in valuation_inputs):
            valuation_scenarios = self.build_valuation_scenarios(
                base_value=kwargs["base_value"],
                bear_multiple=kwargs["bear_multiple"],
                bull_multiple=kwargs["bull_multiple"],
                earnings_base=kwargs["earnings_base"],
            )
        if valuation_scenarios is None:
            valuation_scenarios = {
                "status": "INSUFFICIENT_DATA",
                "reason": "Cenários não calculados sem lucro-base e premissas de múltiplos explicitamente fornecidos.",
            }
        return {
            "ticker": ticker,
            "sector": sector,
            "executive_summary": kwargs.get(
                "executive_summary",
                "Tese apoiada por dados quantitativos do setor e por evidência operacional relevante; a interpretação depende da consistência de vendas, caixa e alavancagem.",
            ),
            "company_research": company,
            "peer_analysis": peer_analysis,
            "valuation_scenarios": valuation_scenarios,
            "sources": kwargs.get("sources", []),
            "contradiction_matrix": self.build_contradiction_matrix(
                kwargs.get("supporting_evidence"),
                kwargs.get("contradicting_evidence"),
                confidence=kwargs.get("confidence", "medium"),
            ),
            "evidence_chain": [
                "RAW DATA",
                "NORMALIZATION",
                "FEATURE",
                "ENGINE RESULT",
                "SCORE CONTRIBUTION",
                "THESIS INTERPRETATION",
                "REPORT CLAIM",
            ],
            "data_quality_status": kwargs.get("data_quality_status", "INSUFFICIENT_DATA"),
            "confidence": kwargs.get("confidence", "medium"),
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

    def build_valuation_scenarios(
        self,
        base_value: float,
        bear_multiple: float,
        bull_multiple: float,
        earnings_base: float,
    ) -> Dict[str, Dict[str, Any]]:
        base = float(base_value)
        earnings = float(earnings_base) if earnings_base is not None else 0.0
        return {
            "bear": {
                "valuation_method": "sensitivity analysis",
                "metric_used": "earnings_base",
                "reference_earnings": earnings,
                "multiple": float(bear_multiple),
                "implied_value": round(earnings * float(bear_multiple), 2),
                "assumptions": ["desaceleração operacional", "juros mais altos", "margens pressionadas"],
                "limitations": ["Não é preço-alvo oficial; é cenário de sensibilidade."],
            },
            "base": {
                "valuation_method": "base case",
                "metric_used": "earnings_base",
                "reference_earnings": earnings,
                "multiple": round(base / earnings, 2) if earnings else None,
                "implied_value": round(base, 2),
                "assumptions": ["execução operacional estável", "mix e níveis de caixa coerentes"],
                "limitations": ["Sem DCF completo, a premissa precisa ser validada com evidência de mercado."],
            },
            "bull": {
                "valuation_method": "sensitivity analysis",
                "metric_used": "earnings_base",
                "reference_earnings": earnings,
                "multiple": float(bull_multiple),
                "implied_value": round(earnings * float(bull_multiple), 2),
                "assumptions": ["melhora de vendas", "queda de juros e desenvolvimento operacional"],
                "limitations": ["Não é preço-alvo oficial; é cenário de sensibilidade."],
            },
        }

    def build_research_trace(
        self,
        ticker: str,
        metric: str,
        value: Any,
        source: str,
        calculation: str,
        conclusion: str,
    ) -> List[Dict[str, Any]]:
        return [{
            "ticker": ticker,
            "metric": metric,
            "value": value,
            "source": source,
            "calculation": calculation,
            "conclusion": conclusion,
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }]

    def build_news_record(
        self,
        ticker: str,
        title: str,
        date: str,
        source: str,
        url: str,
        summary: str,
        company_impact: str,
        impact: str,
        confidence: str,
    ) -> Dict[str, Any]:
        return {
            "ticker": ticker,
            "title": title,
            "date": date,
            "source": source,
            "url": url,
            "summary": summary,
            "company_impact": company_impact,
            "impact": impact,
            "confidence": confidence,
        }

    def build_macro_driver(
        self,
        sector_name: str,
        macro_variable: str,
        company_impact: str,
        mechanism: str,
        source: str,
    ) -> Dict[str, Any]:
        return {
            "sector": sector_name,
            "macro_variable": macro_variable,
            "company_impact": company_impact,
            "mechanism": mechanism,
            "source": source,
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

    def build_risk_record(
        self,
        risk: str,
        evidence: str,
        mechanism: str,
        impact: str,
        monitoring_indicator: str,
        source: str,
    ) -> Dict[str, Any]:
        return {
            "risk": risk,
            "evidence": evidence,
            "mechanism": mechanism,
            "impact": impact,
            "monitoring_indicator": monitoring_indicator,
            "source": source,
        }

    def build_catalyst_record(
        self,
        catalyst: str,
        evidence: str,
        mechanism: str,
        horizon: str,
        source: str,
    ) -> Dict[str, Any]:
        return {
            "catalyst": catalyst,
            "evidence": evidence,
            "mechanism": mechanism,
            "horizon": horizon,
            "source": source,
        }

    def build_valuation_record(
        self,
        metric: str,
        value: Any,
        reference_date: str,
        source: str,
        company_context: str,
    ) -> Dict[str, Any]:
        return {
            "metric": metric,
            "value": value,
            "reference_date": reference_date,
            "source": source,
            "company_context": company_context,
        }
