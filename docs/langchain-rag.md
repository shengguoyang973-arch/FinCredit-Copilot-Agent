# LangChain 与 RAG 优化说明

## 目标与边界

FinCredit Copilot v0.2 将模型编排和政策检索迁移到 LangChain 标准接口，同时保留确定性授信规则。大模型用于解释、归纳和生成草稿，不负责批准、拒绝、退回或改变申请状态。

这里的“RAG 微调”指分块、召回、融合权重、阈值、Top-K 和重排参数的离线调优。当前版本没有声称训练 OpenAI、DeepSeek 或其他基础模型权重。

## 结构

```mermaid
flowchart LR
    A[申请与脱敏问题] --> B[确定性规则引擎]
    B --> C[Required Policy IDs]
    A --> D[LangChainPolicyRetriever]
    D --> E[Policy Documents + Citations]
    C --> E
    A --> F[最小化只读工具上下文]
    E --> G[ChatPromptTemplate]
    F --> G
    G --> H[ChatOpenAI]
    H --> I[Pydantic Structured Output]
    I --> J[证据与审批边界校验]
    J --> K[Agent Run + RAG Trace + Report]
    J -.失败.-> L[重试/熔断]
    L -.最终失败.-> M[本地确定性降级]
```

主要模块：

- `app/rag/contracts.py`：RAG 配置、命中和追踪契约。
- `app/rag/retriever.py`：LangChain `BaseRetriever` 适配器。
- `app/rag/service.py`：检索结果与确定性规则证据合并。
- `app/rag/tuning.py`：Hit Rate、Recall、MRR 评测与参数网格搜索。
- `app/agent_provider.py`：LCEL 模型链和外部 Provider 适配。
- `app/agent_output.py`：Pydantic 输出模型、证据约束和审批边界校验。

## 检索策略

每个政策条款先按稳定句段切分并生成引用信息。检索分数由词法分数和哈希向量余弦相似度归一化融合：

```text
score = normalized_lexical_score * lexical_weight
      + max(vector_score, 0) * vector_weight
```

当前演示调优值：

| 参数 | 值 |
| --- | ---: |
| `top_k` | 3 |
| `lexical_weight` | 0.85 |
| `vector_weight` | 0.15 |
| `min_vector_score` | 0.0 |
| `chunk_size` | 180 |

确定性规则直接引用的政策编号属于强制证据：即使语义检索未命中，也会附加到证据链并在 RAG Trace 标记 `forced_match=true`。这避免把强制合规证据完全交给概率检索决定。

## 执行调优

评估当前环境配置：

```powershell
python scripts\tune_rag.py --evaluate-current
```

执行 36 组参数网格搜索：

```powershell
python scripts\tune_rag.py
```

保存结果：

```powershell
python scripts\tune_rag.py --output artifacts\rag-tuning.json
```

评测数据位于 `demo_data/rag_evaluation.json`。新增数据时至少提供稳定的 `id`、脱敏 `query` 和一个或多个 `expected_policy_ids`。真实上线前应将数据拆分为训练、验证和时间外测试集，防止在小样本上过拟合。

## 模型调用

OpenAI 和 DeepSeek 都通过 LangChain `ChatOpenAI` 适配器调用：

- OpenAI 使用 Responses API 模式和 `json_schema` 结构化输出。
- DeepSeek 使用 OpenAI 兼容 Base URL 和 `json_mode`。
- LangChain 内部重试关闭，由项目统一的超时、重试和熔断器负责。
- 最终失败后生成本地确定性输出，并记录 `runtime=langchain`、`fallback=true` 和降级原因类型。

## 数据最小化

进入模型上下文的材料工具结果仅包含材料类型、字节数、SHA-256 和已抽取字段名。原始正文及 `text_preview` 不会通过 Agent 工具发送给外部模型。政策正文会进入模型上下文，因为它是 RAG 的受控知识来源。

## 发布门禁

`scripts/release_gate.py` 会同时运行：

1. 场景质量门禁；
2. 确定性 Agent 输出评测；
3. 当前 RAG 配置的 Hit Rate、Recall 和 MRR 评测。

任何 RAG Hit Rate 低于 `1.0`、Recall 低于 `0.95` 或 MRR 低于 `0.75` 的版本都会阻止发布。

## 后续路线

- 将哈希向量替换为受控 Embedding Provider，并保存向量模型版本。
- 将内存向量库替换为 PGVector/Milvus/Elasticsearch，加入租户和政策版本过滤。
- 建立政策生效、失效、审批发布和历史版本模型。
- 引入经合规审批的难负样本、冲突政策、多跳查询和时间有效性测试。
- 若确需基础模型微调，另建数据治理、训练作业、模型注册、灰度、回滚和偏差评估流程。

## 参考

- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
- [LangChain semantic search and retrievers](https://docs.langchain.com/oss/python/langchain/knowledge-base)
