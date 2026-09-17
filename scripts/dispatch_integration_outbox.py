from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.bootstrap import initialize_application  # noqa: E402
from app.integration_outbox import dispatch_pending  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch due FinCredit SIEM and work-item outbox events.")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    initialize_application()
    print(json.dumps(dispatch_pending(limit=max(1, min(args.limit, 200))), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
