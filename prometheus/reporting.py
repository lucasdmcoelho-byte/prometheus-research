import datetime as dt
import copy
import hashlib
import html
import json
import re
import shutil
import statistics
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from pypdf import PdfReader, PdfWriter

from prometheus.thesis_engine import calculate_score, get_state

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.ticker import FuncFormatter
except Exception:  # pragma: no cover - optional dependency for report export only
    matplotlib = None
    plt = None
    FuncFormatter = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfdoc import PDFString
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except Exception:  # pragma: no cover - optional dependency for pdf export only
    colors = None
    A4 = None
    letter = None
    mm = 1.0
    PDFString = None
    pdf_canvas = None
    Image = None
    PageBreak = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None

from prometheus.data_engine import validate_ticker
from prometheus.data_quality import calculate_research_quality
from prometheus.business_quality import BusinessQualityEngine
from prometheus.pipeline import PrometheusEngine
from prometheus.editorial_gate import EditorialGate
from prometheus.report_design import (
    CONTENT_WIDTH,
    MARGIN_BOTTOM,
    MARGIN_TOP,
    MARGIN_X,
    PAGE_SIZE,
    PALETTE,
    bullet_paragraphs,
    callout,
    grid_widths,
    metric_cards,
    register_report_fonts,
    report_styles,
    section_heading,
    table_style,
)


class _ResearchDocTemplate(SimpleDocTemplate):
    """A4 document with a logical outline and deterministic reading order."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._outline_sequence = 0
        self._has_outline_root = False

    def beforePage(self) -> None:  # noqa: N802 - ReportLab API
        self.canv.saveState()
        self.canv.setFillColor(PALETTE["paper"])
        self.canv.rect(0, 0, PAGE_SIZE[0], PAGE_SIZE[1], fill=1, stroke=0)
        self.canv.restoreState()

    def afterFlowable(self, flowable: Any) -> None:  # noqa: N802 - ReportLab API
        if not isinstance(flowable, Paragraph):
            return
        level_by_style = {"ReportH1": 0, "ReportH2": 1}
        level = level_by_style.get(getattr(flowable.style, "name", ""))
        if level is None:
            return
        if level == 1 and not self._has_outline_root:
            return
        if level == 0:
            self._has_outline_root = True
        self._outline_sequence += 1
        key = f"section-{self._outline_sequence}"
        title = re.sub(r"<[^>]+>", "", flowable.getPlainText()).strip()
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(title, key, level=level, closed=False)


def _footer_canvas_class(report_data: Dict[str, Any]) -> type:
    """Return a Canvas that replays each page and paints the footer last."""

    class FooterCanvas(pdf_canvas.Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict[str, Any]] = []
            fonts = register_report_fonts()
            self._footer_font = fonts["regular"]
            self._footer_font_bold = fonts["bold"]
            self._apply_metadata()

        def _apply_metadata(self) -> None:
            company = _safe_text(report_data.get("company_name"))
            ticker = _safe_text(report_data.get("ticker"))
            self.setTitle(f"PROMETHEUS Equity Research | {ticker} | {company}")
            self.setAuthor("PROMETHEUS Research")
            self.setSubject("Research financeiro point-in-time, auditável e sujeito a revisão humana")
            self.setCreator("PROMETHEUS Research 2.1.0rc2")
            self.setKeywords("equity research, B3, point-in-time, valuation, auditoria, PROMETHEUS")
            if PDFString is not None:
                self._doc.Catalog.Lang = PDFString("pt-BR")

        def showPage(self) -> None:  # noqa: N802 - ReportLab API
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            for page_state in self._saved_page_states:
                self.__dict__.update(page_state)
                self._draw_footer()
                super().showPage()
            self._apply_metadata()
            super().save()

        def _draw_footer(self) -> None:
            self.saveState()
            if not (report_data.get("editorial_gate") or {}).get("deliverable"):
                self.setFont(self._footer_font_bold, 6.5)
                self.setFillColor(PALETTE["amber"])
                self.drawRightString(PAGE_SIZE[0] - MARGIN_X, PAGE_SIZE[1] - 8 * mm, "DRAFT - HUMAN REVIEW REQUIRED")
            self.setStrokeColor(PALETTE["line"])
            self.line(MARGIN_X, 12 * mm, PAGE_SIZE[0] - MARGIN_X, 12 * mm)
            self.setFont(self._footer_font, 6.5)
            self.setFillColor(PALETTE["slate"])
            self.drawString(MARGIN_X, 8 * mm, "PROMETHEUS | Uso informativo")
            audit_export = report_data.get("audit_export") or {}
            if audit_export.get("filename"):
                self.drawCentredString(
                    PAGE_SIZE[0] / 2, 8 * mm,
                    f"Registro completo: {audit_export['filename']}",
                )
            self.drawRightString(PAGE_SIZE[0] - MARGIN_X, 8 * mm, f"Página {self._pageNumber}")
            self.restoreState()

    return FooterCanvas


def _fmt_money(value: Optional[float]) -> str:
    if value is None:
        return "Não disponível"
    return f"R$ {value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_percent(value: Optional[float]) -> str:
    if value is None:
        return "Não disponível"
    numeric = float(value)
    if -1.0 <= numeric <= 1.0 and numeric != 0:
        numeric *= 100.0
    return f"{numeric:.1f}%".replace(".", ",")


def _fmt_ratio(value: Optional[float]) -> str:
    if value is None:
        return "Não disponível"
    return f"{value:.2f}".replace(".", ",")


def _safe_text(value: Any) -> str:
    if value is None or value == "":
        return "Não disponível"
    text = str(value)
    text = re.sub(r"\bIt also\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIt also pr\.\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else "Não disponível"


def _governance_public_text(governance: Dict[str, Any]) -> str:
    """Canonical client-facing governance wording shared by all sections."""
    return (
        "Dados disponíveis, insuficientes para conclusão. "
        f"Administração: {governance.get('management_records', 0)} registros; "
        f"partes relacionadas: {governance.get('related_party_records', 0)}; "
        f"auditoria: {governance.get('auditor_records', 0)}."
    )


def _infer_metric_unit(metric_name: str, value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    normalized = (metric_name or "").lower()
    if any(token in normalized for token in ["growth", "margin", "yield", "return", "roe", "roa", "change", "sentiment", "score"]):
        return "%"
    if any(token in normalized for token in ["debt", "ratio", "pe", "p_l", "multiple", "beta"]):
        return "x" if "pe" in normalized or "multiple" in normalized else "ratio"
    if any(token in normalized for token in ["market_cap", "price", "cash", "ebitda", "revenue", "profit", "lucro", "receita", "fluxo", "enterprise", "shares"]):
        return "R$"
    return "value"


def _format_metric_value(metric_name: str, value: Any, compact: bool = False) -> str:
    if value is None:
        return "Não disponível"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _safe_text(value)

    if abs(numeric) <= 1.0 and any(token in metric_name.lower() for token in ["growth", "margin", "yield", "roe", "roa", "change", "return"]) and numeric != 0:
        numeric *= 100.0

    unit = _infer_metric_unit(metric_name, value)
    if unit == "%":
        return f"{numeric:.2f}%"
    if unit == "x":
        return f"{numeric:.2f}x"
    if unit == "R$":
        if compact and abs(numeric) >= 1_000_000_000:
            return f"R$ {numeric / 1_000_000_000:.2f} bi"
        if compact and abs(numeric) >= 1_000_000:
            return f"R$ {numeric / 1_000_000:.2f} mi"
        return f"R$ {numeric:,.2f}"
    return f"{numeric:.4f}" if abs(numeric) < 1 else f"{numeric:.2f}"


def _score_reconciliation(report_data: Dict[str, Any]) -> Dict[str, Any]:
    thesis_scores = report_data.get("thesis_scores") or {}
    unavailable = set(((report_data.get("score_availability") or {}).get("unavailable_components") or []))
    weighted_thesis = calculate_score(thesis_scores, unavailable) if thesis_scores else 0.0
    expectation_score = float((report_data.get("expectation_result") or {}).get("expectation_gap_score", 0.0) or 0.0)
    catalyst_score = float((report_data.get("catalyst_result") or {}).get("catalyst_score", 0.0) or 0.0)
    regime_confidence = float((report_data.get("regime_result") or {}).get("confidence", 0.0) or 0.0) * 100.0
    pricing_confidence = float((report_data.get("pricing_result") or {}).get("pricing_confidence", 0.0) or 0.0) * 100.0

    final_score = round(
        weighted_thesis * 0.60 + expectation_score * 0.15 + catalyst_score * 0.10 + regime_confidence * 0.08 + pricing_confidence * 0.07,
        2,
    )
    actual = float(report_data.get("final_score") or 0.0)
    return {
        "weighted_thesis_score": round(weighted_thesis, 2),
        "weighted_thesis_weight": 0.60,
        "expectation_gap_score": round(expectation_score, 2),
        "expectation_weight": 0.15,
        "catalyst_score": round(catalyst_score, 2),
        "catalyst_weight": 0.10,
        "regime_confidence": round(regime_confidence, 2),
        "regime_weight": 0.08,
        "pricing_confidence": round(pricing_confidence, 2),
        "pricing_weight": 0.07,
        "reconstructed_final_score": final_score,
        "report_final_score": actual,
        "delta": round(actual - final_score, 4),
        "reconciled": abs(actual - final_score) <= 1e-6,
    }


def _build_quality_assessment(report_data: Dict[str, Any]) -> Dict[str, Any]:
    quality = report_data.get("fundamental_data_quality") or {}
    errors: list[str] = []
    warnings: list[str] = []

    if not report_data.get("ticker"):
        errors.append("Ticker ausente.")
    if not report_data.get("company_name"):
        errors.append("Empresa não identificada.")
    if report_data.get("final_score") is None:
        errors.append("Score final ausente.")
    if report_data.get("final_state") is None:
        errors.append("Estado da tese ausente.")

    reconciliation = _score_reconciliation(report_data)
    if not reconciliation["reconciled"]:
        errors.append(
            "Reconciliação do score falhou: o score final do relatório não bate com a fórmula do pipeline."
        )

    if quality.get("invalid_count", 0):
        errors.append(f"Data Quality falhou em {quality.get('invalid_count')} campos críticos.")
    if quality.get("missing_count", 0):
        warnings.append(f"{quality.get('missing_count')} campos faltantes foram detectados.")
    if quality.get("suspect_count", 0):
        warnings.append(f"{quality.get('suspect_count')} campos tiveram status suspeito.")
    if not report_data.get("evidence") and not (report_data.get("thesis_result") or {}).get("evidence"):
        warnings.append("Nenhuma evidência explícita foi registrada para a tese.")
    if not report_data.get("business_summary"):
        warnings.append("Resumo da empresa não disponível.")

    return {
        "status": "error" if errors else "warning" if warnings else "pass",
        "errors": errors,
        "warnings": warnings,
        "score_reconciliation": reconciliation,
        "quality_summary": quality,
    }


def _first_valid(values: Any) -> Any:
    if isinstance(values, (list, tuple)):
        for item in values:
            if item is not None:
                return item
        return None
    return values


def _field_value(data: Dict[str, Any], field: str, key: str = "normalized") -> Any:
    if not isinstance(data, dict):
        return None
    value = data.get(field)
    if isinstance(value, dict):
        return value.get(key)
    return value


def _company_summary(report_data: Dict[str, Any]) -> str:
    company_name = _safe_text(report_data.get("company_name"))
    sector = _safe_text(report_data.get("sector_name"))
    disclosed_summary = _safe_text(report_data.get("business_summary"))
    if disclosed_summary != "Não disponível":
        return disclosed_summary
    profile = _sector_profile(report_data)
    if sector != "Não disponível":
        return profile["business_model"]
    return f"{company_name} é uma empresa listada na B3."


def _sector_profile(report_data: Dict[str, Any]) -> Dict[str, str]:
    sector = _safe_text(report_data.get("sector_name")).lower()
    company_name = _safe_text(report_data.get("company_name"))
    model = report_data.get("sector_model") or {}
    model_key = model.get("key")
    if model_key == "real_estate" or "real estate" in sector or "imobili" in sector:
        return {
            "business_model": f"{company_name} gera receita principalmente com venda e desenvolvimento de empreendimentos imobiliários, com a conversão de terrenos e obras em unidades comercializadas e em caixa por venda ou entrega ao cliente.",
            "drivers": "vendas de unidades, ritmo de entrega, financiamento, demanda de crédito e acesso ao programa habitacional.",
            "risk": "queda de demanda, aumento de juros, inadimplência e atrasos de obra ou custos de construção.",
            "macro": "juros, crédito imobiliário, renda, emprego e política habitacional.",
        }
    if model_key == "financial" or "financial" in sector or "bank" in sector or "finance" in sector:
        return {
            "business_model": f"{company_name} ganha dinheiro pela intermediação financeira, spread bancário e serviços de crédito, cobrança de juros e eficiência de carteira de empréstimos.",
            "drivers": "crédito, spread, inadimplência, volume de operações e custo de captação.",
            "risk": "juros, qualidade de crédito, provisionamento e competição por spread.",
            "macro": "Selic, crédito, inadimplência, atividade econômica e política monetária.",
        }
    if model_key == "oil_gas" or "energy" in sector or "petrole" in sector or "oil" in sector:
        return {
            "business_model": f"{company_name} cria valor pela exploração, processamento e comercialização de energia ou commodities, com receitas ligadas a volume de produção, preços e logística.",
            "drivers": "preço de commodity, produção, eficiência operacional, câmbio e demanda global.",
            "risk": "queda de preços, custos operacionais, regulação, câmbio e produção.",
            "macro": "commodities, câmbio, oferta global, demanda internacional e preço do petróleo.",
        }
    if model_key == "mining" or "mining" in sector:
        return {
            "business_model": f"{company_name} gera caixa com extração, beneficiamento e venda de minerais, sendo muito sensível ao mix de produto e à demanda internacional.",
            "drivers": "produção, preço da commodity, produtividade e logística.",
            "risk": "queda de commodity, custos de energia, clima, volatilidade cambial e concentração geográfica.",
            "macro": "preço da commodity, dólar, demanda chinesa e custos logísticos.",
        }
    drivers = ", ".join(model.get("drivers") or [])
    risks = ", ".join(model.get("risks") or [])
    macro = ", ".join(model.get("macro_series") or [])
    label = _safe_text(model.get("label") or report_data.get("sector_name"))
    if model_key == "utilities":
        business_model = (
            f"Pela classificação setorial, {company_name} atua em utilities ou infraestrutura, segmento em que contratos, tarifas, "
            "capacidade, regulação e disciplina de capital tendem a orientar a geração de caixa. A combinação específica deve ser confirmada em fonte primária da companhia."
        )
    elif model_key and model_key != "general":
        business_model = (
            f"A classificação disponível enquadra {company_name} em {label}. O modelo econômico específico e o mix de receitas "
            "devem ser confirmados em fonte primária antes de atribuir características próprias do setor à companhia."
        )
    else:
        business_model = (
            f"O modelo econômico específico de {company_name} não foi confirmado por fonte primária no corte; "
            "a análise não substitui essa lacuna por uma descrição presumida."
        )
    return {
        "business_model": business_model,
        "drivers": drivers or "demanda, eficiência, escala e alocação de capital",
        "risk": risks or "competição, execução e liquidez",
        "macro": macro or "atividade econômica, juros, inflação e câmbio",
    }


def _canonical_score_snapshot(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Single presentation source for all thesis-score render paths."""
    scores = dict(report_data.get("thesis_scores") or {})
    availability = report_data.get("score_availability") or {}
    unavailable = set(availability.get("unavailable_components") or [])
    for key in ("fundamental", "sector", "macro", "expectation_gap", "momentum_velocity", "valuation_margin", "news_sentiment"):
        if scores.get(key) is None:
            unavailable.add(key)
    weighted = calculate_score(scores, unavailable)
    expectation = float((report_data.get("expectation_result") or {}).get("expectation_gap_score", 0.0) or 0.0)
    catalyst = float((report_data.get("catalyst_result") or {}).get("catalyst_score", 0.0) or 0.0)
    regime = float((report_data.get("regime_result") or {}).get("confidence", 0.0) or 0.0) * 100.0
    pricing = float((report_data.get("pricing_result") or {}).get("pricing_confidence", 0.0) or 0.0) * 100.0
    final = round(weighted * 0.60 + expectation * 0.15 + catalyst * 0.10 + regime * 0.08 + pricing * 0.07, 2)
    return {"components": scores, "unavailable": sorted(unavailable), "weights": {"fundamental": 0.23, "sector": 0.14, "macro": 0.10, "expectation_gap": 0.14, "momentum_velocity": 0.14, "valuation_margin": 0.20, "news_sentiment": 0.05}, "weighted_thesis": round(weighted, 2), "final_score": final}


