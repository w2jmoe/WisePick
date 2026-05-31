# Migration Guide — v0.2.2

Hosted Shared Feedback Pool: align schema with runtime (`api_tool_specs` registry + `tool_stats` view).

**Script:** [`scripts/migrate_v0_2_2.sql`](../scripts/migrate_v0_2_2.sql)

**When required:** Any existing Supabase/PostgreSQL database deployed from legacy schema (`tools`-driven `tool_stats` or FKs pointing to `tools`).

**When skipped:** Brand-new database already created with v0.2.2-aligned schema only (rare; most Hosted deployments need this once).

---

## 1. Backup

Before running migration, export or snapshot:

| Object | Why |
| --- | --- |
| `feedback` | ROI / learning data |
| `decisions` | Feedback parent rows |
| `api_tool_specs` | Registry |
| `tools` | Rollback reference (legacy) |
| `tool_stats` view definition | Rollback VIEW |

**Save current view definition:**

```sql
SELECT pg_get_viewdef('public.tool_stats'::regclass, true);
```

**Supabase:** Project → Database → Backups (point-in-time) or run:

```sql
-- logical copy example (run in SQL editor)
CREATE TABLE _backup_v0_2_1_feedback AS SELECT * FROM feedback;
CREATE TABLE _backup_v0_2_1_decisions AS SELECT * FROM decisions;
CREATE TABLE _backup_v0_2_1_api_tool_specs AS SELECT * FROM api_tool_specs;
```

Drop backup tables after successful verification.

---

## 2. Pre-check

Confirm prerequisites:

```sql
-- must return 1
SELECT EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name = 'api_tool_specs'
);

-- orphan preview (should be empty after migration Section 1)
SELECT DISTINCT selected_tool_key FROM decisions
WHERE selected_tool_key NOT IN (SELECT tool_key FROM api_tool_specs);

SELECT DISTINCT tool_key FROM feedback
WHERE tool_key NOT IN (SELECT tool_key FROM api_tool_specs);
```

If `api_tool_specs` is missing: create the table from the ORM definition (`app/models/tool_spec.py`) or restore from backup, then re-run pre-check. `seed_tools()` only inserts missing registry rows; it does not create database tables.

---

## 3. Execute migration

1. Open Supabase **SQL Editor**
2. Paste entire contents of `scripts/migrate_v0_2_2.sql`
3. Run in one session (FK swap uses `BEGIN`/`COMMIT`)
4. Review `NOTICE` output for skipped/already-applied steps

**Order inside script:**

| Section | Action |
| --- | --- |
| 0 | Pre-flight abort if core tables missing |
| 1 | Orphan `tool_key` backfill into `api_tool_specs` |
| 2+3 | Atomic FK swap: `decisions` + `feedback` → `api_tool_specs` |
| 3b | Add `feedback_one_per_decision` UNIQUE (`decision_id`) if missing (F3 prerequisite) |
| 4 | `DROP VIEW IF EXISTS tool_stats` then `CREATE VIEW tool_stats` from `api_tool_specs` |
| 5 | Verification queries |

**After SQL succeeds:** deploy application **v0.2.2+** (F3/F4 code).

---

## 4. Verify

Run Section 5 queries at bottom of `migrate_v0_2_2.sql`. All must show `PASS` where applicable.

Application smoke: [VERIFY.md](../VERIFY.md)

```bash
python scripts/audit_tool_stats.py
```

Expected: `missing: (none)`

Closed-loop SQL:

```sql
SELECT tool_key, feedback_count, success_rate, avg_latency_ms
FROM tool_stats
WHERE feedback_count > 0;
```

---

## 5. Rollback

Use only if migration or post-deploy verification fails critically.

### 5a. Restore VIEW only (app v0.2.1 compatible if FK already on api_tool_specs)

If only VIEW is wrong, re-run saved `pg_get_viewdef` from backup (legacy `FROM tools` definition).

### 5b. Full schema rollback

Requires `tools` table still present with matching `tool_key` rows.

1. Restore VIEW to legacy definition (`FROM tools`)
2. Drop FK on `decisions.selected_tool_key` → `api_tool_specs`
3. Add FK `decisions.selected_tool_key` → `tools(tool_key)`
4. Drop FK on `feedback.tool_key` → `api_tool_specs`
5. Add FK `feedback.tool_key` → `tools(tool_key)`
6. Restore data from backup tables if corrupted
7. Deploy application v0.2.1

**Partial FK failure during original migration:** Re-running v0.2.2 script is preferred over manual rollback; the transactional FK block rolls back failed adds.

### 5c. Data restore from backup tables

```sql
-- example only — adjust if you used backup table names above
TRUNCATE feedback, decisions RESTART IDENTITY CASCADE;  -- destructive
INSERT INTO decisions SELECT * FROM _backup_v0_2_1_decisions;
INSERT INTO feedback SELECT * FROM _backup_v0_2_1_feedback;
```

---

## 6. Post-migration notes

- Legacy `tools` table is **not dropped** in v0.2.2
- Runtime registry reads/writes: **`api_tool_specs` only**
- Placeholder rows (`meta.placeholder = true`) may appear for orphan keys; review and enable/rename if needed
- Maintenance window recommended: FK swap is atomic but brief lock on `decisions`/`feedback`
