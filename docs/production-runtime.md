# 生产运行：规则、数据中台、Embedding、pgvector 与 OIDC

FinCredit Copilot v0.6 提供五条可独立测试、但在生产共同受控的链路：政策规则发布生命周期、信贷数据中台、OpenAI Embedding + pgvector、企业 OIDC JWKS 验签和人工授信审批。`GET /ready` 会拒绝基础设施配置缺项，不会自动降级到演示实现。

## 生产配置模板

```text
FINCREDIT_ENVIRONMENT=production
FINCREDIT_IDENTITY_PROVIDER=oidc
FINCREDIT_OIDC_JWKS_URL=https://id.example.com/.well-known/jwks.json
FINCREDIT_OIDC_ISSUER=https://id.example.com/
FINCREDIT_OIDC_AUDIENCE=fincredit-api
FINCREDIT_OIDC_ALGORITHMS=RS256
FINCREDIT_OIDC_ROLES_CLAIM=roles
FINCREDIT_OIDC_ORG_CLAIM=organization_id
FINCREDIT_OIDC_NAME_CLAIM=name
FINCREDIT_OIDC_ROLE_MAPPINGS={"credit-risk-group":"risk_manager"}
FINCREDIT_OIDC_LEEWAY_SECONDS=30

FINCREDIT_EMBEDDING_PROVIDER=openai
FINCREDIT_EMBEDDING_MODEL=text-embedding-3-small
FINCREDIT_EMBEDDING_DIMENSIONS=256
OPENAI_API_KEY=<inject-from-secret-manager>

FINCREDIT_VECTOR_STORE_BACKEND=pgvector
FINCREDIT_PGVECTOR_CONNECTION=postgresql+psycopg://user:password@host:5432/fincredit
FINCREDIT_PGVECTOR_COLLECTION=fincredit_policy_chunks
FINCREDIT_POLICY_TIMEZONE=Asia/Shanghai
FINCREDIT_DATA_PLATFORM_MAX_BATCH_RECORDS=500
```

不要把密钥或带密码的连接串提交到 Git。应由 Secret Manager、Kubernetes Secret 或同等受控设施注入。

## 政策规则发布

规则不是 Python 表达式，不允许 `eval` 或任意代码。当前白名单解释器为：

| 类型 | 用途 | 允许的关键参数 |
| --- | --- | --- |
| `minimum` | 最低经营年限等准入下限 | `source=customer`、白名单 `field`、`minimum` |
| `ratio_cap` | 营收比例与绝对额度上限 | 白名单申请/客户字段、`ratio`、`absolute_cap` |
| `any_threshold` | 任一阈值触发人工审查 | 白名单字段、`gt/gte/lt/lte`、数值 |
| `required_materials` | 必需材料集合 | 材料类型到展示标签的映射 |

合规作者调用 `POST /v1/knowledge/rules` 创建不可变草稿，然后提交复核；另一名合规管理员才能批准或驳回。生效日不晚于当前日期时，批准事务先停用旧版本再启用新版本；未来日期版本进入 `scheduled`，到期后在规则读取边界原子切换。`GET /v1/knowledge/rules?include_inactive=true` 可查询全历史，审计链记录作者、提交人、复核人、决定和切换事件。规则若引用 `policy_id`，该条款会作为确定性强制证据加入 RAG Trace。

待复核版本保存 canonical SHA-256；审批时重新计算并拒绝已被修改的内容。复核人可先读取结构化 diff。回滚不会直接重启历史记录，而是从已批准版本复制出带原因的新草稿，再完整走一遍四眼流程。详细 API 见 [政策规则发布生命周期](policy-rule-lifecycle.md)。

发布前至少执行规则单元测试、脱敏回放和 `scripts/release_gate.py`。生产环境还应把计划生效扫描迁移到受监控的调度作业，并为逾期未审任务配置告警。

## 信贷数据中台

当前数据中台由数据控制面和数据服务面组成：

- 控制面：合规管理员发布不可覆盖的 `数据契约 ID + 版本`。契约声明领域、实体类型、业务键、必填字段、字段类型、数据分级和允许来源系统；新版本会退役旧生效版本。
- 接入面：`POST /v1/data-platform/ingestion-batches` 只接受绑定生效契约且来源在白名单中的批次。系统对载荷产生 SHA-256 指纹，执行完整性、类型一致性和批内业务键去重；任何失败都会拒绝整个批次，不发布部分记录。
- 服务面：`GET /v1/data-platform/records/{entity_type}` 返回当前规范记录。风险经理和审批人只能读取所属组织，合规管理员可做全局治理查询。
- 治理面：每个接入结果都写入质量回执、全局审计链和独立数据血缘哈希链。`GET /v1/data-platform/lineage/integrity` 可验证血缘链。

