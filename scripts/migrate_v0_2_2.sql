-- =============================================================================
-- WisePick v0.2.2 — Step A Migration (F1 + F2)
--
-- F1: Schema alignment — api_tool_specs is the authoritative registry.
--     decisions and feedback FKs migrate from tools(tool_key)
--     to api_tool_specs(tool_key).
--
-- F2: tool_stats VIEW rebuilt to drive from api_tool_specs instead of tools.
--
-- Safe to re-run: all operations are idempotent.
-- Target: Supabase PostgreSQL (Postgres 15+).
-- =============================================================================


-- =============================================================================
-- SECTION 0: PRE-FLIGHT CHECK
-- Abort if api_tool_specs does not exist.
-- decisions and feedback must also exist; their absence means the database
-- was never initialised and this migration has nothing to operate on.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name   = 'api_tool_specs'
    ) THEN
        RAISE EXCEPTION
            E'ABORT: api_tool_specs not found in schema public.\n'
            'Start the application once so seed_tools() can run, or create the '
            'table manually from the ORM definition, then re-run this script.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name   = 'decisions'
    ) THEN
        RAISE EXCEPTION
            E'ABORT: decisions table not found. Database is not initialised.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name   = 'feedback'
    ) THEN
        RAISE EXCEPTION
            E'ABORT: feedback table not found. Database is not initialised.';
    END IF;

    RAISE NOTICE 'Pre-flight check passed: api_tool_specs, decisions, feedback all exist.';
END;
$$;


-- =============================================================================
-- SECTION 1: ORPHAN TOOL_KEY BACKFILL  (F1)
--
-- Any tool_key present in decisions or feedback but absent from api_tool_specs
-- is inserted as a disabled placeholder so that FK constraints can be added
-- without referential integrity violations.
--
-- Placeholders are inserted with enabled = false so the decide engine will
-- never select them. They exist only to satisfy FK relationships for
-- historical data rows.
-- =============================================================================

-- Backfill orphans from decisions.selected_tool_key
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
    d.selected_tool_key                                          AS tool_key,
    d.selected_tool_key                                          AS name,
    ''                                                           AS description,
    ''                                                           AS capabilities,
    false                                                        AS enabled,
    0.0000                                                       AS bootstrap_weight,
    '{"backfilled_by":"migrate_v0_2_2","placeholder":true}'::jsonb AS meta,
    now()                                                        AS created_at,
    now()                                                        AS updated_at
FROM decisions d
WHERE d.selected_tool_key IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM api_tool_specs a
      WHERE a.tool_key = d.selected_tool_key
  )
ON CONFLICT (tool_key) DO NOTHING;

-- Backfill orphans from feedback.tool_key
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
    f.tool_key                                                   AS tool_key,
    f.tool_key                                                   AS name,
    ''                                                           AS description,
    ''                                                           AS capabilities,
    false                                                        AS enabled,
    0.0000                                                       AS bootstrap_weight,
    '{"backfilled_by":"migrate_v0_2_2","placeholder":true}'::jsonb AS meta,
    now()                                                        AS created_at,
    now()                                                        AS updated_at
FROM feedback f
WHERE f.tool_key IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM api_tool_specs a
      WHERE a.tool_key = f.tool_key
  )
ON CONFLICT (tool_key) DO NOTHING;

DO $$
DECLARE
    v_count int;
BEGIN
    SELECT count(*) INTO v_count
    FROM api_tool_specs
    WHERE (meta->>'placeholder')::boolean IS TRUE;

    IF v_count > 0 THEN
        RAISE NOTICE 'Backfill complete: % placeholder row(s) inserted into api_tool_specs.', v_count;
    ELSE
        RAISE NOTICE 'Backfill: no orphan tool_keys found. No placeholders needed.';
    END IF;
END;
$$;


-- =============================================================================
-- SECTION 2+3: FK MIGRATION  (F1) — atomic transaction
--
-- decisions.selected_tool_key and feedback.tool_key FK swaps run inside one
-- transaction so a failed ADD rolls back the preceding DROP (no orphan window).
-- Idempotent: skips when the target FK on each column already exists.
-- =============================================================================

BEGIN;

