# Prompt 发布后双人复盘

FinCredit Copilot v1.2 将“看到 Prompt 分群指标”升级为可审计的人机协同处置闭环。它固化的是无客户信息的聚合观察快照，并要求另一名合规管理员确认或驳回复盘建议；已确认的排查或受控回滚建议可进一步形成有人负责的处置作业单。该机制不自动激活/回滚 Prompt、不修改规则、不调用模型，也不作出任何授信决定。

## 状态机

```text
已达到最小人工工作流样本的 Prompt 分群
  -> 合规管理员创建 pending_review 观察快照
  -> 另一名合规管理员 acknowledged / rejected
  -> 若已确认且建议 investigate / rollback_recommended
       -> 可人工创建唯一处置作业单（负责人、到期日、状态、结论证据）
       -> 若需回滚，人工另行创建 Prompt 回滚草稿
       -> 既有四眼发布流程审批，才可能激活
```

复盘建议只有三种：

| 建议 | 含义 | 自动效果 |
| --- | --- | --- |
| `continue_monitoring` | 当前继续观察 | 无 |
| `investigate` | 建议排查 Prompt、检索、数据或业务流程 | 无 |
| `rollback_recommended` | 建议人工发起受控回滚评估 | 无；必须另走回滚草稿与四眼复核 |

创建人不能确认自己的复盘。复盘决定的 URL 必须与该 Prompt 任务和版本匹配，不能借其他路径处理同一记录。一次快照哈希只能发起一条复盘，避免同一证据被重复制造多条相互冲突的处置历史。

## 快照与数据边界

创建复盘时，服务重新计算最近观察窗口中目标 Prompt 的聚合数据，且只有 `workflow_outcome_count >= FINCREDIT_PROMPT_OUTCOME_MIN_SAMPLES` 才允许创建。快照包含：

- Prompt 任务、ID、版本和当前内容哈希；
- Run 数、人工反馈数量/覆盖率/采纳率/修订率；
- 最终人工审批工作流结果数量、覆盖率及批准/拒绝/退回计数；
- 窗口大小与最小样本阈值。

快照不会保存申请号、客户、材料、报告正文、人工评论、模型 Prompt 正文或模型输出。结果不是模型正确率、因果效果、贷款表现或训练标签；人工审批还受材料、规则、尽调和人员判断共同影响，不能单独归因给 Prompt。

## API

所有接口均要求 `compliance_admin`。

| API | 用途 |
| --- | --- |
| `GET /v1/observability/prompt-performance/{task}/{version}/reviews` | 获取版本的完整复盘历史及证据快照 |
| `POST /v1/observability/prompt-performance/{task}/{version}/reviews` | 基于当前窗口创建待独立复核的快照；提交建议与原因 |
| `POST /v1/observability/prompt-performance/{task}/{version}/reviews/{review_id}/decision` | 由另一名合规管理员 `acknowledged` 或 `rejected` |

创建和处理动作分别进入全局哈希审计链：`prompt_observation_review_created`、`prompt_observation_review_acknowledged`、`prompt_observation_review_rejected`。综合指标接口中的每个 Prompt cohort 只显示最新复盘的 ID、状态、建议和时间，不显示复盘原因或完整快照。

被独立确认且建议为 `investigate` 或 `rollback_recommended` 的复盘可创建一张唯一人工处置作业单。作业单只能由指定负责人推进或关闭；关闭时必须记录结论类型和参考编号。作业单是处置留痕，不会自动创建回滚草稿、激活/退役 Prompt、修改规则或改变授信状态，详见 [prompt-remediation.md](prompt-remediation.md)。

生产实施还应将 `investigate` 接入变更/事件工单，指定风险、合规、模型与数据责任人，并通过脱敏回放、离线评测、灰度和回滚演练验证处置结果。长期贷款表现、偏差与公平性评估须由独立模型风险管理流程承担，不能被本地观察快照替代。
