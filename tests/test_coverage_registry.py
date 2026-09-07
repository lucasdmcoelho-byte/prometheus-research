from prometheus.coverage_registry import CoverageRegistry


def test_coverage_registry_requires_active_exact_cvm_identity(monkeypatch):
    registry = CoverageRegistry()
    monkeypatch.setattr(registry, "_rows", lambda: [
        {"CD_CVM": "25100", "DENOM_SOCIAL": "CURY", "CNPJ_CIA": "08.797.760/0001-83", "SIT": "ATIVO"},
        {"CD_CVM": "999", "DENOM_SOCIAL": "OLD", "CNPJ_CIA": "00.000.000/0001-00", "SIT": "CANCELADO"},
    ])
    result = registry.validate({"CURY3": "25100", "OLD3": "999"})
    assert result["status"] == "FAIL"
    assert result["validated_count"] == 1
    assert result["instruments"][0]["cnpj"] == "08.797.760/0001-83"
    assert result["failures"][0]["ticker"] == "OLD3"


def test_coverage_registry_rejects_active_issuer_without_cnpj(monkeypatch):
    registry = CoverageRegistry()
    monkeypatch.setattr(registry, "_rows", lambda: [
        {"CD_CVM": "1", "DENOM_SOCIAL": "SEM CNPJ", "CNPJ_CIA": "", "SIT": "ATIVO"},
    ])
    result = registry.validate({"TEST3": "1"})
    assert result["status"] == "FAIL"
    assert result["validated_count"] == 0