def _build_summary(report_data: Dict[str, Any]) -> str:
    company_name = _safe_text(report_data.get("company_name"))
    ticker = _safe_text(report_data.get("ticker"))
    sector = _safe_text(report_data.get("sector_name"))
    price = report_data.get("price")
    score = report_data.get("final_score")
    state = report_data.get("final_state")
    research_quality = report_data.get("research_quality") or {}
    quality = research_quality.get("overall_research_confidence")
    quality_text = "Não disponível" if quality is None else f"{quality:.0f}/100"
    revenue_growth = _field_value(report_data.get("financials", {}), "revenue_growth")
    profit_margin = _field_value(report_data.get("financials", {}), "profit_margin")
    summary = (
        f"{company_name} ({ticker}) encerrou o período comparável com receita {_fmt_percent(revenue_growth)} maior e margem líquida de {_fmt_percent(profit_margin)}. "
        f"A referência de mercado é {_fmt_brl(price)}; a leitura do sistema é sem convicção direcional, com score {_fmt_decimal(score, 2)}, sem convertê-lo em recomendação. "
        f"A confiança geral do research é {quality_text}, distinta da completude dos demonstrativos financeiros."
    )
    return _safe_text(summary)


def _build_company_profile(report_data: Dict[str, Any]) -> str:
    company_name = _safe_text(report_data.get("company_name"))
    ticker = _safe_text(report_data.get("ticker"))
    sector = _safe_text(report_data.get("sector_name"))
    market_cap = report_data.get("market_cap")
    profile = _sector_profile(report_data)
    return (
        f"{company_name} ({ticker}) atua em {sector}. "
        f"{profile['business_model']} "
        f"A escala de mercado é refletida por capitalização de {_fmt_money(market_cap)}."
    )


def _build_business_model(report_data: Dict[str, Any]) -> str:
    sector_profile = _sector_profile(report_data)
    company_name = _safe_text(report_data.get("company_name"))
    revenue_growth = _field_value(report_data.get("financials", {}), "revenue_growth")
    profit_margin = _field_value(report_data.get("financials", {}), "profit_margin")
    if (report_data.get("sector_model") or {}).get("key") == "real_estate":
        return (
            f"{company_name} transforma terrenos e execução de obras em unidades vendidas, recebíveis e caixa. "
            "O ciclo passa por aquisição do terreno, aprovação, lançamento, venda, construção, repasse do financiamento e entrega; "
            "a receita e a margem contábil não coincidem necessariamente com recebimento de caixa no mesmo período. "
            f"No corte, receita variou {_fmt_percent(revenue_growth)} e margem líquida foi {_fmt_percent(profit_margin)}. "
            "Regiões, faixa de renda, participação no Minha Casa Minha Vida e mix de projetos permanecem INSUFFICIENT_DATA sem apresentação operacional ou release de resultados elegível."
        )
    return (
        f"{company_name} converte operação em receita e caixa por meio de {sector_profile['drivers']}. "
        f"{sector_profile['business_model']} Receita variou {_fmt_percent(revenue_growth)} e margem foi {_fmt_percent(profit_margin)} no período comparável."
    )


def _build_growth_narrative(report_data: Dict[str, Any]) -> str:
    revenue_growth = _field_value(report_data.get("financials", {}), "revenue_growth")
    earnings_growth = _field_value(report_data.get("financials", {}), "earnings_growth")
    margin = _field_value(report_data.get("financials", {}), "profit_margin")
    parts = []
    if revenue_growth is not None:
        parts.append(f"receita variou {_fmt_percent(revenue_growth)}")
    if earnings_growth is not None:
        parts.append(f"lucro variou {_fmt_percent(earnings_growth)}")
    if margin is not None:
        parts.append(f"margem ficou em {_fmt_percent(margin)}")
    if not parts:
        return "Não há evidência suficiente para explicar a origem do crescimento com dados confiáveis disponíveis."
    return f"No período comparável, {', '.join(parts)}. O ponto essencial é separar variação operacional de efeito de preço, mix ou eventos extraordinários."


def _build_balance_sheet_narrative(report_data: Dict[str, Any]) -> str:
    debt_to_equity = _field_value(report_data.get("financials", {}), "debt_to_equity")
    roe = _field_value(report_data.get("financials", {}), "roe")
    company_name = _safe_text(report_data.get("company_name"))
    debt_text = f"dívida/patrimônio de {_fmt_ratio(debt_to_equity)}" if debt_to_equity is not None else "nível de alavancagem não disponível"
    roe_text = f"ROE de {_fmt_percent(roe)}" if roe is not None else "ROE não disponível"
    return (
        f"{company_name} mostra {debt_text} e {roe_text}. "
        "A pergunta central é se o negócio consegue sustentar crescimento e manutenção financeira sem depender de alavancagem excessiva. "
        "Quando a dívida cresce mais rápido que a geração de caixa, a tese fica mais sensível a juros e ciclos."
    )


def _build_cash_flow_narrative(report_data: Dict[str, Any]) -> str:
    ttm = (report_data.get("ttm") or {}).get("metrics") or {}
    operating_cashflow = (ttm.get("operating_cash_flow") or {}).get("normalized")
    net_income = (ttm.get("net_income") or {}).get("normalized")
    conversion = operating_cashflow / net_income if operating_cashflow is not None and net_income else None
    sector_key = (report_data.get("sector_model") or {}).get("key")
    sector_context = (
        "incorporação consome e libera capital conforme terrenos, obras, recebíveis e repasses avançam"
        if sector_key == "real_estate"
        else "a conversão de resultado em caixa deve ser confrontada com os indicadores operacionais específicos do setor"
    )
    return (
        f"Nos 12 meses até o corte, o fluxo de caixa operacional foi {_fmt_money(operating_cashflow)} frente a lucro líquido de {_fmt_money(net_income)}, "
        f"conversão de {_fmt_ratio(conversion)}x. A diferença importa porque {sector_context}; "
        "um único TTM não prova recorrência e deve ser confrontado com KPIs operacionais e capital de giro."
    )


def _build_quality_of_earnings(report_data: Dict[str, Any]) -> str:
    revenue_growth = _field_value(report_data.get("financials", {}), "revenue_growth")
    earnings_growth = _field_value(report_data.get("financials", {}), "earnings_growth")
    if revenue_growth is not None and earnings_growth is not None:
        spread = float(earnings_growth) - float(revenue_growth)
        return (
            f"Receita variou {_fmt_percent(revenue_growth)} e lucro líquido {_fmt_percent(earnings_growth)}, diferença de {_fmt_percent(spread)}. "
            "O alinhamento reduz, mas não elimina, o risco de crescimento contábil sem caixa; conversão TTM e evolução do capital de giro continuam determinantes."
        )
    return "A qualidade do lucro não pode ser avaliada com confiabilidade suficiente com os dados disponíveis no momento."


def _build_sector_narrative(report_data: Dict[str, Any]) -> str:
    sector_profile = _sector_profile(report_data)
    macro = str(sector_profile["macro"]).rstrip(" .")
    drivers = str(sector_profile["drivers"]).rstrip(" .")
    sector_key = (report_data.get("sector_model") or {}).get("key")
    if sector_key == "real_estate":
        evidence_gap = "Sem VSO, distratos, lançamentos e repasses, o relatório não atribui vantagem competitiva apenas a crescimento ou margem."
    elif sector_key == "healthcare":
        evidence_gap = "Sem beneficiários, ticket, sinistralidade, churn e composição da rede, o relatório não atribui vantagem competitiva apenas a crescimento ou margem."
    else:
        evidence_gap = "Sem os KPIs setoriais rastreáveis, o relatório não atribui vantagem competitiva apenas a crescimento ou margem."
    return f"O setor é sensível a {macro}. Os drivers {drivers} ligam demanda, execução e geração de caixa. {evidence_gap}"


def _build_competitors(report_data: Dict[str, Any]) -> str:
    analysis = ((report_data.get("research") or {}).get("peer_analysis") or {})
    valuation = report_data.get("valuation") or {}
    method = valuation.get("method") or analysis.get("multiple_method")
    metric_by_method = {"P/B": "price_to_book", "EV/EBIT": "ev_to_ebit", "P/E": "trailing_pe"}
    label_by_method = {"P/B": "P/VP", "EV/EBIT": "EV/EBIT TTM", "P/E": "P/L TTM"}
    metric = metric_by_method.get(method, "trailing_pe")
    metric_label = label_by_method.get(method, "P/L TTM")
    peers = [row for row in analysis.get("peers") or [] if row.get(metric) is not None]
    if not peers:
        return "Não há observações comparáveis suficientes para afirmar prêmio ou desconto setorial."
    details = "; ".join(f"{row['ticker']} {row[metric]:.1f}x" for row in peers[:6])
    median = statistics.median(row[metric] for row in peers)
    return (
        f"O conjunto comparável mantido para este segmento contém {len(peers)} observações válidas no período {analysis.get('target_period')}. "
        f"{metric_label}: {details}. Mediana: {median:.1f}x. A comparação é um ponto de partida; mix, risco e qualidade de caixa podem justificar diferenças."
    )


def _build_macro_narrative(report_data: Dict[str, Any]) -> str:
    sector_profile = _sector_profile(report_data)
    observations = report_data.get("macro_observations") or []
    observed = "; ".join(
        f"{item.get('metric')} {float(item.get('value')):.2f} ({item.get('date')})"
        for item in observations if isinstance(item.get("value"), (int, float))
    )
    macro = str(sector_profile["macro"]).rstrip(" .")
    if not observed:
        return f"INSUFFICIENT_DATA: nenhuma série macro elegível foi incorporada no corte. A transmissão a monitorar é {macro}; direção e intensidade não são inferidas sem observação datada."
    return f"Variáveis macro relevantes: {macro}. Observações oficiais no corte: {observed}. Correlação não é tratada como causalidade."


def _build_news_summary(report_data: Dict[str, Any]) -> str:
    catalysts = (report_data.get("catalyst_result") or {}).get("catalysts") or []
    if not catalysts:
        return "Nenhuma notícia elegível e material foi confirmada dentro da data de corte; o relatório não preenche a lacuna com eventos presumidos."
    return "Publicações monitoradas (o título não confirma sozinho o evento): " + "; ".join(
        f"[{item.get('category')}] {_safe_text(item.get('title'))} - {_safe_text(item.get('source'))}, {_safe_text(item.get('published_at'))}"
        for item in catalysts[:5]
    ) + "."


def _build_catalysts(report_data: Dict[str, Any]) -> str:
    catalysts = (report_data.get("catalyst_result") or {}).get("catalysts") or []
    if catalysts:
        confirmed = [item for item in catalysts if item.get("factual_status") == "PRIMARY_CONFIRMED"]
        reported = [item for item in catalysts if item.get("factual_status") != "PRIMARY_CONFIRMED"]
        sections = []
        if confirmed:
            sections.append("Eventos confirmados em fonte primária: " + "; ".join(
                f"[{_safe_text(item.get('category'))}] {_safe_text(item.get('title'))} - "
                f"{_safe_text(item.get('source'))}, {_safe_text(item.get('published_at'))}"
                for item in confirmed[:5]
            ))
        if reported:
            sections.append("Relatos secundários ainda não confirmados por fonte primária: " + "; ".join(
                f"[{_safe_text(item.get('category'))}] {_safe_text(item.get('title'))} - "
                f"{_safe_text(item.get('source'))}, {_safe_text(item.get('published_at'))}"
                for item in reported[:5]
            ))
        return ". ".join(sections) + "."
    sector_profile = _sector_profile(report_data)
    return (
        "Nenhum catalisador factual elegível foi confirmado dentro da data de corte. "
        f"Drivers setoriais a acompanhar - que não são eventos confirmados - incluem {sector_profile['drivers']}."
    )


def _build_risks(report_data: Dict[str, Any]) -> str:
    sector_profile = _sector_profile(report_data)
    return f"Os riscos críticos incluem {sector_profile['risk']}. Em linguagem simples, os pontos mais importantes são se a empresa consegue manter caixa, crescimento e disciplina mesmo em cenário de juros, demanda ou competição mais desafiadores."


def _build_valuation_narrative(report_data: Dict[str, Any]) -> str:
    valuation = report_data.get("valuation") or {}
    if not _valuation_publishable(report_data):
        return "Valuation não publicado: o gate editorial rejeitou ou não recebeu base, fórmulas, períodos e múltiplos comparáveis suficientemente rastreáveis."
    metrics, scenarios = valuation["metrics"], valuation["scenarios"]
    refs = _claim_refs(report_data, "valuation")
    if valuation.get("method") == "P/B":
        peer_label = "mediana dos peers ajustada por ROE anualizado" if metrics.get("peer_median_roe_adjusted_pb") is not None else "mediana dos peers"
        multiple_text = f"P/VP corrente {_fmt_ratio(metrics.get('current_pb'))}x e {peer_label} {_fmt_ratio(metrics.get('peer_median_pb'))}x"
    elif valuation.get("method") == "EV/EBIT":
        multiple_text = f"EV/EBIT corrente calculado {_fmt_ratio(metrics.get('current_ev_ebit'))}x e mediana TTM dos peers {_fmt_ratio(metrics.get('peer_median_ev_ebit'))}x"
    else:
        multiple_text = f"P/L corrente calculado {_fmt_ratio(metrics.get('current_pe'))}x e mediana TTM dos peers {_fmt_ratio(metrics.get('peer_median_pe'))}x"
    return (
        f"O preço de referência é {_fmt_money(report_data.get('price'))}. {multiple_text}. "
        f"A sensibilidade produz R$ {scenarios['bear']['implied_value_per_share']:.2f} no bear, R$ {scenarios['base']['implied_value_per_share']:.2f} no base e R$ {scenarios['bull']['implied_value_per_share']:.2f} no bull. "
        f"Não são preços-alvo: são resultados mecânicos das premissas declaradas. Evidências: {refs}."
    )


def _build_expectation_gap(report_data: Dict[str, Any]) -> str:
    final_score = report_data.get("final_score")
    state = _safe_text(report_data.get("final_state"))
    return (
        f"O conjunto de evidências do PROMETHEUS está em estado {state}. "
        f"O score atual da tese é {final_score}. Sem uma fonte explícita de consenso, o relatório não afirma expectativas agregadas do mercado; apenas pergunta quais premissas parecem necessárias para reconciliar preço e fundamentos."
    )


def _build_thesis(report_data: Dict[str, Any]) -> str:
    final_score = report_data.get("final_score")
    state = _safe_text(report_data.get("final_state"))
    if final_score is None:
        score_text = "Não disponível"
    else:
        score_text = f"{float(final_score):.1f}"
    reconciliation = ((report_data.get("business_quality") or {}).get("valuation_reconciliation") or {})
    return (
        f"O estado agregado é {state}, com score {score_text}, mas qualidade operacional e atratividade do preço são leituras separadas. "
        f"{_safe_text(reconciliation.get('explanation'))}"
    )


