# Prompt 人工处置作业单

FinCredit Copilot v1.2 把已独立确认的 Prompt 发布后观察建议，转换为可分派、可跟踪、可关闭的人工处置作业单。它解决“已发现问题但没有明确责任、时限和结论留痕”的协同缺口；作业单只记录治理过程，绝不自动回滚 Prompt、修改规则、调用模型或作出授信决定。

## 适用范围与状态机

只有状态为 `acknowledged`、且建议为 `investigate` 或 `rollback_recommended` 的观察复盘，才可创建一张作业单。每个复盘最多一张，避免同一证据产生彼此冲突的处置路径。

```text
已确认的 investigate / rollback_recommended 复盘
  -> 合规管理员创建 open 作业单（负责人、到期日）
  -> 指定负责人推进为 in_progress
  -> 指定负责人 resolved（结论类型 + 参考编号）
     或 cancelled（记录取消原因）
```

只有作业单 `owner_id` 所代表的合规负责人可以改变状态。可用迁移为 `open -> in_progress / cancelled` 与 `in_progress -> resolved / cancelled`；关闭或取消后不能重开。演示身份模式下，负责人必须是已登记的 `compliance_admin`。企业 OIDC 模式下，`owner_id` 是经 IdP 验签的业务主体标识；生产接入应将该标识与企业目录及合规岗位授权同步校验。

`resolved` 必须同时写入以下两项：

- `resolution_type`：`investigation_completed`、`monitoring_completed`、`rollback_draft_created` 或 `no_change_justified`；
- `resolution_reference`：可在企业治理系统追溯的结论、评测、变更或回滚草稿编号。

`rollback_draft_created` 只是证明负责人创建了候选草稿。该草稿仍须走既有 Prompt 四眼审批；作业单状态变化不会自动激活、退役或回滚任何 Prompt。

## 数据、审计与到期边界

作业单保存复盘 ID、冻结的 Prompt 任务/版本/ID、建议类型、负责人、到期日、状态、创建/关闭操作者与时间，以及关闭结论的最小参考信息。它不保存申请号、客户、材料、报告正文、模型 Prompt 正文、模型输出或复盘快照正文。

读取列表时服务依照 `FINCREDIT_POLICY_TIMEZONE` 计算 `on_track`、`due_today`、`overdue` 或 `closed` 到期状态。当前实现展示与审计这些状态，不会自行发送通知、变更负责人或关闭工单；生产环境应将到期事项接入企业工单、值班或通知系统，并保留同步失败告警。

创建和状态变更分别写入全局哈希审计链：

- `prompt_remediation_case_created`
- `prompt_remediation_case_status_updated`

每次状态变更还会追加一条不可覆盖的作业单事件，保留来源状态、目标状态、评论、操作者和时间。

## API

所有接口都要求 `compliance_admin`；更改状态还要求当前身份与 `owner_id` 精确一致。

| API | 用途 |
| --- | --- |
| `POST /v1/observability/prompt-performance/{task}/{version}/reviews/{review_id}/remediation-cases` | 为已确认的可处置复盘创建唯一作业单，提交 `owner_id` 与 `due_date`（`YYYY-MM-DD`） |
| `GET /v1/observability/prompt-remediation-cases?status=open` | 查询作业单、到期状态及按状态汇总 |
| `GET /v1/observability/prompt-remediation-cases/{case_id}` | 查询单张作业单与关闭结论 |
| `GET /v1/observability/prompt-remediation-cases/{case_id}/events` | 查询追加式状态事件 |
| `POST /v1/observability/prompt-remediation-cases/{case_id}/status` | 由负责人提交 `in_progress`、`resolved` 或 `cancelled` 与处置评论；关闭时附加结论类型和参考编号 |

作业单不是通用写操作入口。任何实际 Prompt 变更仍应通过 [Prompt 发布治理](prompt-governance.md)，任何实际规则变更仍应通过 [政策规则发布生命周期](policy-rule-lifecycle.md)，任何授信决定仍只能由既有人工审批状态机处理。
