from __future__ import annotations

import hashlib
import base64
import json
import sys
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ("prometheus", "tests", "docs", "config", "scripts", "main.py", "pyproject.toml", "requirements.txt", "README.md")
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "tmp", "build", "dist", ".git"}
FIXED_TIME = (2020, 1, 1, 0, 0, 0)
VERSION = str(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])


def files():
    for entry in INCLUDE:
        path = ROOT / entry
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
        for candidate in candidates:
            relative = candidate.relative_to(ROOT)
            if not any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in relative.parts):
                yield candidate, relative


def main(destination: str = "dist"):
    output = ROOT / destination
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"prometheus-research-{VERSION}-source.zip"
    manifest = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path, relative in files():
            payload = path.read_bytes()
            info = zipfile.ZipInfo(str(Path("PROMETHEUS") / relative).replace("\\", "/"), FIXED_TIME)
            info.external_attr = 0o644 << 16
            zipped.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            manifest.append({"path": str(relative).replace("\\", "/"), "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)})
    wheel_path = output / f"prometheus_research-{VERSION}-py3-none-any.whl"
    _build_wheel(wheel_path)
    # Only artifacts produced by this invocation belong to the manifest. Old
    # files in a reused destination must never contaminate a new release.
    artifacts = [
        {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
        for path in (archive, wheel_path)
    ]
    release_manifest = {
        "product": "PROMETHEUS Research", "version": VERSION, "python": ">=3.11",
        "release_stage": "release_candidate" if "rc" in VERSION else "general_availability",
        "commercial_validation": "A release is client-deliverable only when scripts/audit_release.py returns PASS for current artifacts.",
        "source_files": manifest, "artifacts": artifacts,
        "reproducibility": "Source ZIP uses sorted paths and a fixed timestamp; wheel is built without dependency resolution.",
    }
    manifest_path = output / f"prometheus-research-{VERSION}-manifest.json"
    manifest_path.write_text(json.dumps(release_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(manifest_path)


def _build_wheel(path: Path) -> None:
    dist_info = f"prometheus_research-{VERSION}.dist-info"
    members = []
    for source in sorted((ROOT / "prometheus").glob("*.py")) + [ROOT / "main.py"]:
        archive_name = str(source.relative_to(ROOT)).replace("\\", "/")
        members.append((archive_name, source.read_bytes()))
    metadata = f"""Metadata-Version: 2.1
Name: prometheus-research
Version: {VERSION}
Summary: Point-in-time financial research and auditable PDF reports for B3 equities
Requires-Python: >=3.11
Requires-Dist: matplotlib>=3.8,<4
Requires-Dist: reportlab>=4,<5
Requires-Dist: pypdf>=5,<7
Requires-Dist: yfinance>=0.2.54,<2
""".encode()
    wheel = """Wheel-Version: 1.0
Generator: PROMETHEUS reproducible builder
Root-Is-Purelib: true
Tag: py3-none-any
""".encode()
    entry_points = "[console_scripts]\nprometheus-research = main:main\n".encode()
    members.extend([
        (f"{dist_info}/METADATA", metadata), (f"{dist_info}/WHEEL", wheel),
        (f"{dist_info}/entry_points.txt", entry_points), (f"{dist_info}/top_level.txt", b"prometheus\nmain\n"),
    ])
    records = []
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, payload in members:
            info = zipfile.ZipInfo(name, FIXED_TIME); info.external_attr = 0o644 << 16
            zipped.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
            records.append(f"{name},sha256={digest},{len(payload)}")
        record_name = f"{dist_info}/RECORD"
        record_payload = ("\n".join(records + [f"{record_name},,"]) + "\n").encode()
        info = zipfile.ZipInfo(record_name, FIXED_TIME); info.external_attr = 0o644 << 16
        zipped.writestr(info, record_payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dist")