def _build_central_thesis(report_data: Dict[str, Any]) -> str:
    financials = report_data.get("financials") or {}
    research_quality = report_data.get("research_quality") or {}
    ticker = _safe_text(report_data.get("ticker"))
    company = _safe_text(report_data.get("company_name"))
    model = report_data.get("sector_model") or {}
    sector = _safe_text(model.get("label") or report_data.get("sector_name"))
    valuation = report_data.get("valuation") or {}
    peer_analysis = (report_data.get("research") or {}).get("peer_analysis") or {}
    method = valuation.get("method") or peer_analysis.get("multiple_method")
    metrics = valuation.get("metrics") or {}
    multiple_key = {"P/E": ("current_pe", "peer_median_pe"), "P/B": ("current_pb", "peer_median_pb"), "EV/EBIT": ("current_ev_ebit", "peer_median_ev_ebit")}.get(method)
    current_multiple = metrics.get(multiple_key[0]) if multiple_key else None
    peer_multiple = metrics.get(multiple_key[1]) if multiple_key else None
    premium = current_multiple / peer_multiple - 1.0 if current_multiple and peer_multiple else None
    valuation_sentence = (
        f"O múltiplo {method} calculado é {_fmt_ratio(current_multiple)}x, {_fmt_percent(premium)} versus a mediana elegível de {_fmt_ratio(peer_multiple)}x."
        if valuation.get("status") == "AVAILABLE" and method and current_multiple and peer_multiple
        else "O valuation comparável permanece INSUFFICIENT_DATA no corte; o relatório não substitui essa lacuna por múltiplos não elegíveis."
    )
    sentences = [
        f"{company} ({ticker}), classificada em {sector}, combina crescimento de receita de {_fmt_percent(_field_value(financials, 'revenue_growth'))}, margem líquida de {_fmt_percent(_field_value(financials, 'profit_margin'))} e dívida líquida de {_fmt_brl_compact(((report_data.get('official_metrics') or {}).get('net_debt') or {}).get('normalized'))}.",
        valuation_sentence,
        "A principal questão é se crescimento, retorno e conversão de caixa conseguem persistir sem elevar a necessidade de capital ou os riscos próprios do setor.",
        f"A conclusão tem confiança de {_fmt_decimal(research_quality.get('overall_research_confidence'), 0, '/100')} porque governança, macro e KPIs operacionais permanecem incompletos.",
    ]
    return " ".join(sentences)


def _build_implicit_expectations_data(report_data: Dict[str, Any]) -> Dict[str, Any]:
    valuation = report_data.get("valuation") or {}
    metrics = valuation.get("metrics") or {}
    if valuation.get("method") != "P/E":
        return {"status": "INSUFFICIENT_DATA", "reason": "implemented only for observed P/E sensitivity"}
    current = metrics.get("current_pe")
    peer = metrics.get("peer_median_pe")
    eps = metrics.get("eps")
    price = report_data.get("price")
    if not all(isinstance(value, (int, float)) and value > 0 for value in (current, peer, eps, price)):
        return {"status": "INSUFFICIENT_DATA", "reason": "positive current multiple, peer multiple, EPS and price required"}
    required_eps = float(price) / float(peer)
    return {
        "status": "AVAILABLE",
        "current_pe": float(current),
        "peer_median_pe": float(peer),
        "multiple_premium": float(current) / float(peer) - 1.0,
        "ttm_eps": float(eps),
        "eps_required_at_peer_median": required_eps,
        "required_eps_change": required_eps / float(eps) - 1.0,
        "formula": "reference_price / peer_median_PE; required_change = required_EPS / TTM_EPS - 1",
        "interpretation": "Crescimento implícito mecânico para igualar o preço à mediana, com ações e múltiplo constantes; não é projeção ou consenso.",
    }


def _build_scenarios(report_data: Dict[str, Any]) -> str:
    valuation = report_data.get("valuation") or {}
    if not _valuation_publishable(report_data):
        return "Cenários quantitativos indisponíveis; não foram fabricadas premissas substitutas."
    scenarios = valuation["scenarios"]
    descriptions = []
    for name, values in scenarios.items():
        if values.get("method") == "enterprise_value_to_ebit":
            basis = f"EV R$ {float(values['enterprise_value']):,.0f} e equity R$ {float(values['equity_value']):,.0f}"
        else:
            per_share_basis = values.get("future_eps", values.get("book_value_per_share"))
            basis = f"base por ação {float(per_share_basis):.2f}" if isinstance(per_share_basis, (int, float)) else "base não disponível"
        descriptions.append(
            f"{name.upper()}: múltiplo {values['multiple']:.2f}x, {basis}, "
            f"valor implícito R$ {values['implied_value_per_share']:.2f} "
            f"({values['upside_downside']:.1%} versus a referência)."
        )
    return " ".join(descriptions)


def _claim_refs(report_data: Dict[str, Any], section: str) -> str:
    identifiers = [item.get("claim_id") for item in report_data.get("claims") or [] if item.get("section") == section]
    return ", ".join(identifier for identifier in identifiers if identifier) or "não disponível"


def _build_watchlist(report_data: Dict[str, Any]) -> str:
    revenue_growth = _field_value(report_data.get("financials", {}), "revenue_growth")
    margin = _field_value(report_data.get("financials", {}), "profit_margin")
    debt = _field_value(report_data.get("financials", {}), "debt_to_equity")
    pieces = [
        f"Receita e crescimento: {_fmt_percent(revenue_growth) if revenue_growth is not None else 'Não disponível'}",
        f"Margem: {_fmt_percent(margin) if margin is not None else 'Não disponível'}",
        f"Alavancagem: {_fmt_ratio(debt) if debt is not None else 'Não disponível'}",
        "Fluxo de caixa operacional",
        "Risco macro e setor",
    ]
    return "Os indicadores a acompanhar são: " + "; ".join(pieces) + "."


def _build_conclusion(report_data: Dict[str, Any]) -> str:
    company_name = _safe_text(report_data.get("company_name"))
    state = _safe_text(report_data.get("final_state"))
    return (
        f"A leitura do PROMETHEUS sobre {company_name} está em {state}. "
        "O que importa não é apenas o número no papel, mas se a empresa consegue converter operação em caixa, manter disciplina e reagir bem ao cenário econômico."
    )


def _build_score_breakdown(report_data: Dict[str, Any]) -> str:
    snapshot = _canonical_score_snapshot(report_data)
    thesis_scores = snapshot["components"]
    reconciliation = report_data.get("score_reconciliation") or _score_reconciliation(report_data)
    weights = {
        "fundamental": 0.23,
        "sector": 0.14,
        "macro": 0.10,
        "expectation_gap": 0.14,
        "momentum_velocity": 0.14,
        "valuation_margin": 0.20,
        "news_sentiment": 0.05,
    }
    if not thesis_scores:
        return "Fórmula: 0.23*fundamental + 0.14*sector + 0.10*macro + 0.14*expectation_gap + 0.14*momentum_velocity + 0.20*valuation_margin + 0.05*news_sentiment. Dados do score não disponíveis."

    pieces = []
    total = 0.0
    unavailable_components = set(snapshot["unavailable"])
    component_status = (report_data.get("score_availability") or {}).get("component_status") or {}
    for key, weight in weights.items():
        if key in unavailable_components:
            status = component_status.get(key) or {}
            reason = status.get("reason") or "INSUFFICIENT_DATA"
            pieces.append(f"{key}: indisponível — {reason} (peso renormalizado)")
            continue
        value = float(thesis_scores.get(key, 0.0) or 0.0)
        contribution = value * weight
        total += contribution
        pieces.append(f"{key}: {value:.2f} × {weight} = {contribution:.2f}")

    final_score = snapshot["final_score"]
    final_state = _safe_text(report_data.get("final_state"))
    availability = report_data.get("score_availability") or {}
    coverage = availability.get("evidence_coverage")
    unavailable = ", ".join(availability.get("unavailable_components") or []) or "nenhum"
    return (
        "Fórmula: 0.23*fundamental + 0.14*sector + 0.10*macro + 0.14*expectation_gap + 0.14*momentum_velocity + 0.20*valuation_margin + 0.05*news_sentiment. "
        f"Componentes: {'; '.join(pieces)}. "
        f"Fórmula do pipeline: 0.60*weighted_thesis + 0.15*expectation_gap + 0.10*catalyst + 0.08*regime_confidence + 0.07*pricing_confidence. "
        f"Cobertura de evidência: {coverage if isinstance(coverage, (int, float)) else 'não disponível'}%; componentes renormalizados: {unavailable}. "
        f"Total calculado: {float(final_score if final_score is not None else reconciliation.get('reconstructed_final_score', total)):.2f}. Estado: {final_state}."
    )


def _build_narrative(report_data: Dict[str, Any]) -> Dict[str, str]:
    narrative = {
        "summary": _build_summary(report_data),
        "empresa_em_30_segundos": _build_company_profile(report_data),
        "como_ganha_dinheiro": _build_business_model(report_data),
        "business_model": _build_business_model(report_data),
        "fundamentos": _build_balance_sheet_narrative(report_data),
        "crescimento": _build_growth_narrative(report_data),
        "saude_financeira": _build_balance_sheet_narrative(report_data),
        "fluxo_de_caixa": _build_cash_flow_narrative(report_data),
        "qualidade_do_lucro": _build_quality_of_earnings(report_data),
        "setor": _build_sector_narrative(report_data),
        "concorrentes": _build_competitors(report_data),
        "macro": _build_macro_narrative(report_data),
        "noticias": _build_news_summary(report_data),
        "catalisadores": _build_catalysts(report_data),
        "riscos": _build_risks(report_data),
        "valuation": _build_valuation_narrative(report_data),
        "expectation_gap": _build_expectation_gap(report_data),
        "thesis": _build_thesis(report_data),
        "central_thesis": _build_central_thesis(report_data),
        "score_breakdown": _build_score_breakdown(report_data),
        "cenarios": _build_scenarios(report_data),
        "o_que_acompanhar": _build_watchlist(report_data),
        "conclusao": _build_conclusion(report_data),
        "qa": _safe_text(str(_build_quality_assessment(report_data))),
    }
    return narrative


def _build_markdown_like_text(report_data: Dict[str, Any]) -> list:
    quality = (report_data.get("research_quality") or {}).get("overall_research_confidence")
    coverage = (report_data.get("score_availability") or {}).get("evidence_coverage")
    rows = [
        ["Empresa", _safe_text(report_data.get("company_name"))],
        ["Ticker", _safe_text(report_data.get("ticker"))],
        ["Setor", _safe_text(report_data.get("sector_name"))],
        ["Preço de referência", _fmt_money(report_data.get("price"))],
        ["Market cap", _fmt_money(report_data.get("market_cap"))],
        ["Thesis Score", f"{report_data.get('final_score'):.1f}" if report_data.get("final_score") is not None else "Não disponível"],
        ["Cobertura de evidência do score", f"{coverage:.0f}%" if isinstance(coverage, (int, float)) else "Não disponível"],
        ["Estado da tese", _safe_text(report_data.get("final_state"))],
        ["Confiança geral do research", f"{quality:.0f}/100" if quality is not None else "Não disponível"],
    ]
    return rows


def _build_source_rows(report_data: Dict[str, Any], body_style: Any) -> list:
    sources = (report_data.get("research") or {}).get("sources") or []
    source_groups = {
        "official_disclosure": "documentos oficiais (ver seção Documentos Oficiais Recentes)",
        "news_report": "notícias (ver resumo de notícias e export)",
        "news_sentiment_interpretation": "cálculos de sentimento de notícias (ver export)",
    }
    hidden_source_counts = {
        metric: sum(1 for source in sources if source.get("metric") == metric)
        for metric in source_groups
    }
    rows = [["Métrica", "Valor", "Período", "Fonte / disponibilidade"]]
    disclosure_count = sum(1 for source in sources if source.get("metric") == "official_disclosure")
    visible_sources = []
    visible_disclosures = 0
    for source in sources:
        if source.get("metric") in source_groups:
            continue
        if source.get("metric") == "official_disclosure":
            if visible_disclosures >= 10:
                continue
            visible_disclosures += 1
        visible_sources.append(source)
    for source in visible_sources:
        value = source.get("value")
        unit = str(source.get("unit") or "").lower()
        if isinstance(value, (int, float)) and unit in {"brl", "monetary"}:
            absolute = abs(float(value))
            if absolute >= 1_000_000_000:
                display_value = f"R$ {value / 1_000_000_000:.1f} bi".replace(".", ",")
            elif absolute >= 1_000_000:
                display_value = f"R$ {value / 1_000_000:.1f} mi".replace(".", ",")
            else:
                display_value = _fmt_money(value)
        elif isinstance(value, (int, float)) and unit in {"percentage", "percent"}:
            display_value = f"{value * 100:.2f}%"
        elif isinstance(value, (int, float)) and "percent_per_year" in unit:
            display_value = f"{value:.2f}% a.a."
        elif isinstance(value, (int, float)) and unit == "ratio":
            display_value = f"{value:.2f}x"
        else:
            display_value = f"{value:.4f}" if isinstance(value, (int, float)) else _safe_text(value)
        source_name = html.escape(_safe_text(source.get("source")))
        publication = html.escape(_safe_text(source.get("publication_date")))
        source_url = source.get("source_url")
        source_text = f"{source_name}<br/>{publication}"
        if source_url:
            escaped_url = html.escape(str(source_url), quote=True)
            source_text += f'<br/><link href="{escaped_url}">abrir fonte</link>'
        rows.append([
            Paragraph(html.escape(_safe_text(source.get("metric"))), body_style),
            Paragraph(html.escape(display_value), body_style),
            Paragraph(html.escape(_safe_text(source.get("period"))), body_style),
            Paragraph(source_text, body_style),
        ])
    omitted = disclosure_count - visible_disclosures
    if omitted > 0:
        rows.append([
            Paragraph("official_disclosure", body_style),
            Paragraph(f"{omitted} documentos adicionais", body_style),
            Paragraph("ver JSON auditável", body_style),
            Paragraph("CVM IPE; lista integral preservada no artefato JSON", body_style),
        ])
    return rows


def _write_placeholder_chart(path: Path, title: str, message: str) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=180)
    fig.patch.set_facecolor("#F7F4EE")
    ax.set_facecolor("#F7F4EE")
    ax.axis("off")
    ax.text(
        0.5,
        0.5,
        message,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=9,
        color="#5B6675",
    )
    ax.set_title(title, fontsize=10, fontweight="bold", color="#10233F", pad=18, loc="left")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _style_chart_axes(ax: Any, y_grid: bool = True) -> None:
    ax.set_facecolor("#F7F4EE")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D8D3C9")
    ax.spines["bottom"].set_color("#D8D3C9")
    ax.tick_params(colors="#5B6675", labelsize=8, length=0)
    if y_grid:
        ax.grid(axis="y", color="#D8D3C9", alpha=0.75, linewidth=0.7)
        ax.set_axisbelow(True)


def _save_chart(fig: Any, path: Path) -> Path:
    fig.patch.set_facecolor("#F7F4EE")
    fig.tight_layout(pad=0.8)
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def _compact_currency_axis(value: float, _: Any = None) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"R$ {value / 1_000_000_000:.1f} bi".replace(".", ",")
    if absolute >= 1_000_000:
        return f"R$ {value / 1_000_000:.0f} mi".replace(".", ",")
    return f"R$ {value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_price_chart(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    history = report_data.get("price_history") or []
    points = [row for row in history if row.get("date") and isinstance(row.get("close"), (int, float))]
    if len(points) < 2:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=180)
    values = [row["close"] for row in points]
    ax.plot([row["date"] for row in points], values, color="#10233F", linewidth=2.2)
    _style_chart_axes(ax)
    ax.set_ylabel("Preço (R$)", color="#5B6675", fontsize=8)
    ax.annotate(
        f"R$ {values[-1]:.2f}".replace(".", ","),
        xy=(len(points) - 1, values[-1]), xytext=(7, 0), textcoords="offset points",
        va="center", fontsize=8, fontweight="bold", color="#10233F",
    )
    image_path = output_dir / f"{ticker}_price_chart.png"
    return _save_chart(fig, image_path)


def _build_revenue_profit_chart(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    history = report_data.get("financial_history") or []
    points = [row for row in history if row.get("period")]
    if len(points) < 2:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=180)
    labels = [_period_horizon_label(row) for row in points]
    revenue = [row.get("revenue") for row in points]
    net_income = [row.get("net_income") for row in points]
    positions = list(range(len(points)))
    width = 0.36
    if all(isinstance(value, (int, float)) for value in revenue):
        ax.bar([value - width / 2 for value in positions], revenue, width=width, label="Receita", color="#10233F")
    if all(isinstance(value, (int, float)) for value in net_income):
        ax.bar([value + width / 2 for value in positions], net_income, width=width, label="Lucro líquido", color="#D79A2B")
    ax.set_xticks(positions, labels, rotation=0)
    _style_chart_axes(ax)
    ax.set_ylabel("R$", color="#5B6675", fontsize=8)
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncols=2)
    if FuncFormatter is not None:
        ax.yaxis.set_major_formatter(FuncFormatter(_compact_currency_axis))
    ax.margins(x=0.03)
    image_path = output_dir / f"{ticker}_revenue_profit_chart.png"
    return _save_chart(fig, image_path)


