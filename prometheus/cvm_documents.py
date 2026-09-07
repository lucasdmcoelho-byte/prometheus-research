from __future__ import annotations

import csv
import hashlib
import io
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class CVMReferenceFormClient:
    """Point-in-time reader for structured CVM Formulário de Referência data.

    Personally identifying fields such as CPF and birth date are intentionally
    discarded; the report only needs professional governance information.
    """

    BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{year}.zip"
    DATASETS = {
        "management": "administrador_membro_conselho_fiscal",
        "capital": "capital_social",
        "ownership_distribution": "distribuicao_capital",
        "related_parties": "transacao_parte_relacionada",
        "auditors": "auditor",
        "shareholders": "posicao_acionaria",
    }
    SAFE_FIELDS = {
        "management": ("Orgao_Administracao", "Nome", "Profissao", "Cargo_Eletivo_Ocupado", "Complemento_Cargo_Eletivo_Ocupado", "Data_Eleicao", "Data_Posse", "Prazo_Mandato", "Eleito_Controlador", "Outro_Cargo_Funcao", "Experiencia_Profissional", "Numero_Mandatos_Consecutivos", "Percentual_Participacao_Reunioes"),
        "capital": ("Tipo_Capital", "Data_Autorizacao_Aprovacao", "Valor_Capital", "Quantidade_Acoes_Ordinarias", "Quantidade_Acoes_Preferenciais", "Quantidade_Total_Acoes"),
        "ownership_distribution": ("Quantidade_Acionistas_PF", "Quantidade_Acionistas_PJ", "Quantidade_Acionistas_Investidores_Institucionais", "Quantidade_Total_Acoes_Circulacao", "Percentual_Total_Acoes_Circulacao", "Data_Ultima_Assembleia"),
        "related_parties": ("Parte_Relacionada", "Tipo_Pessoa", "Relacao_Emissor", "Data_Transacao", "Objeto_Contrato", "Montante_Envolvido", "Saldo_Existente", "Natureza_Razao_Operacao", "Taxa_Juros", "Posicao_Contratual_Emissor"),
        "auditors": ("Auditor", "Data_Inicio_Atuacao", "Data_Fim_Atuacao", "Responsavel_Tecnico"),
        "shareholders": ("Acionista", "Tipo_Pessoa", "Nacionalidade", "Quantidade_Acoes_Ordinarias", "Quantidade_Acoes_Preferenciais", "Percentual_Total_Acoes"),
    }

    def __init__(self, cache_dir: Optional[str] = None, timeout_seconds: float = 30.0, cache_ttl_seconds: float = 86_400.0):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds

    def load_company(self, cvm_code: str, as_of: datetime, years: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        candidates: List[Dict[str, Any]] = []
        requested = list(years or range(max(2018, as_of.year - 2), as_of.year + 1))
        archives: Dict[int, bytes] = {}
        for year in requested:
            try:
                archive = self._download(year)
            except Exception:
                continue
            archives[year] = archive
            candidates.extend(self._metadata(archive, year, cvm_code, as_of))
        if not candidates:
            return {"status": "INSUFFICIENT_DATA", "sections": {}, "limitations": ["Nenhum FRE disponível até a data de corte."]}
        chosen = max(candidates, key=lambda item: (item["received_at"], int(item["version"] or 0)))
        archive = archives[chosen["dataset_year"]]
        sections = {
            section: self._section_rows(archive, chosen["dataset_year"], suffix, chosen)
            for section, suffix in self.DATASETS.items()
        }
        return {
            "status": "AVAILABLE",
            "company_name": chosen["company_name"],
            "reference_date": chosen["reference_date"],
            "received_at": chosen["received_at"].isoformat(),
            "version": chosen["version"],
            "document_id": chosen["document_id"],
            "source_url": chosen["source_url"],
            "source_dataset": self.BASE_URL.format(year=chosen["dataset_year"]),
            "source_sha256": hashlib.sha256(archive).hexdigest(),
            "sections": sections,
            "privacy": "CPF, data de nascimento e outros identificadores pessoais foram descartados.",
            "limitations": ["O conjunto aberto estruturado do FRE não contém todas as narrativas do documento integral."],
        }

    def _download(self, year: int) -> bytes:
        url = self.BASE_URL.format(year=year)
        cache_path = self.cache_dir / f"fre_cia_aberta_{year}.zip" if self.cache_dir else None
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if cache_path.exists() and time.time() - cache_path.stat().st_mtime <= self.cache_ttl_seconds:
                return cache_path.read_bytes()
        request = urllib.request.Request(url, headers={"User-Agent": "PROMETHEUS/1.0 research@example.invalid"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read()
        if cache_path:
            cache_path.write_bytes(payload)
        return payload

    def _metadata(self, archive: bytes, year: int, cvm_code: str, as_of: datetime) -> List[Dict[str, Any]]:
        filename = f"fre_cia_aberta_{year}.csv"
        rows = self._csv_rows(archive, filename)
        output = []
        for row in rows:
            if str(row.get("CD_CVM", "")).strip().lstrip("0") != str(cvm_code).strip().lstrip("0"):
                continue
            received = self._date(row.get("DT_RECEB"))
            if not received or received > as_of.replace(tzinfo=None):
                continue
            output.append({
                "company_name": row.get("DENOM_CIA"), "reference_date": row.get("DT_REFER"),
                "received_at": received, "version": row.get("VERSAO"), "document_id": row.get("ID_DOC"),
                "source_url": row.get("LINK_DOC"), "dataset_year": year,
            })
        return output

    def _section_rows(self, archive: bytes, year: int, suffix: str, chosen: Dict[str, Any]) -> List[Dict[str, Any]]:
        name = f"fre_cia_aberta_{suffix}_{year}.csv"
        allowed = self.SAFE_FIELDS[next(key for key, value in self.DATASETS.items() if value == suffix)]
        rows = []
        for raw in self._csv_rows(archive, name):
            if str(raw.get("ID_Documento", "")) != str(chosen["document_id"]):
                continue
            if str(raw.get("Versao", "")) != str(chosen["version"]):
                continue
            cleaned = {key: self._clean(raw.get(key)) for key in allowed if raw.get(key) not in (None, "")}
            if cleaned:
                rows.append(cleaned)
        return rows

    @staticmethod
    def _csv_rows(archive: bytes, filename: str) -> List[Dict[str, str]]:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            try:
                payload = zipped.read(filename)
            except KeyError:
                return []
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = payload.decode("latin-1")
        return list(csv.DictReader(io.StringIO(text), delimiter=";"))

    @staticmethod
    def _date(value: Any) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value).replace("\x07", " ").split())
