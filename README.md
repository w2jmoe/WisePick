<img src="./logo.png" align="left" height="40" alt="WisePick logo" />

# WisePick

<br clear="all" />

[![GitHub stars](https://img.shields.io/github/stars/w2jmoe/WisePick?style=flat-square)](https://github.com/w2jmoe/WisePick/stargazers)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](./LICENSE)
[![Follow on X](https://img.shields.io/badge/Follow-%40w2jmoe-000000?style=flat-square&logo=x)](https://twitter.com/w2jmoe)

<img width="1943" height="800" alt="WisePick contrast flowchart" src="https://github.com/user-attachments/assets/30a0d5a1-42df-4732-812e-a83a1cb5e520" />

---

**🚀 WisePick Decision API (WPDA) v0.1.3 — The deterministic scaffold for agentic capability routing.**

**智选决策 API（WPDA）v0.1.3 — 面向 Agent 能力路由的确定性脚手架。**

> WisePick does not recommend apps to humans. It routes executable capabilities to agents.

> 智选不向人类推荐应用；它为 Agent 路由可执行能力。

---

## 🛡️ Decision Infrastructure | 决策基础设施

From intent → one executable capability unit (ECU).

输入意图 → 单一可执行能力单元（ECU）。

```text
Executable Capability Unit (ECU)

A standardized executable capability an agent can route, invoke, and learn from.

可执行能力单元（ECU）：可被路由、调用并通过反馈学习的标准化能力抽象。

```

---

## ❓ What Problem It Solves | 解决什么问题

Most agents fail from poor capability routing, not weak models.

多数失败来自能力路由失准，而非模型能力不足。

- Blind capability search · 盲目遍历能力
- Trial-and-error execution · 反复试错执行  
- No execution feedback loop · 缺少反馈闭环

WisePick replaces guessing with learned routing.

智选用数据驱动的能力路由替代猜测。

---

## 🚀 Quick Start | 快速启动

Configure `DATABASE_URL` in `.env` (see [.env.example](./.env.example)). Full API and ops detail: [README_API.md](./README_API.md).

在 `.env` 中配置 `DATABASE_URL`（参考 [.env.example](./.env.example)）。完整接口与运维说明见 [README_API.md](./README_API.md)。

```bash
pip install -r requirements.txt
```

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Smoke test:

```bash
curl -s http://localhost:8000/health
```

---

## ⚡ Why Integrate WisePick | 为什么接入智选

- Lower cost and latency by cutting trial-and-error.
更低成本与延迟：减少无效试错与 Token 浪费。
 
- Deterministic selection: one best ECU per decision.
确定性输出：每次决策对应单一最优 ECU。

- Self-evolving loop: routing improves from execution feedback.
自进化闭环：执行反馈持续修正路由统计。

---

## 📜 Performance | 性能报告

Production-oriented routing: under high load, sub-millisecond average latency on the isolated scaffold. Benchmarks: [STRESS_TEST_RESULTS.md](./docs/STRESS_TEST_RESULTS.md).

面向生产的确定性路由；隔离脚手架下平均亚毫秒级延迟。基准数据见 [STRESS_TEST_RESULTS.md](./docs/STRESS_TEST_RESULTS.md)。

---

## 🔌 Integration | 集成接入

WisePick is a **stateless decision layer**: `/v1/decide` maps intent → ECU only; it does not retain execution state. Run tools in your runtime, then **POST `/v1/feedback`** to close the loop.

**无状态决策层：** `/v1/decide` 仅完成意图 → ECU 映射；**不保存**执行状态。能力在你侧执行后，通过 **`/v1/feedback`** 回传结果。

**Prerequisite:** Deploy and run the API on your infrastructure ([deployment guide](./README_API.md#quick-start)).

**前提条件：** 自托管部署并完成启动（[README_API.md — 部署与运行](./README_API.md#quick-start)）。

```python
import requests

BASE_URL = "http://localhost:8000"  # replace with your host

decision = requests.post(
    f"{BASE_URL}/v1/decide",
    json={"task": "Generate a technical summary"},
).json()

# Execute locally: your_agent.run(decision["capability_id"], decision["provider"])

requests.post(
    f"{BASE_URL}/v1/feedback",
    json={"decision_id": decision["decision_id"], "success": True},
)
```

---

## 🧠 How It Works | 工作原理

### Capability Matching | 能力匹配

Task text → capability labels derived from bootstrap rules.

任务文本 → 由引导规则得到能力标签。

```text
task → capabilities

```

### Capability Scoring | 能力评分

```text
score =
capability_match       * 0.70  (语义匹配度)
execution_success_rate * 0.20  (历史成功率)
bootstrap_weight       * 0.10  (初始权重 / 冷启动偏好)

```

### Optional YantrikDB | 可选 YantrikDB

*Enterprise cluster awareness · 企业级集群感知*

Optional integration via `YANTRIK_DB_URL` (and optional `YANTRIK_DB_API_KEY`): reads YantrikDB `/v1/health`, may scale ECU scores under high replication lag—no primary schema change.

可选接入：读取 YantrikDB `/v1/health`，复制滞后过高时可缩放 ECU 分数；**不修改**主库 Schema。

### Feedback Loop | 反馈闭环

```text
decision → execution → feedback → capability_stats → next decision

```

Routing updates from real execution outcomes.

路由统计随真实执行结果更新。

### Components | 核心组件

- **Routing core** (`decision_engine`) — Task → ECU scoring and selection. · **路由核心** — 任务评分与 ECU 选择。
- **Capability registry** (`api_tool_specs`) — Enabled providers, capability tags, bootstrap weights. · **能力注册表** — 可用 provider、标签与冷启动权重。
- **Execution memory** (`tool_stats`, `feedback`) — Success rates and outcomes for closed-loop learning. · **执行记忆** — 成功率与反馈闭环。

---

## 🦜 Semantic Upgrade | 语义升级

WisePick evolved from `tool selection` → `executable capability routing`.

演进路径：从「选工具」到「可执行能力路由」。

| Legacy · 传统 | New · 智选 |
| --- | --- |
| `tool_key` | `capability_id` + `provider` |
| Tool-centric | Capability-centric |
| Tool selection | Capability routing |

### Example ECU Response | ECU 响应示例

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

Program against capabilities, not product names.

对「能力」编程，不对「产品名」编程。

---

## 🧪 Agent Workflow | Agent 工作流

```text
Ask WisePick for routing        → 请求路由
Receive ECU                     → 获取 ECU
Map ECU → local API / MCP       → 映射到本地实现
Execute                         → 执行
Send feedback                   → 回传反馈

```

WisePick provides decision, routing, and execution learning—not task execution.

智选提供决策、路由与执行侧学习信号；**不替代**任务执行本身。

---

## 🔮 Vision | 愿景

**Today:** Local execution learning.  
**Tomorrow:** Shared decision memory.

**当下：** 本地执行反馈驱动学习。  
**下一步：** 共享决策记忆。

Execution outcomes become portable capability experience—not repeated trial and error.

执行结果沉淀为可迁移的能力经验，而非重复试错。

---

## 🤖 Agent Runtime Integration | 运行时集成

Machine-readable contract and runtime loop: [AGENTS.md](./AGENTS.md).

机器可读的集成语义与运行时闭环见 [AGENTS.md](./AGENTS.md)。

---

## 🗺️ Roadmap | 路线图

- **✅v0.1**: Core Capability Routing · 核心路由层实现
    Sub-millisecond isolated core latency.
    ECU protocol & feedback loop logic.
- **🔄v0.2**: Agentic Workflow Routing · 复杂 Agent 流转路由支持（从单点路由向多步协同演进）
- **🔄v0.3**: Collective Decision Memory · 集体决策记忆（让真实的执行结果沉淀为可复用的路由经验）
- **🔄Ongoing**: ECU Ecology · 持续扩展主流 MCP 与 API 能力库，构建最全的可执行能力索引

---

## 🤗 Feedback & Integration | 反馈与集成

Share use cases, routing results, or failure reports.

欢迎反馈接入场景、路由结果或失败案例。

- **Issues:** [GitHub Issues](https://github.com/w2jmoe/WisePick/issues)
- **Email:** [w2jmoe@gmail.com](mailto:w2jmoe@gmail.com)

**Every routing decision is observable, feedback-driven, and reproducible.**
**每一次路由决策可观测、可反馈、可复现。**

**Every decision sharpens the path to perfect agency.**
**每一次决策，都在打磨通往完美能动性的路径。˗ˋˏ( ´͈ ᗜ `͈ )ˎˊ˗**
