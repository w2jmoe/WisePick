# Hermes ↔ WisePick routing benchmark

## Purpose | 目的

This folder holds **optional** scripts used to validate that a Hermes-style agent can
prime its first tool choice from WisePick’s `/v1/decide` and log comparable metrics
for baseline vs routed runs. It does **not** exercise the WisePick API server’s
internal scoring in isolation; end-to-end runs need Hermes plus model credentials.

本目录用于在 **Hermes 类 Agent** 侧验证：能否用 WisePick 的 `/v1/decide` 结果预置首轮
工具选择，并在 **基线** 与 **开启路由** 两种模式下记录可对比指标。完整跑通需要
Hermes 与模型凭证；不替代 WisePick 服务端的独立压测。

## Baseline vs WisePick | 基线 vs 智选

| Mode | Env | Meaning |
|------|-----|---------|
| **Baseline** | `HERMES_WISEPICK_ROUTING=0` | Hermes does not call `/v1/decide`; normal tool selection. |
| **WisePick** | `HERMES_WISEPICK_ROUTING=1` | Hermes may POST `/v1/decide` and inject `tool_choice` on the first completion (see Hermes integration). |

The compare runner executes the same `benchmark/tasks/wisepick_validation_tasks.json`
tasks under each mode and writes one JSONL log per mode.

## How to run | 如何运行

1. Clone/configure **Hermes** so its root contains `run_agent.py`.
2. Point **`HERMES_AGENT_ROOT`** at that directory (or use a sibling folder named
   `hermes-agent` next to this repo).
3. Set model credentials (`OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, etc.).
4. Optionally start WisePick (`WISEPICK_DECIDE_URL`, default `http://localhost:8000/v1/decide`).

```bash
export HERMES_AGENT_ROOT=/path/to/hermes-agent
export OPENAI_API_KEY=...
python benchmark/runners/wisepick_bench_compare.py
```

Common options: `--tasks`, `--out-dir`, `--toolsets`, `--model`, `--max-tasks`,
`--baseline-only`, `--wisepick-only`.

Instrumentation lives in `benchmark/instrumentation/wisepick_bench.py` (copy or import
from Hermes as in your integration); it appends one JSON object per line when
`HERMES_WISEPICK_BENCH_LOG` is set to a file path.

## Metrics | 指标含义

Key fields in each JSONL row (see ``append_turn_record`` in ``benchmark/instrumentation/wisepick_bench.py``):

| Field | Meaning |
|-------|---------|
| `total_tool_calls` | Count of tool executions in the turn. |
| `api_call_count` / `execution_path_length` | Model API round-trips (Hermes-reported). |
| `invalid_tool_rounds` | Rounds where tool use failed validation / repair. |
| `first_tool_name` | First executed registry tool name. |
| `whether_wisepick_primed` | A `/v1/decide` mapping was applied for this turn. |
| `first_tool_matches_wisepick_primed` | First tool equals primed suggestion (if applicable). |
| `final_response_success` | Turn finished with a final response and no failure flags. |

`summary.json` (compare script) aggregates averages and alignment rates across
matching `task_id` rows in baseline vs wisepick logs.