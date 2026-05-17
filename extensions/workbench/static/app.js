const state = {
  currentUserId: localStorage.getItem("workbench.currentUserId") || "",
  latestRecord: null,
  latestContext: null,
  templates: { groups: [], experiments: [], instruments: [] },
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", async () => {
  bindNavigation();
  bindActions();
  await Promise.all([loadUsers(), loadTemplates()]);
  if (state.currentUserId) {
    await selectUser(state.currentUserId);
  }
});

function bindNavigation() {
  document.querySelectorAll("nav button").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
}

function bindActions() {
  $("choose-user-btn").addEventListener("click", async () => {
    await selectUser($("user-select").value);
    showView("record");
  });

  $("create-user-btn").addEventListener("click", async () => {
    const userId = $("new-user-id").value.trim();
    const displayName = $("new-user-name").value.trim();
    if (!userId) return toast("请先填写用户 ID");
    await request(`/workbench/api/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      body: JSON.stringify({ display_name: displayName || userId }),
    });
    await loadUsers();
    await selectUser(userId);
    showView("record");
    toast("已创建新用户");
  });

  $("record-form").addEventListener("submit", submitRecord);
  $("profile-form").addEventListener("submit", saveProfile);
  $("reanalyze-btn").addEventListener("click", async () => {
    if (!state.latestRecord || !state.latestContext) return toast("还没有最近记录可重新分析");
    await runPersonalizedAnalysis(state.latestRecord, state.latestContext);
    toast("已用新规则重新分析");
  });
}

function showView(name) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  document.querySelectorAll("nav button").forEach((button) => button.classList.remove("active"));
  $(`view-${name}`).classList.add("active");
  document.querySelector(`nav button[data-view="${name}"]`).classList.add("active");
}

async function loadUsers() {
  const users = await request("/workbench/api/users");
  const select = $("user-select");
  select.innerHTML = users.length
    ? users.map((user) => `<option value="${escapeHtml(user.user_id)}">${escapeHtml(user.display_name)}</option>`).join("")
    : `<option value="">暂无用户</option>`;
}

async function loadTemplates() {
  state.templates = await request("/workbench/api/templates");
  fillTemplateSelect($("group-template"), state.templates.groups, "materials_default");
  fillTemplateSelect($("experiment-template"), state.templates.experiments, "");
  fillTemplateSelect($("instrument-template"), state.templates.instruments, "");
}

function fillTemplateSelect(select, items, defaultValue) {
  const blank = select.id === "group-template" ? "" : `<option value="">不指定</option>`;
  select.innerHTML =
    blank +
    items
      .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name)}</option>`)
      .join("");
  select.value = defaultValue;
}

async function selectUser(userId) {
  if (!userId) return;
  const profile = await request(`/workbench/api/users/${encodeURIComponent(userId)}`);
  state.currentUserId = userId;
  localStorage.setItem("workbench.currentUserId", userId);
  $("current-user-label").textContent = profile.display_name || userId;
  $("operator").value = profile.display_name || userId;
  populateProfileForm(profile);
  await refreshEffectiveProfile();
}

function populateProfileForm(profile) {
  $("profile-display-name").value = profile.display_name || "";
  $("profile-aliases").value = Object.entries(profile.term_aliases || {})
    .map(([raw, canonical]) => `${raw}=${canonical}`)
    .join("\n");
  $("profile-patterns").value = (profile.sample_id_patterns || []).join("\n");
  $("profile-required").value = (profile.required_fields || []).join("\n");
  $("profile-preferred").value = (profile.preferred_fields || []).join("\n");
  $("profile-notes").value = (profile.handwriting_notes || []).join("\n");
}

async function refreshEffectiveProfile() {
  if (!state.currentUserId) return;
  const query = new URLSearchParams(
    Object.entries(currentContext()).filter(([, value]) => value),
  ).toString();
  const summary = await request(`/workbench/api/effective-profile?${query}`);
  const messages = summary.messages.map((message) => `<li>${escapeHtml(message)}</li>`).join("");
  const layers = summary.layers
    .filter((layer) => layer.id)
    .map((layer) => `<span class="pill">${escapeHtml(layer.label)}：${escapeHtml(layer.id)}${layer.loaded ? "" : "（未加载）"}</span>`)
    .join("");
  $("effective-profile-summary").innerHTML = `
    <ul>${messages}</ul>
    <div class="pill-row">${layers}</div>
  `;
}

async function submitRecord(event) {
  event.preventDefault();
  if (!state.currentUserId) return toast("请先选择当前用户");

  const form = new FormData();
  form.append("experiment_id", $("experiment-id").value.trim());
  if ($("operator").value.trim()) form.append("operator", $("operator").value.trim());
  [...$("images").files].forEach((file) => form.append("images", file));
  [...$("instrument-files").files].forEach((file) => form.append("instrument_files", file));

  const record = await request("/experiments/draft/upload", { method: "POST", body: form }, false);
  state.latestRecord = record;
  state.latestContext = currentContext();
  await runPersonalizedAnalysis(record, state.latestContext);
  $("analysis-result").classList.remove("hidden");
  toast("分析完成");
}

async function runPersonalizedAnalysis(record, context) {
  const payload = await request("/workbench/api/personalized-analysis", {
    method: "POST",
    body: JSON.stringify({ record, ...context }),
  });
  renderAnalysis(record, payload);
  await refreshEffectiveProfile();
}

function renderAnalysis(record, analysis) {
  $("recognized-summary").innerHTML = `
    <ul>
      <li>实验 ID：${escapeHtml(record.experiment_id || "—")}</li>
      <li>材料数：${(record.materials_catalog || record.materials || []).length}</li>
      <li>事件数：${(record.events || []).length}</li>
      <li>主干复核问题：${(record.review_issues || []).length}</li>
    </ul>
  `;

  $("normalized-summary").innerHTML = analysis.normalized_step_changes.length
    ? `<ul>${analysis.normalized_step_changes
        .map(
          (step) =>
            `<li>${escapeHtml(step.raw_step_type)} → ${escapeHtml(step.normalized_step_type)}</li>`,
        )
        .join("")}</ul>`
    : `<p class="muted">这次没有发现需要按个人习惯改写的步骤术语。</p>`;

  $("missing-summary").innerHTML = analysis.missing_required_fields.length
    ? `<div class="pill-row">${analysis.missing_required_fields
        .map((field) => `<span class="pill">${escapeHtml(field)}</span>`)
        .join("")}</div>`
    : `<p class="muted">当前个性化规则要求的字段都已出现。</p>`;

  $("next-step-summary").innerHTML = analysis.review_issues.length
    ? `<ul>${analysis.review_issues
        .map((issue) => `<li>${escapeHtml(issue.detail)}</li>`)
        .join("")}</ul>`
    : `<p class="muted">这份记录暂时没有新增的个性化补充建议。</p>`;
}

async function saveProfile(event) {
  event.preventDefault();
  if (!state.currentUserId) return toast("请先选择当前用户");
  const payload = {
    display_name: $("profile-display-name").value.trim(),
    term_aliases: parsePairs($("profile-aliases").value),
    sample_id_patterns: parseLines($("profile-patterns").value),
    required_fields: parseLines($("profile-required").value),
    preferred_fields: parseLines($("profile-preferred").value),
    handwriting_notes: parseLines($("profile-notes").value),
  };
  const profile = await request(`/workbench/api/users/${encodeURIComponent(state.currentUserId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  populateProfileForm(profile);
  $("current-user-label").textContent = profile.display_name || state.currentUserId;
  await refreshEffectiveProfile();
  toast("个人规则已保存");
}

function currentContext() {
  return {
    user_id: state.currentUserId || "",
    group_id: $("group-template").value || "materials_default",
    experiment_template_id: $("experiment-template").value || null,
    instrument_id: $("instrument-template").value || null,
  };
}

function parseLines(value) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parsePairs(value) {
  return Object.fromEntries(
    parseLines(value)
      .map((line) => line.split("=", 2).map((item) => item.trim()))
      .filter(([raw, canonical]) => raw && canonical),
  );
}

async function request(url, options = {}, json = true) {
  const response = await fetch(url, {
    headers: json ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return response.json();
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 1800);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
