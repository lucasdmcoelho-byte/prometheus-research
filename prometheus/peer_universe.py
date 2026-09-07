from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PeerIdentity:
    ticker: str
    cvm_code: str
    sector_key: str
    company: str


# Explicit identities prevent unsafe company-name guessing. CVM codes are from
# cad_cia_aberta.csv; sector assignment is a maintained research decision.
PEERS = (
    PeerIdentity("CURY3", "25100", "real_estate", "Cury"),
    PeerIdentity("DIRR3", "21350", "real_estate", "Direcional"),
    PeerIdentity("MRVE3", "20915", "real_estate", "MRV"),
    PeerIdentity("TEND3", "21148", "real_estate", "Tenda"),
    PeerIdentity("CYRE3", "14460", "real_estate", "Cyrela"),
    PeerIdentity("LAVV3", "25062", "real_estate", "Lavvi"),
    PeerIdentity("PLPL3", "25070", "real_estate", "Plano & Plano"),
    PeerIdentity("MTRE3", "24902", "real_estate", "Mitre"),
    PeerIdentity("ITUB4", "19348", "financial", "Itaú Unibanco"),
    PeerIdentity("BBAS3", "1023", "financial", "Banco do Brasil"),
    PeerIdentity("BBDC4", "906", "financial", "Bradesco"),
    PeerIdentity("SANB11", "20532", "financial", "Santander Brasil"),
    PeerIdentity("PETR4", "9512", "oil_gas", "Petrobras"),
    PeerIdentity("PRIO3", "22187", "oil_gas", "PRIO"),
    PeerIdentity("RECV3", "25780", "oil_gas", "PetroReconcavo"),
    PeerIdentity("VALE3", "4170", "mining", "Vale"),
    PeerIdentity("CMIN3", "25585", "mining", "CSN Mineração"),
    PeerIdentity("CSNA3", "4030", "mining", "CSN"),
    PeerIdentity("GGBR4", "3980", "mining", "Gerdau"),
    PeerIdentity("WEGE3", "5410", "industrial", "WEG"),
    PeerIdentity("TUPY3", "6343", "industrial", "Tupy"),
    PeerIdentity("ROMI3", "7510", "industrial", "Indústrias Romi"),
    # Healthcare fallback universe. Dynamic selection still requires the exact
    # point-in-time FCA activity; this list only prevents a network/catalogue
    # outage from silently collapsing the maintained universe to one issuer.
    PeerIdentity("HAPV3", "24392", "healthcare", "Hapvida"),
    PeerIdentity("RDOR3", "24821", "healthcare", "Rede D'Or"),
    PeerIdentity("DASA3", "19623", "healthcare", "Dasa"),
    PeerIdentity("FLRY3", "21881", "healthcare", "Fleury"),
    PeerIdentity("ONCO3", "26123", "healthcare", "Oncoclínicas"),
    PeerIdentity("MATD3", "25690", "healthcare", "Mater Dei"),
    PeerIdentity("SAUD3", "20125", "healthcare", "Bradesaúde"),
)


def peers_for(ticker: str, sector_key: str, limit: int = 6) -> List[PeerIdentity]:
    normalized = ticker.upper()
    return [item for item in PEERS if item.sector_key == sector_key and item.ticker != normalized][:limit]


def cvm_codes() -> Dict[str, str]:
    return {item.ticker: item.cvm_code for item in PEERS}


def identity_for(ticker: str) -> Optional[PeerIdentity]:
    normalized = ticker.upper()
    return next((item for item in PEERS if item.ticker == normalized), None)


def benchmark_for_ticker(ticker: str) -> Optional[str]:
    identity = identity_for(ticker)
    if not identity:
        return None
    from prometheus.sector_models import MODELS
    model = next((item for item in MODELS if item.key == identity.sector_key), None)
    return model.benchmark if model else None
