# WisePick
<img width="1943" height="800" alt="wisepick_contrast_flowchart" src="https://github.com/user-attachments/assets/f104df31-4164-458c-95ec-e8c4d4718f95" />

**🚀 WisePick Decision API (WPDA) v0.1.3** | 
**The Deterministic Scaffold for Agentic Capability Routing.**

> **WisePick does not recommend apps to humans.**
> **It routes executable capabilities to agents at 0.0s latency.**

> **智选不是给人类推荐工具。**
> **而是为 Agent 提供 0.0s 延迟的确定性决策路由。**

---

## 🛡️ Decision Infrastructure | 决策基础设施

**From intent → to one executable capability unit.**
**输入意图 → 输出可执行能力单元。**

```text
Executable Capability Unit (ECU)

A standardized executable capability
that an agent can:

- route
- invoke
- learn from

可执行能力单元（ECU）

一种标准化可执行能力，
Agent 可以：

- 路由
- 调用
- 学习

```

---

## ❓ What Problem It Solves | 解决什么问题

Most AI agents fail not because of weak models, but because of poor capability routing.

大多数 Agent 的失败，不是因为模型不够强，而是因为不会选择正确能力。

Common problems:

- **Blind capability search** (盲目遍历能力)
- **Trial-and-error execution** (反复试错执行)
- **No execution feedback loop** (没有反馈闭环)

WisePick replaces guessing with **learned routing**.
智选用“数据驱动能力路由”替代盲目猜测。

---

## ⚡ Why Integrate WisePick | 为什么接入智选

Lower Cost & Latency: Minimizes trial-and-error to save Tokens and execution time.

Deterministic Selection: Guarantees the single best executable capability unit (ECU).

Self-evolving Loop: Continuously optimizes routing through real execution feedback.

更低成本与延迟：大幅减少无效试错，节省 Token 消耗与执行时间。

确定性决策：确保输出唯一最优的可执行能力单元 (ECU)。

持续进化闭环：基于真实执行反馈，自动迭代路由准确度。

---

## 🚀 Performance | 性能报告

WisePick is built for production-grade reliability. Under 1,000+ RPS load, it maintains sub-millisecond (avg ~0.6ms) deterministic routing. See [Isolated Routing Scaffold Benchmark (P50/P95/P99)](./docs/STRESS_TEST_RESULTS.md).

---

## 🔌 Quick Integration (30s) | 快速接入（约 30 秒）

**WisePick is a stateless decision layer:** each `/v1/decide` call only maps intent → ECU (`capability_id`, `provider`, `decision_id`, …). It does **not** hold your execution state—you run tools locally, then **POST `/v1/feedback`** so routing can learn.

**WisePick 是无状态的决策层：** 单次 `/v1/decide` 只负责把意图映射成 ECU（`capability_id`、`provider`、`decision_id` 等）。**它不替你保存执行状态**——能力在你侧执行，再通过 **`/v1/feedback`** 回传结果以参与学习。

