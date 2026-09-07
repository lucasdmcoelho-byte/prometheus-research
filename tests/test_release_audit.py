import hashlib
import json

from scripts.audit_release import audit_release_manifests, audit_report, audit_report_portfolio


def test_release_auditor_fails_closed_when_report_files_are_missing(tmp_path):
    result = audit_report(tmp_path / "missing.json", tmp_path / "missing.pdf", expected_ticker="EGIE3")
    assert result["status"] == "FAIL"
    assert result["ticker"] == "EGIE3"
    assert "report JSON missing" in result["failures"][0]


def test_release_manifest_audit_detects_reproducible_artifacts(tmp_path):
    dirs = [tmp_path / "a", tmp_path / "b"]
    payload = b"deterministic wheel"
    digest = hashlib.sha256(payload).hexdigest()
    for directory in dirs:
        directory.mkdir()
        (directory / "product.whl").write_bytes(payload)
        manifest = {
            "version": "2.1.0rc1", "release_stage": "release_candidate",
            "source_files": [{"path": "main.py", "sha256": "a" * 64, "size": 1}],
            "artifacts": [{"path": "product.whl", "sha256": digest, "size": len(payload)}],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = audit_release_manifests(dirs[0] / "manifest.json", dirs[1] / "manifest.json")
    assert result["status"] == "PASS"
    assert result["verified_artifacts"] == {"product.whl": digest}


def test_release_manifest_audit_rejects_different_second_build(tmp_path):
    dirs = [tmp_path / "a", tmp_path / "b"]
    for index, directory in enumerate(dirs):
        directory.mkdir()
        payload = f"build-{index}".encode()
        digest = hashlib.sha256(payload).hexdigest()
        (directory / "product.whl").write_bytes(payload)
        (directory / "manifest.json").write_text(json.dumps({
            "version": "2.1.0rc1", "source_files": [],
            "artifacts": [{"path": "product.whl", "sha256": digest, "size": len(payload)}],
        }), encoding="utf-8")
    result = audit_release_manifests(dirs[0] / "manifest.json", dirs[1] / "manifest.json")
    assert result["status"] == "FAIL"
    assert "non-reproducible artifact: product.whl" in result["failures"]


def test_release_auditor_requires_three_distinct_current_sector_reports():
    one = audit_report_portfolio([{"status": "PASS", "ticker": "ITUB4", "sector_key": "financial"}])
    assert one["status"] == "FAIL"
    assert any("3 passing" in item for item in one["failures"])
    complete = audit_report_portfolio([
        {"status": "PASS", "ticker": "ITUB4", "sector_key": "financial"},
        {"status": "PASS", "ticker": "EGIE3", "sector_key": "utilities"},
        {"status": "PASS", "ticker": "CURY3", "sector_key": "real_estate"},
    ])
    assert complete["status"] == "PASS"
