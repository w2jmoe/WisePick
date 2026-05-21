"""Audit tool_stats view columns against live DATABASE_URL."""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL", "").strip()
if not url:
    print("DATABASE_URL not set")
    sys.exit(1)

from sqlalchemy import create_engine, text

REQUIRED = ("avg_latency_ms", "avg_token_cost", "avg_result_quality")
engine = create_engine(url, pool_pre_ping=True)
with engine.connect() as conn:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'tool_stats'
            ORDER BY ordinal_position
            """
        )
    ).fetchall()
    cols = [r[0] for r in rows]
    print("columns:", cols)
    missing = [c for c in REQUIRED if c not in cols]
    print("missing:", missing or "(none)")
