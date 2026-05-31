-- WisePick API v0
-- Minimal, auditable, Supabase/Postgres-first schema 

create extension if not exists pgcrypto;

create table if not exists tools (
    id bigserial primary key,
    tool_key text not null unique,
    name text not null,
    description text not null default '',
    capabilities jsonb not null default '[]'::jsonb,
    enabled boolean not null default true,
    bootstrap_weight numeric(5,4) not null default 0.5000,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint tools_capabilities_is_array check (jsonb_typeof(capabilities) = 'array')
);

create index if not exists idx_tools_enabled on tools (enabled);
create index if not exists idx_tools_tool_key on tools (tool_key);
create index if not exists idx_tools_capabilities_gin on tools using gin (capabilities);

create table if not exists decisions (
    id bigserial primary key,
    decision_id text not null unique default 'dec_' || replace(gen_random_uuid()::text, '-', ''),
    task text not null,
    context jsonb not null default '{}'::jsonb,
    constraints jsonb not null default '{}'::jsonb,
    selected_tool_key text not null references tools(tool_key),
    reason text not null,
    confidence numeric(5,4) not null,
    score_breakdown jsonb not null default '{}'::jsonb,
    explain jsonb not null default '{}'::jsonb,
    trace jsonb not null default '{}'::jsonb,
    bootstrap_version text not null default 'v0',
    created_at timestamptz not null default now(),
    constraint decisions_context_is_object check (jsonb_typeof(context) = 'object'),
    constraint decisions_constraints_is_object check (jsonb_typeof(constraints) = 'object'),
    constraint decisions_score_breakdown_is_object check (jsonb_typeof(score_breakdown) = 'object'),
    constraint decisions_explain_is_object check (jsonb_typeof(explain) = 'object'),
    constraint decisions_trace_is_object check (jsonb_typeof(trace) = 'object'),
    constraint decisions_confidence_range check (confidence >= 0 and confidence <= 1)
);

create index if not exists idx_decisions_decision_id on decisions (decision_id);
create index if not exists idx_decisions_selected_tool_key on decisions (selected_tool_key);
create index if not exists idx_decisions_created_at on decisions (created_at desc);

create table if not exists feedback (
    id bigserial primary key,
    decision_id text not null references decisions(decision_id) on delete cascade,
    tool_key text not null references tools(tool_key),
    outcome text not null default 'completed',
    success boolean not null,
    latency_ms integer not null,
    token_cost jsonb,
    result_quality numeric(5,4),
    user_note text not null default '',
    trace jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint feedback_one_per_decision unique (decision_id),
    constraint feedback_trace_is_object check (jsonb_typeof(trace) = 'object'),
    constraint feedback_latency_non_negative check (latency_ms >= 0),
    constraint feedback_token_cost_is_object check (token_cost is null or jsonb_typeof(token_cost) = 'object'),
    constraint feedback_result_quality_range check (result_quality is null or (result_quality >= 0 and result_quality <= 1))
);

create index if not exists idx_feedback_decision_id on feedback (decision_id);
create index if not exists idx_feedback_tool_key on feedback (tool_key);
create index if not exists idx_feedback_created_at on feedback (created_at desc);

create or replace view tool_stats as
select
    t.tool_key,
    t.name,
    count(distinct d.decision_id) as decision_count,
    count(f.id) as feedback_count,
    count(*) filter (where f.success is true) as success_count,
    count(*) filter (where f.success is false) as failure_count,
    case
        when count(f.id) = 0 then null
        else round((count(*) filter (where f.success is true))::numeric / count(f.id), 4)
    end as success_rate,
    round(avg(f.latency_ms)::numeric, 2) as avg_latency_ms,
    case
        when count(f.token_cost) filter (where f.token_cost is not null) = 0 then null
        else round(
            avg(
                coalesce((f.token_cost->>'input')::numeric, 0)
                + coalesce((f.token_cost->>'output')::numeric, 0)
            ) filter (where f.token_cost is not null),
            2
        )
    end as avg_token_cost,
    round(avg(f.result_quality)::numeric, 4) as avg_result_quality,
    max(f.created_at) as last_feedback_at
from tools t
left join decisions d on d.selected_tool_key = t.tool_key
left join feedback f on f.decision_id = d.decision_id
group by t.tool_key, t.name;

comment on table tools is 'Registry of tools that WisePick can select.';
comment on table decisions is 'Immutable decision log returned by POST /v1/decide.';
comment on table feedback is 'Outcome feedback returned after the caller executes the selected tool.';
comment on view tool_stats is 'Derived per-tool aggregate metrics used for transparent success-rate reporting.';

-- Optional seed examples for bootstrap
insert into tools (tool_key, name, description, capabilities, bootstrap_weight, metadata)
values
    (
        'feishu_minutes',
        'Feishu Minutes',
        'Meeting transcription tool',
        '["transcription", "audio", "meeting"]'::jsonb,
        0.70,
        '{"provider":"feishu","bootstrap":true}'::jsonb
    ),
    (
        'tongyi_tingwu',
        'Tongyi Tingwu',
        'Meeting transcription tool',
        '["transcription", "audio", "meeting"]'::jsonb,
        0.65,
        '{"provider":"alibaba","bootstrap":true}'::jsonb
    ),
    (
        'github_copilot',
        'GitHub Copilot',
        'Coding assistant',
        '["coding", "code_generation"]'::jsonb,
        0.70,
        '{"provider":"github","bootstrap":true}'::jsonb
    ),
    (
        'chatgpt',
        'ChatGPT',
        'General writing and reasoning tool',
        '["writing", "summary", "general_llm"]'::jsonb,
        0.60,
        '{"provider":"openai","bootstrap":true}'::jsonb
    )
on conflict (tool_key) do nothing;

-- ROI feedback columns (existing deployments; safe to re-run)
alter table feedback add column if not exists token_cost jsonb;
alter table feedback add column if not exists result_quality numeric(5,4);
update feedback set latency_ms = 0 where latency_ms is null;
alter table feedback alter column latency_ms set not null;
alter table feedback drop constraint if exists feedback_latency_non_negative;
alter table feedback add constraint feedback_latency_non_negative check (latency_ms >= 0);
alter table feedback drop constraint if exists feedback_token_cost_is_object;
alter table feedback add constraint feedback_token_cost_is_object
    check (token_cost is null or jsonb_typeof(token_cost) = 'object');
alter table feedback drop constraint if exists feedback_result_quality_range;
alter table feedback add constraint feedback_result_quality_range
    check (result_quality is null or (result_quality >= 0 and result_quality <= 1));
