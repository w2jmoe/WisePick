# WisePick API v0

WisePick routes tasks to executable capabilities for AI agents. 

---

## Core Loop

WisePick provides deterministic capability routing:

1. **Decide** → POST `/v1/decide` with task description
2. **Execute** → Agent executes the selected capability
3. **Feedback** → POST `/v1/feedback` with execution outcome
4. **Learn** → `capability_stats` updated for future routing

**Key principle**: WisePick does not execute capabilities, it only routes to them.

---

## Endpoints

### GET /health

Health check endpoint for monitoring and load balancing.

**Response**:
```json
{
  "status": "ok",
  "service": "wisepick-api", 
  "version": "v0"
}
```

---

### POST /v1/decide

Main routing endpoint. Send a task description, receive executable capability.

**Request**:
```json
{
  "task": "Transcribe today's meeting audio",
  "context": {
    "meeting_duration": "45 minutes",
    "language": "Chinese"
  },
  "constraints": {
    "max_cost": 10.0,
    "timeout_seconds": 300
  }
}
```

**Response**:
```json
{
  "decision_id": "dec_abc123def4567890",
  "capability_id": "audio_transcription",
  "execution_type": "api",
  "provider": "feishu_minutes",
  "reason": "Task matched capabilities: audio_transcription; Provider capabilities: transcription, audio, meeting; Effective bootstrap weight: 0.5000; Execution success rate: 50% (default); Confidence score: 0.75",
  "confidence": 0.75,
  "callable": true,
  "explain": {
    "scoring_formula": "capability_match * 0.70 + execution_success_rate * 0.20 + effective_bootstrap_weight * 0.10",
    "selected_capability": {
      "capability_id": "audio_transcription",
      "provider": "feishu_minutes",
      "score": 0.75,
      "matched_capabilities": ["audio_transcription"]
    },
    "candidate_count": 4,
    "feedback_count": 0,
    "effective_bootstrap_weight": 0.5
  },
  "trace": {
    "timestamp": 1712345678.123,
    "latency_ms": 45,
    "top_candidates": [
      {"capability_id": "audio_transcription", "provider": "feishu_minutes", "score": 0.75, "rank": 1},
      {"capability_id": "audio_transcription", "provider": "tongyi_tingwu", "score": 0.70, "rank": 2}
    ]
  }
}
```

**Response Fields**:
- `decision_id`: Unique identifier for this routing decision (required for feedback)
- `capability_id`: The executable capability type (e.g., `audio_transcription`, `image_generation`)
- `execution_type`: How to execute (`api`, `mcp`, `function_call`)
- `provider`: Specific provider implementation (e.g., `feishu_minutes`, `openai`)
- `reason`: Human-readable explanation of the routing decision
- `confidence`: Routing confidence score (0.0-1.0)
- `callable`: Whether this capability can be directly executed
- `explain`: Technical details for auditability
- `trace`: Performance and debugging information

**Key concept**: Agent sees `capability_id`, not the underlying provider name. The capability is what matters for execution planning.

---

### POST /v1/feedback

Record execution outcome to improve future capability routing.

**Request**:
```json
{
  "decision_id": "dec_abc123def4567890",
  "success": true,
  "latency_ms": 1200,
  "user_note": "{\"token_usage\": 450, \"cost_usd\": 0.01}"
}
```

**Response**:
```json
{
  "ok": true
}
```

**Notes**:
- `success` updates the capability's execution success rate in `capability_stats`
- `latency_ms` — optional execution duration (milliseconds)
- `user_note` — **type `string`**, optional free-form metadata. **Recommended:** store a **serialized JSON object** (JSON-in-string) for ROI signals—token usage, USD cost, or other metrics—so future decision logic can consume structured cost data without schema changes. Example object before serialization: `{"token_usage": 450, "cost_usd": 0.01}`.
- Feedback drives the system from rule-based to execution-data-driven routing

---

## Decision Philosophy

WisePick v0 implements capability routing:

- **Capability-first**: Bootstrap rules provide initial capability matching
- **Deterministic routing**: Same task → same executable capability (for reproducibility)
- **Execution-feedback driven**: Execution success rates influence future routing
- **Bootstrap decay**: Static rules gradually give way to real execution data

**Scoring Formula**:
```
score = capability_match * 0.70 + execution_success_rate * 0.20 + effective_bootstrap_weight * 0.10
```

