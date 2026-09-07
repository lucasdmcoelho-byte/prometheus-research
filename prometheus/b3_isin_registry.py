from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class B3Issuer:
    code: str
    name: str
    cnpj: str
    registered_at: str


@dataclass(frozen=True)
class B3Isin:
    reference_date: str
    isin: str
    issuer_code: str
    cfi_code: str
    description: str
    asset_type: str
    category: str
    species: str
    status: str
    numbering_agency: str


@dataclass(frozen=True)
class B3IsinRegistry:
    source_sha256: str
    issuers: dict[str, B3Issuer]
    securities: dict[str, B3Isin]


def parse_isin_registry_zip(path: str | Path) -> B3IsinRegistry:
    source = Path(path)
    raw_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with zipfile.ZipFile(source) as archive:
        names = {name.upper(): name for name in archive.namelist()}
        if "EMISSOR.TXT" not in names or "NUMERACA.TXT" not in names:
            raise ValueError("B3 ISIN archive must contain EMISSOR.TXT and NUMERACA.TXT")
        issuers: dict[str, B3Issuer] = {}
        with archive.open(names["EMISSOR.TXT"]) as binary:
            for row in csv.reader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")):
                if len(row) < 4:
                    continue
                issuer = B3Issuer(row[0].strip(), row[1].strip(), "".join(c for c in row[2] if c.isdigit()), row[3].strip())
                if issuer.code and len(issuer.cnpj) == 14:
                    issuers[issuer.code] = issuer
        securities: dict[str, B3Isin] = {}
        with archive.open(names["NUMERACA.TXT"]) as binary:
            for row in csv.reader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")):
                if len(row) < 45:
                    continue
                record = B3Isin(
                    reference_date=row[0].strip(), isin=row[2].strip().upper(), issuer_code=row[3].strip(),
                    cfi_code=row[4].strip(), description=row[5].strip(), asset_type=row[20].strip(),
                    category=row[21].strip(), species=row[22].strip(), status=row[42].strip(),
                    numbering_agency=row[44].strip(),
                )
                if record.isin:
                    securities[record.isin] = record
    if not issuers or not securities:
        raise ValueError("B3 ISIN archive contains no usable records")
    return B3IsinRegistry(raw_hash, issuers, securities)
