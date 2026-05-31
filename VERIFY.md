# VERIFY — WisePick v0.2.2

Verification checklist for **Hosted Shared Feedback Pool MVP**.

Environment: PostgreSQL/Supabase with v0.2.2 migration applied, API v0.2.2 running, `DATABASE_URL` configured.

---

## Pre-flight

| ID | Check | PASS | FAIL |
| --- | --- | --- | --- |
| P1 | `api_tool_specs`, `decisions`, `feedback` exist | All three present | Any missing |
| P2 | Migration V04/V05 from `migrate_v0_2_2.sql` §5 | `PASS` | `FAIL` |
| P3 | `GET /health` | HTTP 200 | Non-200 |

---

## Decide verification

| ID | Action | PASS | FAIL |
| --- | --- | --- | --- |
| D1 | `POST /v1/decide` with valid task | HTTP 200, body contains `decision_id`, `capability_id`, `provider` | 422/500 or missing fields |
| D2 | Row in `decisions` for returned `decision_id` | Row exists | 200 but no row (ghost ID) |
| D3 | `explain` includes `feedback_count` (may be 0 on cold start) | Field present | Missing |

Record: `decision_id`, `provider`, `confidence` baseline.

---

## Feedback verification

| ID | Action | PASS | FAIL |
| --- | --- | --- | --- |
| F1 | `POST /v1/feedback` with valid `decision_id` | HTTP 200, `{"ok":true}` | 404/500 |
| F2 | Row in `feedback` for `decision_id` | One row, `tool_key` matches decision | No row |
| F3 | Unknown `decision_id` | HTTP 404, `error: not_found` | 200 or 500 |

---

## tool_stats verification

| ID | Action | PASS | FAIL |
| --- | --- | --- | --- |
| T1 | `SELECT * FROM tool_stats WHERE tool_key = '<provider>'` | Row exists | Error or no row for seeded tool |
| T2 | After F1 feedback, `feedback_count >= 1` | Count incremented | Still 0 while `feedback` has rows |
| T3 | `success_rate`, `avg_latency_ms` populated after feedback | Non-null where applicable | All null despite feedback rows |

Runtime read path: `_get_tool_metrics()` uses `success_rate`, `avg_latency_ms`, `avg_token_cost`, `avg_result_quality`, `feedback_count`.

---

## F3 — Feedback idempotency

| ID | Action | PASS | FAIL |
| --- | --- | --- | --- |
| I1 | POST same `decision_id` twice | Both HTTP 200, `{"ok":true}` | Second request 500 |
| I2 | `SELECT count(*) FROM feedback WHERE decision_id = ?` | Exactly 1 | > 1 |
| I3 | Second duplicate does not duplicate Langfuse execution feedback | Single telemetry event per decision (if Langfuse enabled) | Duplicate spans |

---

## F4 — Decision persistence safety

| ID | Action | PASS | FAIL |
| --- | --- | --- | --- |
| S1 | Normal decide after migration | 200 + persisted `decision_id` | 500 with no row |
| S2 | Persistence failure (e.g. DB unavailable / FK violation) | HTTP 500, JSON `{"error":"persistence_failed","message":"Failed to persist decision log"}` — **no** `decision_id` in success body | HTTP 200 with `decision_id` but no DB row |
| S3 | Feedback for failed-persist decide | N/A if decide returned error | Client must not receive usable `decision_id` on S2 failure |

---

## Hosted Feedback Pool (closed loop)

| ID | Action | PASS | FAIL |
| --- | --- | --- | --- |
| H1 | decide → feedback → second decide (same task class) | Second decide `explain` shows `feedback_count >= 1` for used provider | Metrics unchanged after feedback |
| H2 | Negative feedback (`success: false`) then third decide | `success_rate` decreases or ranking changes for that tool | No metric change |
| H3 | Two runtimes share same Supabase | Both feedback rows aggregate into same `tool_stats.tool_key` bucket | Isolated per-runtime buckets |

---

## Migration script self-check

Run Section 5 queries in `scripts/migrate_v0_2_2.sql` after migration:

| Query | Expected |
| --- | --- |
| V01 | `PASS` |
| V02 | `PASS` (6 columns) |
| V03 | `PASS` |
| V04 | `PASS` |
| V05 | `PASS` |
| V06 | `PASS` (orphan_count = 0) |
| V07 | `PASS` (orphan_count = 0) |

Optional audit script:

```bash
python scripts/audit_tool_stats.py
```

Expected: `missing: (none)`

---

## Sign-off

- [ ] All P*, D*, F*, T*, I*, S*, H* checks relevant to your deployment passed
- [ ] SafeAgent or ChainWeaver smoke (if used): decide → execute → feedback → decide
