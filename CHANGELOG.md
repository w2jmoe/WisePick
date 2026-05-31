# Changelog

All notable changes to WisePick Decision API (WPDA).

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.2] — 2026-05-31

### Fixed

- **F1 — Schema alignment:** Authoritative registry is `api_tool_specs`. Migration script re-targets `decisions.selected_tool_key` and `feedback.tool_key` foreign keys from legacy `tools` to `api_tool_specs`. Orphan `tool_key` backfill for historical rows.
- **F2 — tool_stats registry migration:** `tool_stats` view rebuilt to drive from `api_tool_specs` instead of `tools`, restoring the feedback → aggregation → scoring closed loop for Hosted Shared Feedback Pool.
- **F3 — Feedback idempotency:** Duplicate `POST /v1/feedback` for the same `decision_id` returns `{"ok": true}` via `ON CONFLICT (decision_id) DO NOTHING`; no 500 on retry. Duplicate requests do not re-emit Langfuse execution feedback.
- **F4 — Decision persistence safety:** `_create_decision_log()` failures propagate; no ghost `decision_id` returned when the decision row is not persisted. `/v1/decide` returns structured JSON `{"error":"persistence_failed",...}` on persistence failure.

### Added

- `scripts/migrate_v0_2_2.sql` — idempotent Supabase/PostgreSQL migration (F1 + F2 + Section 3b F3 prerequisite)
- `docs/MIGRATION_v0_2_2.md` — backup, execute, rollback, verify guide
- `INSTALL_FOR_AGENTS.md` — agent operator install path
- `VERIFY.md` — v0.2.2 verification checklist

### Notes

- Legacy `tools` table is retained (not dropped) for rollback reference; runtime reads/writes use `api_tool_specs` only.
- HTTP API contract unchanged; no breaking request/response field changes.
- Requires `feedback.decision_id` unique constraint (`feedback_one_per_decision`) for F3.
