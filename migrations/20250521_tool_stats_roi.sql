-- WisePick ROI feedback + tool_stats view upgrade
-- Run against Supabase/PostgreSQL (SQL editor or psql). Idempotent where noted.

-- ---------------------------------------------------------------------------
-- 1. feedback table: structured ROI columns
-- ---------------------------------------------------------------------------
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS token_cost jsonb;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS result_quality numeric(5,4);

UPDATE feedback SET latency_ms = 0 WHERE latency_ms IS NULL;

ALTER TABLE feedback ALTER COLUMN latency_ms SET NOT NULL;

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_latency_non_negative;
ALTER TABLE feedback ADD CONSTRAINT feedback_latency_non_negative
    CHECK (latency_ms >= 0);

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_token_cost_is_object;
ALTER TABLE feedback ADD CONSTRAINT feedback_token_cost_is_object
    CHECK (token_cost IS NULL OR jsonb_typeof(token_cost) = 'object');

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_result_quality_range;
ALTER TABLE feedback ADD CONSTRAINT feedback_result_quality_range
    CHECK (result_quality IS NULL OR (result_quality >= 0 AND result_quality <= 1));

-- ---------------------------------------------------------------------------
-- 2. tool_stats view: replace legacy definition with ROI aggregates
--    (live DB may only expose tool_key, success_rate, total — this replaces it)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW tool_stats AS
SELECT
    t.tool_key,
    t.name,
    count(DISTINCT d.decision_id) AS decision_count,
    count(f.id) AS feedback_count,
    count(*) FILTER (WHERE f.success IS TRUE) AS success_count,
    count(*) FILTER (WHERE f.success IS FALSE) AS failure_count,
    CASE
        WHEN count(f.id) = 0 THEN NULL
        ELSE round((count(*) FILTER (WHERE f.success IS TRUE))::numeric / count(f.id), 4)
    END AS success_rate,
    round(avg(f.latency_ms)::numeric, 2) AS avg_latency_ms,
    CASE
        WHEN count(f.token_cost) FILTER (WHERE f.token_cost IS NOT NULL) = 0 THEN NULL
        ELSE round(
            avg(
                coalesce((f.token_cost->>'input')::numeric, 0)
                + coalesce((f.token_cost->>'output')::numeric, 0)
            ) FILTER (WHERE f.token_cost IS NOT NULL),
            2
        )
    END AS avg_token_cost,
    round(avg(f.result_quality)::numeric, 4) AS avg_result_quality,
    max(f.created_at) AS last_feedback_at
FROM tools t
LEFT JOIN decisions d ON d.selected_tool_key = t.tool_key
LEFT JOIN feedback f ON f.decision_id = d.decision_id
GROUP BY t.tool_key, t.name;

COMMENT ON VIEW tool_stats IS
    'Per-tool aggregates: success_rate, avg_latency_ms, avg_token_cost, avg_result_quality';
