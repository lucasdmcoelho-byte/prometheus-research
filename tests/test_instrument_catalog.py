import json

import pytest

from prometheus.instrument_catalog import InstrumentCatalog, InstrumentIdentity
from main import load_cvm_codes


def _instrument():
    return InstrumentIdentity("CURY3", "25100", "08797760000183", "CURY CONSTRUTORA E INCORPORADORA S.A.", "B3 reviewed file", "2026-08-16", "2026-08-16T00:00:00Z")


def test_catalog_round_trip_and_content_hash(tmp_path):
    path = tmp_path / "catalog.json"
    InstrumentCatalog([_instrument()], {"version": 1}).dump(path)
    loaded = InstrumentCatalog.load(path)
    assert loaded.mapping() == {"CURY3": "25100"}
    assert loaded.content_sha256()
    assert load_cvm_codes(None, str(path))["CURY3"] == "25100"


def test_catalog_mapping_excludes_non_primary_instrument_by_default():
    temporary = InstrumentIdentity("AALR12", "24058", "42771949000135", "ALLIANCA", "B3", "2026-08-14", "2026-08-16T00:00:00Z", research_eligible=False, eligibility_reason="TEMPORARY")
    catalog = InstrumentCatalog([_instrument(), temporary])
    assert catalog.mapping() == {"CURY3": "25100"}
    assert catalog.mapping(eligible_only=False)["AALR12"] == "24058"


def test_explicit_catalog_is_authoritative_and_does_not_merge_defaults(tmp_path):
    path = tmp_path / "catalog.json"
    InstrumentCatalog([_instrument()]).dump(path)
    assert load_cvm_codes(None, str(path)) == {"CURY3": "25100"}


def test_catalog_preserves_b3_branch_and_cvm_headquarters_cnpj(tmp_path):
    item = InstrumentIdentity("TUPY3", "6343", "84683374000149", "TUPY SA", "B3", "2026-08-14", "2026-08-16T00:00:00Z", b3_issuer_cnpj="84683374000300", identity_match_method="UNIQUE_CNPJ_ROOT")
    path = tmp_path / "catalog.json"
    InstrumentCatalog([item]).dump(path)
    loaded = InstrumentCatalog.load(path).instruments[0]
    assert loaded.cnpj == "84683374000149"
    assert loaded.b3_issuer_cnpj == "84683374000300"
    assert loaded.identity_match_method == "UNIQUE_CNPJ_ROOT"


def test_catalog_rejects_tampering(tmp_path):
    path = tmp_path / "catalog.json"
    InstrumentCatalog([_instrument()]).dump(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["instruments"][0]["cvm_code"] = "999"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        InstrumentCatalog.load(path)


def test_catalog_audits_cnpj_name_and_active_status(tmp_path):
    registry = tmp_path / "cvm.csv"
    registry.write_text("CD_CVM;CNPJ_CIA;DENOM_SOCIAL;SIT\n25100;08.797.760/0001-83;CURY CONSTRUTORA E INCORPORADORA S.A.;ATIVO\n", encoding="latin-1")
    result = InstrumentCatalog([_instrument()]).audit_against_cvm_csv(registry)
    assert result["status"] == "PASS"


def test_catalog_rejects_atomic_identity_mismatch(tmp_path):
    registry = tmp_path / "cvm.csv"
    registry.write_text("CD_CVM;CNPJ_CIA;DENOM_SOCIAL;SIT\n25100;00.000.000/0001-00;OUTRA;ATIVO\n", encoding="latin-1")
    result = InstrumentCatalog([_instrument()]).audit_against_cvm_csv(registry)
    assert result["status"] == "FAIL"
    assert set(result["failures"][0]["reasons"]) == {"CNPJ_MISMATCH", "COMPANY_NAME_MISMATCH"}
