from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SectorModel:
    key: str
    label: str
    aliases: tuple[str, ...]
    benchmark: Optional[str]
    kpis: tuple[str, ...]
    drivers: tuple[str, ...]
    risks: tuple[str, ...]
    macro_series: tuple[str, ...]
    valuation_methods: tuple[str, ...]


MODELS = (
    SectorModel("healthcare", "Saúde, farmacêuticas e biotecnologia", ("healthcare", "health care", "pharmaceutical", "biotech", "medical", "hospital", "serviços médicos", "servicos medicos", "farmacêutico", "farmaceutico"), None, ("beneficiários saúde", "beneficiários odonto", "ticket médio mensal saúde", "sinistralidade caixa", "churn", "cancelamentos", "rede própria", "rede credenciada", "leitos totais", "taxa média ocupação leitos", "pacientes-dia", "procedimentos cirúrgicos", "hospitais operados", "beneficiários saúde e odonto", "sinistralidade consolidada"), ("demografia", "acesso", "inovação", "expansão de capacidade"), ("validade clínica", "aprovação regulatória", "pagadores e reembolso", "concorrência", "execução operacional"), ("selic_target", "ipca", "employment"), ("DCF", "EV/EBITDA", "P/L", "rNPV")),
    SectorModel("real_estate", "Construção e incorporação", ("real estate", "construction", "homebuilding", "construção civil", "construcao civil", "const. civil"), "XFIX11", ("lançamentos", "vendas brutas", "vendas líquidas", "VSO", "distratos", "unidades lançadas", "unidades vendidas", "ticket médio", "unidades entregues", "margem bruta ajustada", "margem REF", "receita a apropriar", "landbank", "geração de caixa", "repasses", "estoque pronto", "estoque em construção", "participação no MCMV"), ("crédito imobiliário", "renda", "velocidade de vendas", "execução de obras"), ("juros", "distratos", "atrasos", "custos de construção"), ("selic_target", "ipca", "employment"), ("P/L", "P/VP", "DCF")),
    SectorModel("financial", "Bancos e serviços financeiros", ("financial", "bank", "insurance", "bancos", "intermediação financeira", "intermediacao financeira", "seguradoras", "securitização", "securitizacao", "crédito imobiliário", "credito imobiliario"), "FIND11", ("NIM", "inadimplência", "cobertura", "custo de crédito", "carteira", "Basileia", "eficiência"), ("spread", "crescimento de crédito", "captação", "serviços"), ("inadimplência", "pressão de spread", "liquidez", "risco regulatório"), ("selic_target", "credit_growth", "delinquency"), ("P/VP", "P/L", "dividend discount")),
    SectorModel("mining", "Mineração", ("mining", "metals", "extração mineral", "extracao mineral"), "MATB11", ("produção", "preço realizado", "cash cost", "teor", "frete", "capex"), ("preço da commodity", "China", "volume", "câmbio"), ("commodity", "licença", "barragens", "logística"), ("usd_brl", "iron_ore", "china_activity"), ("EV/EBIT", "EV/EBITDA", "DCF", "NAV")),
    SectorModel("oil_gas", "Petróleo e gás", ("oil", "gas", "energy", "petróleo", "petroleo", "gás natural", "gas natural"), "ENRG11", ("produção", "lifting cost", "reservas", "utilização de refino", "capex"), ("Brent", "produção", "câmbio", "refino"), ("Brent", "interferência regulatória", "execução de capex", "reservas"), ("usd_brl", "brent"), ("EV/EBIT", "EV/EBITDA", "DCF", "NAV")),
    SectorModel("retail", "Varejo e consumo", ("retail", "consumer cyclical", "consumer defensive", "comércio", "comercio", "têxtil", "textil", "brinquedos", "hospedagem", "bebidas e fumo"), "XFIX11", ("vendas mesmas lojas", "ticket", "volume", "estoques", "margem bruta", "ciclo de caixa"), ("renda", "tráfego", "mix", "digital"), ("estoque", "competição", "juros", "queda de demanda"), ("selic_target", "ipca", "employment"), ("P/L", "EV/EBITDA", "DCF")),
    SectorModel("utilities", "Utilities e infraestrutura", ("utilities", "electric", "water", "infrastructure", "energia elétrica", "energia eletrica", "saneamento", "água e gás", "agua e gas"), "UTIL11", ("RAP", "geração", "capacidade", "tarifa", "perdas", "alavancagem regulatória"), ("reajustes", "demanda", "expansão", "eficiência"), ("regulação", "hidrologia", "capex", "juros"), ("selic_target", "ipca"), ("EV/EBIT", "dividend discount", "EV/EBITDA", "DCF")),
    SectorModel("transport_logistics", "Transporte e logística", ("transport", "logistics", "transporte e logística", "transporte e logistica"), "BOVA11", ("volume transportado", "yield", "ocupação", "tarifa", "custo por unidade", "capex", "concessões"), ("atividade econômica", "comércio exterior", "combustível", "infraestrutura"), ("combustível", "concessões", "capacidade", "execução de capex"), ("usd_brl", "ipca", "industrial_activity"), ("EV/EBIT", "EV/EBITDA", "DCF", "P/L")),
    SectorModel("telecom", "Telecomunicações", ("telecom", "telecomunicações", "telecomunicacoes"), "BOVA11", ("ARPU", "churn", "adições líquidas", "cobertura", "capex/receita", "margem EBITDA"), ("dados móveis", "fibra", "convergência", "monetização"), ("competição", "espectro", "regulação", "intensidade de capex"), ("ipca", "selic_target"), ("EV/EBITDA", "DCF", "P/L")),
    SectorModel("materials", "Materiais básicos", ("metalurgia", "siderurgia", "papel e celulose", "petroquímicos", "petroquimicos", "embalagens"), "MATB11", ("volume", "preço realizado", "spread", "cash cost", "utilização", "capex"), ("commodity", "câmbio", "demanda industrial", "disciplina de oferta"), ("commodity", "ciclo", "energia", "execução de capex"), ("usd_brl", "industrial_activity"), ("EV/EBIT", "EV/EBITDA", "DCF", "P/L")),
    SectorModel("agribusiness_food", "Agronegócio e alimentos", ("agricultura", "alimentos", "açúcar", "acucar", "cana"), "BOVA11", ("volume", "preço realizado", "rendimento", "custo por tonelada", "estoques", "capital de giro"), ("safra", "commodity", "câmbio", "demanda externa"), ("clima", "sanidade", "commodity", "logística"), ("usd_brl", "ipca"), ("EV/EBITDA", "DCF", "P/L")),
    SectorModel("education", "Educação", ("educação", "educacao"), "BOVA11", ("base de alunos", "ticket médio", "evasão", "captação", "ocupação", "CAC"), ("renda", "emprego", "financiamento estudantil", "ensino digital"), ("evasão", "regulação", "inadimplência", "competição"), ("employment", "ipca", "selic_target"), ("P/L", "EV/EBITDA", "DCF")),
    SectorModel("technology_media", "Tecnologia, mídia e comunicação", ("technology", "software", "informática", "informatica", "comunicação e informática", "comunicacao e informatica"), "BOVA11", ("receita recorrente", "ARR", "churn", "retenção líquida", "CAC", "LTV", "margem bruta"), ("digitalização", "inovação", "expansão de clientes", "monetização"), ("obsolescência", "competição", "cibersegurança", "retenção"), ("usd_brl", "selic_target"), ("EV/Receita", "EV/EBITDA", "DCF")),
    SectorModel("industrial", "Indústria", ("industrial", "industrials", "machinery", "máquinas", "maquinas", "equipamentos", "veículos e peças", "veiculos e pecas"), "INDX", ("carteira de pedidos", "utilização", "mix", "exportações", "margem", "retorno do capex"), ("atividade industrial", "pedidos", "eficiência", "câmbio"), ("ciclo", "custos", "execução", "competição"), ("usd_brl", "industrial_activity", "selic_target"), ("EV/EBIT", "EV/EBITDA", "P/L", "DCF")),
)

