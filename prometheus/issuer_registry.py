"""Validated B3 ticker to CVM issuer identities.

Codes were checked against CVM's daily ``cad_cia_aberta.csv`` registry. Keep
this mapping small and explicit; silently guessing issuer identity is unsafe.
"""

DEFAULT_CVM_CODES = {
    "CURY3": "25100",
    "ITUB3": "19348",
    "ITUB4": "19348",
    "PETR3": "9512",
    "PETR4": "9512",
    "VALE3": "4170",
    "WEGE3": "5410",
}

try:
    from prometheus.peer_universe import cvm_codes as _peer_cvm_codes
    DEFAULT_CVM_CODES.update(_peer_cvm_codes())
except Exception:
    pass

CVM_REGISTRY_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
CVM_REGISTRY_VERIFIED_AT = "2026-08-16"