def _build_margin_chart(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    history = report_data.get("financial_history") or []
    points = [row for row in history if row.get("period")]
    if len(points) < 2:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=180)
    available = [("profit_margin", "Margem líquida", "#10233F"), ("roe", "ROE", "#D79A2B")]
    plotted = False
    for key, label, color in available:
        series = [row.get(key) for row in points]
        if all(isinstance(value, (int, float)) for value in series):
            plotted_values = [value * 100 for value in series]
            ax.plot(range(len(points)), plotted_values, label=label, color=color, linewidth=2.2, marker="o", markersize=3)
            ax.annotate(label, (len(points) - 1, plotted_values[-1]), xytext=(7, 0), textcoords="offset points", va="center", fontsize=8, color=color, fontweight="bold")
            plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_xticks(range(len(points)), [_period_horizon_label(row) for row in points], rotation=0)
    _style_chart_axes(ax)
    ax.set_ylabel("%", color="#5B6675", fontsize=8)
    ax.margins(x=0.08)
    image_path = output_dir / f"{ticker}_margin_chart.png"
    return _save_chart(fig, image_path)


def _period_horizon_label(row: Dict[str, Any]) -> str:
    period = str(row.get("period") or "")
    year = period[2:4] if len(period) >= 4 else period
    source_rows = (((row.get("metric_metadata") or {}).get("revenue") or {}).get("source_rows") or [])
    period_start = str((source_rows[0] if source_rows else {}).get("period_start") or "")
    try:
        end = dt.date.fromisoformat(period[:10])
        start = dt.date.fromisoformat(period_start[:10])
        months = max(1, (end.year - start.year) * 12 + end.month - start.month + 1)
        if months >= 11:
            return f"FY{year}"
        return f"{months}M{year}"
    except ValueError:
        return period


def _build_valuation_chart(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    price = report_data.get("price")
    valuation = report_data.get("valuation") or {}
    scenarios = valuation.get("scenarios") or {}
    if price is None or not _valuation_publishable(report_data) or not scenarios:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=180)
    labels = ["Referência", "Pessimista", "Base", "Otimista"]
    values = [float(price)] + [float((scenarios.get(key) or {}).get("implied_value_per_share")) for key in ("bear", "base", "bull")]
    bars = ax.barh(labels, values, color=["#10233F", "#B3473D", "#D79A2B", "#10233F"], height=0.58)
    _style_chart_axes(ax, y_grid=False)
    ax.grid(axis="x", color="#D8D3C9", alpha=0.75, linewidth=0.7)
    ax.set_xlabel("R$ por ação", color="#5B6675", fontsize=8)
    for bar, val in zip(bars, values):
        ax.text(val + max(values) * 0.015, bar.get_y() + bar.get_height() / 2, f"R$ {val:.2f}".replace(".", ","), ha="left", va="center", fontsize=8, fontweight="bold", color="#1C2733")
    ax.invert_yaxis()
    image_path = output_dir / f"{ticker}_valuation_chart.png"
    return _save_chart(fig, image_path)


def _build_score_chart(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    snapshot = _canonical_score_snapshot(report_data)
    thesis_scores = snapshot["components"]
    if not thesis_scores:
        return None
    labels = ["Fundamental", "Setor", "Macro", "Gap", "Momentum", "Valuation", "Notícias"]
    keys = ["fundamental", "sector", "macro", "expectation_gap", "momentum_velocity", "valuation_margin", "news_sentiment"]
    unavailable = set(snapshot["unavailable"])
    displayed = [(label, key) for label, key in zip(labels, keys) if key not in unavailable]
    if not displayed:
        return None
    labels, keys = zip(*displayed)
    values = [float(thesis_scores.get(key, 0.0) or 0.0) for key in keys]
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=180)
    bars = ax.bar(labels, values, color=["#10233F"] * 5 + ["#D79A2B", "#2D5D7B"], width=0.62)
    ax.set_ylabel("Score")
    ax.set_ylim(0, 110)
    _style_chart_axes(ax)
    ax.tick_params(axis="x", labelrotation=25, labelsize=8)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 2, f"{value:.1f}".replace(".", ","), ha="center", va="bottom", fontsize=7, color="#1C2733")
    image_path = output_dir / f"{ticker}_score_chart.png"
    return _save_chart(fig, image_path)


def _build_thesis_chart(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    thesis_result = report_data.get("thesis_result") or {}
    drivers = thesis_result.get("drivers") or []
    risk_evidence = (report_data.get("risk") or {}).get("evidence") or []
    if not drivers and not risk_evidence:
        return None
    favor = max(len(drivers), 1)
    against = max(len(risk_evidence), 1)
    fig, ax = plt.subplots(figsize=(7.2, 2.7), dpi=180)
    bars = ax.barh(["Favoráveis", "Desfavoráveis"], [favor, against], color=["#237A57", "#B3473D"], height=0.55)
    ax.set_ylabel("Quantidade")
    _style_chart_axes(ax, y_grid=False)
    ax.grid(axis="x", color="#D8D3C9", alpha=0.75, linewidth=0.7)
    for bar, value in zip(bars, [favor, against]):
        ax.text(value + 0.08, bar.get_y() + bar.get_height() / 2, str(value), va="center", fontsize=8, fontweight="bold")
    ax.invert_yaxis()
    image_path = output_dir / f"{ticker}_thesis_chart.png"
    return _save_chart(fig, image_path)


def _build_sector_chart(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> Optional[Path]:
    peers = ((report_data.get("research") or {}).get("peer_analysis") or {}).get("peers") or []
    if not peers:
        return None
    metrics = ["profit_margin", "roe"]
    companies = sorted({str(row.get("ticker") or row.get("company")) for row in peers if row.get("ticker") or row.get("company")})
    if len(companies) < 2:
        return None
    values: dict[tuple[str, str], float] = {}
    for row in peers:
        company = str(row.get("ticker") or row.get("company") or "")
        if not company:
            continue
        # Current peer records are wide; the second branch preserves support
        # for the older metric/value representation.
        for metric in metrics:
            if isinstance(row.get(metric), (int, float)):
                values[(company, metric)] = float(row[metric]) * 100.0
        if row.get("metric") in metrics and isinstance(row.get("value"), (int, float)):
            values[(company, str(row["metric"]))] = float(row["value"]) * 100.0
    if not values:
        return None
    positions = list(range(len(companies)))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), dpi=180)
    for ax, (metric, label, color) in zip(axes, [
        ("profit_margin", "Margem líquida", "#10233F"),
        ("roe", "ROE", "#D79A2B"),
    ]):
        series = [values.get((company, metric), 0.0) for company in companies]
        bars = ax.barh(positions, series, color=color, height=0.56)
        ax.set_title(label, fontsize=9, fontweight="bold", color="#10233F", loc="left")
        ax.set_yticks(positions, companies)
        ax.set_xlabel("%", color="#5B6675", fontsize=8)
        _style_chart_axes(ax, y_grid=False)
        ax.grid(axis="x", color="#D8D3C9", alpha=0.75, linewidth=0.7)
        ax.invert_yaxis()
        maximum = max(series) if series else 0
        for bar, value in zip(bars, series):
            ax.text(value + max(maximum * 0.02, 0.2), bar.get_y() + bar.get_height() / 2, f"{value:.1f}%".replace(".", ","), va="center", fontsize=7, color="#1C2733")
        ax.set_xlim(0, maximum * 1.22 if maximum > 0 else 1)
    image_path = output_dir / f"{ticker}_sector_chart.png"
    return _save_chart(fig, image_path)


def _valuation_publishable(report_data: Dict[str, Any]) -> bool:
    """Refuse to repeat scenario values that the live editorial gate rejected."""
    valuation = report_data.get("valuation") or {}
    if valuation.get("status") != "AVAILABLE":
        return False
    blockers = (report_data.get("editorial_gate") or {}).get("blockers") or []
    method = valuation.get("method")
    for blocker in blockers:
        code = str(blocker.get("code") or "")
        detail = str(blocker.get("detail") or "")
        if code.startswith("VALUATION_") or code in {"INSUFFICIENT_ELIGIBLE_PEERS", "INCOMPATIBLE_PEER_PERIODS"}:
            return False
        if code.startswith("LOOKAHEAD_"):
            return False
        if code == "TTM_INCOMPLETE" and method in {"P/E", "EV/EBIT"}:
            return False
        if code == "CVM_RAW_HASH_MISSING" and detail in {"ttm_pe", "price_to_book", "ev_to_ebit"}:
            return False
    return True


def _build_chart_artifacts(ticker: str, report_data: Dict[str, Any], output_dir: Path) -> list[tuple[str, Path]]:
    artifacts: list[tuple[str, Path]] = []
    for title, builder in [
        ("Evolução da ação", lambda: _build_price_chart(ticker, report_data, output_dir)),
        ("Receita e lucro", lambda: _build_revenue_profit_chart(ticker, report_data, output_dir)),
        ("Margens e resultado", lambda: _build_margin_chart(ticker, report_data, output_dir)),
        ("Indicadores de valuation", lambda: _build_valuation_chart(ticker, report_data, output_dir)),
        ("Score Prometheus", lambda: _build_score_chart(ticker, report_data, output_dir)),
        ("Comparação setorial", lambda: _build_sector_chart(ticker, report_data, output_dir)),
    ]:
        path = builder()
        if path is not None and path.exists():
            artifacts.append((title, path))
    return artifacts


