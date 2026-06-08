-- WisePick v0.3.0 — runtime_name + automatic observed_tools ledger
-- Idempotent. Paste entirely into Supabase SQL Editor and run once.
--
-- F1: feedback.runtime_name          (analytics/runtimes endpoint)
-- F2: feedback.latency_ms NOT NULL   (schema alignment)
-- F3: observed_tools table           (auto-populated from actual_tool_used, no human review)

-- ============================================================
-- F1: runtime_name
-- ============================================================
ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS runtime_name text;

COMMENT ON COLUMN feedback.runtime_name IS
    'Optional runtime self-label for analytics attribution.';

-- ============================================================
-- F2: latency_ms NOT NULL alignment
-- ============================================================
UPDATE feedback SET latency_ms = 0 WHERE latency_ms IS NULL;

ALTER TABLE feedback ALTER COLUMN latency_ms SET DEFAULT 0;
ALTER TABLE feedback ALTER COLUMN latency_ms SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.feedback'::regclass
          AND conname = 'feedback_latency_non_negative'
    ) THEN
        ALTER TABLE feedback
            ADD CONSTRAINT feedback_latency_non_negative CHECK (latency_ms >= 0);
    END IF;
END;
$$;

-- ============================================================
-- F3: observed_tools
-- Automatic execution ledger. No human review columns.
-- Populated by feedback handler when actual_tool_used is set.
-- Running averages maintained incrementally on each upsert.
-- ============================================================
CREATE TABLE IF NOT EXISTS observed_tools (
    id                     bigserial    PRIMARY KEY,
    tool_key               text         NOT NULL UNIQUE,

    -- occurrence counters
    observation_count      bigint       NOT NULL DEFAULT 1,
    success_count          bigint       NOT NULL DEFAULT 0,
    failure_count          bigint       NOT NULL DEFAULT 0,

    -- running ROI averages (incremental Welford-style mean)
    avg_latency_ms         numeric      NOT NULL DEFAULT 0,
    avg_result_quality     numeric,

    -- last-seen snapshot (for quick dashboard queries)
    last_success           boolean,
    last_latency_ms        integer,
    last_task_text         text,
    last_runtime_name      text,

    -- deduplicated samples (jsonb arrays, capped at 5 unique entries)
    sample_tasks           jsonb        NOT NULL DEFAULT '[]'::jsonb,
    sample_task_signatures jsonb        NOT NULL DEFAULT '[]'::jsonb,
    sample_runtimes        jsonb        NOT NULL DEFAULT '[]'::jsonb,

    -- bookkeeping
    source                 text         NOT NULL DEFAULT 'feedback',
    first_seen_at          timestamptz  NOT NULL DEFAULT now(),
    last_seen_at           timestamptz  NOT NULL DEFAULT now(),
    updated_at             timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE observed_tools IS
    'Automatic ledger of tools seen in feedback.actual_tool_used. '
    'No human review. Populated by feedback handler. '
    'Promotion to api_tool_specs happens via code rules or threshold checks only.';

-- Remove review_status if it was added by an earlier migration attempt
ALTER TABLE observed_tools DROP COLUMN IF EXISTS review_status;
ALTER TABLE observed_tools DROP COLUMN IF EXISTS task_signature;
ALTER TABLE observed_tools DROP COLUMN IF EXISTS last_actual_tool_used;

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_observed_tools_last_seen
    ON observed_tools (last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_observed_tools_count
    ON observed_tools (observation_count DESC);

CREATE INDEX IF NOT EXISTS idx_observed_tools_source
    ON observed_tools (source);

-- ============================================================
-- Verification
-- ============================================================
SELECT
    'V01_runtime_name' AS check_id,
    CASE WHEN EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'feedback'
          AND column_name = 'runtime_name'
    ) THEN 'PASS' ELSE 'FAIL' END AS result;

SELECT
    'V02_latency_not_null' AS check_id,
    CASE WHEN (
        SELECT is_nullable FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'feedback'
          AND column_name = 'latency_ms'
    ) = 'NO' THEN 'PASS' ELSE 'FAIL' END AS result;

SELECT
    'V03_observed_tools' AS check_id,
    CASE WHEN EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'observed_tools'
    ) THEN 'PASS' ELSE 'FAIL' END AS result;
