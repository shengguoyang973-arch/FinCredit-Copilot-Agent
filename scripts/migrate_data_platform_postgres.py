from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.bootstrap import initialize_application  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.data_platform_cutover import build_source_snapshot, migrate_snapshot, snapshot_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a verified SQLite-to-PostgreSQL data-platform cutover.")
    parser.add_argument("--execute", action="store_true", help="Copy records only after an explicit fingerprint confirmation.")
    parser.add_argument("--confirm-source-fingerprint", default="")
    parser.add_argument("--destination-dsn", default="")
    parser.add_argument("--schema", default="")
    parser.add_argument("--actor-id", default="data-platform-cutover")
    args = parser.parse_args()

    initialize_application()
    settings = get_settings()
    source_label = f"sqlite:{settings.database_path.name}"
    snapshot = build_source_snapshot()
    manifest = snapshot_manifest(snapshot, source_label)
    if not args.execute:
        print(json.dumps({"status": "dry_run", "manifest": manifest}, ensure_ascii=False, indent=2))
        return 0
    dsn = args.destination_dsn or settings.data_platform_postgres_dsn
    if not dsn:
        parser.error("--destination-dsn 或 FINCREDIT_DATA_PLATFORM_POSTGRES_DSN 必填")
    result = migrate_snapshot(
        snapshot,
        destination_dsn=dsn,
        schema=args.schema or settings.data_platform_postgres_schema,
        source_label=source_label,
        source_fingerprint=args.confirm_source_fingerprint,
        actor_id=args.actor_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
