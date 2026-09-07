from scripts.audit_release import (
    DEFAULT_RELEASE_MANIFEST,
    DEFAULT_REPORT_SPECS,
    DEFAULT_REPRO_MANIFEST,
    PACKAGE_VERSION,
)


def test_release_audit_defaults_follow_the_declared_package_version_and_current_validation_portfolio():
    assert PACKAGE_VERSION == "2.1.0rc2"
    assert f"prometheus-research-{PACKAGE_VERSION}-manifest.json" == DEFAULT_RELEASE_MANIFEST.name
    assert DEFAULT_RELEASE_MANIFEST.parent.name == "release_current_a"
    assert DEFAULT_REPRO_MANIFEST.parent.name == "release_current_b"
    assert [item.split("|", 1)[0] for item in DEFAULT_REPORT_SPECS] == ["ITUB4", "EGIE3", "CURY3"]
    assert all("20260817" in item for item in DEFAULT_REPORT_SPECS)