-- decisions.selected_tool_key: tools → api_tool_specs
DO $$
DECLARE
    v_legacy_fk text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class     r ON r.oid = c.conrelid
        JOIN pg_class     f ON f.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = r.relnamespace
        JOIN pg_attribute a ON a.attrelid = r.oid
                           AND a.attnum = ANY (c.conkey)
                           AND NOT a.attisdropped
        WHERE n.nspname  = 'public'
          AND r.relname  = 'decisions'
          AND c.contype  = 'f'
          AND f.relname  = 'api_tool_specs'
          AND a.attname  = 'selected_tool_key'
    ) THEN
        RAISE NOTICE 'decisions.selected_tool_key → api_tool_specs FK already present; skipping.';
        RETURN;
    END IF;

    SELECT c.conname INTO v_legacy_fk
    FROM pg_constraint c
    JOIN pg_class     r ON r.oid = c.conrelid
    JOIN pg_class     f ON f.oid = c.confrelid
    JOIN pg_namespace n ON n.oid = r.relnamespace
    JOIN pg_attribute a ON a.attrelid = r.oid
                       AND a.attnum = ANY (c.conkey)
                       AND NOT a.attisdropped
    WHERE n.nspname = 'public'
      AND r.relname = 'decisions'
      AND c.contype = 'f'
      AND f.relname = 'tools'
      AND a.attname = 'selected_tool_key'
    LIMIT 1;

    IF v_legacy_fk IS NOT NULL THEN
        EXECUTE format('ALTER TABLE decisions DROP CONSTRAINT %I', v_legacy_fk);
        RAISE NOTICE 'Dropped decisions.selected_tool_key → tools FK: %', v_legacy_fk;
    END IF;

    ALTER TABLE decisions
        ADD CONSTRAINT decisions_selected_tool_key_fkey
        FOREIGN KEY (selected_tool_key)
        REFERENCES api_tool_specs (tool_key)
        ON DELETE RESTRICT;
    RAISE NOTICE 'Added decisions.selected_tool_key → api_tool_specs FK.';
END;
$$;

-- feedback.tool_key: tools → api_tool_specs  (feedback.decision_id FK unchanged)
DO $$
DECLARE
    v_legacy_fk text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class     r ON r.oid = c.conrelid
        JOIN pg_class     f ON f.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = r.relnamespace
        JOIN pg_attribute a ON a.attrelid = r.oid
                           AND a.attnum = ANY (c.conkey)
                           AND NOT a.attisdropped
        WHERE n.nspname  = 'public'
          AND r.relname  = 'feedback'
          AND c.contype  = 'f'
          AND f.relname  = 'api_tool_specs'
          AND a.attname  = 'tool_key'
    ) THEN
        RAISE NOTICE 'feedback.tool_key → api_tool_specs FK already present; skipping.';
        RETURN;
    END IF;

    SELECT c.conname INTO v_legacy_fk
    FROM pg_constraint c
    JOIN pg_class     r ON r.oid = c.conrelid
    JOIN pg_class     f ON f.oid = c.confrelid
    JOIN pg_namespace n ON n.oid = r.relnamespace
    JOIN pg_attribute a ON a.attrelid = r.oid
                       AND a.attnum = ANY (c.conkey)
                       AND NOT a.attisdropped
    WHERE n.nspname = 'public'
      AND r.relname = 'feedback'
      AND c.contype = 'f'
      AND f.relname = 'tools'
      AND a.attname = 'tool_key'
    LIMIT 1;

    IF v_legacy_fk IS NOT NULL THEN
        EXECUTE format('ALTER TABLE feedback DROP CONSTRAINT %I', v_legacy_fk);
        RAISE NOTICE 'Dropped feedback.tool_key → tools FK: %', v_legacy_fk;
    END IF;

    ALTER TABLE feedback
        ADD CONSTRAINT feedback_tool_key_fkey
        FOREIGN KEY (tool_key)
        REFERENCES api_tool_specs (tool_key)
        ON DELETE RESTRICT;
    RAISE NOTICE 'Added feedback.tool_key → api_tool_specs FK.';
END;
$$;

COMMIT;


-- =============================================================================
-- SECTION 3b: feedback idempotency constraint (F3 prerequisite)
-- ON CONFLICT (decision_id) requires a unique constraint on decision_id.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.feedback'::regclass
          AND conname = 'feedback_one_per_decision'
    ) THEN
        ALTER TABLE feedback
            ADD CONSTRAINT feedback_one_per_decision UNIQUE (decision_id);
        RAISE NOTICE 'Added feedback_one_per_decision UNIQUE (decision_id).';
    ELSE
        RAISE NOTICE 'feedback_one_per_decision already exists; skipping.';
    END IF;
END;
$$;


-- =============================================================================
-- SECTION 4: REBUILD tool_stats VIEW  (F2)
--
-- Driver table changed from tools → api_tool_specs.
-- DROP required when legacy view column layout differs (CREATE OR REPLACE alone
-- cannot reorder/rename view columns in PostgreSQL).
-- =============================================================================

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
LEFT JOIN feedback  f ON f.decision_id        = d.decision_id
GROUP BY t.tool_key, t.name;

COMMENT ON VIEW tool_stats IS
    'v0.2.2 — Shared Feedback Pool aggregate metrics. '
    'Driver: api_tool_specs (migrated from tools in v0.2.2). '
    'Runtime reads: success_rate, avg_latency_ms, avg_token_cost, avg_result_quality, feedback_count.';


