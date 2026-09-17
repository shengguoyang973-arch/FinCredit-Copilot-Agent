# 脱敏评测与灰度发布

v1.3 将 Agent 离线评测从内嵌样例提升为版本化脱敏数据集，并提供受四眼复核约束的灰度控制面。默认数据集位于 `demo_data/deidentified_agent_evaluation.json`；加载时校验数据集 ID、案例 ID、脱敏别名、直接标识模式、任务范围和内容哈希。

## 数据集与门禁

```powershell
python scripts\validate_evaluation_dataset.py
python scripts\evaluate_agents.py
python scripts\release_gate.py
```

评测集必须标记 `classification=deidentified`，使用 `EVAL-*` 申请标识与“脱敏企业-*”别名。发现身份证/统一社会信用代码/手机号等直接标识模式会拒绝加载。发布门禁继续检查准确率、证据召回、自动决策边界与 RAG 指标。

## 灰度状态机

```text
draft -> pending_review -> approved -> running -> passed -> promoted
                           \-> rejected        \-> failed -> rolled_back
```

创建人与提交人不能审批；创建人也不能最终推进或确认回退。执行阶段只在脱敏评测集上比较 candidate 与 baseline，检查准确率、证据召回、自动决策边界和相对回归。`traffic_percent` 是后续部署系统可读取的最大灰度上限，并不由本服务自动分流真实客户流量。

API 为 `POST /v1/release-canaries`、`/{id}/submit`、`/{id}/decision`、`/{id}/execute` 和 `/{id}/finalize`。即使状态为 `promoted`，仍只表示人工允许按既有部署、Prompt 四眼发布和变更流程继续推进；不会自动激活模型、Prompt、规则或授信动作。