# Publication vocabulary is part of the sector contract.  Consumers such as the
# editorial gate must import this mapping rather than maintaining local lists.
SECTOR_SEMANTIC_TERMS: Dict[str, tuple[str, ...]] = {
    "real_estate": ("mcmv", "vso", "distratos", "landbank", "terrenos", "obras", "recebiveis", "repasses", "incorporacao", "incorporadora"),
    "healthcare": ("sinistralidade", "beneficiarios", "ans", "rede credenciada", "rede propria", "operadora de saude"),
    "financial": ("spread bancario", "inadimplencia bancaria", "banco comercial"),
    "oil_gas": ("barril de petroleo", "producao de oleo", "reservas provadas"),
    "utilities": ("tarifa de energia", "distribuicao de energia", "concessao eletrica"),
    "mining": ("teor de minerio", "cash cost", "barragem", "frete ferroviario"),
    "retail": ("vendas mesmas lojas", "sell out", "estoque de lojas", "trafego de lojas"),
    "transport_logistics": ("volume transportado", "yield de frete", "concessao rodoviaria", "custo por tonelada"),
    "telecom": ("arpu", "adicoes liquidas", "espectro", "fibra otica"),
    "materials": ("preco realizado", "spread de aco", "celulose", "capacidade instalada"),
    "agribusiness_food": ("safra", "rendimento agricola", "custo por tonelada", "sanidade animal"),
    "education": ("base de alunos", "evasao", "captacao de alunos", "fies"),
    "technology_media": ("receita recorrente", "arr", "retencao liquida", "custo de aquisicao"),
    "industrial": ("carteira de pedidos", "utilizacao de capacidade", "mix de exportacao", "maquinas industriais"),
}


def resolve_sector_model(sector: Optional[str], industry: Optional[str] = None) -> SectorModel:
    text = f"{sector or ''} {industry or ''}".lower()
    for model in MODELS:
        if any(alias in text for alias in model.aliases):
            return model
    return SectorModel("general", "Empresas em geral", (), "BOVA11", ("receita", "margem", "ROIC", "caixa", "alavancagem"), ("crescimento", "eficiência", "alocação de capital"), ("competição", "execução", "liquidez"), ("selic_target", "ipca", "usd_brl"), ("P/L", "EV/EBITDA", "DCF"))


def sector_catalog() -> List[Dict[str, object]]:
    return [model.__dict__.copy() for model in MODELS]
