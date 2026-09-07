from __future__ import annotations

import statistics
from typing import Any, Dict, Iterable, Optional


class ValuationEngine:
    """Deterministic valuation with explicit, auditable assumptions."""

    def evaluate(
        self,
        price: Optional[float],
        shares: Optional[float],
        net_income: Optional[float],
        operating_cash_flow: Optional[float],
        net_debt: Optional[float],
        peer_multiples: Optional[Iterable[float]] = None,
        assumptions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        assumptions = dict(assumptions or {})
        missing = [name for name, value in {"price": price, "shares": shares, "net_income": net_income}.items() if value is None]
        invalid = []
        if price is not None and float(price) <= 0:
            invalid.append("positive_price")
        if not shares or float(shares) <= 0:
            invalid.append("positive_shares")
        if net_income is not None and float(net_income) <= 0:
            invalid.append("positive_ttm_net_income")
        if missing or invalid:
            return {"status": "INSUFFICIENT_DATA", "missing": missing + invalid, "scenarios": {}, "assumptions": assumptions}
        eps = float(net_income) / float(shares)
        current_pe = float(price) / eps
        peers = sorted(float(value) for value in (peer_multiples or []) if value is not None and float(value) > 0)
        peer_median = None
        if peers:
            middle = len(peers) // 2
            peer_median = peers[middle] if len(peers) % 2 else (peers[middle - 1] + peers[middle]) / 2.0
        explicit_base = assumptions.get("base_pe")
        if explicit_base is None and 0 < len(peers) < 2:
            return {
                "status": "PARTIAL", "missing": ["at_least_two_peer_multiples"],
                "metrics": {"eps": eps, "current_pe": current_pe, "peer_median_pe": peer_median},
                "scenarios": {}, "assumptions": assumptions,
            }
        base_multiple = explicit_base if explicit_base is not None else peer_median
        if base_multiple is None:
            return {
                "status": "PARTIAL",
                "missing": ["base_pe_or_peer_multiples"],
                "metrics": {"eps": eps, "current_pe": current_pe, "peer_median_pe": peer_median},
                "scenarios": {},
                "assumptions": assumptions,
            }
        if explicit_base is not None and not str(assumptions.get("assumption_source") or "").strip():
            return {
                "status": "PARTIAL", "missing": ["assumption_source"],
                "metrics": {"eps": eps, "current_pe": current_pe, "peer_median_pe": peer_median},
                "scenarios": {}, "assumptions": assumptions,
            }
        try:
            base_multiple = float(base_multiple)
            growth = float(assumptions.get("earnings_growth", 0.0))
            horizon = int(assumptions.get("horizon_years", 1))
            multiples = {
                "bear": float(assumptions.get("bear_pe", base_multiple * 0.8)),
                "base": base_multiple,
                "bull": float(assumptions.get("bull_pe", base_multiple * 1.2)),
            }
        except (TypeError, ValueError, OverflowError):
            return {"status": "INSUFFICIENT_DATA", "missing": ["valid_numeric_assumptions"], "scenarios": {}, "assumptions": assumptions}
        if growth <= -1.0 or horizon < 0 or horizon > 30:
            return {"status": "INSUFFICIENT_DATA", "missing": ["valid_growth_or_horizon"], "scenarios": {}, "assumptions": assumptions}
        if any(value <= 0 for value in multiples.values()) or not (multiples["bear"] <= multiples["base"] <= multiples["bull"]):
            return {"status": "INSUFFICIENT_DATA", "missing": ["ordered_positive_scenario_multiples"], "scenarios": {}, "assumptions": assumptions}
        future_eps = eps * ((1.0 + growth) ** horizon)
        scenarios = {}
        for name, multiple in multiples.items():
            implied = future_eps * multiple
            scenarios[name] = {
                "method": "earnings_multiple",
                "implied_value_per_share": round(implied, 4),
                "upside_downside": round(implied / float(price) - 1.0, 6) if price else None,
                "multiple": multiple,
                "future_eps": future_eps,
                "formula": "future_eps * scenario_multiple",
                "input_values": {"future_eps": future_eps, "scenario_multiple": multiple},
                "upside_downside_formula": "implied_value_per_share / reference_price - 1",
            }
        cash_conversion = operating_cash_flow / net_income if operating_cash_flow is not None and net_income else None
        return {
            "status": "AVAILABLE",
            "method": "P/E",
            "formula": "(TTM net_income / shares) * (1 + earnings_growth)^horizon_years * scenario_multiple",
            "metrics": {
                "eps": eps,
                "current_pe": current_pe,
                "peer_median_pe": peer_median,
                "net_debt": net_debt,
                "cash_conversion": cash_conversion,
            },
            "scenarios": scenarios,
            "assumptions": {
                **assumptions,
                "base_pe": base_multiple,
                "earnings_growth": growth,
                "horizon_years": horizon,
                "assumption_source": assumptions.get("assumption_source") or "peer_median",
            },
            "limitations": ["Não é recomendação ou preço-alvo; é uma sensibilidade determinística às premissas declaradas."],
        }

    def evaluate_dcf(
        self,
        price: Optional[float],
        shares: Optional[float],
        base_free_cash_flow: Optional[float],
        net_debt: Optional[float],
        forecast_growth_rates: Iterable[float],
        discount_rate: Optional[float],
        terminal_growth: Optional[float],
        assumptions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Multi-year FCFF sensitivity; never supplies un-attributed forecasts."""
        assumptions = dict(assumptions or {})
        rates = [float(rate) for rate in forecast_growth_rates]
        if (
            price is None or float(price) <= 0 or shares is None or float(shares) <= 0
            or base_free_cash_flow is None or discount_rate is None or terminal_growth is None
            or net_debt is None
        ):
            return {"status": "INSUFFICIENT_DATA", "missing": ["price_shares_fcf_net_debt_discount_rate_terminal_growth"], "scenarios": {}, "assumptions": assumptions}
        if not str(assumptions.get("assumption_source") or "").strip():
            return {"status": "PARTIAL", "missing": ["assumption_source"], "scenarios": {}, "assumptions": assumptions}
        if not 3 <= len(rates) <= 10 or any(rate <= -1.0 for rate in rates):
            return {"status": "INSUFFICIENT_DATA", "missing": ["three_to_ten_valid_growth_years"], "scenarios": {}, "assumptions": assumptions}
        rate, terminal = float(discount_rate), float(terminal_growth)
        if rate <= terminal or rate <= 0 or terminal <= -1.0:
            return {"status": "INSUFFICIENT_DATA", "missing": ["discount_rate_above_terminal_growth"], "scenarios": {}, "assumptions": assumptions}

        def scenario(name: str, discount_adjustment: float, terminal_adjustment: float) -> Dict[str, Any]:
            scenario_rate, scenario_terminal = rate + discount_adjustment, terminal + terminal_adjustment
            if scenario_rate <= scenario_terminal:
                raise ValueError("invalid scenario discount spread")
            cash_flow = float(base_free_cash_flow)
            present_value = 0.0
            forecast = []
            for year, growth in enumerate(rates, start=1):
                cash_flow *= 1.0 + growth
                pv = cash_flow / ((1.0 + scenario_rate) ** year)
                present_value += pv
                forecast.append({"year": year, "growth": growth, "free_cash_flow": cash_flow, "present_value": pv})
            terminal_value = cash_flow * (1.0 + scenario_terminal) / (scenario_rate - scenario_terminal)
            terminal_pv = terminal_value / ((1.0 + scenario_rate) ** len(rates))
            equity_value = present_value + terminal_pv - float(net_debt)
            implied = equity_value / float(shares)
            return {
                "method": "DCF FCFF", "implied_value_per_share": round(implied, 4),
                "upside_downside": round(implied / float(price) - 1.0, 6),
                "forecast": forecast, "discount_rate": scenario_rate, "terminal_growth": scenario_terminal,
                "terminal_value": terminal_value, "terminal_value_present_value": terminal_pv,
                "formula": "sum(FCF_t/(1+WACC)^t) + terminal_value/(1+WACC)^n - net_debt; divided by shares",
            }

        try:
            scenarios = {
                "bear": scenario("bear", 0.02, -0.01),
                "base": scenario("base", 0.0, 0.0),
                "bull": scenario("bull", -0.02, 0.01),
            }
        except ValueError:
            return {"status": "INSUFFICIENT_DATA", "missing": ["valid_dcf_scenarios"], "scenarios": {}, "assumptions": assumptions}
        return {
            "status": "AVAILABLE", "method": "DCF FCFF",
            "formula": "multi_year_fcff_discounted_cash_flow",
            "metrics": {"base_free_cash_flow": float(base_free_cash_flow), "net_debt": float(net_debt), "reference_price": float(price)},
            "scenarios": scenarios,
            "assumptions": {**assumptions, "forecast_growth_rates": rates, "discount_rate": rate, "terminal_growth": terminal},
            "limitations": ["A projeção só é publicável quando cada premissa possuir fonte, data de disponibilidade e revisão humana."],
        }

    @staticmethod
    def multiple_history_stats(current_multiple: Optional[float], history: Iterable[float]) -> Dict[str, Any]:
        """Describe, never forecast from, a dated historical multiple series."""
        values = sorted(float(value) for value in history if value is not None and float(value) > 0)
        if current_multiple is None or len(values) < 8:
            return {"status": "INSUFFICIENT_DATA", "missing": ["current_multiple_and_eight_historical_observations"]}
        current = float(current_multiple)
        mean = statistics.mean(values)
        deviation = statistics.pstdev(values)
        percentile = round(100.0 * sum(value <= current for value in values) / len(values), 2)
        return {
            "status": "AVAILABLE", "observation_count": len(values), "median": statistics.median(values),
            "mean": mean, "standard_deviation": deviation, "percentile": percentile,
            "z_score": (current - mean) / deviation if deviation else None,
            "method": "empirical point-in-time multiple distribution; descriptive only",
        }

    def evaluate_book_value(
        self, price: Optional[float], shares: Optional[float], equity: Optional[float],
        peer_multiples: Optional[Iterable[float]] = None, assumptions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        assumptions = dict(assumptions or {})
        if price is None or float(price) <= 0 or not shares or shares <= 0 or equity is None or equity <= 0:
            return {"status": "INSUFFICIENT_DATA", "missing": ["price_shares_or_positive_equity"], "scenarios": {}, "assumptions": assumptions}
        book_value_per_share = float(equity) / float(shares)
        current_pb = float(price) / book_value_per_share
        peers = sorted(float(value) for value in (peer_multiples or []) if value is not None and float(value) > 0)
        explicit_base = assumptions.get("base_pb")
        if explicit_base is None and len(peers) < 2:
            return {"status": "PARTIAL", "metrics": {"book_value_per_share": book_value_per_share, "current_pb": current_pb}, "scenarios": {}, "assumptions": assumptions}
        if explicit_base is not None and not str(assumptions.get("assumption_source") or "").strip():
            return {"status": "PARTIAL", "missing": ["assumption_source"], "metrics": {"book_value_per_share": book_value_per_share, "current_pb": current_pb}, "scenarios": {}, "assumptions": assumptions}
        median = statistics.median(peers) if peers else None
        try:
            base = float(explicit_base if explicit_base is not None else median)
            multiples = {"bear": float(assumptions.get("bear_pb", base * .8)), "base": base, "bull": float(assumptions.get("bull_pb", base * 1.2))}
        except (TypeError, ValueError, OverflowError):
            return {"status": "INSUFFICIENT_DATA", "missing": ["valid_numeric_assumptions"], "scenarios": {}, "assumptions": assumptions}
        if any(value <= 0 for value in multiples.values()) or not (multiples["bear"] <= multiples["base"] <= multiples["bull"]):
            return {"status": "INSUFFICIENT_DATA", "missing": ["ordered_positive_scenario_multiples"], "scenarios": {}, "assumptions": assumptions}
        scenarios = {
            name: {"method": "book_value_multiple", "implied_value_per_share": round(book_value_per_share * multiple, 4),
                   "upside_downside": round((book_value_per_share * multiple) / float(price) - 1, 6), "multiple": multiple,
                   "book_value_per_share": book_value_per_share,
                   "formula": "book_value_per_share * scenario_multiple",
                   "input_values": {"book_value_per_share": book_value_per_share, "scenario_multiple": multiple},
                   "upside_downside_formula": "implied_value_per_share / reference_price - 1"}
            for name, multiple in multiples.items()
        }
        return {
            "status": "AVAILABLE", "method": "P/B", "formula": "(equity / shares) * scenario_multiple",
            "metrics": {"book_value_per_share": book_value_per_share, "current_pb": current_pb, "peer_median_pb": median},
            "scenarios": scenarios, "assumptions": {**assumptions, "base_pb": base, "assumption_source": assumptions.get("assumption_source", "peer_median")},
            "limitations": ["P/VP não captura sozinho qualidade da carteira, custo de capital, ROE sustentável ou riscos fora do balanço."],
        }

    def evaluate_ev_ebit(
        self, price: Optional[float], shares: Optional[float], ttm_ebit: Optional[float],
        net_debt: Optional[float], peer_multiples: Optional[Iterable[float]] = None,
        assumptions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Capital-structure-aware sensitivity without pretending EBIT is EBITDA."""
        assumptions = dict(assumptions or {})
        if (
            price is None or float(price) <= 0 or not shares or float(shares) <= 0
            or ttm_ebit is None or float(ttm_ebit) <= 0 or net_debt is None
        ):
            return {
                "status": "INSUFFICIENT_DATA",
                "missing": ["positive_price_shares_ttm_ebit_and_net_debt"],
                "scenarios": {}, "assumptions": assumptions,
            }
        peers = sorted(float(value) for value in (peer_multiples or []) if value is not None and float(value) > 0)
        explicit_base = assumptions.get("base_ev_ebit")
        if explicit_base is None and len(peers) < 2:
            return {
                "status": "PARTIAL", "missing": ["at_least_two_peer_ev_ebit_multiples"],
                "metrics": {}, "scenarios": {}, "assumptions": assumptions,
            }
        if explicit_base is not None and not str(assumptions.get("assumption_source") or "").strip():
            return {"status": "PARTIAL", "missing": ["assumption_source"], "scenarios": {}, "assumptions": assumptions}
        median = statistics.median(peers) if peers else None
        try:
            base = float(explicit_base if explicit_base is not None else median)
            multiples = {
                "bear": float(assumptions.get("bear_ev_ebit", base * 0.8)),
                "base": base,
                "bull": float(assumptions.get("bull_ev_ebit", base * 1.2)),
            }
        except (TypeError, ValueError, OverflowError):
            return {"status": "INSUFFICIENT_DATA", "missing": ["valid_numeric_assumptions"], "scenarios": {}, "assumptions": assumptions}
        if any(value <= 0 for value in multiples.values()) or not (multiples["bear"] <= multiples["base"] <= multiples["bull"]):
            return {"status": "INSUFFICIENT_DATA", "missing": ["ordered_positive_scenario_multiples"], "scenarios": {}, "assumptions": assumptions}
        market_cap = float(price) * float(shares)
        current_enterprise_value = market_cap + float(net_debt)
        current_multiple = current_enterprise_value / float(ttm_ebit) if current_enterprise_value > 0 else None
        scenarios = {}
        for name, multiple in multiples.items():
            enterprise_value = float(ttm_ebit) * multiple
            equity_value = enterprise_value - float(net_debt)
            implied = equity_value / float(shares)
            if implied <= 0:
                return {
                    "status": "INSUFFICIENT_DATA", "missing": [f"non_positive_{name}_equity_value"],
                    "scenarios": {}, "assumptions": assumptions,
                }
            scenarios[name] = {
                "method": "enterprise_value_to_ebit",
                "implied_value_per_share": round(implied, 4),
                "upside_downside": round(implied / float(price) - 1.0, 6),
                "multiple": multiple, "enterprise_value": enterprise_value,
                "equity_value": equity_value,
                "formula": "(ttm_ebit * scenario_multiple - net_debt) / shares",
                "input_values": {
                    "ttm_ebit": float(ttm_ebit), "scenario_multiple": multiple,
                    "net_debt": float(net_debt), "shares": float(shares),
                },
                "upside_downside_formula": "implied_value_per_share / reference_price - 1",
            }
        return {
            "status": "AVAILABLE", "method": "EV/EBIT",
            "formula": "(TTM EBIT * scenario EV/EBIT - net_debt) / shares",
            "metrics": {
                "ttm_ebit": float(ttm_ebit), "net_debt": float(net_debt),
                "current_enterprise_value": current_enterprise_value,
                "current_ev_ebit": current_multiple, "peer_median_ev_ebit": median,
            },
            "scenarios": scenarios,
            "assumptions": {
                **assumptions, "base_ev_ebit": base,
                "assumption_source": assumptions.get("assumption_source") or "peer_median",
            },
            "limitations": [
                "EV/EBIT não é EV/EBITDA e não neutraliza diferenças de depreciação, capex, concessões ou qualidade dos ativos.",
                "Sensibilidade mecânica, não recomendação nem preço-alvo.",
            ],
        }
