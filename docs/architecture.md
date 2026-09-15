# FinCredit Copilot Architecture

FinCredit Copilot is organized as a small but enterprise-shaped FastAPI service. Version 0.5 adds a four-eyes policy-rule release lifecycle, scheduled activation, immutable review hashes, version diffs, and governed rollback to the LangChain/pgvector/OIDC workflow.

## Module Layout

- `app/main.py`: FastAPI application assembly, static workbench mounting, and router registration.
- `app/routers/`: Domain-oriented API routers for applications, knowledge, approval, audit, and health.
- `app/schemas.py`: Pydantic request models used by the API boundary.
- `app/config.py`: Environment-backed runtime settings.
- `app/database.py`: SQLite adapter entrypoint for database path and connections.
- `app/migrations/`: Migration registry for local schema creation and future database evolution.
- `app/bootstrap.py`: Startup initialization for local stores.
- `app/domain.py`: Domain entities and enums.
- `app/security.py`: Fail-closed identity selection, role checks, and organization-scoped application access.
- `app/identity.py`: Demo identity plus production JWT verification using JWKS, issuer, audience, algorithm allowlists, and claim mapping.
- `app/services.py`: Business workflow orchestration for policy search, pre-review, Agent brief generation, real-time Agent Q&A, and approval submission.
- `app/rule_store.py`: Versioned rule repository, safe validation, draft/review/schedule/activation state machine, content hashes, diffs, and rollback drafts.
- `app/risk_rules.py`: Safe interpreters for admission, amount, threshold, and material rules; no dynamic code execution.
- `app/embedding.py` / `app/vector_store.py`: Hash/OpenAI embedding adapters and memory/pgvector stores with persistent manifests.
- `app/approval_policy.py`: Submission guardrail engine for missing materials, blocking rules, high-risk findings, and override reasons.
- `app/agent_provider.py`: LangChain LCEL prompt/model/structured-output pipeline with local deterministic fallback, OpenAI Responses, and DeepSeek-compatible implementations.
- `app/rag/`: LangChain `BaseRetriever`, RAG contracts, evidence-chain service, offline evaluation, and parameter tuning.
- `app/prompt_registry.py`: Versioned governed prompts; every Agent Run records prompt identity and version.
- `app/evaluation.py`: Offline evaluation contract for accuracy, evidence recall, boundary violations, latency, and cost.
- `app/agent_runtime/`: Agent Run state machine, recovery queue, reliability policy, guardrails, provider routing, and release evaluation primitives.
- `app/agent_output.py`: Agent response schemas and local validation for governed brief and business-answer outputs.
- `app/agent_tools.py`: Read-only Agent tool allowlist and tool execution trace for application, material, policy, and approval status lookups.
- `app/observability.py`: Request ID propagation, JSON logging, and structured operational events.
- `app/metrics.py`: Agent run metric aggregation for latency, fallback, provider, task, and tool usage.
- `app/*_store.py`: Local repository adapters for policies, transactional workflow state, applications, hash-chained audit events, and documents. Stores own queries and seed data, while migrations own schema changes.
- `app/static/`: Browser workbench, including pre-review, Agent Q&A, approval, material archive, and Agent observability panels.
- `scripts/quality_gate.py`: Scenario-based regression gate for financial Agent behavior.
- `tests/`: API and behavior regression tests.

## Request Flow

