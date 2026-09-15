import json
import subprocess
import sys


def test_quality_gate_script_passes() -> None:
    completed = subprocess.run([sys.executable, "scripts/quality_gate.py"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["suite"] == "fincredit-agent-quality-gate"
    assert result["failed"] == 0
    assert result["passed"] == 9
