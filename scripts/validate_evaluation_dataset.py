from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation_dataset import load_evaluation_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a de-identified Agent evaluation dataset.")
    parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args()
    manifest, cases = load_evaluation_dataset(args.path)
    print(json.dumps({"status": "valid", "manifest": manifest, "case_ids": [case.id for case in cases]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