def _fmt_brl(value: Any, decimals: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "Não disponível"
    formatted = f"{float(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _fmt_brl_compact(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "Não disponível"
    numeric = float(value)
    sign = "-" if numeric < 0 else ""
    absolute = abs(numeric)
    if absolute >= 1_000_000_000:
        scaled, suffix = absolute / 1_000_000_000, " bi"
    elif absolute >= 1_000_000:
        scaled, suffix = absolute / 1_000_000, " mi"
    elif absolute >= 1_000:
        scaled, suffix = absolute / 1_000, " mil"
    else:
        return f"{sign}{_fmt_brl(absolute)}"
    return f"{sign}R$ {scaled:.2f}{suffix}".replace(".", ",")


def _fmt_decimal(value: Any, decimals: int = 1, suffix: str = "") -> str:
    if not isinstance(value, (int, float)):
        return "Não disponível"
    return f"{float(value):.{decimals}f}".replace(".", ",") + suffix


def _fmt_date_time(value: Any) -> str:
    text = _safe_text(value)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M UTC")
    except (TypeError, ValueError):
        return text


def _p(value: Any, style: Any, trusted_markup: bool = False) -> Paragraph:
    text = _safe_text(value)
    return Paragraph(text if trusted_markup else html.escape(text), style)


def _evidence_text(item: Any) -> str:
    if isinstance(item, str):
        return _safe_text(item)
    if not isinstance(item, dict):
        return _safe_text(item)
    for key in ("text", "claim", "description", "reason", "title", "metric", "condition"):
        if item.get(key):
            return _safe_text(item[key])
    return _safe_text(json.dumps(item, ensure_ascii=False, sort_keys=True))


def _humanize_driver(value: Any) -> str:
    text = _safe_text(value)
    labels = {
        "fundamental momentum": "Momentum fundamental",
        "expectation gap": "Assimetria entre evidência e expectativa",
        "pricing bias": "Viés de precificação",
    }
    label = labels.get(text.lower(), text.replace("_", " ").capitalize())
    translations = {
        "Assimetria entre evidência e expectativa": "O que o preço parece pressupor pode estar distante do que os dados confirmam.",
        "Viés de precificação": "A leitura mecânica indica diferença entre a referência de mercado e os fundamentos observados.",
        "Momentum fundamental": "Os indicadores financeiros recentes dão suporte ao acompanhamento da operação.",
    }
    return f"{label} — {translations.get(label, 'Sinal a interpretar junto com os dados e suas limitações.')}"


def _humanize_risk(value: Any) -> str:
    text = _safe_text(value)
    labels = {
        "smaller capitalization implies idiosyncratic risk": "Menor capitalização implica risco idiossincrático.",
    }
    return labels.get(text.lower(), text)


def _valuation_method_label(value: Any) -> str:
    return {"P/E": "P/L TTM", "P/B": "P/VP", "EV/EBIT": "EV/EBIT TTM"}.get(_safe_text(value), _safe_text(value))


def _format_source_value(source: Dict[str, Any]) -> str:
    value = source.get("value")
    if not isinstance(value, (int, float)):
        return _safe_text(value)
    numeric = float(value)
    unit = str(source.get("unit") or "").lower()
    metric = str(source.get("metric") or "").lower()
    if unit in {"percentage", "percent"}:
        return _fmt_percent(numeric)
    if unit == "ratio" and any(token in metric for token in ("margin", "roe", "roa", "growth", "yield")):
        return _fmt_percent(numeric)
    if unit in {"brl", "monetary"}:
        return _fmt_brl_compact(numeric)
    if unit in {"brl/share", "brl_per_share"}:
        return _fmt_brl(numeric)
    if unit in {"brl/unit", "brl_per_unit"}:
        return f"{_fmt_brl(numeric)} / unidade"
    if unit == "units":
        return f"{numeric:,.0f} unidades".replace(",", ".")
    if unit in {"beds", "hospitals", "procedures", "patient-days", "beneficiaries"}:
        labels = {
            "beds": "leitos", "hospitals": "hospitais", "procedures": "procedimentos",
            "patient-days": "pacientes-dia", "beneficiaries": "beneficiários",
        }
        return f"{numeric:,.0f} {labels[unit]}".replace(",", ".")
    if unit == "shares":
        if abs(numeric) >= 1_000_000:
            return f"{numeric / 1_000_000:.2f} mi ações".replace(".", ",")
        return f"{numeric:,.0f} ações".replace(",", ".")
    if unit in {"ratio", "x"}:
        return _fmt_decimal(numeric, 2, "x")
    if unit == "score_0_100":
        return _fmt_decimal(numeric, 1, "/100")
    return _fmt_decimal(numeric, 4)


def _compact_source_ids(source_ids: list[str]) -> str:
    identifiers = [str(item) for item in source_ids if item]
    if len(identifiers) <= 3:
        return ", ".join(identifiers) or "INSUFFICIENT_DATA"
    return f"{', '.join(identifiers[:2])} · +{len(identifiers) - 2} IDs no snapshot JSON"


def _metric_label(metric: Any) -> str:
    key = str(metric or "").strip().lower()
    prefixes = {"history_": "Histórico - ", "ttm_": "TTM - ", "score_": "Score - "}
    prefix = ""
    for raw_prefix, label in prefixes.items():
        if key.startswith(raw_prefix):
            key, prefix = key[len(raw_prefix):], label
            break
    labels = {
        "revenue": "Receita",
        "net_income": "Lucro líquido",
        "gross_profit": "Lucro bruto",
        "operating_income": "Resultado operacional",
        "revenue_growth": "Crescimento da receita",
        "earnings_growth": "Crescimento do lucro",
        "profit_margin": "Margem líquida",
        "gross_margin": "Margem bruta",
        "operating_margin": "Margem operacional",
        "operating_cash_flow": "Fluxo de caixa operacional",
        "operating_cash_flow_margin": "Margem de caixa operacional",
        "cash_conversion": "Conversão de caixa",
        "roe": "ROE",
        "roa": "ROA",
        "debt_to_equity": "Dívida / patrimônio",
        "net_debt_to_equity": "Dívida líquida / patrimônio",
        "net_debt": "Dívida líquida",
        "gross_debt": "Dívida bruta",
        "cash": "Caixa",
        "equity": "Patrimônio líquido",
        "total_assets": "Ativos totais",
        "current_assets": "Ativos circulantes",
        "asset_turnover": "Giro dos ativos",
        "current_ratio": "Liquidez corrente",
        "shares_outstanding": "Ações em circulação",
        "market_cap": "Valor de mercado",
        "price": "Preço de referência",
        "ttm_pe": "P/L TTM do peer",
        "pe": "P/L do peer",
        "fundamental": "Fundamental",
        "sector": "Setor",
        "macro": "Macro",
        "expectation_gap": "Expectativas",
        "momentum_velocity": "Momentum",
        "valuation_margin": "Valuation",
        "news_sentiment": "Notícias",
        "fundamental_data_quality_score": "Completude financeira",
        "prometheus_final_score": "Score final PROMETHEUS",
    }
    return prefix + labels.get(key, key.replace("_", " ").strip().capitalize())


def _sector_kpi_status(report_data: Dict[str, Any]) -> list[Dict[str, str]]:
    sources = list((report_data.get("research") or {}).get("sources") or [])
    metrics = {_canonical_metric_key(item.get("metric")): item for item in sources}
    operational_metrics = (report_data.get("operational_kpis") or {}).get("metrics") or {}
    required_document = {
        "lançamentos": "release operacional ou apresentação de resultados",
        "vendas brutas": "release operacional ou apresentação de resultados",
        "vendas líquidas": "release operacional ou apresentação de resultados",
        "vso": "release operacional com estoque e vendas",
        "distratos": "release operacional ou notas explicativas",
        "unidades lançadas": "release operacional",
        "unidades vendidas": "release operacional",
        "ticket médio": "release operacional com vendas e unidades",
        "unidades entregues": "release operacional",
        "margem bruta ajustada": "release de resultados com reconciliação",
        "margem ref": "release de resultados com definição da companhia",
        "receita a apropriar": "release de resultados ou nota de contratos",
        "landbank": "apresentação de resultados ou FRE",
        "geração de caixa": "DFC e reconciliação operacional",
        "repasses": "release operacional",
        "estoque pronto": "release operacional",
        "estoque em construção": "release operacional",
        "participação no mcmv": "apresentação institucional ou release operacional",
    }
    alias_map = {
        "beneficiarios saude": "beneficiarios_saude", "beneficiarios odonto": "beneficiarios_odonto",
        "ticket medio mensal saude": "ticket_medio_mensal_saude", "sinistralidade caixa": "sinistralidade_caixa",
        "leitos totais": "leitos_totais", "taxa media ocupacao leitos": "taxa_media_ocupacao_leitos",
        "pacientes-dia": "pacientes_dia", "procedimentos cirurgicos": "procedimentos_cirurgicos",
        "hospitais operados": "hospitais_operados",
        "beneficiarios saude e odonto": "beneficiarios_saude_e_odonto",
        "sinistralidade consolidada": "sinistralidade_consolidada",
    }
    rows = []
    for label in (report_data.get("sector_model") or {}).get("kpis") or []:
        aliases = {
            _canonical_metric_key(str(label).replace(" ", "_")),
            _canonical_metric_key(str(label).replace(" ", "")),
        }
        operational_key = alias_map.get(_canonical_metric_key(label), _canonical_metric_key(str(label).replace(" ", "_")))
        operational = operational_metrics.get(operational_key) or {}
        # An operational metric with a distinct semantic name always wins.
        # In particular, a combined health-and-dental beneficiary count is not
        # allowed to fill the "beneficiários saúde" row through fuzzy matching.
        source = operational if operational.get("status") == "AVAILABLE" else next(
            (item for key, item in metrics.items() if key in aliases), None
        )
        rows.append({
            "kpi": str(label),
            "status": "AVAILABLE" if source and source.get("value") is not None else "INSUFFICIENT_DATA",
            "value": _format_source_value(source) if source else "-",
            "period": _safe_text(source.get("period")) if source else "-",
            "needed": required_document.get(str(label).lower(), "documento operacional oficial com definição e período"),
        })
    return rows


def _canonical_metric_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(character for character in text if not unicodedata.combining(character))


def _two_column_panel(
    left: list[Any], right: list[Any], spans: tuple[int, int] = (6, 6),
    left_tone: str = "white", right_tone: str = "white",
) -> Table:
    table = Table([[left, right]], colWidths=grid_widths(spans), hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), PALETTE[left_tone]),
        ("BACKGROUND", (1, 0), (1, 0), PALETTE[right_tone]),
        ("BOX", (0, 0), (-1, -1), 0.45, PALETTE["line"]),
        ("INNERGRID", (0, 0), (-1, -1), 2.2 * mm, PALETTE["paper"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _business_flow(report_data: Dict[str, Any]) -> Table:
    styles = report_styles()
    sector_key = (report_data.get("sector_model") or {}).get("key")
    if sector_key == "real_estate":
        labels = [
            ("1", "Terrenos", "Originação e disciplina de aquisição"),
            ("2", "Lançamentos", "Produto, preço e velocidade"),
            ("3", "Vendas", "VSO, distratos e recebíveis"),
            ("4", "Obras", "Execução, custos e entregas"),
            ("5", "Caixa", "Conversão do lucro e capital"),
        ]
        spans = [2, 2, 3, 3, 2]
    else:
        drivers = list((report_data.get("sector_model") or {}).get("drivers") or [])[:4]
        labels = [(str(index + 1), _safe_text(driver).title(), "Driver setorial a validar em fonte primária") for index, driver in enumerate(drivers)]
        if len(labels) < 4:
            labels = [
                ("1", "Demanda", "Volume, mix e preço"),
                ("2", "Operação", "Capacidade e eficiência"),
                ("3", "Margem", "Custos e disciplina"),
                ("4", "Caixa", "Conversão e capital"),
            ]
        spans = [3, 3, 3, 3]
    cells = []
    for number, title, note in labels:
        cells.append([
            Paragraph(number, styles["kicker"]),
            Paragraph(html.escape(title), styles["small_bold"]),
            Paragraph(html.escape(note), styles["micro"]),
        ])
    table = Table([cells], colWidths=grid_widths(spans), hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALETTE["card"]),
        ("LINEABOVE", (0, 0), (-1, 0), 2, PALETTE["amber"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _chart_lookup(chart_artifacts: list[tuple[str, Path]]) -> dict[str, Path]:
    return {title: path for title, path in chart_artifacts if path.exists()}


def _image_flow(path: Optional[Path], width: float = CONTENT_WIDTH, height: float = 62 * mm) -> list[Any]:
    if path is None or not path.exists():
        return []
    return [Image(str(path.resolve()), width=width, height=height)]


def _compose_premium_story(
    report_data: Dict[str, Any], narrative: Dict[str, str],
    chart_artifacts: list[tuple[str, Path]], audit_identity: Dict[str, Any],
) -> list[Any]:
    styles = report_styles()
    charts = _chart_lookup(chart_artifacts)
    story: list[Any] = []
    ticker = _safe_text(report_data.get("ticker"))
    company = _safe_text(report_data.get("company_name"))
    sector = _safe_text(report_data.get("sector_name"))
    gate = report_data.get("editorial_gate") or {}
    financial_quality_score = (report_data.get("fundamental_data_quality") or {}).get("score")
    research_quality = report_data.get("research_quality") or {}
    quality_score = research_quality.get("overall_research_confidence")
    valuation = report_data.get("valuation") or {}
    scenarios = valuation.get("scenarios") or {}
    base_case = scenarios.get("base") or {}
    price = report_data.get("price")

    # Cover — commercial decision page.
    cover_header = [[[
        Paragraph("PROMETHEUS · INTELIGÊNCIA DE EMPRESA", styles["cover_eyebrow"]),
        Paragraph(html.escape(ticker), styles["cover_ticker"]),
        Paragraph(html.escape(company), styles["cover_company"]),
        Spacer(1, 5),
        Paragraph(
            f"{html.escape(sector)} · corte em {html.escape(_fmt_date_time(report_data.get('analysis_as_of') or report_data.get('timestamp')))}",
            styles["cover_company"],
        ),
    ]]]
    cover_table = Table(cover_header, colWidths=[CONTENT_WIDTH], rowHeights=[51 * mm], hAlign="LEFT")
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALETTE["navy"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.extend([Spacer(1, 4 * mm), cover_table, Spacer(1, 5 * mm)])
    if gate.get("deliverable"):
        review_text = f"APROVADO PARA ENTREGA · responsável: {html.escape(_safe_text(gate.get('approved_by')))}"
        story.append(callout("Status editorial", review_text, "positive"))
    else:
        story.append(callout("DRAFT - HUMAN REVIEW REQUIRED", "A análise passou pelos gates automáticos disponíveis, mas ainda exige revisão e aprovação humana nominal antes de qualquer entrega ao cliente.", "warning"))
    if report_data.get("data_source_status") == "DEGRADED":
        story.extend([
            Spacer(1, 3 * mm),
            callout(
                "ATENÇÃO: DADOS DEGRADADOS",
                "Fonte primária (CVM) indisponível neste corte — dados limitados ao snapshot de mercado secundário. KPIs operacionais, governança e valuation oficial não puderam ser calculados.",
                "warning",
            ),
        ])
    regression = report_data.get("regression_alert") or {}
    if regression.get("status") == "REGRESSION_ALERT":
        story.extend([
            Spacer(1, 3 * mm),
            callout(
                "ALERTA DE REGRESSÃO DE COBERTURA",
                "Este corte perdeu cobertura material versus o anterior. Ver seção de rastreabilidade e o export de auditoria antes de circular o documento.",
                "warning",
            ),
        ])
    story.extend([
        Spacer(1, 4 * mm),
        metric_cards([
            ("Preço de referência", _fmt_brl(price), "observação point-in-time"),
            ("Thesis score", _fmt_decimal(report_data.get("final_score"), 1, "/100"), "não é recomendação"),
            ("Leitura do sistema", "sem convicção direcional", "não é rating"),
            ("Confiança do research", _fmt_decimal(quality_score, 0, "/100"), "cobertura total"),
        ]),
        Spacer(1, 5 * mm),
    ])
    valuation_takeaway = "Valuation quantitativo não publicado pelo gate editorial."
    if _valuation_publishable(report_data) and isinstance(base_case.get("implied_value_per_share"), (int, float)):
        valuation_takeaway = (
            f"A sensibilidade-base resulta em {_fmt_brl(base_case.get('implied_value_per_share'))}, "
            f"{_fmt_percent(base_case.get('upside_downside'))} versus a referência. É uma saída mecânica das premissas, não um preço-alvo."
        )
    story.append(_two_column_panel(
        [Paragraph("LEITURA EXECUTIVA", styles["small_bold"]), _p(narrative["summary"], styles["body"])],
        [Paragraph("COMO LER", styles["small_bold"]), _p("Abertura concentrada no negócio, nos riscos e no que a evidência sustenta. A sensibilidade de valuation aparece na seção própria.", styles["body"])],
        spans=(7, 5), left_tone="white", right_tone="white",
    ))
    story.extend([
        Spacer(1, 7 * mm),
        Paragraph("Como ler este relatório", styles["h2"]),
        Paragraph(
            "Fatos, cálculos, interpretações, estimativas, riscos e limitações permanecem separados. "
            "O documento explica o negócio e os cenários; não promete retorno, não prescreve operação e não substitui análise pessoal.",
            styles["small"],
        ),
        PageBreak(),
    ])

    # Company in one page.
    story.extend(section_heading("A empresa em uma página", "01 · mapa do negócio"))
    official = dict(report_data.get("official_classification") or {})
    if not official.get("cnpj"):
        disclosures = (report_data.get("official_disclosures") or {}).get("documents") or []
        first_cnpj = next((item.get("cnpj") for item in disclosures if item.get("cnpj")), None)
        if first_cnpj:
            official["cnpj"] = first_cnpj
    if (report_data.get("sector_model") or {}).get("key") == "real_estate":
        company_overview = (
            f"{company} está classificada pela CVM em {sector} e atua em incorporação residencial. "
            "O snapshot confirma demonstrações financeiras e identidade regulatória; regiões, faixas de renda e exposição ao Minha Casa Minha Vida não são afirmadas sem documento operacional elegível."
        )
        business_model_text = narrative["como_ganha_dinheiro"]
    else:
        company_overview = narrative["empresa_em_30_segundos"]
        business_model_text = narrative["como_ganha_dinheiro"]
    identity_left = [
        Paragraph("O QUE A EMPRESA FAZ", styles["h2"]),
        _p(company_overview, styles["body"]),
        Paragraph("COMO O MODELO ECONÔMICO GERA VALOR", styles["h2"]),
        _p(business_model_text, styles["body"]),
    ]
    identity_right = [
        Paragraph("IDENTIDADE VALIDADA", styles["h2"]),
        _p(f"Ticker: {ticker}", styles["small"]),
        _p(f"CNPJ: {_safe_text(official.get('cnpj'))}", styles["small"]),
        _p(f"Código CVM: {_safe_text(official.get('cvm_code'))}", styles["small"]),
        _p(f"Setor CVM: {sector}", styles["small"]),
        _p(f"Indústria: {_safe_text(report_data.get('industry_name'))}", styles["small"]),
        _p(f"Capitalização: {_fmt_money(report_data.get('market_cap'))}", styles["small"]),
    ]
    story.extend([
        _two_column_panel(identity_left, identity_right, spans=(8, 4), left_tone="white", right_tone="card"),
        Spacer(1, 5 * mm), Paragraph("MAPA DE CRIAÇÃO DE VALOR", styles["h2"]),
        _business_flow(report_data), Spacer(1, 5 * mm),
    ])
    financials = report_data.get("financials") or {}
    story.append(metric_cards([
        ("Crescimento da receita", _fmt_percent(_field_value(financials, "revenue_growth")), "período comparável"),
        ("Margem líquida", _fmt_percent(_field_value(financials, "profit_margin")), "resultado / receita"),
        ("ROE", _fmt_percent(_field_value(financials, "roe")), "retorno sobre patrimônio"),
        ("Dívida / patrimônio", _fmt_decimal(_field_value(financials, "debt_to_equity"), 2, "x"), "alavancagem contábil"),
    ]))
    quality = report_data.get("business_quality") or {}
    moat = quality.get("moat") or {}
    governance = quality.get("governance") or {}
    story.extend([
        Spacer(1, 5 * mm),
        _two_column_panel(
            [Paragraph("O QUE A EVIDÊNCIA SUSTENTA", styles["small_bold"]), _p(_safe_text(moat.get("conclusion")), styles["body"])],
            [Paragraph("O QUE AINDA NÃO ESTÁ PROVADO", styles["small_bold"]), _p(_governance_public_text(governance), styles["body"])],
            spans=(6, 6), left_tone="green_soft", right_tone="amber_soft",
        ),
        Spacer(1, 4 * mm),
        Paragraph("QUALIDADE DA EVIDÊNCIA", styles["h2"]),
        metric_cards([
            ("Financeiro", _fmt_decimal(financial_quality_score, 0, "/100"), "campos e validação"),
            ("Proveniência", _fmt_decimal(research_quality.get("source_provenance"), 0, "/100"), "fonte, período e data"),
            ("Cobertura", _fmt_decimal(research_quality.get("research_coverage"), 0, "/100"), "módulos preenchidos"),
        ]),
        Spacer(1, 2 * mm),
        metric_cards([
            ("Valuation", _fmt_decimal(research_quality.get("valuation_confidence"), 0, "/100"), "base rastreável"),
            ("Qualitativo", _fmt_decimal(research_quality.get("qualitative_evidence_coverage"), 0, "/100"), "governança e operação"),
            ("Confiança geral", _fmt_decimal(quality_score, 0, "/100"), "média ponderada"),
        ]),
        PageBreak(),
    ])

    # Financial dashboard.
    story.extend(section_heading("Dashboard financeiro", "02 · trajetória e qualidade"))
    ttm = report_data.get("ttm") or {}
    ttm_metrics = ttm.get("metrics") or {}
    allocation = quality.get("capital_allocation") or {}
    story.extend([
        metric_cards([
            ("Receita TTM", _fmt_brl_compact((ttm_metrics.get("revenue") or {}).get("normalized")), _safe_text(ttm.get("status"))),
            ("Lucro líquido TTM", _fmt_brl_compact((ttm_metrics.get("net_income") or {}).get("normalized")), "últimos 12 meses"),
            ("Caixa", _fmt_brl_compact(allocation.get("cash")), _safe_text(allocation.get("status"))),
            ("Dívida líquida", _fmt_brl_compact(allocation.get("net_debt")), "dívida bruta menos caixa"),
        ]),
        Spacer(1, 4 * mm),
    ])
    revenue_chart = charts.get("Receita e lucro")
    margin_chart = charts.get("Margens e resultado")
    if revenue_chart:
        story.extend([Paragraph("RECEITA E LUCRO LÍQUIDO", styles["h2"])] + _image_flow(revenue_chart, height=53 * mm))
    if margin_chart:
        story.extend([Spacer(1, 2 * mm), Paragraph("MARGEM E RETORNO", styles["h2"])] + _image_flow(margin_chart, height=50 * mm))
    story.extend([
        Spacer(1, 2 * mm),
        Paragraph(
            "Leitura dos gráficos: FY representa exercício anual; 3M e 6M são acumulados intermediários. Compare apenas horizontes equivalentes. As barras não representam crescimento sequencial entre períodos incompatíveis.",
            styles["micro"],
        ),
        Spacer(1, 2 * mm),
        callout("Qualidade do lucro", narrative["qualidade_do_lucro"], "neutral"),
        Spacer(1, 3 * mm),
        _two_column_panel(
            [Paragraph("CONSTRUÇÃO DO TTM", styles["small_bold"]), _p(f"Status: {_safe_text(ttm.get('status'))}. Método: {_safe_text(ttm.get('formula'))}.", styles["small"])],
            [Paragraph("CONVERSÃO EM CAIXA", styles["small_bold"]), _p(narrative["fluxo_de_caixa"], styles["small"])],
            spans=(5, 7), left_tone="white", right_tone="white",
        ),
        PageBreak(),
    ])

    # Sector-specific operating evidence. Missing items are explicit, never inferred.
    story.extend(section_heading("KPIs operacionais", "03 · o que está medido e o que falta"))
    sector_key = (report_data.get("sector_model") or {}).get("key")
    kpi_intro = (
        "Uma incorporadora deve ser acompanhada por vendas, estoque, execução, repasses e capital."
        if sector_key == "real_estate" else
        "Uma operadora de saúde deve ser acompanhada por beneficiários, ticket, sinistralidade, churn e composição da rede."
        if sector_key == "healthcare" else
        "A empresa deve ser acompanhada pelos indicadores operacionais específicos do seu modelo econômico."
    )
    story.append(Paragraph(
        kpi_intro + " O quadro abaixo separa dados encontrados no snapshot de documentos ainda ausentes.",
        styles["body"],
    ))
    if report_data.get("sector_coverage") == "GENERIC":
        story.extend([
            Spacer(1, 3 * mm),
            callout("Cobertura setorial: GENERIC", "Não há módulo dedicado para a classificação CVM deste emissor. O PROMETHEUS não reutiliza KPIs de outro setor; fundamentos, valuation e demais componentes independentes seguem disponíveis conforme suas próprias evidências.", "warning"),
        ])
    kpi_rows: list[list[Any]] = [[
        _p("KPI", styles["table_header"]), _p("Status / valor", styles["table_header"]),
        _p("Período", styles["table_header"]), _p("Evidência necessária quando ausente", styles["table_header"]),
    ]]
    kpi_status_rows = _sector_kpi_status(report_data)
    for item in kpi_status_rows:
        status_value = item["value"] if item["status"] == "AVAILABLE" else "INSUFFICIENT_DATA"
        kpi_rows.append([
            _p(item["kpi"], styles["micro"]), _p(status_value, styles["micro"]),
            _p(item["period"], styles["micro"]), _p(item["needed"], styles["micro"]),
        ])
    kpi_table = Table(kpi_rows, colWidths=grid_widths([3, 3, 2, 4]), repeatRows=1, hAlign="LEFT")
    kpi_table.setStyle(table_style(compact=True))
    story.extend([
        Spacer(1, 4 * mm), kpi_table, Spacer(1, 4 * mm),
        callout(
            "Cobertura operacional",
            (
                f"{sum(item['status'] == 'AVAILABLE' for item in kpi_status_rows)} de {len(kpi_status_rows)} KPIs possuem valor rastreável. "
                "Campos não identificados de forma inequívoca permanecem INSUFFICIENT_DATA; o sistema não infere valores a partir de gráficos, texto qualitativo ou métricas de outro setor."
            ),
            "neutral" if all(item["status"] == "AVAILABLE" for item in kpi_status_rows) else "warning",
        ),
        PageBreak(),
    ])

    # Thesis / antithesis.
    story.extend(section_heading("Tese e antítese", "04 · evidência em equilíbrio"))
    thesis_result = report_data.get("thesis_result") or {}
    positive = [_humanize_driver(_evidence_text(item)) for item in thesis_result.get("drivers") or []]
    negative = [_humanize_risk(_evidence_text(item)) for item in (report_data.get("risk") or {}).get("evidence") or []]
    if not positive:
        positive = ["Nenhum driver positivo explícito foi confirmado no snapshot."]
    if not negative:
        negative = [_safe_text(item) for item in (report_data.get("sector_model") or {}).get("risks") or []]
    story.extend([callout("Tese central", narrative["central_thesis"], "neutral"), Spacer(1, 4 * mm)])
    story.append(_two_column_panel(
        [Paragraph("EVIDÊNCIAS FAVORÁVEIS", styles["small_bold"])] + bullet_paragraphs([html.escape(item) for item in positive], "small", 5),
        [Paragraph("EVIDÊNCIAS DESFAVORÁVEIS", styles["small_bold"])] + bullet_paragraphs([html.escape(item) for item in negative], "small", 5),
        spans=(6, 6), left_tone="green_soft", right_tone="red_soft",
    ))
    score_chart = charts.get("Score Prometheus")
    if score_chart:
        story.extend([Spacer(1, 4 * mm), Paragraph("COMPOSIÇÃO VISUAL DO SCORE", styles["h2"])] + _image_flow(score_chart, height=49 * mm))
    story.extend([
        Spacer(1, 3 * mm),
        _two_column_panel(
            [Paragraph("MOAT E ALOCAÇÃO", styles["small_bold"]), _p(f"Moat: {_safe_text(moat.get('status'))}. Alocação: {_safe_text(allocation.get('status'))}. Caixa {_fmt_money(allocation.get('cash'))}; dívida bruta {_fmt_money(allocation.get('gross_debt'))}.", styles["body"])],
            [Paragraph("GOVERNANÇA", styles["small_bold"]), _p(_governance_public_text(governance), styles["body"])],
            spans=(6, 6), left_tone="white", right_tone="white",
        ),
        Spacer(1, 4 * mm),
        callout(
            "O que invalidaria a leitura",
            "; ".join(_safe_text(item.get("condition")) for item in quality.get("thesis_breakers") or []) or "INSUFFICIENT_DATA - fatores de invalidação não registrados.",
            "warning",
        ),
        Spacer(1, 3 * mm),
        _two_column_panel(
            [Paragraph("LEITURA DO SISTEMA", styles["small_bold"]), _p(narrative["thesis"], styles["small"])],
            [Paragraph("PERGUNTAS PARA A REVISÃO", styles["small_bold"])] + bullet_paragraphs(
                [html.escape(_safe_text(item)) for item in quality.get("clarifying_questions") or ["INSUFFICIENT_DATA"]], "micro", 3
            ),
            spans=(6, 6), left_tone="white", right_tone="card",
        ),
        PageBreak(),
    ])

    # Sector and peers.
    story.extend(section_heading("Setor e comparáveis", "05 · contexto e comparabilidade"))
    peer_analysis = (report_data.get("research") or {}).get("peer_analysis") or {}
    selection_label = {
        "exact_cvm_activity_sector_unique_issuer": "mesmo setor oficial CVM; emissor único; classe de instrumento compatível",
        "maintained_economic_model_and_exact_cvm_activity": "modelo econômico residencial mantido e mesmo setor oficial CVM",
        "maintained_sector_universe": "universo setorial mantido e revisável",
    }.get(_safe_text(peer_analysis.get("selection_method")), _safe_text(peer_analysis.get("selection_method")))
    scale_label = {"total_assets": "ativos totais"}.get(
        _safe_text(peer_analysis.get("scale_policy")), _safe_text(peer_analysis.get("scale_policy"))
    )
    story.append(callout(
        "Seleção explicável",
        f"Método: {selection_label}. Setor oficial: {_safe_text(peer_analysis.get('target_activity_sector'))}. "
        f"Período-alvo: {_safe_text(peer_analysis.get('target_period'))}. Escala: {scale_label}. "
        "A tabela usa apenas múltiplos elegíveis; o gráfico pode manter métricas operacionais de peers do mesmo período mesmo quando o múltiplo não está disponível.",
        "neutral",
    ))
    peer_rows: list[list[Any]] = [["Ticker", "P/L TTM", "P/VP", "EV/EBIT", "Margem", "ROE", "Período"]]
    for peer in peer_analysis.get("peers") or []:
        if not peer.get("period_compatible") or not peer.get("multiple_eligible"):
            continue
        peer_rows.append([
            _safe_text(peer.get("ticker")), _fmt_decimal(peer.get("trailing_pe"), 1, "x"),
            _fmt_decimal(peer.get("price_to_book"), 1, "x"), _fmt_decimal(peer.get("ev_to_ebit"), 1, "x"),
            _fmt_percent(peer.get("profit_margin")), _fmt_percent(peer.get("roe")), _safe_text(peer.get("reference_date")),
        ])
    if len(peer_rows) > 1:
        peer_table = Table(peer_rows, colWidths=grid_widths([2, 2, 2, 2, 1, 1, 2]), repeatRows=1, hAlign="LEFT")
        peer_table.setStyle(table_style())
        story.extend([Spacer(1, 4 * mm), peer_table])
    else:
        story.append(callout("Comparáveis", "INSUFFICIENT_DATA - não há observações elegíveis e compatíveis.", "warning"))
    sector_chart = charts.get("Comparação setorial")
    if sector_chart:
        story.extend([Spacer(1, 4 * mm), Paragraph("MARGEM E ROE DOS COMPARÁVEIS", styles["h2"])] + _image_flow(sector_chart, height=53 * mm))
    outliers = ", ".join(peer_analysis.get("outlier_tickers") or [])
    story.extend([
        Spacer(1, 3 * mm),
        Paragraph(
            "A mediana é um ponto de partida, não uma prova de valor. Margem, ROE, balanço e conversão de caixa são exibidos para evitar equivalência automática entre empresas. "
            + (f"Outliers sinalizados: {html.escape(outliers)}." if outliers else "Nenhum outlier acima de 3x ou abaixo de 1/3 da mediana foi sinalizado."),
            styles["small"],
        ),
        Spacer(1, 3 * mm),
        _two_column_panel(
            [Paragraph("DINÂMICA SETORIAL", styles["small_bold"]), _p(narrative["setor"], styles["small"])],
            [Paragraph("TRANSMISSÃO DO MACRO", styles["small_bold"]), _p(narrative["macro"], styles["small"])],
            spans=(6, 6), left_tone="white", right_tone="white",
        ),
        Spacer(1, 4 * mm),
        Paragraph("CHECKLIST OPERACIONAL", styles["h2"]),
    ])
    monitor_rows: list[list[Any]] = [[
        _p("Indicador", styles["table_header"]), _p("Evidência atual", styles["table_header"]),
        _p("Fortalece a tese", styles["table_header"]), _p("Enfraquece a tese", styles["table_header"]),
    ]]
    for item in _sector_kpi_status(report_data)[:6]:
        monitor_rows.append([
            _p(item["kpi"], styles["micro"]), _p(item["status"], styles["micro"]),
            _p("melhora confirmada vs. período comparável", styles["micro"]),
            _p("deterioração material vs. período comparável", styles["micro"]),
        ])
    monitor_table = Table(monitor_rows, colWidths=grid_widths([2, 3, 3, 4]), repeatRows=1, hAlign="LEFT")
    monitor_table.setStyle(table_style(compact=True))
    story.extend([
        monitor_table,
        PageBreak(),
    ])

    # Valuation.
    story.extend(section_heading("Valuation e cenários", "06 · preço e expectativas implícitas"))
    story.append(callout("Tensão central", valuation_takeaway, "amber" if _valuation_publishable(report_data) else "warning"))
    story.append(Spacer(1, 3 * mm))
    if _valuation_publishable(report_data):
        scenario_cards = []
        scenario_labels = [("bear", "Pessimista"), ("base", "Base"), ("bull", "Otimista")]
        for key, label in scenario_labels:
            scenario = scenarios.get(key) or {}
            scenario_cards.append((label, _fmt_brl(scenario.get("implied_value_per_share")), f"{_fmt_percent(scenario.get('upside_downside'))} vs. referência"))
        story.extend([
            metric_cards([
                ("Preço de referência", _fmt_brl(price), "observação de mercado"),
                *scenario_cards,
            ]),
            Spacer(1, 4 * mm),
        ])
        valuation_chart = charts.get("Indicadores de valuation")
        if valuation_chart:
            story.extend([Paragraph("FAIXA DE SENSIBILIDADE", styles["h2"])] + _image_flow(valuation_chart, height=58 * mm))
        scenario_rows = [["Cenário", "Múltiplo", "Base por ação", "Valor implícito", "Diferença"]]
        for key, label in scenario_labels:
            scenario = scenarios.get(key) or {}
            basis = scenario.get("future_eps", scenario.get("book_value_per_share"))
            scenario_rows.append([
                label, _fmt_decimal(scenario.get("multiple"), 2, "x"), _fmt_brl(basis),
                _fmt_brl(scenario.get("implied_value_per_share")), _fmt_percent(scenario.get("upside_downside")),
            ])
        scenario_table = Table(scenario_rows, colWidths=grid_widths([2, 2, 3, 3, 2]), repeatRows=1, hAlign="LEFT")
        scenario_table.setStyle(table_style())
        story.extend([
            Spacer(1, 4 * mm), scenario_table, Spacer(1, 4 * mm),
            callout("Interpretação", "Os cenários são sensibilidades determinísticas às premissas declaradas. Não são preços-alvo, recomendação ou promessa de retorno. Fórmulas e inputs estão no anexo de auditoria.", "warning"),
            Spacer(1, 3 * mm),
            callout(
                "O que o preço exige",
                (
                    f"Ao múltiplo mediano de {_fmt_decimal((report_data.get('implicit_expectations') or {}).get('peer_median_pe'), 2, 'x')}, "
                    f"o preço observado exigiria lucro por ação de {_fmt_brl((report_data.get('implicit_expectations') or {}).get('eps_required_at_peer_median'))}, "
                    f"{_fmt_percent((report_data.get('implicit_expectations') or {}).get('required_eps_change'))} acima do EPS TTM. "
                    "É uma equivalência mecânica com ações e múltiplo constantes, não uma projeção."
                    if (report_data.get("implicit_expectations") or {}).get("status") == "AVAILABLE"
                    else "INSUFFICIENT_DATA: não foi possível calcular expectativas implícitas sem múltiplo corrente e mediana elegível."
                ),
                "neutral",
            ),
            Spacer(1, 3 * mm),
            callout(
                "Coerência entre score e valuation",
                _safe_text(((report_data.get("business_quality") or {}).get("valuation_reconciliation") or {}).get("explanation")),
                "warning",
            ),
            Spacer(1, 3 * mm),
            _two_column_panel(
                [Paragraph("MÉTODO", styles["small_bold"]), _p(f"{_valuation_method_label(valuation.get('method'))} · {valuation.get('peer_observations', 0)} observações elegíveis · mediana {_fmt_decimal((valuation.get('metrics') or {}).get('peer_median_pe'), 2, 'x')}", styles["small"])],
                [Paragraph("QUALIDADE DA BASE", styles["small_bold"]), _p(f"Conversão de caixa: {_fmt_decimal((valuation.get('metrics') or {}).get('cash_conversion'), 2, 'x')}. Período: {_safe_text(peer_analysis.get('target_period'))}. Premissas completas no anexo.", styles["small"])],
                spans=(6, 6), left_tone="white", right_tone="white",
            ),
        ])
    else:
        story.append(callout("Valuation bloqueado", "O gate editorial não liberou cenários quantitativos; nenhuma premissa substituta foi fabricada.", "warning"))
    story.append(PageBreak())

    # Risk, catalysts and monitoring.
    story.extend(section_heading("Riscos, catalisadores e monitoramento", "07 · o que muda a leitura"))
    risks = list((report_data.get("sector_model") or {}).get("risks") or [])[:5]
    risk_rows: list[list[Any]] = [["Risco", "Evidência / status", "Sinal de deterioração", "Ação de monitoramento"]]
    for risk in risks:
        risk_rows.append([
            _p(risk, styles["micro"]), _p("Risco setorial - interpretação", styles["micro"]),
            _p("INSUFFICIENT_DATA - gatilho específico não definido", styles["micro"]),
            _p("Revisar KPIs e documentos oficiais no próximo corte elegível.", styles["micro"]),
        ])
    if len(risk_rows) > 1:
        risk_table = Table(risk_rows, colWidths=grid_widths([3, 3, 3, 3]), repeatRows=1, hAlign="LEFT")
        risk_table.setStyle(table_style())
        story.append(risk_table)
    catalysts = (report_data.get("catalyst_result") or {}).get("catalysts") or []
    factual = [item for item in catalysts if item.get("factual_status") == "PRIMARY_CONFIRMED"]
    reported = [item for item in catalysts if item.get("factual_status") != "PRIMARY_CONFIRMED"]
    catalyst_body = (
        "; ".join(f"{_safe_text(item.get('title'))} ({_safe_text(item.get('published_at'))})" for item in factual[:5])
        if factual else "Nenhum catalisador factual foi confirmado em fonte primária dentro da data de corte."
    )
    if reported:
        catalyst_body += " Relatos secundários permanecem não confirmados: " + "; ".join(_safe_text(item.get("title")) for item in reported[:3]) + "."
    story.extend([
        Spacer(1, 4 * mm), callout("Catalisadores factuais", catalyst_body, "neutral"),
        Spacer(1, 4 * mm), Paragraph("PAINEL DO QUE ACOMPANHAR", styles["h2"]),
        metric_cards([
            ("Receita", _fmt_percent(_field_value(financials, "revenue_growth")), "variação comparável"),
            ("Margem", _fmt_percent(_field_value(financials, "profit_margin")), "pressão ou expansão"),
            ("Alavancagem", _fmt_decimal(_field_value(financials, "debt_to_equity"), 2, "x"), "dívida / patrimônio"),
            ("Caixa operacional", _fmt_money(_field_value(financials, "cash_flow")), "conversão do resultado"),
        ]),
        Spacer(1, 4 * mm),
        callout("Regra de revisão", "Atualizar a leitura somente com informação cuja data de disponibilidade seja anterior ou igual ao novo corte. Contradições e lacunas devem permanecer explícitas.", "warning"),
    ])
    disclosures = (report_data.get("official_disclosures") or {}).get("documents") or []
    if disclosures:
        story.extend([Spacer(1, 3 * mm), Paragraph("DOCUMENTOS OFICIAIS RECENTES", styles["h2"])])
        disclosure_rows = [["Entrega", "Categoria", "Assunto"]]
        for item in disclosures[:5]:
            disclosure_rows.append([
                _safe_text(item.get("delivered_at")), _safe_text(item.get("category")), _safe_text(item.get("subject")),
            ])
        disclosure_table = Table(disclosure_rows, colWidths=grid_widths([2, 3, 7]), repeatRows=1, hAlign="LEFT")
        disclosure_table.setStyle(table_style(compact=True))
        story.append(disclosure_table)
    story.extend([
        Spacer(1, 3 * mm),
        _two_column_panel(
            [Paragraph("PRÓXIMA REVISÃO", styles["small_bold"]), Paragraph("Na próxima publicação oficial elegível, sem usar informação posterior ao novo corte.", styles["small"])],
            [Paragraph("QUESTÕES EM ABERTO", styles["small_bold"])] + bullet_paragraphs(
                [html.escape(_safe_text(item)) for item in quality.get("clarifying_questions") or ["INSUFFICIENT_DATA"]], "micro", 3
            ),
            spans=(4, 8), left_tone="white", right_tone="card",
        ),
        PageBreak(),
    ])

    # Audit appendix begins here. Commercial pages above intentionally contain no formulas.
    story.extend(section_heading("Anexo de auditoria", "08 · rastreabilidade e governança"))
    story.append(Paragraph("IDENTIDADE TEMPORAL E COGNITIVA", styles["h2"]))
    temporal_rows = [
        ["Campo", "Valor", "Interpretação"],
        ["analysis_as_of / effective_as_of", _safe_text(report_data.get("analysis_as_of")), "Data de corte efetiva do snapshot de research"],
        ["occurred_at", _safe_text(audit_identity.get("occurred_at") or "INSUFFICIENT_DATA"), "Não inferido de outro timestamp"],
        ["recorded_at", _safe_text(audit_identity.get("recorded_at") or "INSUFFICIENT_DATA"), "Não inferido de outro timestamp"],
        ["research_case_id", _safe_text(audit_identity.get("research_case_id") or "INSUFFICIENT_DATA"), "Ausente no snapshot legado quando não propagado"],
        ["event_hash", _safe_text(audit_identity.get("event_hash") or "INSUFFICIENT_DATA"), "Hash do Journal somente quando fornecido"],
        ["snapshot_hash cognitivo", _safe_text(audit_identity.get("snapshot_hash") or "INSUFFICIENT_DATA"), "Não substituído por hash parcial"],
        ["report_snapshot_sha256", _safe_text(audit_identity.get("report_snapshot_sha256")), "SHA-256 do JSON exato usado na renderização"],
        ["SHA-256 do PDF", "Ver manifesto externo", "Não inserido no próprio PDF"],
        ["Registro completo", _safe_text((report_data.get("audit_export") or {}).get("filename") or "INSUFFICIENT_DATA"), "Claims e warnings completos em JSON"],
        ["data_source_status", _safe_text(report_data.get("data_source_status") or "PRIMARY"), "DEGRADED exige revisão antes de circulação"],
        ["regression_alert", _safe_text((report_data.get("regression_alert") or {}).get("status") or "NOT_APPLICABLE"), "Comparação com o corte anterior do mesmo ticker"],
    ]
    temporal_table_data = [
        [_p(cell, styles["table_header"] if row_index == 0 else styles["micro"]) for cell in row]
        for row_index, row in enumerate(temporal_rows)
    ]
    temporal_table = Table(temporal_table_data, colWidths=grid_widths([3, 5, 4]), repeatRows=1, hAlign="LEFT")
    temporal_table.setStyle(table_style(compact=True))
    story.extend([temporal_table, Spacer(1, 4 * mm)])
    claim_audit = gate.get("claim_audit") or {}
    story.append(_two_column_panel(
        [Paragraph("GATE EDITORIAL", styles["small_bold"]), _p(f"Status: {_safe_text(gate.get('status'))}. Deliverable: {bool(gate.get('deliverable'))}. Blockers: {len(gate.get('blockers') or [])}. Warnings: {len(gate.get('warnings') or [])}.", styles["small"])],
        [Paragraph("AUDITORIA DE CLAIMS", styles["small_bold"]), _p(f"Status: {_safe_text(claim_audit.get('status'))}. Claims: {claim_audit.get('claim_count', 0)}; verificados: {claim_audit.get('verified_count', 0)}; fontes: {claim_audit.get('source_count', 0)}.", styles["small"])],
        spans=(6, 6), left_tone="white", right_tone="white",
    ))
    gate_entries = [
        ("BLOCKER", item) for item in (gate.get("blockers") or [])
    ] + [
        ("WARNING", item) for item in (gate.get("warnings") or [])
    ]
    if gate_entries:
        story.extend([Spacer(1, 4 * mm), Paragraph("CONTEÚDO DO GATE EDITORIAL", styles["h2"])])
        gate_rows: list[list[Any]] = [[
            _p("Severidade", styles["table_header"]), _p("Código", styles["table_header"]),
            _p("Mensagem", styles["table_header"]), _p("Detalhe", styles["table_header"]),
        ]]
        grouped_warnings: dict[str, list[Dict[str, Any]]] = {}
        presentation_entries: list[tuple[str, Dict[str, Any]]] = []
        for severity, item in gate_entries:
            if severity == "WARNING":
                grouped_warnings.setdefault(str(item.get("code") or "UNKNOWN"), []).append(item)
            else:
                presentation_entries.append((severity, item))
        for code, items in grouped_warnings.items():
            if len(items) >= 2:
                presentation_entries.append(("WARNING", {
                    "code": code,
                    "message": (
                        f"{len(items)} documentos oficiais catalogados apenas por metadado "
                        "(sem extração de conteúdo) — não influenciam o score. Ver export para lista completa."
                    ) if code == "OFFICIAL_DOCUMENT_METADATA_ONLY" else f"{len(items)} avisos com o mesmo código — ver export para lista completa.",
                    "detail": "PDF_AGGREGATED",
                }))
            else:
                presentation_entries.append(("WARNING", items[0]))
        for severity, item in presentation_entries:
            gate_rows.append([
                _p(severity, styles["micro"]), _p(item.get("code"), styles["micro"]),
                _p(item.get("message") or item.get("detail"), styles["micro"]),
                _p(item.get("detail"), styles["micro"]),
            ])
        gate_table = Table(gate_rows, colWidths=grid_widths([2, 3, 5, 2]), repeatRows=1, hAlign="LEFT")
        gate_table.setStyle(table_style(compact=True))
        story.append(gate_table)
    story.extend([Spacer(1, 4 * mm), Paragraph("FÓRMULAS E PREMISSAS", styles["h2"])])
    score_breakdown = narrative.get("score_breakdown") or "INSUFFICIENT_DATA"
    story.extend([
        callout("Thesis score e score final", score_breakdown, "neutral"),
        Spacer(1, 3 * mm),
    ])
    formula_rows = [["Objeto", "Fórmula / método", "Premissas e origem"], [
        f"Valuation {_valuation_method_label(valuation.get('method'))}",
        _safe_text(valuation.get("formula")),
        _safe_text((valuation.get("assumptions") or {}).get("assumption_source")),
    ], [
        "Confiança geral do research",
        "25% financeiro + 20% proveniência + 20% cobertura + 20% valuation + 15% evidência qualitativa",
        "Checks determinísticos de disponibilidade; não altera o thesis score",
    ], [
        "Expectativa implícita por P/L",
        _safe_text((report_data.get("implicit_expectations") or {}).get("formula") or "INSUFFICIENT_DATA"),
        "Preço, EPS TTM e mediana dos peers elegíveis",
    ]]
    formula_table_data = [
        [_p(cell, styles["table_header"] if row_index == 0 else styles["micro"]) for cell in row]
        for row_index, row in enumerate(formula_rows)
    ]
    formula_table = Table(formula_table_data, colWidths=grid_widths([3, 5, 4]), repeatRows=1, hAlign="LEFT")
    formula_table.setStyle(table_style(compact=True))
    story.extend([
        formula_table, Spacer(1, 4 * mm),
        Paragraph("METODOLOGIA E LIMITAÇÕES", styles["h2"]),
        Paragraph(
            "Hierarquia de fontes: documentos regulatórios e relações com investidores são primários; provedores de mercado são secundários. "
            "TTM, comparáveis e valuation só são publicados quando o gate aceita períodos, disponibilidade, unidades, fórmulas e rastreabilidade. "
            "INSUFFICIENT_DATA é mantido quando a evidência não suporta uma conclusão.",
            styles["body"],
        ),
        callout("Limitações", "Este relatório não comprova qualidade de gestão, moat, recorrência, consenso de mercado ou retorno futuro quando as fontes disponíveis não o fazem. Backtests, aconselhamento personalizado e execução de operações estão fora do escopo.", "warning"),
        Spacer(1, 4 * mm),
        Paragraph("AVISO", styles["h2"]),
        Paragraph("Documento informativo e educacional. Não constitui recomendação individualizada, oferta, promessa de rentabilidade, garantia de resultado ou solicitação de compra ou venda de valores mobiliários.", styles["small"]),
        PageBreak(),
    ])

    # Full source registry.
    story.extend(section_heading("Fontes e disponibilidade", "09 · registro integral"))
    story.append(Paragraph("Registro integral das métricas utilizadas, com unidade, período, data de disponibilidade e origem. Links são mantidos como trilha de auditoria.", styles["small"]))
    sources = (report_data.get("research") or {}).get("sources") or []
    source_groups = {
        "official_disclosure": "documentos oficiais catalogados por metadado",
        "news_report": "notícias catalogadas",
        "news_sentiment_interpretation": "cálculos de sentimento de notícias",
    }
    hidden_source_counts: dict[str, int] = {metric: 0 for metric in source_groups}
    source_rows: list[list[Any]] = [[
        _p("Métrica", styles["table_header"]), _p("Valor / unidade", styles["table_header"]),
        _p("Período", styles["table_header"]), _p("Disponibilidade", styles["table_header"]), _p("Fonte", styles["table_header"]),
    ]]
    for source in sources:
        metric = str(source.get("metric") or "")
        if metric in hidden_source_counts:
            hidden_source_counts[metric] += 1
            continue
        value = _format_source_value(source)
        source_name = html.escape(_safe_text(source.get("source")))
        source_url = source.get("source_url")
        if source_url:
            source_name += f'<br/><link href="{html.escape(str(source_url), quote=True)}">abrir fonte</link>'
        source_rows.append([
            _p(_metric_label(source.get("metric")), styles["micro"]),
            _p(value, styles["micro"]),
            _p(source.get("period"), styles["micro"]),
            _p(_fmt_date_time(source.get("publication_date")), styles["micro"]),
            _p(source_name, styles["micro"], trusted_markup=True),
        ])
    if len(source_rows) > 1:
        source_table = Table(source_rows, colWidths=grid_widths([2, 2, 2, 2, 4]), repeatRows=1, hAlign="LEFT")
        source_table.setStyle(table_style(compact=True))
        story.append(source_table)
    else:
        story.append(callout("Fontes", "INSUFFICIENT_DATA - nenhuma fonte rastreável foi fornecida.", "warning"))
    source_summary = [
        f"{count} {source_groups[metric]}" for metric, count in hidden_source_counts.items() if count
    ]
    if source_summary:
        story.extend([
            Spacer(1, 3 * mm),
            callout("Fontes agregadas", "; ".join(source_summary) + ". Lista completa disponível no export JSON.", "neutral"),
        ])
    story.append(PageBreak())

    # Full claim registry.
    story.extend(section_heading("Registro de afirmações", "10 · fatos, cálculos e julgamentos"))
    claims = report_data.get("claims") or []
    counts: dict[str, int] = {}
    for claim in claims:
        classification = _safe_text(claim.get("classification"))
        counts[classification] = counts.get(classification, 0) + 1
    count_text = " · ".join(f"{key}: {value}" for key, value in sorted(counts.items())) or "INSUFFICIENT_DATA"
    story.extend([
        callout("Classificação", f"{len(claims)} afirmações registradas. {count_text}.", "neutral"),
        Spacer(1, 4 * mm),
    ])
    news_scores: list[float] = []
    display_claims: list[Dict[str, Any]] = []
    hidden_disclosures = 0
    for claim in claims:
        text = str(claim.get("text") or "")
        classification = str(claim.get("classification") or "")
        if classification == "FACT" and text.startswith("official_disclosure no período"):
            hidden_disclosures += 1
            continue
        if (classification == "FACT" and " publicou a manchete:" in text) or (
            classification == "CALCULATION" and text.startswith("Sentimento lexical da manchete")
        ):
            if classification == "CALCULATION":
                match = re.search(r":\s*(-?\d+(?:\.\d+)?)/100", text)
                if match:
                    news_scores.append(float(match.group(1)))
            continue
        display_claims.append(claim)
    if news_scores:
        distribution = (
            f"≤40: {sum(score <= 40 for score in news_scores)}; "
            f"41-59: {sum(40 < score < 60 for score in news_scores)}; "
            f"≥60: {sum(score >= 60 for score in news_scores)}"
        )
        story.extend([
            callout(
                "Notícias agregadas",
                f"{len(news_scores)} manchetes analisadas; sentimento médio {statistics.mean(news_scores):.1f}/100, "
                f"mínimo {min(news_scores):.1f}, máximo {max(news_scores):.1f}. Distribuição: {distribution}. "
                "Claims individuais permanecem no export JSON.",
                "neutral",
            ), Spacer(1, 3 * mm),
        ])
    if hidden_disclosures:
        story.extend([
            callout("Disclosures agregados", f"{hidden_disclosures} claims de documentos oficiais não são repetidos aqui; ver seção Documentos Oficiais Recentes e export JSON.", "neutral"),
            Spacer(1, 3 * mm),
        ])
    claim_rows: list[list[Any]] = [[
        _p("ID", styles["table_header"]), _p("Classe", styles["table_header"]), _p("Seção / afirmação", styles["table_header"]),
        _p("Fonte(s)", styles["table_header"]), _p("Status", styles["table_header"]),
    ]]
    for claim_index, claim in enumerate(display_claims, start=1):
        claim_rows.append([
            _p(f"C{claim_index:02d} · {_safe_text(claim.get('claim_id'))}", styles["micro"]),
            _p(claim.get("classification"), styles["micro"]),
            _p(f"{_safe_text(claim.get('section'))} - {_safe_text(claim.get('text'))}", styles["micro"]),
            _p(_compact_source_ids(claim.get("source_ids") or []), styles["micro"]),
            _p("verificado" if claim.get("verified") else "não verificado", styles["micro"]),
        ])
    if len(claim_rows) > 1:
        claim_table = Table(claim_rows, colWidths=grid_widths([2, 2, 5, 2, 1]), repeatRows=1, hAlign="LEFT")
        claim_table.setStyle(table_style(compact=True))
        story.append(claim_table)
    else:
        story.append(callout("Claims", "INSUFFICIENT_DATA - nenhuma afirmação verificável foi liberada.", "warning"))
    return story


def _build_pdf(
    report_data: Dict[str, Any], narrative: Dict[str, str], output_path: Path,
    chart_artifacts: list[tuple[str, Path]], audit_identity: Optional[Dict[str, Any]] = None,
) -> None:
    audit_identity = audit_identity or {}
    doc = _ResearchDocTemplate(
        str(output_path), pagesize=PAGE_SIZE,
        rightMargin=MARGIN_X, leftMargin=MARGIN_X,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title=f"PROMETHEUS Equity Research | {_safe_text(report_data.get('ticker'))}",
        author="PROMETHEUS Research",
    )
    story = _compose_premium_story(report_data, narrative, chart_artifacts, audit_identity)
    doc.build(story, canvasmaker=_footer_canvas_class(report_data))
    return

@lru_cache(maxsize=32)
def _cached_company_snapshot(ticker: str) -> Dict[str, Any]:
    engine = PrometheusEngine()
    return engine.evaluate(ticker, sentiment_score=50.0, news_items=[], journal_metadata={"source": "reporting"})["report"]


def _canonical_snapshot_hash(report_data: Dict[str, Any]) -> str:
    payload = json.dumps(report_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cognitive_audit_identity(report_data: Dict[str, Any], report_snapshot_sha256: str) -> Dict[str, Any]:
    event = report_data.get("journal_event") if isinstance(report_data.get("journal_event"), dict) else {}
    return {
        "research_case_id": event.get("research_case_id") or report_data.get("research_case_id"),
        "occurred_at": event.get("occurred_at") or report_data.get("occurred_at"),
        "recorded_at": event.get("recorded_at") or report_data.get("recorded_at"),
        "event_hash": event.get("event_hash") or report_data.get("event_hash"),
        "snapshot_hash": event.get("snapshot_hash") or report_data.get("snapshot_hash"),
        "report_snapshot_sha256": report_snapshot_sha256,
    }


def _write_report_manifest(
    report_path: Path, report_data: Dict[str, Any], gate: Dict[str, Any],
    audit_identity: Dict[str, Any], generated_at: str,
) -> tuple[Path, str]:
    pdf_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest_path = report_path.with_suffix(".manifest.json")
    manifest = {
        "schema_version": 1,
        "artifact_type": "prometheus_equity_research_pdf",
        "generator_version": "2.1.0rc2",
        "ticker": _safe_text(report_data.get("ticker")),
        "company_name": _safe_text(report_data.get("company_name")),
        "analysis_as_of": report_data.get("analysis_as_of"),
        "generated_at": generated_at,
        "editorial": {
            "status": gate.get("status"),
            "deliverable": bool(gate.get("deliverable")),
            "approved_by": gate.get("approved_by") if gate.get("deliverable") else None,
            "approved_at": gate.get("approved_at") if gate.get("deliverable") else None,
        },
        "cognitive_identity": {
            "research_case_id": audit_identity.get("research_case_id"),
            "occurred_at": audit_identity.get("occurred_at"),
            "recorded_at": audit_identity.get("recorded_at"),
            "event_hash": audit_identity.get("event_hash"),
            "snapshot_hash": audit_identity.get("snapshot_hash"),
            "availability": "AVAILABLE" if audit_identity.get("research_case_id") and audit_identity.get("event_hash") else "INSUFFICIENT_DATA",
        },
        "report_snapshot_sha256": audit_identity["report_snapshot_sha256"],
        "artifacts": [{
            "role": "client_pdf",
            "path": report_path.name,
            "sha256": pdf_sha256,
            "size": report_path.stat().st_size,
        }],
        "notes": [
            "The PDF SHA-256 is stored externally to avoid circular self-identification.",
            "A missing cognitive identity is reported as INSUFFICIENT_DATA and is not inferred from legacy timestamps.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, pdf_sha256


def _write_audit_export(
    output_root: Path,
    ticker: str,
    timestamp: str,
    report_data: Dict[str, Any],
    report_snapshot_sha256: str,
) -> Dict[str, str]:
    """Write the complete, machine-readable audit ledger without changing the snapshot."""
    export_path = output_root / f"{ticker}_prometheus_audit_ledger_{timestamp}.json"
    payload = {
        "schema_version": 1,
        "ticker": ticker,
        "analysis_as_of": report_data.get("analysis_as_of"),
        "report_snapshot_sha256": report_snapshot_sha256,
        "claims": report_data.get("claims") or [],
        "sources": ((report_data.get("research") or {}).get("sources") or []),
        "editorial_gate": {
            "status": (report_data.get("editorial_gate") or {}).get("status"),
            "deliverable": bool((report_data.get("editorial_gate") or {}).get("deliverable")),
            "blockers": (report_data.get("editorial_gate") or {}).get("blockers") or [],
            "warnings": (report_data.get("editorial_gate") or {}).get("warnings") or [],
            "claim_audit": (report_data.get("editorial_gate") or {}).get("claim_audit") or {},
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    export_path.write_bytes(encoded + b"\n")
    return {"path": str(export_path), "filename": export_path.name, "sha256": hashlib.sha256(encoded + b"\n").hexdigest()}


def _build_executive_report(appendix_path: Path, report_path: Path, max_pages: int = 12) -> None:
    """Create the client-facing PDF from the first pages of the same audit snapshot."""
    reader = PdfReader(str(appendix_path))
    writer = PdfWriter()
    for page in reader.pages[:max_pages]:
        writer.add_page(page)
    with report_path.open("wb") as handle:
        writer.write(handle)


def generate_report(
    ticker: str,
    output_dir: str = "output",
    report_data: Optional[Dict[str, Any]] = None,
    reviewer: Optional[str] = None,
    approval_notes: str = "",
    conflict_declaration: str = "",
) -> Dict[str, Any]:
    normalized = validate_ticker(ticker).upper()
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    analysis_date = _safe_text((report_data or {}).get("analysis_as_of"))[:10].replace("-", "")
    timestamp = analysis_date if len(analysis_date) == 8 and analysis_date.isdigit() else dt.datetime.utcnow().strftime("%Y%m%d")
    report_path = output_root / f"{normalized}_prometheus_report_{timestamp}.pdf"
    appendix_path = output_root / f"{normalized}_prometheus_audit_appendix_{timestamp}.pdf"
    executive_path = output_root / f"{normalized}_prometheus_research_report_{timestamp}.pdf"

    # Reuse the exact evaluated snapshot when supplied. This prevents a PDF from
    # silently re-fetching different data than the JSON/CLI result shown to users.
    report_data = copy.deepcopy(report_data) if report_data is not None else copy.deepcopy(_cached_company_snapshot(normalized))
    # The export location/hash is publication metadata, not analytical evidence.
    # Do not let a previous render contaminate the canonical snapshot on re-render.
    report_data.pop("audit_export", None)
    # Recompute presentation-facing synthesis from the exact supplied snapshot.
    # This upgrades saved legacy bundles without re-fetching or mutating analytics.
    # BusinessQualityEngine records claim timestamps. Reuse the evaluated
    # snapshot when it already contains this section so PDF re-renders remain
    # byte-for-byte equivalent at the report-snapshot layer.
    if not isinstance(report_data.get("business_quality"), dict):
        report_data["business_quality"] = BusinessQualityEngine().evaluate(report_data)
    report_data["research_quality"] = calculate_research_quality(report_data)
    report_data["implicit_expectations"] = _build_implicit_expectations_data(report_data)
    availability = dict(report_data.get("score_availability") or {})
    unavailable = set(availability.get("unavailable_components") or [])
    component_status = dict(availability.get("component_status") or {})
    # Legacy snapshots may carry the neutral sentinel 50.0 although the
    # current sector function returns None. Normalize that sentinel for
    # presentation/audit without changing any quantitative calculation.
    sector_value = (report_data.get("thesis_scores") or {}).get("sector")
    if sector_value is None or (sector_value == 50.0 and "sector" not in component_status):
        unavailable.add("sector")
        component_status.setdefault("sector", {
            "status": "SECTOR_SCORE_UNAVAILABLE",
            "reason": "Sem histórico point-in-time de margens e ROE dos pares suficiente para calcular o Sector Score.",
        })
    availability["unavailable_components"] = sorted(unavailable)
    availability["component_status"] = component_status
    report_data["score_availability"] = availability
    canonical_scores = _canonical_score_snapshot(report_data)
    report_data["score_availability"]["unavailable_components"] = canonical_scores["unavailable"]
    # Keep the displayed final score and all exports on the same canonical
    # calculation, including legacy snapshots with stale sentinel values.
    report_data["final_score"] = canonical_scores["final_score"]
    report_data["final_state"] = get_state(canonical_scores["final_score"])
    report_data["score_reconciliation"] = _score_reconciliation(report_data)
    score_metrics = {f"score_{key}" for key in canonical_scores["components"]}
    sources = (report_data.setdefault("research", {})).setdefault("sources", [])
    sources[:] = [s for s in sources if s.get("metric") not in score_metrics and s.get("metric") != "prometheus_final_score"]
    for key, value in canonical_scores["components"].items():
        if key in canonical_scores["unavailable"] or not isinstance(value, (int, float)):
            continue
        sources.append({"source_id": f"CANONICAL_SCORE_{key}", "metric": f"score_{key}", "value": float(value), "unit": "score_0_100", "period": str(report_data.get("analysis_as_of") or "")[:10], "publication_date": report_data.get("analysis_as_of"), "source": "PROMETHEUS canonical score snapshot", "source_type": "calculated", "confidence": "medium", "formula": "canonical thesis score snapshot"})
    sources.append({"source_id": "CANONICAL_SCORE_FINAL", "metric": "prometheus_final_score", "value": canonical_scores["final_score"], "unit": "score_0_100", "period": str(report_data.get("analysis_as_of") or "")[:10], "publication_date": report_data.get("analysis_as_of"), "source": "PROMETHEUS canonical score snapshot", "source_type": "calculated", "confidence": "medium", "formula": "0.60*weighted_thesis + 0.15*expectation_gap + 0.10*catalyst + 0.08*regime_confidence + 0.07*pricing_confidence"})
    report_data["score_reconciliation"] = _score_reconciliation(report_data)
    classification = dict(report_data.get("official_classification") or {})
    if not classification.get("cnpj"):
        disclosure_cnpj = next(
            (item.get("cnpj") for item in ((report_data.get("official_disclosures") or {}).get("documents") or []) if item.get("cnpj")),
            None,
        )
        if disclosure_cnpj:
            classification["cnpj"] = disclosure_cnpj
            report_data["official_classification"] = classification
    unavailable = set((report_data.get("score_availability") or {}).get("unavailable_components") or [])
    if unavailable and report_data.get("claims"):
        report_data["claims"] = [
            claim for claim in report_data["claims"]
            if not any(
                claim.get("metric") == f"score_{component}"
                or str(claim.get("text") or "").startswith(f"score_{component} ")
                for component in unavailable
            )
        ]
    report_data["claims"] = [c for c in (report_data.get("claims") or []) if not str(c.get("metric") or "").startswith("score_") and not str(c.get("text") or "").startswith(("score_", "prometheus_final_score")) and c.get("metric") != "prometheus_final_score"]
    for source in sources:
        if source.get("metric", "").startswith("score_") or source.get("metric") == "prometheus_final_score":
            report_data["claims"].append({"claim_id": f"CANONICAL-{source['metric']}", "section": "fundamentals", "text": f"{source['metric']}: {source['value']}", "classification": "CALCULATION", "value": source["value"], "unit": source["unit"], "source_ids": [source["source_id"]], "confidence": "medium", "formula": source.get("formula"), "assumptions": ["Score descritivo, não recomendação."], "verified": True})
    report_data["qa"] = _build_quality_assessment(report_data)
    # Generated prose is evidence-bearing publication content. Build it before
    # the gate so identity/sector leakage cannot be hidden by a valid data
    # snapshot or discovered only after the PDF has been written.
    narrative = _build_narrative(report_data)
    report_data["rendered_narratives"] = {"central_thesis": narrative["central_thesis"]}
    gate = EditorialGate().evaluate(report_data)
    if reviewer and not gate.get("blockers"):
        gate = EditorialGate().approve(
            gate,
            reviewer=reviewer,
            notes=approval_notes,
            conflict_declaration=conflict_declaration,
        )
    report_data["editorial_gate"] = gate
    report_snapshot_sha256 = _canonical_snapshot_hash(report_data)
    audit_identity = _cognitive_audit_identity(report_data, report_snapshot_sha256)
    report_data["audit_export"] = _write_audit_export(
        output_root, normalized, timestamp, report_data, report_snapshot_sha256,
    )
    chart_artifacts = _build_chart_artifacts(normalized, report_data, output_root)
    _build_pdf(report_data, narrative, appendix_path, chart_artifacts, audit_identity=audit_identity)
    shutil.copyfile(appendix_path, report_path)
    _build_executive_report(appendix_path, executive_path)
    generated_at = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_path, pdf_sha256 = _write_report_manifest(
        report_path, report_data, gate, audit_identity, generated_at,
    )

    metadata = {
        "ticker": normalized,
        "company_name": _safe_text(report_data.get("company_name")),
        "report_path": str(report_path),
        "audit_appendix_path": str(appendix_path),
        "research_report_path": str(executive_path),
        "generated_at": generated_at,
        "thesis_score": report_data.get("final_score"),
        "state": _safe_text(report_data.get("final_state")),
        "data_quality_score": report_data.get("fundamental_data_quality", {}).get("score"),
        "overall_research_confidence": (report_data.get("research_quality") or {}).get("overall_research_confidence"),
        "price_reference": report_data.get("price"),
        "chart_artifacts": [str(path) for _, path in chart_artifacts],
        "chart_count": len(chart_artifacts),
        "qa_status": report_data["qa"]["status"],
        "editorial_status": gate["status"],
        "deliverable": gate["deliverable"],
        "manifest_path": str(manifest_path),
        "pdf_sha256": pdf_sha256,
        "report_snapshot_sha256": report_snapshot_sha256,
        "audit_export_path": report_data["audit_export"]["path"],
    }
    return {
        "metadata": metadata,
        "report": report_data,
        "narrative": narrative,
        "chart_artifacts": [str(path) for _, path in chart_artifacts],
        "qa": report_data["qa"],
    }


def generate_reports(tickers: list[str], output_dir: str = "output") -> Dict[str, Dict[str, Any]]:
    return {ticker: generate_report(ticker, output_dir=output_dir) for ticker in tickers}
