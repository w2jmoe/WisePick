-- System placeholder for no-match decide routes (feedback anchor only).
-- Safe to re-run.

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
VALUES (
    'fallback_unknown',
    'Fallback Unknown',
    'System placeholder for no-match decide routes; not routable',
    '',
    false,
    0.0000,
    '{"system": true, "no_match_anchor": true}'::jsonb,
    now(),
    now()
)
ON CONFLICT (tool_key) DO NOTHING;

SELECT
    'V01_fallback_unknown' AS check_id,
    CASE WHEN EXISTS (
        SELECT 1 FROM api_tool_specs WHERE tool_key = 'fallback_unknown'
    ) THEN 'PASS' ELSE 'FAIL' END AS result;
