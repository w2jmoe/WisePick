#!/usr/bin/env python3
"""Backfill observed_tools from historical feedback.actual_tool_used rows.

Idempotent when using --rebuild (default): truncates observed_tools and replays
all qualifying feedback in created_at order, so repeated runs yield the same counts.

Usage:
  python scripts/backfill_observed_tools.py
  python scripts/backfill_observed_tools.py --dry-run
  python scripts/backfill_observed_tools.py --no-rebuild   # append-only; may double-count if re-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.observed_tools import upsert_observed_tool
from app.services.schema_compat import observed_tools_exists


_FEEDBACK_ROWS_SQL = """
    SELECT
        f.id,
        f.decision_id,
        f.actual_tool_used,
        f.success,
        f.latency_ms,
        f.result_quality,
        f.runtime_name,
        d.task
    FROM feedback f
    LEFT JOIN decisions d ON d.decision_id = f.decision_id
    WHERE f.actual_tool_used IS NOT NULL
      AND BTRIM(f.actual_tool_used) <> ''
    ORDER BY f.created_at ASC, f.id ASC
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill observed_tools from feedback")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        default=True,
        help="Truncate observed_tools before replay (default: true, idempotent)",
    )
    parser.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Append without truncate (NOT idempotent on re-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rows that would be processed without writing",
    )
    args = parser.parse_args()
    rebuild = args.rebuild and not args.no_rebuild

    if not os.getenv("DATABASE_URL", "").strip():
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    if not observed_tools_exists():
        print("observed_tools table not found; run scripts/migrate_v0_3_0.sql first", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        rows = db.execute(text(_FEEDBACK_ROWS_SQL)).fetchall()
        print(f"feedback rows with actual_tool_used: {len(rows)}")

        if args.dry_run:
            for row in rows:
                print(
                    f"  id={row[0]} decision_id={row[1]} tool={row[2]} "
                    f"success={row[3]} latency_ms={row[4]} task={row[7]!r}"
                )
            return 0

        if rebuild:
            db.execute(text("TRUNCATE observed_tools RESTART IDENTITY"))
            db.commit()
            print("truncated observed_tools (rebuild mode)")

        processed = 0
        skipped = 0
        for row in rows:
            _fid, _did, actual_tool, success, latency_ms, result_quality, runtime_name, task = row
            tool_key = (actual_tool or "").strip()
            if not tool_key:
                skipped += 1
                continue
            upsert_observed_tool(
                db,
                tool_key=tool_key,
                success=bool(success),
                latency_ms=int(latency_ms or 0),
                result_quality=float(result_quality) if result_quality is not None else None,
                runtime_name=(runtime_name or "").strip() or None,
                task=task or "",
            )
            processed += 1

        summary = db.execute(
            text(
                """
                SELECT COUNT(*), COALESCE(SUM(observation_count), 0)
                FROM observed_tools
                """
            )
        ).fetchone()
        tool_rows = int(summary[0] or 0)
        total_obs = int(summary[1] or 0)

        print(f"processed feedback rows: {processed} (skipped: {skipped})")
        print(f"observed_tools distinct tools: {tool_rows}, total observation_count: {total_obs}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
