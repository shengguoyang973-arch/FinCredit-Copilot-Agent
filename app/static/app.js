const state = { applicationId: "APP001", approvalTaskId: null };
const userSelect = document.querySelector("#user-id");

const STATUS_LABELS = {
  draft: "草稿",
  pre_reviewed: "已预审",
  pending_approval: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
  returned: "已退回",
  pending: "待处理",
};

const DOCUMENT_LABELS = {
  business_license: "营业执照",
  financial_statement: "财务报表",
  bank_statement: "银行流水",
};

const TASK_LABELS = {
  generate_brief: "生成预审评述",
  answer_question: "实时业务问答",
  unknown: "历史运行记录",
  untracked: "未受控历史运行",
};

const TOOL_LABELS = {
  get_application_snapshot: "读取授信申请画像",
  get_canonical_customer_snapshot: "读取数据中台客户画像",
  get_material_status: "检查材料完整性",
  get_policy_evidence: "检索政策证据",
  get_approval_status: "查询审批状态",
};

const PROVIDER_LABELS = {
  "openai-responses": "真实大模型服务",
  "deepseek-chat": "DeepSeek 大模型服务",
  "deterministic-local": "本地稳态智能体",
};

const OBSERVATION_REVIEW_LABELS = {
  pending_review: "待独立复核",
  acknowledged: "已独立确认",
  rejected: "已驳回",
  continue_monitoring: "继续观察",
  investigate: "建议排查",
  rollback_recommended: "建议发起受控回滚",
};

const REMEDIATION_CASE_LABELS = {
  open: "待处理",
  in_progress: "处理中",
  resolved: "已关闭",
  cancelled: "已取消",
  overdue: "已逾期",
  due_today: "今日到期",
  on_track: "按期",
};

const getUser = () => userSelect.value;
const headers = () => ({ "X-User-Id": getUser(), "Content-Type": "application/json" });

const toast = (message, error = false) => {
  const el = document.querySelector("#toast");
  el.textContent = message;
  el.style.background = error ? "#c53030" : "#102a43";
  el.style.display = "block";
  setTimeout(() => el.style.display = "none", 3500);
};

function errorMessage(body) {
  if (typeof body.detail === "string") return body.detail;
  if (body.detail?.submission_policy?.reasons?.length) return body.detail.submission_policy.reasons.join(" ");
  if (body.detail?.message) return body.detail.message;
  return "请求失败";
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(body));
  return body;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function money(value) {
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 }).format(value);
}

function labelFrom(map, value, fallback = "-") {
  return map[value] || value || fallback;
}

function pulse(selector) {
  const element = document.querySelector(selector);
  if (!element) return;
  element.classList.remove("just-updated");
  void element.offsetWidth;
  element.classList.add("just-updated");
}

function loadingMarkup(message) {
  return `
    <div class="loading-card">
      <span class="loader-ring" aria-hidden="true"></span>
      <div>
        <strong>${escapeHtml(message)}</strong>
        <p>正在调度规则、材料、政策证据与智能体能力，请稍候…</p>
      </div>
    </div>`;
}

async function withButtonBusy(selector, busyText, action) {
  const button = document.querySelector(selector);
  const originalText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.classList.add("is-loading");
    button.textContent = busyText;
  }
  try {
    return await action();
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove("is-loading");
      button.textContent = originalText;
    }
  }
}

