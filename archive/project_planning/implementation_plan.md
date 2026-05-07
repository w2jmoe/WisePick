# WisePick API v0 Implementation Plan

## P0 - 收缩为最小闭�?
### 1. 固化唯一核心流程

- 保留 `POST /v1/decide`
- 新增 `POST /v1/feedback`
- 明确 v0 只返回决策，不负责执行工�?- 废弃或下�?`/decide` 这种 demo 风格重复接口

交付结果�?
- API 表面只剩一个决策入口和一个反馈入�?- README �?OpenAPI 文档口径一�?
### 2. 收缩响应体为最�?contract

`POST /v1/decide` 只保留：

- `decision_id`
- `tool_key`
- `reason`
- `confidence`
- `explain`
- `trace`

移除或标记内部字段：

- `agent_ready_output`
- `tool_call`
- `fallback_calls`
- `execution`
- 任何暗示 WisePick 负责执行工具的字�?
交付结果�?
- 决策响应足够小，方便审计和接�?
### 3. 将数据库模型对齐�?v0

优先落地�?
- `tools`
- `decisions`
- `feedback`
- `tool_stats` 视图

处理原则�?
- 优先修改现有模型，不重写整个仓库
- 老表�?`api_decision_logs`、`decision_dataset` 可先保留，但从主路径移除
- 新主路径只依�?v0 目标�?
交付结果�?
- 应用运行只依赖最小核心表

## P1 - 让规则透明且可冷启�?
### 4. 抽离 `bootstrap_rules.py`

把当前散落在 `decision_engine.py` 的关键词映射收敛到单独文件：

- versioned bootstrap rules
- 只做 capability 粗分�?- 每条规则有稳�?rule key

建议结构�?
```python
BOOTSTRAP_VERSION = "v0"

RULES = [
    {"key": "audio_to_transcription_v1", "keywords": ["audio", "meeting", "transcribe"], "capability": "transcription"},
]
```

交付结果�?
- bootstrap 被显式标记为 bootstrap
- 规则修改不会混在打分逻辑�?
### 5. 简化评分函�?
当前实现里的多段过滤与特殊分支较多，v0 建议压缩成：

1. 规则命中得到 capability
2. �?`tools` 里筛�?`enabled = true`
3. �?capability 过滤候�?4. 结合 `tool_stats.success_rate` �?`bootstrap_weight` 打分
5. 选第一�?
建议公式�?
```text
score = capability_match * 0.70
      + coalesce(success_rate, 0.50) * 0.20
      + bootstrap_weight * 0.10
```

交付结果�?
- 决策逻辑能在一个文件中完整审计

## P2 - 反馈闭环可验�?
### 6. 实现 `POST /v1/feedback`

请求字段建议�?
- `decision_id`
- `success`
- `latency_ms`
- `user_note`

服务端行为：

- 校验 `decision_id` 存在
- �?`decisions` 反查 `selected_tool_key`
- 写入 `feedback`
- 返回 `recorded=true`

交付结果�?
- 成功率不再写死在 `tools.success_rate`
- 历史成功率由真实反馈驱动

### 7. �?`tool_stats` 替代手写成功率字�?
建议�?
- `tools` 表不存最终真相式 `success_rate`
- 成功率从 `feedback` 聚合得出
- 决策时读�?`tool_stats`，无反馈则回退默认�?
交付结果�?
- 数据流更干净
- 审计时可以从原始反馈重新计算

## P3 - 仓库开源化整理

### 8. README 最小补�?
README 需要新增：

- WisePick �?scope �?non-goals
- 本地启动方式
- Supabase env 配置说明
- SQL schema 初始化方�?- decide �?feedback 示例
- 如何查看 `tool_stats`
- 指向 `architecture.md`

交付结果�?
- 首次访问仓库的人能在 5 分钟内理解项目边�?
### 9. 环境配置收敛

保留现有 `.env`，只补充最小必要项�?
- `DATABASE_URL`
- `APP_TITLE`
- `APP_VERSION`

如果后续�?Vercel，再补最少量运行配置，不引入额外配置矩阵�?
### 10. 部署结构保持极简

Vercel 方向只做最小适配�?
- 保持 `FastAPI` 主应用不�?- 增加极小入口文件即可
- 不引�?Celery、Redis、消息队列、Cron

交付结果�?
- 本地和云端共用一套核心代�?
## 建议修改顺序

1. 先定 `db_schema.sql`
2. 再收�?`app/schemas/decide.py` 和新�?`app/schemas/feedback.py`
3. 再改 `app/services/decision_engine.py`
4. 然后新增 `app/routers/feedback.py`
5. 最后更�?`README.md`

## 风险与取�?
- 风险：当前仓库已�?`api_decision_logs` �?`decision_dataset`，直接删可能影响现有 demo
- 取舍：第一阶段不强删旧文件，先把主路径切到 v0 新表
- 风险：当�?`success_rate` 写在工具表里，容易与真实反馈冲突
- 取舍：v0 �?`tool_stats` 为准，旧字段逐步退�?- 风险：规则过多会重新变复�?- 取舍：bootstrap 规则数量控制�?10 条以�?
## 完成定义
