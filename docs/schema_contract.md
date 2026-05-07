## WisePick API - Final Locked Schema Contract

I've created a definitive schema specification that resolves all inconsistencies and establishes a stable foundation for PostgreSQL migration. The schema is now **LOCKED** and ready for production use.

### Key Resolutions Applied:

1. **âœ?Timezone Standardization**: All `created_at` fields now use consistent UTC timezone handling
2. **âœ?JSON Type Consistency**: All JSON fields use SQLAlchemy `JSON` (database-agnostic)
3. **âœ?NOT NULL Field Coverage**: All required fields have explicit default values
4. **âœ?API Endpoint Consistency**: Unified response formats across all endpoints
5. **âœ?Duplicate Logic Removal**: Eliminated unused tables and inconsistent fields

### Schema Stability Guarantees:

- **No breaking changes** required before PostgreSQL migration
- **Database-agnostic design** compatible with SQLite and PostgreSQL
- **Complete field coverage** with explicit handling for all NOT NULL constraints
- **Consistent API contracts** with validated request/response schemas

This schema contract represents the **final stable state** of the WisePick API database and API design. All identified risks have been mitigated, and the system is now ready for scaling and production deployment.

---

## 7. Future Schema Evolution (v1+)

The following metrics will be added to support advanced capability routing:

### **Planned New Fields for `tool_stats` (or `capability_stats`)**

| Field | Type | Purpose |
|-------|------|---------|
| `avg_latency_ms` | INTEGER | Average execution latency for capability selection |
| `p95_latency_ms` | INTEGER | 95th percentile latency for QoS guarantees |
| `execution_cost` | DECIMAL | Cost per execution (tokens, API calls, etc.) |
| `stability_score` | DECIMAL | Consistency of execution success (0.0-1.0) |
| `capability_tags` | JSON | Semantic tags for capability clustering |
| `embedding_vector` | VECTOR | For semantic similarity matching (future) |

### **Purpose**

These metrics enable Agent-driven capability routing based on:
- **Latency requirements**: Choose faster capabilities for time-sensitive tasks
- **Cost optimization**: Select cost-effective providers for the same capability
- **Quality assurance**: Route to more stable capabilities for critical operations
- **Semantic matching**: Find capabilities by meaning, not just keywords

### **Implementation Note**

These fields are NOT included in v0 to maintain minimalism.
They will be added incrementally as the system evolves toward
execution-data-driven capability routing.

Current v0 focuses on: `capability_match + execution_success_rate + bootstrap_weight`
Future v1+ will add: `latency + cost + stability + semantic_similarity`

---

## 8. Semantic Upgrade: Tool â†?Capability

WisePick v0.1+ has completed the semantic migration from **tool_key-driven** to **capability_id-driven** routing:

### **Legacy vs New Semantic Layer**

| Legacy (v0) | New (v0.1+) | Meaning |
|-------------|-------------|---------|
| `tool_key` | `capability_id` + `provider` | What to execute + Who provides it |
| Tool selection | Capability routing | Intent â†?Executable unit |
| Tool-centric | Capability-centric | Agent execution perspective |

### **Backward Compatibility Strategy**

- âœ?`tool_key` field preserved in all API responses
- âœ?Existing integrations continue to work unchanged
- âœ?New `capability_id` field for agent execution planning
- âœ?No database schema changes required
- âœ?No breaking changes to existing functionality

### **API Response Evolution**

**Legacy Response (v0):**
```json
{
  "tool_key": "feishu_minutes",
  "confidence": 0.87
}
```

**New Response (v0.1+):**
```json
{
  "capability_id": "audio_transcription",
  "provider": "feishu_minutes", 
  "execution_type": "api",
  "tool_key": "feishu_minutes",
  "confidence": 0.87
}
```

### **Key Insight**

Agents don't care about brand names ("Feishu Minutes").
Agents care about: **Can I execute this capability? Will it work? What's the cost?**

This semantic upgrade enables agent-centric execution planning while maintaining full backward compatibility.
