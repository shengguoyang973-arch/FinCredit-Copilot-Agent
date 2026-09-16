# Prompt 发布治理

FinCredit Copilot v0.9 将 Prompt 当作影响授信辅助意见的受控运行时配置，而不是可由环境变量或代码热改的自由文本。系统只支持 `generate_brief` 和 `answer_question` 两个任务；每个任务的 v1 内置 Prompt 在首次启动时写入 `prompt_versions` 作为可追溯活动基线。

## 生命周期与边界

```text
active / retired Prompt
  -> 创建新版本草稿
  -> 提交复核
  -> 独立合规管理员批准或驳回
  -> approved: 原子退役旧 active 并激活候选
  -> rejected: 保留历史但绝不参与运行时选择
```

- 创建人和提交人不能审批自己的候选版本。
- 创建时保存任务、版本、内容、反馈编号、变更原因和 SHA-256 内容哈希；审批时重新计算哈希，篡改即拒绝。
- 每个候选必须保留人工授信决策边界、合法 JSON 约束和任务所需结构化字段。系统拒绝含“忽略…指令”覆盖措辞的内容。
- 只有 `active` 版本可被运行时读取。服务在构建 Agent 上下文时固定 Prompt 内容、ID、版本；执行中的 Run 不会受后来激活影响。
- 回滚从 `active` 或 `retired` 目标创建一个新草稿，不能直接重新激活历史版本。

## 人工反馈关联

草稿可在 `feedback_ids` 中关联已存在的 `AFB-*` 人工复核记录。系统验证每个编号存在，但不把反馈评论、客户资料或原始模型上下文复制到 Prompt 审计事件；审计只记录反馈计数、哈希、版本和状态。关联反馈为复核人提供变更依据，不会自动训练模型、改写规则或修改任一授信结论。

## API

所有接口均要求 `compliance_admin`。

| API | 作用 |
| --- | --- |
| `GET /v1/knowledge/prompts` | 查询活动 Prompt；`include_inactive=true` 返回所有状态版本 |
| `POST /v1/knowledge/prompts` | 创建草稿，输入任务、`vN` 版本、内容、可选反馈编号和变更原因 |
| `GET /v1/knowledge/prompts/{task}/versions/{version}/diff` | 获取候选哈希校验结果、基线版本、内容/反馈/原因差异摘要 |
| `POST /v1/knowledge/prompts/{task}/versions/{version}/submit` | 将草稿转换为 `pending_review` |
| `POST /v1/knowledge/prompts/{task}/versions/{version}/decision` | 独立复核并作出 `approved` 或 `rejected` 决定 |
| `POST /v1/knowledge/prompts/{task}/rollback` | 从已批准版本创建回滚草稿 |

最小草稿示例：

```json
{
  "task": "answer_question",
  "version": "v2",
  "content": "保留当前受控 Prompt 全文，并在不删除人工决策边界和 JSON 约束的前提下进行修订。",
  "feedback_ids": ["AFB-0123456789ABCDEF"],
  "rationale": "根据已复核的证据表达问题，补充事实、证据和人工后续动作的区分。"
}
```

示例中的 `content` 是说明性占位文本；实际请求必须包含完整、通过约束校验的 Prompt 正文。生产上线前还应通过脱敏回放、离线评测和发布门禁。

## 部署一致性

可选设置 `FINCREDIT_PROMPT_VERSION=vN` 作为部署断言：应用仅在当前已激活版本等于该值时继续调用 Prompt。该变量不能覆盖正文、选择退休版本或绕过审批；失配将以错误形式暴露，避免版本标签与实际内容不一致。
