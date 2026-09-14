# FinCredit Copilot

[![FinCredit CI](https://github.com/shengguoyang973-arch/FinCredit-Copilot-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/shengguoyang973-arch/FinCredit-Copilot-Agent/actions/workflows/ci.yml)

面向小微企业流动资金贷款的授信尽调与审批协同 Agent MVP。v0.2 使用 LangChain 统一模型调用、结构化输出和 RAG 检索接口；系统只提供预审建议和报告草稿，绝不自动作出授信决定。

架构说明见 [docs/architecture.md](docs/architecture.md)。

LangChain/RAG 迁移、数据流、调优方式和后续扩展说明见 [docs/langchain-rag.md](docs/langchain-rag.md)。

API 已按领域拆分到 `app/routers/`，`main.py` 只负责应用装配、静态工作台和路由注册。

SQLite 连接集中在 `app/database.py`，建表 SQL 集中在 `app/migrations/`；各 `*_store.py` 只保留 repository/adapter 读写逻辑和演示种子数据。

## 已实现

- 基于角色的访问控制（客户经理、风险经理、审批人、合规管理员）
- LangChain LCEL 模型管线：`ChatPromptTemplate -> ChatModel -> Pydantic structured output`
- LangChain `BaseRetriever` 标准接口下的政策混合检索、引用和检索轨迹
- RAG 离线评测与参数网格搜索，覆盖 Hit Rate、Recall、MRR 和综合分数
- 脱敏模拟客户、授信申请与交易流水查询；申请状态和审计事件均持久化
- 带版本与条款号的授信政策检索
- SQLite 持久化政策库；合规管理员可通过接口新增或更新政策条款
- 预审规则引擎雏形：集中处理行业准入、经营年限、逾期、负债率、申请额度与材料完整性规则
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

访问 `http://127.0.0.1:8000/` 使用审批工作台；`http://127.0.0.1:8000/docs` 保留为接口文档。工作台可直接切换演示身份：`rm_001`（风险经理）、`approver_001`（审批人）、`sales_001`（客户经理）、`compliance_001`（合规管理员）。

## Docker 启动

```powershell
docker compose up --build
```

容器将数据保存到 Docker 命名卷 `fincredit-data`；本地运行默认保存到 `data/fincredit.db`。可通过 `FINCREDIT_DATA_DIR` 指定受控数据目录。

## 配置

- `FINCREDIT_DATA_DIR`：本地数据库和上传材料保存目录，默认 `data/`。
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
- `FINCREDIT_RAG_TOP_K`：RAG 返回条款数量，调优默认值为 `3`。
- `FINCREDIT_RAG_LEXICAL_WEIGHT`：词法召回权重，调优默认值为 `0.85`。
- `FINCREDIT_RAG_VECTOR_WEIGHT`：向量召回权重，调优默认值为 `0.15`。
- `FINCREDIT_RAG_MIN_VECTOR_SCORE`：无词法命中时的最低向量分数，调优默认值为 `0.0`。
- `FINCREDIT_RAG_CHUNK_SIZE`：政策切分最大字符数，默认 `180`。

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

本项目采用“确定性规则 + RAG 证据 + LangChain 模型表达”的分层设计。额度、准入和提交拦截不交给大模型决定；LangChain 负责受控上下文编排和结构化生成。政策检索结果遵循 LangChain `Document`/`BaseRetriever` 契约，可以逐步替换为 PGVector、Milvus、Elasticsearch 或托管检索服务。

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

## 质量门禁

```powershell
python scripts\quality_gate.py
python scripts\release_gate.py
python scripts\tune_rag.py --evaluate-current
python scripts\tune_rag.py
python -m pytest -q
```

`quality_gate.py` 使用临时数据库运行场景化回归评测，不污染本地演示数据。当前覆盖高风险规则命中、越权操作拒绝、缺材料提交拦截、高风险人工覆盖理由、业务问答追踪、Agent 指标聚合和 Agent 输出治理边界。

`release_gate.py` 在质量门禁之上增加 Prompt/Provider 与 RAG 评测门槛，检查准确率、证据引用率、人工审批边界、RAG Hit Rate、Recall 和 MRR；`GET /ready` 用于容器就绪探针。

### RAG 调优说明

`demo_data/rag_evaluation.json` 是脱敏的政策检索评测集。`scripts/tune_rag.py` 对 `top_k`、词法/向量权重和最低向量分数执行网格搜索。当前 6 个演示案例的最优配置为 `top_k=3`、词法权重 `0.85`、向量权重 `0.15`、最低向量分数 `0.0`，Hit Rate、Recall 和 MRR 均为 `1.0`。

该结果只证明演示政策集上的检索参数已校准，不代表基础模型权重已经训练，也不能代替使用真实脱敏标注集进行复测。若需要基础模型微调，应另行建立训练/验证集、模型注册、审批和回滚流程。

## 演示数据

`demo_data/` 提供了一套完整虚拟材料包，包含两个授信案例的营业执照、财务报表、银行流水、智能体问答示例和政策导入示例。演示时可在工作台选择对应申请后上传这些文件，触发材料抽取、规则命中、预审报告、智能体问答和运行观测面板。

政策条款导入接口需要 `X-User-Id: compliance_001`。数据库会自动创建在 `data/fincredit.db`；它仅含演示政策，禁止放入真实客户或生产制度数据。

提交预审后会产生 `APR-<申请编号>` 审批任务。仅 `approver_001` 可通过 `POST /v1/approval-tasks/{task_id}/decision` 给出 `approved`、`rejected` 或 `returned` 决策，并必须填写人工审批意见。

提交审批前会执行策略校验：必需材料缺失或命中阻断规则时不能提交；命中高风险规则时，风险经理必须在请求体中提供 `override_reason`。策略结果会写入审批任务和审计日志。

材料接口使用原始字节请求体和 `X-Filename` 请求头：`PUT /v1/applications/{application_id}/materials/{document_type}`。演示版只支持 UTF-8 文本/CSV 的保守规则抽取，材料类型为 `business_license`、`financial_statement` 和 `bank_statement`，单文件上限为 2MB。

Agent 默认使用 `FINCREDIT_AGENT_PROVIDER=deterministic-local`，不会调用外部模型。配置 `FINCREDIT_AGENT_PROVIDER=openai-responses` 且提供 `OPENAI_API_KEY` 后，会通过 LangChain `ChatOpenAI` 的 Responses API 模式生成报告评述和实时业务问答；配置 `FINCREDIT_AGENT_PROVIDER=deepseek-chat` 且提供 `DEEPSEEK_API_KEY` 后，会通过 LangChain 的 OpenAI 兼容模式调用 DeepSeek。如果密钥缺失、调用失败或结构化输出校验失败，系统会在完成重试/熔断记录后降级到本地确定性 Provider。

每次生成预审报告都会保存一条 Agent 运行记录，可通过 `GET /v1/applications/{application_id}/agent-runs` 查看。运行记录保存结构化输入摘要、政策证据编号、RAG 配置与命中轨迹、材料完整性状态和 Agent 输出，不保存原始上传文件正文。发送给外部模型的材料工具上下文只包含材料类型、大小、哈希和已抽取字段名，不包含正文预览。

Agent 当前白名单工具包括：`get_application_snapshot`、`get_material_status`、`get_policy_evidence`、`get_approval_status`。工具调用轨迹会写入 Agent Run 的 `input_snapshot.tool_names`。

实时业务问答接口为 `POST /v1/applications/{application_id}/agent-question`，请求体示例：`{"question":"为什么这个申请不能提交？"}`。

可观测性接口为 `GET /v1/observability/agent-metrics`，需要 `X-User-Id: compliance_001`。它会聚合 Agent 运行次数、降级率、平均耗时、最大耗时、Provider 分布、任务分布、工具调用次数和最近运行记录。工作台内置“Agent 运行观测”面板，切换到“周合规管理员”后可直接刷新查看；生成预审报告或发起 AI 业务问答后，指标会随 Agent Run 更新。所有 HTTP 响应都会带 `X-Request-Id`，请求日志使用 JSON 结构输出。

## 重要边界

本项目使用完全模拟、脱敏的数据。生产接入前必须替换内存仓储为受控数据服务，接入统一身份认证、字段级权限、密钥管理、DLP、不可篡改审计和人工审批流程。

## 生产上线清单

- 将演示身份头替换为企业 SSO/OIDC，并在服务端强制 RBAC 与字段级数据权限。
- 接入受管对象存储、恶意文件扫描、OCR/版面解析与文档保留策略；不得把未脱敏材料直接发送给外部模型。
- 替换 SQLite 为受管数据库，审计事件写入不可篡改日志平台，并配置备份、告警和灾备。
- 以脱敏、标注过的真实案例建立评测集，覆盖事实准确率、工具调用失败率、越权率、拒答率、延迟与成本。
- 将 RAG 演示评测集扩展为经合规审批的训练集、验证集和时间外测试集，并为每次参数或模型变更保存版本和回滚点。
- 将核心、征信、CRM 和 OA 系统接入限制为最小权限的受控工具；任何高风险写操作均保留人工确认。