演示接口用于验证契约与治理流程，不应作为生产源系统的大载荷导入通道。生产部署应使用服务账号（OIDC 映射到受控接入角色）、API Gateway、限流、幂等键和请求签名，采用 Kafka/CDC/ETL 编排器传输数据；将不可变原始层置于受管对象存储，将规范层/服务层置于受管 PostgreSQL 或湖仓。契约 API 继续作为 schema registry 的控制面，并与企业元数据目录、血缘、DQ 告警、主数据、保留与删除策略集成。

最小的接入请求示例：

```json
{
  "source_system": "crm",
  "contract_id": "DC-CRM-CUSTOMER",
  "organization_id": "branch-shanghai",
  "records": [{
    "customer_id": "C-1001",
    "name": "示例企业",
    "operating_years": 4,
    "annual_revenue": 8500000,
    "debt_ratio": 0.48
  }]
}
```

请求成功仅表示当前契约质量检查通过，不表示征信、反洗钱、制裁名单、主数据匹配或业务审批已经完成。

## Embedding 与向量索引

正式 Embedding 使用 `langchain-openai` 的 `OpenAIEmbeddings`，批量编码政策 chunk，并按配置传递模型、维度、超时和重试参数。向量库使用 `langchain-postgres` 的 psycopg 3 连接、cosine distance 和 HNSW cosine 索引。

```powershell
python scripts\index_policies.py
```

索引器输出政策数、chunk 数、Provider、维度和后端，不输出 API Key 或数据库密码。在线检索也会按需构建索引；内容指纹不变时不会重复调用 Embedding。多进程刷新通过 PostgreSQL advisory lock 串行化，并先 upsert 新文档、后删除 manifest 中的旧 ID。

同维度模型升级可使用新的集合名建立旁路索引，完成检索评测后再切换。改变维度时，由于 `langchain-postgres` 的 embedding 表共享定长 vector 列，应使用独立数据库/schema 或受控表迁移后重建，不能仅更换集合名。

## OIDC Token 契约

请求必须携带 `Authorization: Bearer <JWT>`。验签流程：

1. 从 JWT Header 读取 `kid`，通过配置的 JWKS URL 获取对应公钥；客户端缓存 JWKS 与签名键。
2. 仅允许显式配置的非对称算法；`HS256` 等共享密钥算法被配置校验拒绝。
3. 强制验证签名、`iss`、`aud`、`exp`，并要求 `iat`、`sub` 等声明存在。
4. 将角色声明直接或通过 `FINCREDIT_OIDC_ROLE_MAPPINGS` 映射到 `account_manager`、`risk_manager`、`approver`、`compliance_admin`；没有受支持角色则返回 401。
5. 要求非空组织声明，随后继续执行组织级 ABAC 和审批职责分离。

JWKS 网络故障返回 503，Token 无效、过期、受众错误或角色不可映射返回 401。生产联调必须覆盖签名键轮换、旧键保留窗口、时钟同步、撤销策略、嵌套 claim 路径和 IdP 故障演练。
生产配置还会拒绝非 HTTPS 的 JWKS URL 或 Issuer。数据库连接应按企业 CA 策略启用 TLS，并从 Secret Manager 注入连接凭据。

## 就绪与回滚

`GET /ready` 检查非敏感配置、SQLite 业务库连接和 pgvector 数据库连接；响应只暴露 Provider/后端名称。规则回滚通过重新发布目标参数的新版本完成，保留完整历史。Embedding 回滚使用上一个集合名和对应模型/维度；OIDC 故障不得切回 `demo-header`，应恢复 IdP/JWKS 服务或停止流量。

## 实现参考

- [OpenAI Embeddings 指南](https://developers.openai.com/api/docs/guides/embeddings)
- [LangChain PGVector 集成](https://docs.langchain.com/oss/python/integrations/vectorstores/pgvector)
- [pgvector 官方仓库](https://github.com/pgvector/pgvector)
- [PyJWT JWKS 与 claims 校验](https://pyjwt.readthedocs.io/en/stable/usage.html)
