"""Check whether a host can safely run a PROMETHEUS collection or validation."""

from __future__ import annotations

import argparse
import importlib
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen


REQUIRED_IMPORTS = ("pandas", "yfinance", "reportlab", "pypdf")


def assess_environment(
    cache_dir: str | Path = ".cache/prometheus",
    check_network: bool = False,
    importer: Callable[[str], Any] = importlib.import_module,
    network_probe: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Return a machine-readable readiness report without collecting research data."""
    imports = []
    for package in REQUIRED_IMPORTS:
        try:
            module = importer(package)
            imports.append({"package": package, "status": "AVAILABLE", "version": getattr(module, "__version__", None)})
        except Exception as error:  # import errors include blocked native DLLs
            imports.append({"package": package, "status": "UNAVAILABLE", "error_type": type(error).__name__, "detail": str(error)})

    cache = Path(cache_dir)
    cache_status = {"path": str(cache), "exists": cache.is_dir(), "writable": False}
    try:
        cache.mkdir(parents=True, exist_ok=True)
        probe = cache / ".prometheus_preflight_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        cache_status["writable"] = True
    except OSError as error:
        cache_status.update({"error_type": type(error).__name__, "detail": str(error)})

    network = {"checked": bool(check_network), "status": "NOT_CHECKED"}
    if check_network:
        try:
            (network_probe or _bcb_probe)()
            network["status"] = "AVAILABLE"
        except Exception as error:
            network.update({"status": "UNAVAILABLE", "error_type": type(error).__name__, "detail": str(error)})

    failures = [item["package"] for item in imports if item["status"] != "AVAILABLE"]
    if not cache_status["writable"]:
        failures.append("cache_writable")
    if check_network and network["status"] != "AVAILABLE":
        failures.append("network")
    return {
        "schema": "prometheus.environment_preflight.v1",
        "status": "READY" if not failures else "NOT_READY",
        "failures": failures,
        "imports": imports,
        "cache": cache_status,
        "network": network,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _bcb_probe() -> None:
    with urlopen("https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json", timeout=8) as response:
        if getattr(response, "status", 200) >= 400:
            raise OSError(f"BCB returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="PROMETHEUS environment preflight")
    parser.add_argument("--cache-dir", default=".cache/prometheus")
    parser.add_argument("--check-network", action="store_true", help="Probe BCB connectivity without collecting a research snapshot")
    args = parser.parse_args()
    result = assess_environment(args.cache_dir, check_network=args.check_network)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
