# Prompt 发布后效果观察

FinCredit Copilot v1.0 在 Prompt 四眼发布流程之外，补上“发布后是否有可审计观察依据”的闭环。它记录的是**人工审批工作流结果**，不是模型正确率、客户违约标签、模型训练标签，更不是可用于自动批准、拒绝或退回授信申请的信号。

## 结果关联链

```text
冻结 Prompt（ID + 版本 + 内容）
  -> 预审 Agent Run
  -> 预审报告（含 Run ID）
  -> 提交审批任务（报告 SHA-256 锁定）
  -> 最终人工审批
  -> agent_run_workflow_outcomes（任务、报告哈希、Run、Prompt、人工结果）
```

最终审批在更新审批任务和申请状态的**同一 SQLite 事务**中写入结果记录。若职责分离、报告哈希或并发状态校验失败，审批不会提交，结果记录也不会产生。退回、拒绝和批准均会记录；退回后重新预审、重新提交会关联到新报告中的新 Run，保留完整历史。

历史报告若没有可解析的 Agent Run 或 Prompt 快照，仍可以正常审批，但不会被错误归因到某个 Prompt 版本。

## 观测指标与解释边界

`GET /v1/observability/prompt-performance?limit=200` 仅限 `compliance_admin` 调用，返回最近完成 Run 的以下分群：

| 字段 | 含义 |
| --- | --- |
| `task`、`prompt_id`、`prompt_version` | 运行时冻结的任务与 Prompt 身份 |
| `run_count` | 该 Prompt 组中完成的 Run 数 |
| `feedback_*` | 已提交人工复核的数量、覆盖率、采纳率和修订率 |
| `workflow_outcome_*` | 已完成最终人工审批的数量和相对 Run 的覆盖率 |
| `human_decision_counts` | 人工 `approved`、`rejected`、`returned` 计数 |
| `assessment` | 样本不足或 `observed_only`；永不代表 Prompt 健康、准确或可自动决策 |

`FINCREDIT_PROMPT_OUTCOME_MIN_SAMPLES` 默认是 `10`，仅决定分群何时从“工作流样本不足”变为“仅观察”。达到阈值不会自动激活/回滚 Prompt、创建漂移告警、修改规则、训练模型或改变授信结论。

合规复盘应把该数据与脱敏回放、离线评测、证据质量、反馈内容、业务规则变更和人工案例抽检一起分析。人工批准/拒绝包含客户材料、规则和人工判断等多重因素，不能被简化为 Prompt 的因果效果或拿来比较客户风险。

## API 与审计

| API / 事件 | 用途 |
| --- | --- |
| `GET /v1/observability/prompt-performance` | 查看分群观察报告；写入 `prompt_performance_viewed` 审计事件 |
| `GET /v1/observability/agent-metrics` | 工作台复用的综合指标，其中包含 `prompt_performance` |
| `prompt_workflow_outcome_recorded` | 在最终人工决策事务内追加的哈希链审计事件；只含任务、Prompt 身份与人工结果，不复制客户资料、报告正文或 Prompt 正文 |

生产环境应把指标导出到企业可观测平台，并为 Prompt 变更建立人工发布后复盘、灰度、回滚和责任人流程。该本地实现是审计与契约基线，不替代长期贷款表现监控、偏差/公平性评估或独立模型风险管理。
