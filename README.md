<div align="center">

<img src="./logo.png" height="120" alt="WisePick logo" />

# WisePick | 智选

**The Deterministic Scaffold for Agentic Capability Routing | 面向 Agent 能力路由的确定性脚手架**

[![GitHub stars](https://img.shields.io/github/stars/w2jmoe/WisePick?style=flat-square)](https://github.com/w2jmoe/WisePick/stargazers)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](./LICENSE)
[![Follow on X](https://img.shields.io/badge/Follow-%40w2jmoe-000000?style=flat-square&logo=x)](https://twitter.com/w2jmoe)

<img width="100%" alt="WisePick contrast flowchart" src="https://github.com/user-attachments/assets/30a0d5a1-42df-4732-812e-a83a1cb5e520" />

</div>

---

**🚀 WisePick Decision API (WPDA) v0.1.8**

> WisePick does not recommend apps to humans. It routes executable capabilities to agents at 0.0s latency.  
> 智选不向人类推荐应用；它为 Agent 提供 0.0s 延迟的确定性决策路由。

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

* Blind capability search · 盲目遍历能力
* Trial-and-error execution · 反复试错执行
* No execution feedback loop · 缺少反馈闭环

WisePick replaces guessing with learned routing.

智选用数据驱动的能力路由替代猜测。

---

## 🚀 Quick Start | 快速启动

> **⚠️ Production Deployment Requirement:** WisePick API is **core infrastructure** for your production product and must be deployed independently in your production environment. Local testing is for logic validation only. When you ship, include the WisePick API Server in your production containerized deployment manifest. Agents without an online API revert to inefficient stochastic routing and lose determinism.
>
> **⚠️ 生产部署要求：** WisePick API 是您生产产品的**核心基础设施**，必须在生产环境中独立部署。本地测试仅用于验证逻辑；发布产品时，请务必将 WisePick API Server 纳入您的生产容器化部署清单。未部署在线 API 的 Agent 将回退至低效随机路由，失去确定性。

### 1. 部署决策服务 (Server)
Deploy the WisePick API locally. 
部署本地智选 API 服务。

```bash
# 1. Clone & Config
cp .env.example .env
# Configure DATABASE_URL in .env

# 2. Start Service
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

```

### 2. 接入 SDK (Integration)

> Check out the [15-Minute Developer Integration Guide](./README_API.md#15-minute-integration-checklist) for rapid SDK setup, `tool_choice` hard-injection, and full-loop feedback implementation.

> 查看 [15分钟开发者接入指南](./README_API.md#15-minute-integration-checklist)，获取 SDK 快速接入、`tool_choice` 硬强制注入与反馈闭环全链路实现方案。 

---

## ⚡ Why Integrate WisePick | 为什么接入智选

* Lower cost and latency by cutting trial-and-error.
更低成本与延迟：减少无效试错与 Token 浪费。
* Deterministic selection: one best ECU per decision.
确定性输出：每次决策对应单一最优 ECU。
* Self-evolving loop: routing improves from execution feedback.
自进化闭环：执行反馈持续修正路由统计。

---

## 📜 Performance & Cost Benchmarks | 性能与成本报告

Production-oriented deterministic routing vs. native LLM tool-calling. Tested inside a Hermes-style agent runtime.
面向生产的确定性路由与原生 LLM 工具调用的对比测试。已在 Hermes 类 Agent 运行时中完成验证。

### Runtime Efficiency | 运行时效率提升

| Metrics | Native LLM Calling | WisePick Router | Optimization |
| --- | --- | --- | --- |
| **Tool Calls** | Baseline | **~35% fewer** | Avoid redundant & hallucinated calls |
| **Execution Path** | Baseline | **~27% shorter** | Fast convergence, eliminate infinite loops |
| **Core Latency** | Variable | **Sub-millisecond** | Non-blocking decision making |
| **API Token Cost** | High | **Drastically Reduced** | Zero prompt bloat across long sessions |

### Key Capabilities | 核心优势

* **Zero-Latency Gatekeeping**: Sub-millisecond average latency under isolated routing-core stress testing. (隔离路由核心压测下平均亚毫秒级延迟)
* **Anti-Loop Depth**: Stabilizes execution across 20+ mixed-tool tasks without infinite loops. (在 20+ 混合工具任务下稳定运行，彻底消除无限循环路径)

Benchmark scripts & instrumentation: [BENCHMARK](./benchmark/) | [STRESS_TEST_RESULTS.md](./docs/STRESS_TEST_RESULTS.md)

---

## 🔌 Integration & Router Specification | 集成与路由规范

WisePick acts as a stateless decision layer. You own the execution; we provide the routing.

无状态决策层：仅负责意图路由，不保存执行状态。

* **For Human Builders / 面向人类开发者 ([README_API.md](./README_API.md)):**
SDK integration, programmatic turn interception, multi-turn lock release, and execution hook feedback closure.
SDK 代码集成、首轮意图拦截、多轮强制解锁以及执行钩子反馈闭环。
* **For AI Agents & Automation / 面向智能体与自动配置 ([AGENTS.md](./AGENTS.md)):**
Machine-readable `wisepick.agent.v1` manifest contract, protocol state machine mapping, and runtime environment declaration.
机器可读的声明式配置清单契约、协议状态机映射以及运行时环境依赖声明。

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

### Feedback Loop | 反馈闭环

```text
decision → execution → feedback → capability_stats → next decision

```

Routing updates from real execution outcomes.

路由统计随真实执行结果更新。

### Components | 核心组件

* **Routing Core (decision_engine)** Maps text input to ECU scoring matrices and outputs deterministic selections. (将输入任务转换为 ECU 评分并进行路由决策)
* **Capability Registry (api_tool_specs)** Manages target providers, capability definitions, and cold-start weights. (管理可用 Provider、能力标签及冷启动权重分配)
* **Execution Memory (tool_stats, feedback)** Tracks real-world error rates and response loops for reinforcement behavior. (存储执行成功率与反馈结果，支持闭环优化)

### Optional YantrikDB | 可选 YantrikDB

*Enterprise cluster awareness · 企业级集群感知*

Optional integration via `YANTRIK_DB_URL` (and optional `YANTRIK_DB_API_KEY`): reads YantrikDB `/v1/health`, may scale ECU scores under high replication lag—no primary schema change.

可选接入：读取 YantrikDB `/v1/health`，复制滞后过高时可缩放 ECU 分数；**不修改**主库 Schema。

### Optional Langfuse Telemetry | 可选 Langfuse 遥测

*Decoupled observability · 解耦可观测性*

Optional integration via `WISEPICK_LANGFUSE_PUBLIC_KEY` and `SECRET_KEY`: exports `mcp.route_decision.v1` telemetry via background thread—no impact on request latency.

可选接入：通过后台线程导出 `mcp.route_decision.v1` 遥测数据；**不影响**请求延迟。

---

## 🦜 Semantic Upgrade | 语义升级

WisePick evolved from `tool selection` → `executable capability routing`.

演进路径：从「选工具」到「可执行能力路由」。

| Legacy · 传统 | New · 智选 |
| --- | --- |
| `tool_key` | `capability_id` + `provider` |
| Tool-centric | Capability-centric |
| Tool selection | Capability routing |

## 🔬 Example ECU Response | ECU 响应示例

```json
{
  "decision_id": "dec_abc123def4567890",
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

智选提供决策、路由与执行侧学习信号；**不替代**任务 execution 本身。

---

## 🔮 Vision | 愿景

**Today:** Local execution learning.

**Tomorrow:** Shared decision memory.

**当下：** 本地执行反馈驱动学习。

**下一步：** 共享决策记忆。

Execution outcomes become portable capability experience—not repeated trial and error.

执行结果沉淀为可迁移的能力经验，而非重复试错。

---

## 🗺️ Roadmap | 路线图

* **✅v0.1**: Core Capability Routing · 核心路由层实现
Sub-millisecond isolated core latency.
ECU protocol & feedback loop logic.
* **🔄v0.2**: Agentic Workflow Routing · 复杂 Agent 流转路由支持（从单点路由向多步协同演进）
* **🔄v0.3**: Collective Decision Memory · 集体决策记忆（让真实的执行结果沉淀为可复用的路由经验）
* **🔄Ongoing**: ECU Ecology · 持续扩展主流 MCP 与 API 能力库，构建最全的可执行能力索引

---

## 🤗 Feedback & Integration | 反馈与集成

Share use cases, routing results, or failure reports.

欢迎反馈接入场景、路由结果或失败案例。

* **Issues:** [GitHub Issues](https://github.com/w2jmoe/WisePick/issues)
* **Email:** w2jmoe@gmail.com

**Every routing decision is observable, feedback-driven, and reproducible.** **每一次路由决策可观测、可反馈、可复现。**

**Every decision sharpens the path to perfect agency.** **每一次决策，都在打磨通往完美能动性的路径。˗ˋˏ( ´͈ ᗜ `͈ )ˎˊ˗**

---

## 🌸 License | 许可协议

Apache License 2.0 — see [LICENSE](./LICENSE).