async function loadApplication() {
  try {
    const data = await api(`/v1/applications/${state.applicationId}`);
    const { application, customer } = data;
    document.querySelector("#summary").innerHTML = `
      <div class="section-title">
        <h2>${escapeHtml(customer.name)}</h2>
        <span class="tag">${escapeHtml(labelFrom(STATUS_LABELS, application.status))}</span>
      </div>
      <div class="summary-grid">
        <div class="metric"><small>申请金额</small><strong>${money(application.requested_amount)}</strong></div>
        <div class="metric"><small>经营年限</small><strong>${escapeHtml(customer.operating_years)} 年</strong></div>
        <div class="metric"><small>资产负债率</small><strong>${(customer.debt_ratio * 100).toFixed(0)}%</strong></div>
        <div class="metric"><small>信用等级</small><strong>${escapeHtml(customer.credit_grade)}</strong></div>
        <div class="metric"><small>近12月逾期</small><strong>${escapeHtml(customer.overdue_days_12m)} 天</strong></div>
        <div class="metric"><small>融资用途</small><strong>${escapeHtml(application.purpose)}</strong></div>
      </div>`;
    pulse("#summary");
  } catch (error) {
    document.querySelector("#summary").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

function renderMaterials(data) {
  const tag = document.querySelector("#material-state");
  tag.textContent = data.complete ? "材料齐全" : `缺少 ${data.missing.length} 项`;
  tag.className = `tag ${data.complete ? "approved" : "pending"}`;
  const uploaded = data.documents.length
    ? data.documents.map(d => {
      const extracted = Object.entries(d.extracted)
        .filter(([key]) => key !== "text_preview")
        .map(([key, value]) => `${escapeHtml(key)}=${escapeHtml(value)}`)
        .join("；") || "无";
      return `<div class="document-item"><strong>${escapeHtml(d.filename)}</strong> · ${escapeHtml(labelFrom(DOCUMENT_LABELS, d.document_type))}<br>提取字段：${extracted}</div>`;
    }).join("")
    : "尚未归档材料。";
  const missing = data.missing.length ? `<p class="missing">待补材料：${data.missing.map(x => escapeHtml(x.label)).join("、")}</p>` : "";
  document.querySelector("#material-content").innerHTML = `${missing}${uploaded}`;
}

async function loadMaterials() {
  try {
    renderMaterials(await api(`/v1/applications/${state.applicationId}/materials`));
  } catch (error) {
    document.querySelector("#material-content").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

async function uploadMaterial() {
  const file = document.querySelector("#material-file").files[0];
  if (!file) return toast("请选择文本或表格材料。", true);
  if (file.size > 2_000_000) return toast("材料不能超过 2 兆字节。", true);

  return withButtonBusy("#upload-material", "归档中…", async () => {
    document.querySelector("#material-content").innerHTML = loadingMarkup("正在归档材料并抽取关键字段");
    try {
      const response = await fetch(`/v1/applications/${state.applicationId}/materials/${document.querySelector("#document-type").value}`, {
        method: "PUT",
        headers: {
          "X-User-Id": getUser(),
          "X-Filename": encodeURIComponent(file.name),
          "Content-Type": file.type || "application/octet-stream",
        },
        body: file,
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "上传失败");
      toast("材料已归档并完成字段抽取。");
      document.querySelector("#material-file").value = "";
      await loadMaterials();
      pulse(".materials");
    } catch (error) {
      toast(error.message, true);
      await loadMaterials();
    }
  });
}

function contextGovernanceMarkup(context) {
  if (!context || !context.max_chars) return "";
  const canonical = context.canonical_data || {};
  const freshness = { fresh: "最新", stale: "已过期", unknown: "未知" }[canonical.freshness] || "未接入";
  const conflicts = (canonical.conflicting_fields || []).join("、") || "无";
  return `<p class="context-note">受控上下文：${escapeHtml(context.used_chars || 0)}/${escapeHtml(context.max_chars)} 字符；数据中台：${escapeHtml(freshness)}；跨源字段冲突：${escapeHtml(conflicts)}。</p>`;
}

function feedbackForm(runId) {
  if (!runId) return "";
  return `
    <div class="feedback-form" data-feedback-form data-run-id="${escapeHtml(runId)}">
      <strong>人工复核反馈</strong>
      <select data-feedback-verdict aria-label="复核结论">
        <option value="accepted">可接受</option>
        <option value="needs_revision">需修订</option>
        <option value="incorrect">不正确</option>
      </select>
      <select data-feedback-category aria-label="问题分类">
        <option value="facts">事实</option>
        <option value="evidence">证据</option>
        <option value="risk_assessment">风险判断</option>
        <option value="style">表达</option>
        <option value="other">其他</option>
      </select>
      <input data-feedback-comment maxlength="1000" placeholder="填写至少 5 个字的复核意见（仅用于质量改进）">
      <button data-feedback-submit class="secondary">提交反馈</button>
    </div>`;
}

async function submitAgentFeedback(button) {
  const form = button.closest("[data-feedback-form]");
  const runId = form?.dataset.runId;
  const comment = form?.querySelector("[data-feedback-comment]")?.value?.trim();
  if (!runId || !comment || comment.length < 5) return toast("请填写至少 5 个字的复核意见。", true);
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "提交中…";
  try {
    const feedback = await api(`/v1/applications/${state.applicationId}/agent-runs/${runId}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        verdict: form.querySelector("[data-feedback-verdict]").value,
        category: form.querySelector("[data-feedback-category]").value,
        comment,
      }),
    });
    form.innerHTML = `<span class="context-note">${escapeHtml(feedback.message)}，反馈编号：${escapeHtml(feedback.feedback.id)}</span>`;
    toast("人工复核反馈已纳入线上质量指标。");
    await loadMetrics();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = originalText;
  }
}

function renderReport(report) {
  const findings = report.findings.map(f => `
    <div class="finding ${escapeHtml(f.severity)}">
      <strong>${escapeHtml(f.rule_id)} · ${escapeHtml(f.result)}</strong><br>${escapeHtml(f.message)}
    </div>`).join("");
  const evidence = report.evidence.map(e => `
    <li><strong>${escapeHtml(e.id)} ${escapeHtml(e.title)}</strong>（${escapeHtml(e.version)}，${escapeHtml(e.effective_date)}生效）<br>${escapeHtml(e.content)}</li>`).join("");
  const brief = report.agent_brief ? `
    <div class="agent-brief">
      <h3>智能体评述</h3>
      <p class="run-meta">模型服务：${escapeHtml(labelFrom(PROVIDER_LABELS, report.agent_brief.provider))} · Prompt：${escapeHtml(report.agent_brief.prompt_version || "-")} · 运行编号：${escapeHtml(report.agent_brief.run_id || "-")} · ${escapeHtml(report.agent_brief.created_at || "-")}</p>
      <p>${escapeHtml(report.agent_brief.summary)}</p>
      <div class="brief-grid">
        <div><strong>关键风险</strong><ul>${report.agent_brief.key_risks.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
        <div><strong>建议动作</strong><ul>${report.agent_brief.next_actions.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
      </div>
      ${contextGovernanceMarkup(report.agent_brief.context_governance)}
      <p class="empty">${escapeHtml(report.agent_brief.governance_note)}</p>
      ${feedbackForm(report.agent_brief.run_id)}
    </div>` : "";
  document.querySelector("#report-content").innerHTML = `
    <p><strong>结论：${escapeHtml(report.conclusion)}</strong></p>
    <p class="empty">${escapeHtml(report.disclaimer)}</p>
    ${brief}
    <div class="findings">${findings}</div>
    <div class="evidence"><h3>政策证据</h3><ul>${evidence}</ul></div>`;
  document.querySelector("#report-state").textContent = "已生成";
  pulse(".report");
}

async function preReview() {
  return withButtonBusy("#pre-review", "生成中…", async () => {
    document.querySelector("#report-state").textContent = "智能体处理中";
    document.querySelector("#report-state").className = "tag pending pulse";
    document.querySelector("#report-content").innerHTML = loadingMarkup("正在生成预审报告与政策证据链");
    try {
      const report = await api(`/v1/applications/${state.applicationId}/pre-review`, { method: "POST" });
      renderReport(report);
      toast("预审报告已生成并保存。");
      await loadApplication();
      await loadMetrics();
    } catch (error) {
      document.querySelector("#report-state").textContent = "生成失败";
      document.querySelector("#report-state").className = "tag rejected";
      toast(error.message, true);
    }
  });
}

async function loadReport() {
  return withButtonBusy("#load-report", "读取中…", async () => {
    document.querySelector("#report-content").innerHTML = loadingMarkup("正在读取已保存的预审报告");
    try {
      renderReport(await api(`/v1/applications/${state.applicationId}/pre-review-report`));
      toast("预审报告已加载。");
    } catch (error) {
      toast(error.message, true);
    }
  });
}

function renderAgentAnswer(data) {
  const answer = data.answer;
  document.querySelector("#agent-state").textContent = answer.fallback ? "已降级" : "已回答";
  document.querySelector("#agent-state").className = `tag ${answer.fallback ? "pending" : "approved"}`;
  document.querySelector("#agent-answer").innerHTML = `
    <div class="agent-brief">
      <p class="run-meta">模型服务：${escapeHtml(labelFrom(PROVIDER_LABELS, answer.provider))} · Prompt：${escapeHtml(answer.prompt_version || "-")} · 运行编号：${escapeHtml(answer.run_id || "-")} · ${escapeHtml(answer.created_at || "-")}</p>
      <p>${escapeHtml(answer.answer)}</p>
      <div class="brief-grid">
        <div><strong>证据条款</strong><ul>${(answer.supporting_evidence_ids || []).map(item => `<li>${escapeHtml(item)}</li>`).join("") || "<li>无</li>"}</ul></div>
        <div><strong>建议动作</strong><ul>${(answer.follow_up_actions || []).map(item => `<li>${escapeHtml(item)}</li>`).join("") || "<li>由人工复核。</li>"}</ul></div>
      </div>
      ${answer.fallback_reason ? `<p class="missing">${escapeHtml(answer.fallback_reason)}</p>` : ""}
      ${contextGovernanceMarkup(answer.context_governance)}
      <p class="empty">${escapeHtml(answer.governance_note)}</p>
      ${feedbackForm(answer.run_id)}
    </div>`;
  pulse(".agent-chat");
}

async function askAgent() {
  const question = document.querySelector("#agent-question").value.trim();
  if (!question) return toast("请输入要问智能体的业务问题。", true);
  return withButtonBusy("#ask-agent", "思考中…", async () => {
    document.querySelector("#agent-state").textContent = "智能体思考中";
    document.querySelector("#agent-state").className = "tag pending pulse";
    document.querySelector("#agent-answer").innerHTML = loadingMarkup("正在调用智能体分析业务问题");
    try {
      const result = await api(`/v1/applications/${state.applicationId}/agent-question`, {
        method: "POST",
        body: JSON.stringify({ question }),
      });
      renderAgentAnswer(result);
      toast("智能体已完成业务问答。");
      await loadMetrics();
    } catch (error) {
      document.querySelector("#agent-state").textContent = "失败";
      document.querySelector("#agent-state").className = "tag rejected";
      toast(error.message, true);
    }
  });
}

function renderMetrics(metrics) {
  const rate = `${(metrics.fallback_rate * 100).toFixed(1)}%`;
  const tools = Object.entries(metrics.tool_counts || {})
    .map(([name, count]) => `<li>${escapeHtml(labelFrom(TOOL_LABELS, name))}：${escapeHtml(count)}</li>`)
    .join("") || "<li>暂无工具调用</li>";
  const providers = Object.entries(metrics.provider_counts || {})
    .map(([name, count]) => `<li>${escapeHtml(labelFrom(PROVIDER_LABELS, name))}：${escapeHtml(count)}</li>`)
    .join("") || "<li>暂无数据</li>";
  const online = metrics.online_evaluation || {};
  const observed = online.observed || {};
  const onlineStatus = {
    healthy: "健康", alert: "存在漂移告警", baseline_required: "等待建立基线", insufficient_data: "样本不足",
  }[online.status] || "未评估";
  const promptPerformance = metrics.prompt_performance || {};
  const promptCohorts = (promptPerformance.cohorts || []).map(cohort => {
    const decisions = cohort.human_decision_counts || {};
    const outcomeStatus = cohort.assessment === "observed_only" ? "已达到观察样本" : "工作流样本不足";
    const review = cohort.observation_review;
    const reviewStatus = review
      ? `最新复盘：${labelFrom(OBSERVATION_REVIEW_LABELS, review.status)} · ${labelFrom(OBSERVATION_REVIEW_LABELS, review.recommendation)}`
      : "尚未发起人工复盘";
    const remediationCase = cohort.remediation_case;
    const remediationStatus = remediationCase
      ? `处置单：${labelFrom(REMEDIATION_CASE_LABELS, remediationCase.status)} · ${labelFrom(REMEDIATION_CASE_LABELS, remediationCase.due_state)} · 截止 ${remediationCase.due_date}`
      : "尚无处置作业单";
    return `<li><strong>${escapeHtml(labelFrom(TASK_LABELS, cohort.task))} · ${escapeHtml(cohort.prompt_version)}</strong><br>
      Run：${escapeHtml(cohort.run_count)}；反馈覆盖：${escapeHtml(((cohort.feedback_coverage || 0) * 100).toFixed(1))}%；
      人工工作流结果：${escapeHtml(cohort.workflow_outcome_count)}（批准 ${escapeHtml(decisions.approved || 0)} / 拒绝 ${escapeHtml(decisions.rejected || 0)} / 退回 ${escapeHtml(decisions.returned || 0)}）<br>
      <span class="empty">${escapeHtml(outcomeStatus)}；${escapeHtml(reviewStatus)}；${escapeHtml(remediationStatus)}。仅供人工观察与处置。</span></li>`;
  }).join("") || "<li>暂无可归因的 Prompt 运行。</li>";
  const recent = (metrics.recent_runs || []).map(run => `
    <tr>
      <td>${escapeHtml(run.id)}</td>
      <td>${escapeHtml(labelFrom(TASK_LABELS, run.task || "unknown"))}</td>
      <td>${escapeHtml(labelFrom(PROVIDER_LABELS, run.provider))}</td>
      <td>${escapeHtml(run.duration_ms ?? "-")} 毫秒</td>
      <td>${run.fallback ? "是" : "否"}</td>
      <td>${(run.tool_names || []).map(name => escapeHtml(labelFrom(TOOL_LABELS, name))).join("、") || "-"}</td>
    </tr>`).join("") || `<tr><td colspan="6">暂无智能体运行记录</td></tr>`;

  document.querySelector("#metrics-content").className = "";
  document.querySelector("#metrics-content").innerHTML = `
    <div class="metrics-grid">
      <div class="metric"><small>运行总数</small><strong>${escapeHtml(metrics.total_runs)}</strong></div>
      <div class="metric"><small>降级次数</small><strong>${escapeHtml(metrics.fallback_runs)}</strong></div>
      <div class="metric"><small>降级率</small><strong>${rate}</strong></div>
      <div class="metric"><small>平均耗时</small><strong>${escapeHtml(metrics.average_duration_ms)} 毫秒</strong></div>
      <div class="metric"><small>最大耗时</small><strong>${escapeHtml(metrics.max_duration_ms)} 毫秒</strong></div>
    </div>
    <div class="observability-grid">
      <div><h3>工具调用</h3><ul>${tools}</ul></div>
      <div><h3>模型服务分布</h3><ul>${providers}</ul></div>
    </div>
    <div class="observability-grid">
      <div><h3>线上质量评估</h3><p>状态：${escapeHtml(onlineStatus)}；样本：${escapeHtml(observed.sample_count ?? 0)}；证据覆盖：${escapeHtml(((observed.evidence_coverage || 0) * 100).toFixed(1))}%；人工反馈覆盖：${escapeHtml(((observed.feedback_coverage || 0) * 100).toFixed(1))}%</p></div>
      <div><h3>规划一致性</h3><p>任务规划与实际工具执行：${escapeHtml(observed.plan_adherence_rate == null ? "待采样" : `${(observed.plan_adherence_rate * 100).toFixed(1)}%`)}</p></div>
    </div>
    <div class="observability-grid">
      <div><h3>Prompt 发布后观察</h3><p>最小人工工作流样本：${escapeHtml(promptPerformance.minimum_workflow_outcomes ?? "-")}；处置单：待处理 ${escapeHtml(promptPerformance.remediation_cases?.open ?? 0)}、处理中 ${escapeHtml(promptPerformance.remediation_cases?.in_progress ?? 0)}、逾期 ${escapeHtml(promptPerformance.remediation_cases?.overdue ?? 0)}。人工决定仅记录实际审批流程，不代表模型正确率或自动授信结论。</p></div>
      <div><h3>Prompt 分群</h3><ul>${promptCohorts}</ul></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>运行编号</th><th>任务</th><th>模型服务</th><th>耗时</th><th>是否降级</th><th>调用工具</th></tr></thead>
        <tbody>${recent}</tbody>
      </table>
    </div>`;
  pulse(".observability");
}

async function loadMetrics() {
  return withButtonBusy("#load-metrics", "刷新中…", async () => {
    document.querySelector("#metrics-content").className = "";
    document.querySelector("#metrics-content").innerHTML = loadingMarkup("正在刷新智能体运行观测指标");
    try {
      renderMetrics(await api("/v1/observability/agent-metrics"));
    } catch (error) {
      document.querySelector("#metrics-content").className = "empty";
      document.querySelector("#metrics-content").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    }
  });
}

function renderApproval(task) {
  state.approvalTaskId = task.id;
  const tag = document.querySelector("#approval-state");
  tag.textContent = labelFrom(STATUS_LABELS, task.status);
  tag.className = `tag ${escapeHtml(task.status)}`;
  const controls = task.status === "pending"
    ? `<div class="decision-form"><input id="decision-comment" placeholder="请填写人工审批意见"><button data-decision="approved" class="primary">人工批准</button><button data-decision="returned" class="secondary">退回补充</button><button data-decision="rejected" class="secondary">人工拒绝</button></div>`
    : `<p>处理人：${escapeHtml(task.decided_by || "-")}　处理时间：${escapeHtml(task.decided_at || "-")}<br>审批意见：${escapeHtml(task.decision_comment || "-")}</p>`;
  document.querySelector("#approval-content").innerHTML = `<p><strong>${escapeHtml(task.id)}</strong>　提交人：${escapeHtml(task.submitted_by)}</p>${controls}`;
  document.querySelectorAll("[data-decision]").forEach(button => button.addEventListener("click", () => decide(button.dataset.decision)));
}

async function submit() {
  const override = document.querySelector("#override-reason").value.trim();
  const options = { method: "POST" };
  if (override) options.body = JSON.stringify({ override_reason: override });

  return withButtonBusy("#submit", "提交中…", async () => {
    document.querySelector("#approval-content").innerHTML = loadingMarkup("正在执行审批提交策略校验");
    try {
      const data = await api(`/v1/applications/${state.applicationId}/submit`, options);
      renderApproval(data.approval_task);
      toast("已创建人工审批任务。");
      await loadApplication();
      pulse(".approval");
    } catch (error) {
      document.querySelector("#approval-content").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
      toast(error.message, true);
    }
  });
}

async function decide(decision) {
  const comment = document.querySelector("#decision-comment")?.value?.trim();
  if (!comment) return toast("请先填写人工审批意见。", true);

  return withButtonBusy(`[data-decision="${decision}"]`, "处理中…", async () => {
    try {
      const result = await api(`/v1/approval-tasks/${state.approvalTaskId}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, comment }),
      });
      renderApproval(result.approval_task);
      toast(result.message);
      await loadApplication();
      pulse(".approval");
    } catch (error) {
      toast(error.message, true);
    }
  });
}

document.querySelectorAll(".application-card").forEach(card => card.addEventListener("click", () => {
  document.querySelectorAll(".application-card").forEach(x => x.classList.remove("active"));
  card.classList.add("active");
  state.applicationId = card.dataset.id;
  state.approvalTaskId = null;
  document.querySelector("#report-content").className = "empty";
  document.querySelector("#report-content").textContent = "可生成或查看该申请的预审报告。";
  document.querySelector("#agent-state").textContent = "待提问";
  document.querySelector("#agent-answer").className = "empty";
  document.querySelector("#agent-answer").textContent = "智能体将基于当前申请、材料状态、规则命中和政策证据回答。";
  document.querySelector("#approval-content").className = "empty";
  document.querySelector("#approval-content").textContent = "提交审批后，审批人可在此处理任务。";
  pulse(".applications");
  toast(`已切换到申请 ${card.dataset.id}`);
  loadApplication();
  loadMaterials();
}));

document.querySelector("#pre-review").addEventListener("click", preReview);
document.querySelector("#load-report").addEventListener("click", loadReport);
document.querySelector("#ask-agent").addEventListener("click", askAgent);
document.querySelector("#agent-question").addEventListener("keydown", event => {
  if (event.key === "Enter") askAgent();
});
document.querySelector("#load-metrics").addEventListener("click", loadMetrics);
document.querySelector("#submit").addEventListener("click", submit);
document.querySelector("#upload-material").addEventListener("click", uploadMaterial);
document.addEventListener("click", event => {
  if (event.target.matches("[data-feedback-submit]")) submitAgentFeedback(event.target);
});
document.querySelector("#refresh").addEventListener("click", () => {
  loadApplication();
  loadMaterials();
  loadMetrics();
});
userSelect.addEventListener("change", () => {
  toast(`已切换演示身份：${userSelect.options[userSelect.selectedIndex].textContent}`);
  loadApplication();
  loadMaterials();
  loadMetrics();
});

document.querySelectorAll("button").forEach(button => {
  button.addEventListener("click", event => {
    const ripple = document.createElement("span");
    const rect = button.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    ripple.className = "ripple";
    ripple.style.width = `${size}px`;
    ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;
    button.appendChild(ripple);
    setTimeout(() => ripple.remove(), 620);
  });
});

loadApplication();
loadMaterials();
loadMetrics();
