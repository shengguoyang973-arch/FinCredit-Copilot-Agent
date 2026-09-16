# FinCredit Copilot

[![FinCredit CI](https://github.com/shengguoyang973-arch/FinCredit-Copilot-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/shengguoyang973-arch/FinCredit-Copilot-Agent/actions/workflows/ci.yml)

面向小微企业流动资金贷款的授信尽调与审批协同 Agent。v0.8 在 LangChain、pgvector、企业 OIDC、规则发布治理和信贷数据中台基础上，加入上下文硬预算、规范数据时效/跨源冲突提示、结构化人工复核反馈和漂移告警处置历史；系统只提供预审建议和报告草稿，绝不自动作出授信决定。

架构说明见 [docs/architecture.md](docs/architecture.md)。

LangChain/RAG 迁移、数据流、调优方式和后续扩展说明见 [docs/langchain-rag.md](docs/langchain-rag.md)。

身份、审批一致性与审计完整性说明见 [docs/governed-workflow.md](docs/governed-workflow.md)。

生产 RAG、规则配置和 OIDC 部署说明见 [docs/production-runtime.md](docs/production-runtime.md)。

规则发布状态机、复核 API 和回滚流程见 [docs/policy-rule-lifecycle.md](docs/policy-rule-lifecycle.md)。

数据中台的数据契约、接入、质量、数据服务和血缘接口见 [docs/data-platform.md](docs/data-platform.md)。

任务规划、最小化上下文和线上评估/漂移告警见 [docs/agent-operations.md](docs/agent-operations.md)。

API 已按领域拆分到 `app/routers/`，`main.py` 只负责应用装配、静态工作台和路由注册。

SQLite 连接集中在 `app/database.py`，建表 SQL 集中在 `app/migrations/`；各 `*_store.py` 只保留 repository/adapter 读写逻辑和演示种子数据。

## 已实现

- 基于角色的访问控制（客户经理、风险经理、审批人、合规管理员）
- 身份提供方默认拒绝：未知 Provider 返回服务不可用，生产环境就绪检查禁止演示身份头
- 企业 OIDC 验签：按 `kid` 从 JWKS 取公钥，强制校验非对称算法、签发方、受众、过期时间和必需声明
- 组织级 ABAC、审批职责分离、唯一审批任务历史和报告哈希锁定
- 预审持久化、审批提交与审批决策使用 SQLite 原子事务和条件状态更新
- SHA-256 链式审计事件及合规完整性校验接口
- LangChain LCEL 模型管线：`ChatPromptTemplate -> ChatModel -> Pydantic structured output`
- LangChain `BaseRetriever` 标准接口下的政策混合检索、引用和检索轨迹
- 正式向量路径：OpenAI `text-embedding-3-small` 可配置维度，`langchain-postgres` + pgvector 持久化与多实例安全刷新
- RAG 离线评测与参数网格搜索，覆盖 Hit Rate、Recall、MRR 和综合分数
- 脱敏模拟客户、授信申请与交易流水查询；申请状态和审计事件均持久化
- 带版本与条款号的授信政策检索
- SQLite 持久化政策库；合规管理员可通过接口新增或更新政策条款
- 政策规则发布治理：四类白名单规则、不可变草稿、作者/复核人分离、结构化版本 diff、计划生效、哈希锁定与受控回滚
- 信贷数据中台：客户/授信申请标准数据契约目录、版本不可覆盖、来源系统白名单和契约内容哈希
- 受控数据接入：批次仅保存数据指纹，先执行必填字段、类型一致性、业务键去重校验；失败批次保留回执但绝不发布规范记录
- 规范数据服务与治理：按组织隔离查询当前版本数据、保留历史版本，独立 SHA-256 血缘链和全局审计链均可验证
- 受控任务规划：预审和问答均由版本化任务图编排，只能调用批准的只读工具；计划、工具轨迹和完成状态写入 Agent Run
- 上下文治理：外部模型只接收受字符预算约束的证据副本；完整证据链保留在报告中，规范数据时效与跨源字段冲突作为可审计元数据记录
- 数据中台只读工具：Agent 仅按申请所属组织读取规范客户画像，限制级记录和标识字段不会进入模型上下文
- 线上评估与人机闭环：持续测量降级率、P95 延迟、证据覆盖、规划一致性、反馈覆盖/修订率和自动决策边界；合规管理员可建立基线、查看持久化告警及处置历史
- 可追溯的预审报告草稿、证据链、人工审批任务和审计日志
- 材料归档、SHA-256 完整性摘要、文本字段抽取与缺件校验
- 可插拔 Agent Provider 层；默认本地确定性 Agent 生成尽调摘要、关键风险、建议动作与治理边界
- Agent 运行追踪：记录 Provider、输入快照、输出快照、生成时间和操作者，便于审计复盘
- 实时 AI 业务问答：可基于当前申请、规则、材料和政策证据回答业务问题
- 结构化输出校验与工具白名单：Agent 只能使用只读业务工具，输出必须满足报告/问答 schema 并遵守人工审批边界
- 生产级可观测性雏形：请求 ID、JSON 结构化日志、Agent 延迟/降级/工具调用指标和工作台观测面板
- 审批策略引擎：材料缺失和阻断规则拦截提交，高风险规则要求人工覆盖理由
- 质量门禁脚本：覆盖规则命中、越权拒绝、材料拦截、高风险覆盖理由、业务问答、可观测性和 Agent 输出边界
- 预审报告持久化；审批人可人工批准、拒绝或退回，禁止自动决策

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

开发和 CI 环境使用 `pip install -r requirements-dev.txt`，其中包含 Ruff 与 Coverage；相关配置统一保存在 `pyproject.toml`。

访问 `http://127.0.0.1:8000/` 使用审批工作台；`http://127.0.0.1:8000/docs` 保留为接口文档。工作台可直接切换演示身份：`rm_001`（风险经理）、`approver_001`（审批人）、`sales_001`（客户经理）、`compliance_001`（规则作者）和 `compliance_002`（独立复核人）。

## Docker 启动

```powershell
docker compose up --build
```

Compose 会启动应用和 `pgvector/pgvector:0.8.6-pg16`，业务数据与向量数据分别保存到 `fincredit-data`、`fincredit-vectors` 命名卷。Compose 默认采用 `hash-local + pgvector`，便于无外部密钥验证持久向量链路，但不满足生产配置门禁。

## 配置

- `FINCREDIT_DATA_DIR`：本地数据库和上传材料保存目录，默认 `data/`。
- `FINCREDIT_ENVIRONMENT`：运行环境，可选 `development`、`test`、`production`；生产环境禁止 `demo-header`。
- `FINCREDIT_IDENTITY_PROVIDER`：身份提供方，只接受 `demo-header` 或 `oidc`；未知值不会降级为演示身份。
- `FINCREDIT_OIDC_JWKS_URL` / `FINCREDIT_OIDC_ISSUER` / `FINCREDIT_OIDC_AUDIENCE`：OIDC 验签三项必需配置。
- `FINCREDIT_OIDC_ALGORITHMS`：逗号分隔的非对称算法白名单，默认 `RS256`；不接受 `HS*`。
- `FINCREDIT_OIDC_ROLES_CLAIM` / `FINCREDIT_OIDC_ORG_CLAIM` / `FINCREDIT_OIDC_NAME_CLAIM`：声明映射，支持点号分隔的嵌套路径。
- `FINCREDIT_OIDC_ROLE_MAPPINGS`：企业组到业务角色的 JSON 映射，例如 `{"credit-risk-group":"risk_manager"}`。
- `FINCREDIT_OIDC_LEEWAY_SECONDS`：Token 时钟偏差，默认 `30` 秒。
- `FINCREDIT_AGENT_PROVIDER`：Agent Provider 名称，默认 `deterministic-local`。
- `OPENAI_API_KEY`：使用真实 OpenAI Provider 时必需。
- `OPENAI_MODEL`：真实模型名称，默认 `gpt-4.1-mini`。
- `DEEPSEEK_API_KEY`：使用 DeepSeek Provider 时必需。
- `DEEPSEEK_MODEL`：DeepSeek 模型名称，默认 `deepseek-v4-pro`。
- `DEEPSEEK_BASE_URL`：DeepSeek OpenAI 兼容接口地址，默认 `https://api.deepseek.com`。
- `OPENAI_TIMEOUT_SECONDS`：真实模型调用超时时间，默认 `20`。
- `FINCREDIT_AGENT_MAX_RETRIES`：模型调用最大重试次数，默认 `2`。
- `FINCREDIT_AGENT_CIRCUIT_FAILURE_THRESHOLD`：Provider 连续失败多少次后熔断，默认 `3`。
- `FINCREDIT_AGENT_CIRCUIT_COOLDOWN_SECONDS`：熔断冷却时间，默认 `30` 秒。
- `FINCREDIT_AGENT_PROVIDER_CHAIN`：Provider 路由链，例如 `deepseek-chat,deterministic-local`。
- `FINCREDIT_INPUT_COST_PER_1K_USD` / `FINCREDIT_OUTPUT_COST_PER_1K_USD`：Token 成本估算单价；不配置时只统计 Token，不虚构成本。
- `FINCREDIT_MAX_DOCUMENT_BYTES`：单个材料上传字节上限，默认 `2000000`。
- `FINCREDIT_DATA_PLATFORM_MAX_BATCH_RECORDS`：一次受控接入批次可提交的最多记录数，默认 `500`，范围 `1` 到 `10000`。
- `FINCREDIT_ONLINE_EVALUATION_WINDOW_RUNS`：线上评估读取的最近完成 Agent Run 数，默认 `50`。
- `FINCREDIT_DRIFT_MIN_SAMPLES`：建立基线和判断漂移所需的最小样本数，默认 `10`。
- `FINCREDIT_DRIFT_MAX_FALLBACK_RATE` / `FINCREDIT_DRIFT_MAX_P95_LATENCY_MS`：模型降级率与 P95 延迟上限，默认 `0.2` / `5000`。
- `FINCREDIT_DRIFT_MIN_EVIDENCE_COVERAGE` / `FINCREDIT_DRIFT_MIN_PLAN_ADHERENCE`：最低证据覆盖率和规划一致性，默认 `0.9` / `0.95`。
- `FINCREDIT_AGENT_CONTEXT_MAX_CHARS`：发送到外部模型的受控 JSON 上下文字符上限，默认 `12000`，范围 `2000` 到 `100000`；完整报告证据不受此截断影响。
- `FINCREDIT_CANONICAL_DATA_MAX_AGE_HOURS`：中台规范记录的时效阈值（小时），默认 `168`；超时会写入 `stale` 元数据供人工复核，不会静默当作最新数据。
- `FINCREDIT_RAG_TOP_K`：RAG 返回条款数量，调优默认值为 `3`。
- `FINCREDIT_RAG_LEXICAL_WEIGHT`：词法召回权重，调优默认值为 `0.85`。
- `FINCREDIT_RAG_VECTOR_WEIGHT`：向量召回权重，调优默认值为 `0.15`。
- `FINCREDIT_RAG_MIN_VECTOR_SCORE`：无词法命中时的最低向量分数，调优默认值为 `0.0`。
- `FINCREDIT_RAG_CHUNK_SIZE`：政策切分最大字符数，默认 `180`。
- `FINCREDIT_EMBEDDING_PROVIDER`：`hash-local` 或 `openai`；生产环境必须是 `openai`。
- `FINCREDIT_EMBEDDING_MODEL`：默认 `text-embedding-3-small`。
- `FINCREDIT_EMBEDDING_DIMENSIONS`：向量维度，默认 `256`；修改后会生成新的索引指纹。
- `FINCREDIT_VECTOR_STORE_BACKEND`：`memory` 或 `pgvector`；生产环境必须是 `pgvector`。
- `FINCREDIT_PGVECTOR_CONNECTION`：SQLAlchemy/psycopg 连接串，例如 `postgresql+psycopg://user:password@host/db`。
- `FINCREDIT_PGVECTOR_COLLECTION`：政策向量集合名，默认 `fincredit_policy_chunks`。
- `FINCREDIT_POLICY_TIMEZONE`：计划生效使用的 IANA 业务时区，默认 `Asia/Shanghai`。

`FINCREDIT_ENVIRONMENT=production` 时，就绪检查要求同时配置 `oidc + openai embedding + pgvector`。完整模板、Token 声明和索引命令见 [生产运行文档](docs/production-runtime.md)。

## LangChain 与 RAG 数据流

```text
申请/问题
  -> 确定性风控规则
  -> LangChainPolicyRetriever（词法 + 向量 + 重排）
  -> 脱敏只读工具上下文
  -> ChatPromptTemplate
  -> ChatOpenAI（OpenAI Responses 或 DeepSeek 兼容接口）
  -> Pydantic 结构化输出与证据/人工审批边界校验
  -> Agent Run、RAG Trace、预审报告和审计日志
```

本项目采用“配置化确定性规则 + RAG 证据 + LangChain 模型表达”的分层设计。额度、准入和提交拦截不交给大模型决定；LangChain 负责受控上下文编排和结构化生成。开发默认使用确定性哈希向量和内存库，生产路径使用 OpenAI Embedding 与 pgvector，并在政策内容、切分或向量配置变化时刷新索引。

## 数据中台数据流

```text
CRM / 核心信贷 / 风险引擎（受控服务身份）
  -> 数据契约目录：业务键、必填字段、字段类型、数据分级、来源白名单
  -> 接入批次：仅计算规范 JSON 的 SHA-256 指纹，不在审计中复制原始载荷
  -> 数据质量：完整性、类型一致性、批内业务键唯一性
  -> accepted：版本化规范数据 + 血缘哈希链 + 全局审计链
  -> rejected：质量结果和血缘回执，零规范记录发布
  -> 组织隔离数据 API -> 授信审批、风险分析、Agent 最小化只读工具
```

数据中台不以“把所有数据复制到一个数据库”为目标。每次接入必须绑定一份生效数据契约和授权来源；成功记录按 `组织 + 实体类型 + 业务键` 维护当前规范视图，同时保留历史版本。当前实现提供 SQLite 本地适配器以便演示和回归测试；生产应迁移到受管 PostgreSQL、对象存储和企业调度/CDC 平台，详见 [数据中台说明](docs/data-platform.md)。

任务执行先由确定性任务规划器生成“读取申请、读取中台规范画像、核验材料、检索政策、上下文质量检查、结构化输出、人工边界”的依赖图；仅流程类问答才额外读取审批状态。规划不能引入未登记工具，也不执行授信决定。模型调用前会对证据文本执行硬字符预算，保留所有证据 ID，并记录中台数据的时效与跨源冲突字段。每次运行完成后系统会计算线上质量信号；样本达到阈值后，由合规管理员固化基线，后续超出基线容差或硬阈值时产生漂移告警。复核人员可对完成 Run 提交一次结构化反馈，合规人员可对告警写入不可变处置记录。

真实大模型模式示例：

```powershell
$env:FINCREDIT_AGENT_PROVIDER = "openai-responses"
$env:OPENAI_API_KEY = "<your-api-key>"
$env:OPENAI_MODEL = "gpt-4.1-mini"
uvicorn app.main:app --reload
```

DeepSeek 模式示例：

```powershell
$env:FINCREDIT_AGENT_PROVIDER = "deepseek-chat"
$env:DEEPSEEK_API_KEY = "<your-deepseek-api-key>"
$env:DEEPSEEK_MODEL = "deepseek-v4-pro"
uvicorn app.main:app --reload
```

构建当前环境的政策向量索引：

```powershell
python scripts\index_policies.py
```

## 政策规则版本管理

合规管理员通过 `POST /v1/knowledge/rules` 创建草稿。系统只接受 `minimum`、`ratio_cap`、`any_threshold`、`required_materials` 四种解释器和显式字段白名单；草稿提交后必须由另一名合规管理员批准。立即生效版本会原子停用旧版本，未来日期版本进入 `scheduled` 并在首次读取时短事务切换。历史记录可通过 `GET /v1/knowledge/rules?include_inactive=true` 查询，示例见 `demo_data/policy_rule_import_example.json`。

复核前可调用版本 diff 接口查看相对当前生效版的参数、严重度、消息与生效日变化。规则内容从建稿到审批由 SHA-256 锁定；回滚会复制已批准版本生成新草稿，不能绕过四眼复核。政策正文与可执行规则分离：`policy_id` 把规则发现结果绑定到 RAG 强制证据，`MAT-1` 等无正文规则可将 `policy_id` 置空。所有状态变化进入审计链。

## 质量门禁

```powershell
python scripts\quality_gate.py
python scripts\release_gate.py
python scripts\tune_rag.py --evaluate-current
python scripts\tune_rag.py
python -m pytest -q
```

`quality_gate.py` 使用临时数据库运行场景化回归评测，不污染本地演示数据。当前 12 个场景覆盖高风险规则命中、规则四眼发布与版本切换、生产配置 fail-closed、越权操作拒绝、缺材料提交拦截、高风险人工覆盖理由、业务问答与上下文预算追踪、人工反馈指标、Agent 指标聚合、Agent 输出治理边界、审批职责分离和审计链校验。

`release_gate.py` 在质量门禁之上增加 Prompt/Provider 与 RAG 评测门槛，检查准确率、证据引用率、人工审批边界、RAG Hit Rate、Recall 和 MRR；`GET /ready` 用于容器就绪探针。

### RAG 调优说明

`demo_data/rag_evaluation.json` 是脱敏的政策检索评测集。`scripts/tune_rag.py` 对 `top_k`、词法/向量权重和最低向量分数执行网格搜索。当前 6 个演示案例的最优配置为 `top_k=3`、词法权重 `0.85`、向量权重 `0.15`、最低向量分数 `0.0`，Hit Rate、Recall 和 MRR 均为 `1.0`。

该结果只证明演示政策集上的检索参数已校准，不代表基础模型权重已经训练，也不能代替使用真实脱敏标注集进行复测。若需要基础模型微调，应另行建立训练/验证集、模型注册、审批和回滚流程。

## 演示数据

`demo_data/` 提供了一套完整虚拟材料包，包含两个授信案例的营业执照、财务报表、银行流水、智能体问答、政策条款和政策规则导入示例。演示时可在工作台选择对应申请后上传这些文件，触发材料抽取、规则命中、预审报告、智能体问答和运行观测面板。

政策条款导入接口需要 `X-User-Id: compliance_001`。数据库会自动创建在 `data/fincredit.db`；它仅含演示政策，禁止放入真实客户或生产制度数据。

提交预审后会产生 `APR-<申请编号>-<唯一后缀>` 审批任务，每次退回重提都会保留一条独立历史记录。仅 `approver_001` 可通过 `POST /v1/approval-tasks/{task_id}/decision` 给出 `approved`、`rejected` 或 `returned` 决策，并必须填写人工审批意见。

提交审批前会执行策略校验：必需材料缺失或命中阻断规则时不能提交；命中高风险规则时，风险经理必须在请求体中提供 `override_reason`。策略结果会写入审批任务和审计日志。

审批任务锁定提交时的预审报告 SHA-256；最终审批前会再次验证报告未变化。申请创建人、预审/提交人不能审批自己的任务，重复或并发决策会通过条件更新拒绝。退回后申请进入独立的 `returned` 状态，必须重新预审才可再次提交。`GET /v1/audit-events/integrity` 供合规管理员验证本地审计哈希链。

材料接口使用原始字节请求体和 `X-Filename` 请求头：`PUT /v1/applications/{application_id}/materials/{document_type}`。演示版只支持 UTF-8 文本/CSV 的保守规则抽取，材料类型为 `business_license`、`financial_statement` 和 `bank_statement`，单文件上限为 2MB。

Agent 默认使用 `FINCREDIT_AGENT_PROVIDER=deterministic-local`，不会调用外部模型。配置 `FINCREDIT_AGENT_PROVIDER=openai-responses` 且提供 `OPENAI_API_KEY` 后，会通过 LangChain `ChatOpenAI` 的 Responses API 模式生成报告评述和实时业务问答；配置 `FINCREDIT_AGENT_PROVIDER=deepseek-chat` 且提供 `DEEPSEEK_API_KEY` 后，会通过 LangChain 的 OpenAI 兼容模式调用 DeepSeek。如果密钥缺失、调用失败或结构化输出校验失败，系统会在完成重试/熔断记录后降级到本地确定性 Provider。

每次生成预审报告都会保存一条 Agent 运行记录，可通过 `GET /v1/applications/{application_id}/agent-runs` 查看。运行记录保存结构化输入摘要、政策证据编号、RAG 配置与命中轨迹、材料完整性状态和 Agent 输出，不保存原始上传文件正文。发送给外部模型的材料工具上下文只包含材料类型、大小、哈希和已抽取字段名，不包含正文预览。

Agent 当前白名单工具包括：`get_application_snapshot`、`get_canonical_customer_snapshot`、`get_material_status`、`get_policy_evidence`、`get_approval_status`。工具调用轨迹会写入 Agent Run 的 `input_snapshot.tool_names`。

实时业务问答接口为 `POST /v1/applications/{application_id}/agent-question`，请求体示例：`{"question":"为什么这个申请不能提交？"}`。

可观测性接口为 `GET /v1/observability/agent-metrics`，需要 `X-User-Id: compliance_001`。它会聚合 Agent 运行次数、降级率、平均耗时、最大耗时、Provider 分布、任务分布、工具调用次数和最近运行记录。工作台内置“Agent 运行观测”面板，切换到“周合规管理员”后可直接刷新查看；生成预审报告或发起 AI 业务问答后，指标会随 Agent Run 更新。所有 HTTP 响应都会带 `X-Request-Id`，请求日志使用 JSON 结构输出。

## 重要边界

本项目使用完全模拟、脱敏的数据。当前 SQLite 的审计和数据血缘哈希链能够发现修改，但不等同于外部 WORM/不可变存储；数据质量仅覆盖契约完整性、类型和批内业务键，并不替代企业级 DQ、主数据、反洗钱或征信核验。OIDC/JWKS 与 pgvector 已提供正式适配，但生产接入前仍须把本地业务仓储和数据中台适配器迁到受控数据服务，并完成密钥管理、DLP、不可篡改日志平台和企业 IdP 联调。

## 生产上线清单

- 在预生产环境联调企业 SSO/OIDC JWKS 轮换、签发方、受众、Token 时钟偏差与撤销策略；生产环境不得启用演示身份头。
- 接入受管对象存储、恶意文件扫描、OCR/版面解析与文档保留策略；不得把未脱敏材料直接发送给外部模型。
- 替换 SQLite 为支持事务隔离和行锁的受管数据库；将本地防篡改哈希链复制到 WORM/SIEM，并配置备份、告警和灾备。
- 将数据中台迁移到受管 PostgreSQL/湖仓与对象存储，接入企业 CDC 或编排器、模式注册表、数据目录、血缘平台、质量告警、保留/删除策略和主数据治理；不要把生产源数据通过演示 HTTP 批量接口直接导入。
- 以脱敏、标注过的真实案例建立评测集，覆盖事实准确率、工具调用失败率、越权率、拒答率、延迟与成本。
- 将 RAG 演示评测集扩展为经合规审批的训练集、验证集和时间外测试集，并为每次参数或模型变更保存版本和回滚点。
- 将核心、征信、CRM 和 OA 系统接入限制为最小权限的受控工具；任何高风险写操作均保留人工确认。
