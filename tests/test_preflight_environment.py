from types import SimpleNamespace

from scripts.preflight_environment import assess_environment


def test_preflight_reports_missing_native_dependency_and_network_without_hiding_it(tmp_path):
    def importer(name):
        if name == "pandas":
            raise ImportError("native DLL blocked")
        return SimpleNamespace(__version__="test")

    def offline():
        raise OSError("socket forbidden")

    result = assess_environment(tmp_path / "cache", check_network=True, importer=importer, network_probe=offline)

    assert result["status"] == "NOT_READY"
    assert result["failures"] == ["pandas", "network"]
    assert result["imports"][0]["error_type"] == "ImportError"
    assert result["network"]["status"] == "UNAVAILABLE"
    assert result["cache"]["writable"] is True


def test_preflight_is_ready_with_dependencies_writable_cache_and_optional_network_probe(tmp_path):
    result = assess_environment(
        tmp_path / "cache", check_network=True,
        importer=lambda _name: SimpleNamespace(__version__="test"), network_probe=lambda: None,
    )
    assert result["status"] == "READY"
    assert result["failures"] == []
    assert result["network"]["status"] == "AVAILABLE"
