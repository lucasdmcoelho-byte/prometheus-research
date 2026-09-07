import subprocess
import sys
from pathlib import Path


def test_unknown_ticker_exits_nonzero_when_official_identity_is_required():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable, "main.py", "--ticker", "ZZZZ99", "--as-of", "2026-08-23",
            "--instrument-catalog", "config/instrument_catalog.json", "--quiet",
        ],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 2
    assert "Missing validated CVM issuer codes" in completed.stderr