As execution feedback accumulates, bootstrap weight decays, shifting from rule-driven to execution-data-driven routing.

---

## Optional YantrikDB (cluster health)

WisePick can optionally integrate with **YantrikDB** during `/v1/decide` so replication lag can influence routing confidence. This is **plugin-style**: no Supabase/PostgreSQL schema changes; leave variables empty to disable.

**Environment variables** (see `.env.example`):

- **`YANTRIK_DB_URL`** — Base URL of YantrikDB. If empty, cluster health logic is skipped entirely.
- **`YANTRIK_DB_API_KEY`** — Optional. When set, sent as `Authorization: Bearer <token>` on the health request.

**Behavior**:

1. When `YANTRIK_DB_URL` is set, WisePick calls `GET {base}/v1/health` (timeout bounded).
2. It parses **`replication_lag_log_entries`** from the JSON response.
3. If lag **> 500**, all candidate ECU scores for that request are multiplied by **0.5** before ranking (uniform health penalty on **confidence**).
4. If the URL is unset, or the health request fails or omits the field, WisePick uses the standard score only—no hard failure.

**Response fields**: When YantrikDB is configured for the process, `explain.yantrik_cluster` and `trace.yantrik_cluster` may include `configured`, `replication_lag_log_entries`, `health_penalty_applied`, and `health_score_multiplier`.

---

## Minimal Integration Example

```python
import json

# 1. Send task to WisePick for capability routing
response = requests.post("http://localhost:8000/v1/decide", json={
    "task": "Summarize this technical document"
})
routing = response.json()

# 2. Execute the routed capability
capability_id = routing["capability_id"]
provider = routing["provider"]
result = execute_capability(capability_id, provider, routing["task"])

# 3. Send execution feedback (optional user_note: ROI metrics as JSON string)
requests.post("http://localhost:8000/v1/feedback", json={
    "decision_id": routing["decision_id"],
    "success": result.success,
    "latency_ms": result.latency_ms,
    "user_note": json.dumps({"token_usage": 450, "cost_usd": 0.01}),
})
```

**Key point**: Your agent receives `capability_id` (what to do) and `provider` (how to do it), not just a tool name.

---

## ECU Integration Flow

```text
Agent → WisePick → ECU → Local Execution → Feedback
```

### Example ECU Response

```json
{
  "capability_id": "audio_transcription",
  "execution_type": "api",
  "provider": "feishu_minutes",
  "callable": true
}
```

### What Agent Developers Need To Do

**WisePick's Role:**
- Routes executable capabilities (ECUs)
- Learns from execution outcomes
- Tracks capability performance

**Agent Developer's Role:**
- Map ECU to local API / MCP / tools
- Execute the capability
- Send execution feedback

### Example Mapping

```python
ECU_ROUTER = {
    "audio_transcription": transcribe_audio,
    "presentation_generation": generate_slides,
    "translation": translate_text,
    "general_content": chat_completion
}

# Usage
def execute_capability(capability_id: str, provider: str, task: str):
    if capability_id in ECU_ROUTER:
        return ECU_ROUTER[capability_id](provider, task)
    else:
        raise ValueError(f"Unknown capability: {capability_id}")
```

**Important**: WisePick does not replace MCP. It's a decision layer above execution layer.

---

## Notes

- **WisePick does not execute capabilities** - it only routes to them
- **Designed for agent integration** - minimal API surface for easy embedding
- **All routing decisions are auditable** - explain and trace provide full transparency
- **Supabase-backed** - PostgreSQL-compatible database for capability stats
- **Optional YantrikDB** - When `YANTRIK_DB_URL` is set, `/v1/decide` can factor replication lag into ECU scores (see **Optional YantrikDB**)
- **Open source v0** - focused on core capability routing; enterprise-style cluster awareness is opt-in via YantrikDB

**Error Responses**: All endpoints return consistent JSON error format:
```json
{
  "error": "error_type",
  "message": "Human-readable description"
}
```

---

## Quick Start

1. Clone repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure database connection (and optionally `YANTRIK_DB_URL` / `YANTRIK_DB_API_KEY` for cluster health—see **Optional YantrikDB (cluster health)**)
4. Run: `uvicorn app.main:app --reload`
5. Test: `curl http://localhost:8000/health`

**Next**: Send your first capability routing request to `/v1/decide`.