**Prerequisite:** Self-hosted deployment required—run the API locally or on your infrastructure ([deployment guide](./README_API.md#quick-start): install, env, `uvicorn`).

**前提条件：** WisePick 为自托管服务，请先在本地或自有服务器完成部署与启动（步骤见 [README_API.md 部署与运行](./README_API.md#quick-start)）。

```python
import requests

# Self-hosted API base URL (placeholder — replace with your deployment host/port)
BASE_URL = "http://localhost:8000"

# 1. Route: Get the best capability for the task
decision = requests.post(f"{BASE_URL}/v1/decide",
                         json={"task": "Generate a technical summary"}).json()

# 2. Execute: Your agent uses the routed ECU (capability_id + provider)
# result = your_agent.execute(decision['capability_id'], decision['provider'])

# 3. Feedback: Close the loop to let WisePick learn
requests.post(f"{BASE_URL}/v1/feedback",
              json={"decision_id": decision['decision_id'], "success": True})
```

---

## 🧠 How It Works | 工作原理

### Capability Matching | 能力匹配

任务 → 能力标签

```text
task → capabilities

```

### Capability Scoring | 能力评分

Each ECU is scored using:

```text
score =
capability_match       * 0.70  (语义匹配度)
execution_success_rate * 0.20  (历史成功率)
bootstrap_weight       * 0.10  (初始权重/冷启动偏好)

```

### Optional YantrikDB | 可选 YantrikDB

*Enterprise cluster awareness · 企业级集群感知*

WisePick can integrate with **YantrikDB** by setting `YANTRIK_DB_URL` (and optionally `YANTRIK_DB_API_KEY`). When configured, it reads cluster health from YantrikDB’s `/v1/health` and may scale ECU scores when replication lag is high—without changing your primary database schema.

配置 `YANTRIK_DB_URL`（及可选 `YANTRIK_DB_API_KEY`）后，WisePick 会从 YantrikDB 的 `/v1/health` 读取集群健康信号，并在复制滞后较高时对 ECU 分数做确定性调整；不修改主库 Schema。

### Feedback Loop | 反馈闭环

```text
decision
→ execution
→ feedback
→ capability_stats
→ next decision

```

The system learns from real execution outcomes.
系统基于真实执行结果持续优化能力路由。

### Components | 核心组件

- **Routing core** (`decision_engine`) — Task → ECU scoring and selection. · **路由核心** — 任务评分与 ECU 选择。
- **Capability registry** (`api_tool_specs`) — Enabled providers, capability tags, bootstrap weights. · **能力注册表** — 可用 provider、标签与冷启动权重。
- **Execution memory** (`tool_stats`, `feedback`) — Success rates and outcomes for closed-loop learning. · **执行记忆** — 成功率与反馈闭环。

---

## 🦜 Semantic Upgrade | 语义升级

WisePick evolved from:
`tool selection` → `executable capability routing`


| Legacy (传统)    | New (智选)                 |
| -------------- | ------------------------ |
| tool_key       | capability_id + provider |
| Tool-centric   | Capability-centric       |
| Tool selection | Capability routing       |


### Example ECU Response

```json
{
  "decision_id": "xxx",
  "capability_id": "audio_transcription",
  "execution_type": "api",
  "provider": "feishu_minutes",
  "tool_key": "feishu_minutes",
  "confidence": 0.87,
  "callable": true
}

```

**Programming against Capabilities, not Products.**
Agent 对“能力”编程，不对“产品名”编程。

---

## 🧪 Agent Workflow | Agent 工作流

```text
1. Ask WisePick for capability routing (请求能力路由)
2. Receive ECU (获取 ECU)
3. Map ECU → local API / MCP / skill (映射 ECU → 本地技能)
4. Execute (执行)
5. Send feedback back to WisePick (回传执行反馈)

```

WisePick does not execute tasks. It provides:

- **decision** (决策)
- **routing** (路由)
- **execution learning** (执行反馈学习)

---

## 🔮 Vision | 愿景

**Today:** Local execution learning
**Tomorrow:** Shared decision memory

Instead of every agent repeating the same trial-and-error, execution outcomes can become **shared capability experience**.

与其让每个 Agent 重复踩坑，不如让真实执行结果，逐渐沉淀为**共享决策经验**。

**From prompt guessing → to collective decision memory**
**从 Prompt 猜测 → 到共享决策记忆**

---

## 🤖 Agent Runtime Integration | 运行时集成

See [AGENTS.md](./AGENTS.md) for machine-readable integration semantics and runtime workflow.

---

## 🗺️ Roadmap | 路线图

- **v0.2**: Agentic Workflow Routing · 复杂 Agent 流转路由支持（从单点路由向多步协同演进）
- **v0.3**: Collective Decision Memory · 集体决策记忆（让真实的执行结果沉淀为可复用的路由经验）
- **Ongoing**: ECU Ecology · 持续扩展主流 MCP 与 API 能力库，构建最全的可执行能力索引

---

## 🤗 Feedback & Integration | 反馈与集成

If you integrate WisePick, feel free to share your use case, routing results, or failure cases.

欢迎接入智选 API。如果遇到 routing 问题、失败案例、或真实 Agent 使用场景，也欢迎反馈。

- **Issues**: GitHub Issues
- **Email**: [w2jmoe@gmail.com](mailto:w2jmoe@gmail.com)

**Every routing decision is observable, feedback-driven, and reproducible.**
**每一次路由决策可观测、可反馈、可复现。**

**Every decision sharpens the path to perfect agency.**
**每一次决策，都在打磨通往完美能动性的路径。˗ˋˏ( ´͈ ᗜ `͈ )ˎˊ˗**