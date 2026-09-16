# 信贷数据中台

FinCredit Copilot v0.8 将原有面向单一应用的本地数据仓储升级为可治理的数据中台基线，并将最小化规范客户画像作为 Agent 的只读工具上下文。它不是把 CRM、核心信贷、征信和 OA 的数据无差别复制到一个数据库，而是提供一条受控路径：**数据契约决定可接入的结构与来源，质量规则决定能否发布，规范数据服务提供最小权限读取，血缘与审计证明数据如何进入系统。**

## 能力边界

| 能力 | 当前实现 | 生产演进 |
| --- | --- | --- |
| 数据目录/契约 | 版本化 SQLite 目录，字段、类型、业务键、分级、来源白名单、内容哈希 | Schema Registry 与企业元数据目录同步 |
| 数据接入 | 受控 REST 批次、载荷指纹、原子发布/拒绝回执 | API Gateway + Kafka/CDC/ELT 编排、幂等键和服务账号 |
| 数据质量 | 完整性、类型一致性、批内业务键唯一性 | DQ 平台、跨源对账、SLA、异常告警和人工处置 |
| 规范层 | 按组织、实体类型、业务键维护当前视图并保留历史；Agent 上下文标注记录时效和跨源字段冲突 | 受管 PostgreSQL/湖仓、SCD 策略和主数据匹配 |
| 血缘和审计 | 独立 SHA-256 血缘链 + 现有全局审计哈希链 | 企业血缘图谱、WORM/SIEM、数据保留和删除证明 |

当前启动时内置两个脱敏演示契约：`DC-CRM-CUSTOMER`（`crm` 来源）和 `DC-CORE-APPLICATION`（`core_credit` 来源）。内置契约只描述数据结构，不自动同步或替换现有授信申请库。

## 数据模型

```text
data_contracts (控制面)
  └─ 一个 ID 的一个 active 版本：业务域、实体类型、业务键、字段类型、分级、来源白名单、hash

data_ingestion_batches (接入回执)
  ├─ data_quality_results (完整性 / 类型 / 业务键唯一性)
  └─ data_lineage_events (来源 -> canonical.<domain>.<entity> 的哈希链)

data_records (服务面)
  └─ organization_id + entity_type + business_key 的 current 版本；历史记录保留但不由默认 API 返回
```

原始 JSON 请求不会被复制进接入批次、质量结果、血缘事件或审计事件；这些治理记录只保存计数、字段名/行号示例和 SHA-256 指纹。规范数据本身按契约分级保存在 `data_records`，生产部署必须设置数据库加密、访问策略、脱敏和保留规则。

## 角色和隔离

- 合规管理员：发布契约、运行受控接入、查询批次/质量/血缘、验证血缘链；可跨组织进行治理查询。
- 风险经理、审批人：读取数据目录和本组织的规范数据。指定其他组织会返回 `403`。
- 客户经理：不能读取数据中台的规范数据或治理信息。

机器接入在生产中应使用专用 OIDC 服务账号及最小角色映射，不能复用个人管理员身份。当前演示阶段由合规管理员角色执行，以确保所有写入经过治理权限。

## API

| API | 权限 | 作用 |
| --- | --- | --- |
| `GET /v1/data-platform/catalog` | 风险/审批/合规 | 查询生效数据契约；`include_retired=true` 仅合规可用 |
| `POST /v1/data-platform/contracts` | 合规 | 发布不可覆盖的契约版本，并退役同 ID 的旧生效版 |
| `POST /v1/data-platform/ingestion-batches` | 合规 | 执行来源校验、质量检查并原子发布或生成拒绝回执 |
| `GET /v1/data-platform/batches` | 合规 | 查询接入批次摘要 |
| `GET /v1/data-platform/batches/{batch_id}` | 合规 | 查询批次及全部质量结果 |
| `GET /v1/data-platform/records/{entity_type}` | 风险/审批/合规 | 查询当前规范数据，自动执行组织范围约束 |
| `GET /v1/data-platform/lineage` | 合规 | 查询接入血缘事件 |
| `GET /v1/data-platform/lineage/integrity` | 合规 | 验证数据血缘哈希链 |

发布新契约的请求示例：

```json
{
  "id": "DC-RISK-SIGNAL",
  "version": "1.0.0",
  "domain_name": "risk",
  "entity_type": "risk_signal",
  "schema": {
    "business_key": "signal_id",
    "required_fields": ["signal_id", "score"],
    "field_types": {"signal_id": "string", "score": "number"}
  },
  "classification": "restricted",
  "description": "风险信号数据契约，统一风险评分和来源追踪字段。",
  "allowed_sources": ["risk_engine"]
}
```

同一契约 ID/version 不能覆盖；要修改结构，发布新版本，例如 `1.1.0`。当前实现会原子退役旧版本，因此接入方应先完成兼容性评估和回放验证，再发布新版。

## 质量和可追溯性

每批数据均运行以下阻断规则：

1. `DQ_REQUIRED_FIELDS`：所有契约必填字段均存在且非空。
2. `DQ_TYPE_CONFORMANCE`：出现的字段符合契约声明的 JSON 类型。
3. `DQ_DUPLICATE_BUSINESS_KEY`：批次内业务键不重复。

任何规则失败，批次状态为 `rejected`，`accepted_count=0`，不会写入 `data_records`。系统仍保留质量结果、接入载荷哈希和血缘事件，便于上游修复重传。成功批次会关闭同一 `组织 + 实体类型 + 业务键` 的前一当前版本，再插入新的当前规范记录。

血缘事件使用前序事件哈希和规范事件内容计算 SHA-256；全局审计链则记录契约发布、批次接收/拒绝、读取和完整性检查。两条链都应在生产同步至不可变日志平台，SQLite 链仅用于演示和回归验证。

## 生产落地顺序

1. 先将本地 SQLite 业务库和数据中台表迁到受管 PostgreSQL，按组织实施行级安全、备份、加密和密钥轮换。
2. 为 CRM、核心信贷、风险、征信和 OA 定义契约责任人、兼容性策略、数据分级、保留期限和删除流程。
3. 使用 CDC/Kafka/编排器接入，加入 schema compatibility、幂等、死信队列、限流与重放；演示 REST 接口只保留给小批量治理验证。
4. 对接企业数据目录、血缘、数据质量告警、主数据、对象存储/WORM 和 SIEM；将数据质量从契约校验扩展到跨源对账和业务规则。
5. 在通过 DLP 与字段级授权评审后，再将规范数据以只读、最小化工具形式接入 Agent 上下文；不得把限制级原始数据直接发送到外部模型。