1. A user selects an application and role in the workbench.
2. API routes authenticate the demo user with `X-User-Id` and enforce role permissions.
3. Service orchestration loads application, customer, policy, and material status from stores.
4. Separately, compliance authors create immutable rule drafts; another compliance actor reviews the diff and approves, rejects, or schedules the version.
5. Due scheduled rules atomically retire the previous active version and extend the audit chain.
6. The pre-review engine loads only active rule versions and produces deterministic findings plus their required policy IDs.
7. `LangChainPolicyRetriever` performs lexical/vector hybrid retrieval using the configured embedding/vector adapters and emits citation-bearing `Document` objects.
8. The tool allowlist supplies minimized, read-only business context without document body previews.
9. `ChatPromptTemplate` and `ChatOpenAI` produce a Pydantic structured response; model exceptions flow through retry/circuit-breaker handling before deterministic fallback.
10. Output validation checks nested types, retrieved evidence IDs, and the no-auto-decision boundary.
11. One database transaction persists the report, completes the Agent Run, and moves the application to `pre_reviewed`.
12. Observability middleware and Agent events emit request IDs, JSON logs, and metrics.
13. The approval policy engine evaluates whether the application can be submitted.
14. Submission atomically creates a uniquely identified approval task, locks the report hash, and moves the application to `pending_approval`.
15. The final decision enforces organization scope and separation of duties, then atomically updates the task and application with compare-and-set conditions; returned applications must be re-reviewed before resubmission.
16. Audit writes extend a SHA-256 chain that compliance users can verify through the integrity endpoint.

## Current Guardrails

- The Agent does not approve, reject, or return credit applications.
- Real-model Providers fall back to the local deterministic Provider when credentials are missing or calls fail.
- Agent tools are read-only and selected from an explicit allowlist.
- External-model tool context excludes uploaded document text previews and registration identifiers.
- Agent outputs are locally validated before being saved or shown.
- Agent evidence IDs must be present in the retrieved RAG context.
- Release gating includes RAG Hit Rate, Recall, and MRR thresholds.
- Every HTTP response carries `X-Request-Id`, and audit events include the active request ID when available.
- Agent runs record latency, fallback status, and tool-call summaries for operational review.
- The workbench observability panel reads the compliance-only metrics endpoint so demo operators can see recent Agent runs, fallback rate, latency, provider distribution, and tool usage without leaving the business flow.
- Uploaded document records store SHA-256 hashes and extracted fields.
- Agent run records store structured input summaries and outputs, not raw document bodies.
- Policy imports require the compliance administrator role.
- Submission is blocked when required materials are missing or a blocking rule is triggered.
- High-risk submissions require an explicit manual override reason.
- Approval decisions require the approver role and a human comment.
- An approver cannot be the application creator, report reviewer, or approval submitter.
- Every resubmission creates a new task; old returned or decided tasks remain queryable.
- Pending approval tasks lock the pre-review report hash and reject decisions against changed evidence.
- Unknown identity providers fail closed, and `/ready` rejects demo-header authentication in production.
- OIDC validates the JWT signature by `kid` against cached JWKS keys and requires `exp`, `iat`, `iss`, `sub`, and `aud` claims.
- Production readiness requires OIDC, OpenAI Embeddings, and pgvector; local-only adapters cannot silently pass production checks.
- Rule imports are limited to four interpreters and approved business fields; message placeholders are validated before activation.
- Rule authors and submitters cannot approve their own version; pending content is hash-checked, and rollback creates a new reviewable draft.
- pgvector refreshes use stable IDs, a manifest, and a PostgreSQL advisory lock so multi-worker updates upsert before stale-vector cleanup.
- Application access is scoped to the creator's organization except for compliance administrators.
- Audit events include previous/current SHA-256 hashes, with a compliance-only integrity endpoint.
- The quality gate checks rule hits, authorization failures, missing-material blocks, override handling, Agent output boundaries, separation of duties, and audit integrity.
- The release gate checks offline Agent quality thresholds before a build is considered releasable.
- `/ready` checks non-secret runtime configuration and database connectivity for container orchestration.

## Production Extension Points

- Replace the SQLite adapter with PostgreSQL-backed repositories and promote `app/migrations/` to Alembic-managed migrations.
- Add OIDC discovery, token revocation/introspection where required by the enterprise IdP, and persist tenant identifiers on applications.
- Harden the OpenAI Provider with stricter structured output validation, DLP, tool-call allowlists, retry policy, cost tracking, and model-output eval scoring.
- Expand `scripts/quality_gate.py` into CI/CD quality gates with larger labeled cases and model-output scoring.
- Export observability data to OpenTelemetry, Prometheus, or an enterprise SIEM/log platform.
- Replicate the local tamper-evident audit chain and Agent runs to an immutable log platform.
- Connect document storage to object storage, OCR, malware scanning, and retention policies.
