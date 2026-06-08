-- WisePick API — actual_tool_used for ROI attribution on the executed tool
-- Adds optional actual_tool_used to feedback; rebuilds tool_stats to credit it.
-- Safe to re-run (IF NOT EXISTS / DROP VIEW IF EXISTS).

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS actual_tool_used text;

COMMENT ON COLUMN feedback.actual_tool_used IS
    'Optional tool/MCP name actually executed; ROI metrics aggregate here when set.';

-- Backfill placeholders for orphan actual_tool_used keys (disabled, same as migrate_v0_2_2)
INSERT INTO api_tool_specs (
    tool_key,
    name,
    description,
    capabilities,
    enabled,
    bootstrap_weight,
    meta,
    created_at,
    updated_at
)
SELECT DISTINCT
    f.actual_tool_used                                           AS tool_key,
    f.actual_tool_used                                           AS name,
    ''                                                           AS description,
    ''                                                           AS capabilities,
    false                                                        AS enabled,
    0.0000                                                       AS bootstrap_weight,
    '{"backfilled_by":"migrate_actual_tool_used","placeholder":true}'::jsonb AS meta,
    now()                                                        AS created_at,
    now()                                                        AS updated_at
FROM feedback f
WHERE f.actual_tool_used IS NOT NULL
  AND BTRIM(f.actual_tool_used) <> ''
  AND NOT EXISTS (
      SELECT 1 FROM api_tool_specs a WHERE a.tool_key = f.actual_tool_used
  )
ON CONFLICT (tool_key) DO NOTHING;

DROP VIEW IF EXISTS tool_stats;

CREATE VIEW tool_stats AS
SELECT
    t.tool_key,
    t.name,

    count(DISTINCT d.decision_id)                               AS decision_count,
    count(f.id)                                                 AS feedback_count,
    count(*) FILTER (WHERE f.success IS TRUE)                   AS success_count,
    count(*) FILTER (WHERE f.success IS FALSE)                  AS failure_count,

    CASE
        WHEN count(f.id) = 0 THEN NULL
        ELSE round(
                (count(*) FILTER (WHERE f.success IS TRUE))::numeric
                / count(f.id),
                4
             )
    END                                                         AS success_rate,

    round(avg(f.latency_ms)::numeric, 2)                       AS avg_latency_ms,

    CASE
        WHEN count(f.token_cost) FILTER (WHERE f.token_cost IS NOT NULL) = 0
        THEN NULL
        ELSE round(
                avg(
                    coalesce((f.token_cost->>'input')::numeric,  0)
                  + coalesce((f.token_cost->>'output')::numeric, 0)
                ) FILTER (WHERE f.token_cost IS NOT NULL),
                2
             )
    END                                                         AS avg_token_cost,

    round(avg(f.result_quality)::numeric, 4)                   AS avg_result_quality,
    max(f.created_at)                                           AS last_feedback_at

FROM api_tool_specs t
LEFT JOIN decisions d ON d.selected_tool_key = t.tool_key
LEFT JOIN feedback  f ON COALESCE(NULLIF(BTRIM(f.actual_tool_used), ''), f.tool_key) = t.tool_key
GROUP BY t.tool_key, t.name;

COMMENT ON VIEW tool_stats IS
    'Shared Feedback Pool aggregate metrics. '
    'decision_count: recommendations (decisions.selected_tool_key). '
    'feedback ROI: attributed to COALESCE(actual_tool_used, tool_key).';

-- Verification
SELECT
    'V01_actual_tool_used_column' AS check_id,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'feedback'
              AND column_name = 'actual_tool_used'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS result;

SELECT
    'V02_tool_stats_actual_tool_attribution' AS check_id,
    CASE
        WHEN pg_get_viewdef('tool_stats'::regclass) LIKE '%actual_tool_used%'
        THEN 'PASS'
        ELSE 'FAIL'
    END AS result;