-- =============================================================================
-- SECTION 5: VERIFICATION QUERIES
--
-- Execute these after the migration to confirm all changes succeeded.
-- Each query returns a labelled result; review before declaring migration done.
-- =============================================================================

-- 5.1  tool_stats VIEW is queryable (row count ≥ 0; any error = failure)
SELECT
    'V01_tool_stats_readable'                       AS check_id,
    count(*)                                        AS row_count,
    CASE WHEN count(*) >= 0 THEN 'PASS' ELSE 'FAIL' END AS result
FROM tool_stats;

-- 5.2  All six runtime-required columns exist in tool_stats
SELECT
    'V02_tool_stats_required_columns'               AS check_id,
    string_agg(column_name, ', ' ORDER BY column_name) AS found_columns,
    CASE
        WHEN count(*) = 6 THEN 'PASS'
        ELSE 'FAIL — missing: ' ||
             array_to_string(
                 array(
                     SELECT x FROM unnest(ARRAY[
                         'avg_latency_ms','avg_result_quality','avg_token_cost',
                         'feedback_count','success_rate','tool_key'
                     ]) x
                     WHERE x NOT IN (
                         SELECT column_name
                         FROM information_schema.columns
                         WHERE table_schema = 'public'
                           AND table_name   = 'tool_stats'
                     )
                 ),
                 ', '
             )
    END                                             AS result
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name   = 'tool_stats'
  AND column_name IN (
      'tool_key','success_rate','avg_latency_ms',
      'avg_token_cost','avg_result_quality','feedback_count'
  );

-- 5.3  tool_stats is driven by api_tool_specs (view definition check)
SELECT
    'V03_view_references_api_tool_specs'            AS check_id,
    CASE
        WHEN pg_get_viewdef('tool_stats'::regclass) LIKE '%api_tool_specs%'
        THEN 'PASS'
        ELSE 'FAIL — VIEW still references wrong table'
    END                                             AS result;

-- 5.4  decisions.selected_tool_key FK references api_tool_specs
SELECT
    'V04_decisions_tool_key_fk'                     AS check_id,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class     r ON r.oid = c.conrelid
            JOIN pg_class     f ON f.oid = c.confrelid
            JOIN pg_namespace n ON n.oid = r.relnamespace
            JOIN pg_attribute a ON a.attrelid = r.oid
                               AND a.attnum = ANY (c.conkey)
                               AND NOT a.attisdropped
            WHERE n.nspname = 'public'
              AND r.relname = 'decisions'
              AND c.contype = 'f'
              AND f.relname = 'api_tool_specs'
              AND a.attname = 'selected_tool_key'
        ) THEN 'PASS'
        ELSE 'FAIL — selected_tool_key FK not pointing to api_tool_specs'
    END                                             AS result;

-- 5.5  feedback.tool_key FK references api_tool_specs (decision_id FK ignored)
SELECT
    'V05_feedback_tool_key_fk'                      AS check_id,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class     r ON r.oid = c.conrelid
            JOIN pg_class     f ON f.oid = c.confrelid
            JOIN pg_namespace n ON n.oid = r.relnamespace
            JOIN pg_attribute a ON a.attrelid = r.oid
                               AND a.attnum = ANY (c.conkey)
                               AND NOT a.attisdropped
            WHERE n.nspname = 'public'
              AND r.relname = 'feedback'
              AND c.contype = 'f'
              AND f.relname = 'api_tool_specs'
              AND a.attname = 'tool_key'
        ) THEN 'PASS'
        ELSE 'FAIL — tool_key FK not pointing to api_tool_specs'
    END                                             AS result;

-- 5.6  No orphan tool_keys remain in decisions
SELECT
    'V06_orphan_check_decisions'                    AS check_id,
    count(*)                                        AS orphan_count,
    CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL — orphans remain' END AS result
FROM decisions d
WHERE NOT EXISTS (
    SELECT 1 FROM api_tool_specs a WHERE a.tool_key = d.selected_tool_key
);

-- 5.7  No orphan tool_keys remain in feedback
SELECT
    'V07_orphan_check_feedback'                     AS check_id,
    count(*)                                        AS orphan_count,
    CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL — orphans remain' END AS result
FROM feedback f
WHERE NOT EXISTS (
    SELECT 1 FROM api_tool_specs a WHERE a.tool_key = f.tool_key
);

-- 5.8  Placeholder rows summary (informational)
SELECT
    'V08_placeholder_rows'                          AS check_id,
    count(*)                                        AS placeholder_count,
    CASE WHEN count(*) = 0
         THEN 'OK — no placeholders (clean data)'
         ELSE 'INFO — review and enable/rename as needed'
    END                                             AS result
FROM api_tool_specs
WHERE (meta->>'placeholder')::boolean IS TRUE;

-- =============================================================================
-- END OF MIGRATION
-- All PASS results in Section 5 = migration complete.
-- Proceed to: deploy v0.2.2 application (F3 + F4 code changes).
-- =============================================================================
