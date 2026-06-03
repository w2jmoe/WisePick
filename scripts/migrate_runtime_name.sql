-- WisePick API — runtime attribution (usage validation only)
-- Adds optional runtime_name to feedback for analytics; no data backfill required.
-- Safe to re-run (IF NOT EXISTS).

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS runtime_name text;

COMMENT ON COLUMN feedback.runtime_name IS
    'Optional runtime self-label for usage analytics (no auth/billing).';

-- Verification
SELECT
    'V01_runtime_name_column' AS check_id,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'feedback'
              AND column_name = 'runtime_name'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS result;
