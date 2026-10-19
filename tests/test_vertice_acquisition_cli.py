from pathlib import Path
import ast

def test_fetch_script_is_valid_python_and_uses_environment_token():
    path=Path(__file__).parents[1]/"scripts"/"fetch_intraday.py"
    source=path.read_text()
    ast.parse(source)
    assert "BRAPI_TOKEN" in source
    assert "synthetic" in source and "False" in source
    assert "SEU_TOKEN" not in source
