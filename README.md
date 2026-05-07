# WisePick

<b>🚀🚀🚀 2026-05-07 | WPDA（WisePick Decision API）v0.1.0 🚀🚀🚀</b>

> **WisePick does not recommend apps to humans.**
> **It routes executable capabilities to agents.**

> **智选不是给人类推荐工具。**
> **而是给 Agent 路由可执行能力。**
 
---

## 🛡️ Decision Infrastructure for AI Agents

## 🛡️ AI Agent 的决策基础设施

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

Most AI agents fail not because of weak models,
but because of poor capability routing.

大多数 Agent 的失败，
不是因为模型不够强，
而是因为不会选择正确能力。

Common problems:

* Blind capability search
* Trial-and-error execution
* No execution feedback loop

常见问题：

* 盲目遍历能力
* 反复试错执行
* 没有反馈闭环

WisePick replaces guessing with learned routing.

智选用“数据驱动能力路由”替代盲目猜测。

---

## 🧠 How It Works | 工作原理

### Capability Matching

任务 → 能力标签

```text
task → capabilities
```

---

### Capability Scoring

Each ECU is scored using:

* capability_match
* execution_success_rate
* bootstrap_weight

```text
score =
capability_match       * 0.70 +
execution_success_rate * 0.20 +
bootstrap_weight       * 0.10
```

---

### Feedback Loop

```text
decision
→ execution
→ feedback
→ capability_stats
→ next decision
```

The system learns from real execution outcomes.

系统基于真实执行结果持续优化能力路由。

---

## 🦜 Semantic Upgrade | 语义升级

WisePick evolved from:

```text
tool selection
→ executable capability routing
```

| Legacy         | New                      |
| -------------- | ------------------------ |
| tool_key       | capability_id + provider |
| Tool-centric   | Capability-centric       |
| Tool selection | Capability routing       |

---

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

Agent sees:

```text
audio_transcription
```

not:

```text
"Feishu Minutes"
```

Agent 看到的是“能力”，
而不是某个具体产品名字。

---

## ⚡ Why WisePick | 为什么用智选

### Deterministic

Always return one best executable capability.

始终返回一个最优可执行能力。

---

### Self-improving

Routing improves through execution feedback.

基于真实执行反馈持续优化。

---

### Observable

Every routing decision is traceable.

每次能力路由都可追踪。

---

## 🧪 Agent Workflow | Agent 工作流

```text
1. Ask WisePick for capability routing
2. Receive ECU
3. Map ECU → local API / MCP / skill
4. Execute
5. Send feedback back to WisePick
```

```text
1. 请求能力路由
2. 获取 ECU
3. 映射 ECU → 本地 API / MCP / 技能
4. 执行
5. 回传执行反馈
```

WisePick does not execute tasks.

It provides:

* decision
* routing
* execution learning

智选不负责执行。

智选负责：

* 决策
* 路由
* 执行反馈学习

---

## 🧱 Architecture | 架构

```text
decision_engine.py
→ capability router

api_tool_specs
→ executable capability registry

tool_stats
→ execution performance memory

feedback
→ learning loop
```

---

## 🔮 Vision | 愿景

Today:

```text
local execution learning
```

Tomorrow:

```text
shared decision memory
```

Instead of every agent repeating the same trial-and-error,
execution outcomes can become shared capability experience.

与其让每个 Agent 重复踩坑，

不如让真实执行结果，
逐渐沉淀为共享决策经验。

---

**From prompt guessing → to collective decision memory**

**从 Prompt 猜测 → 到共享决策记忆**
