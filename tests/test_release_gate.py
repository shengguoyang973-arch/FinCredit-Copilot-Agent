import json
import subprocess
import sys


def test_release_gate_passes() -> None:
    result = subprocess.run([sys.executable, "scripts/release_gate.py"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
