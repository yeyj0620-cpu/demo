"use strict";

// 舆情全链路智能处置工作台 · 前端逻辑
// 处置留痕存 localStorage（key: handling_log）；研判对象存 current_target
// 数据源：RSS 新闻 或 导入的舆情 Excel（Brandwatch mentions 导出）

const $ = (sel) => document.querySelector(sel);

const LS_LOG = "handling_log";
const LS_TARGET = "current_target";
const LS_HIDE_IRRELEVANT = "hide_irrelevant";

// 机器英文情感 → 中文
const SENT_MAP = { positive: "正面", neutral: "中性", negative: "负面" };

const state = {
  hasKey: false,
  keySource: null, // 'env' | 'file' | null
  maskedKey: "",
  target: null, // 当前研判对象（统一条目结构）
  news: [],      // 当前采集列表（RSS 或导入）
  newsSource: "rss", // 'rss' | 'import'
  hideIrrelevant: true,
  sentimentSource: "ai",
};

// ---------- 初始化 ----------
window.addEventListener("DOMContentLoaded", init);

async function init() {
  state.target = JSON.parse(localStorage.getItem(LS_TARGET) || "null");
  state.hideIrrelevant = localStorage.getItem(LS_HIDE_IRRELEVANT) !== "0";
  bindEvents();
  renderTargets();
  await checkKey();
  await refreshNews();
}

// ---------- Key 状态 ----------
async function checkKey() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    state.hasKey = !!data.deepseek;
    state.keySource = data.source || null;
    state.maskedKey = data.masked || "";
  } catch (e) {
    state.hasKey = false;
    state.keySource = null;
    state.maskedKey = "";
  }
  renderKeyStatus();
}

function renderKeyStatus() {
  const badge = $("#key-status");
  const banner = $("#no-key-banner");
  if (state.hasKey) {
    badge.textContent = state.maskedKey ? `DeepSeek ${state.maskedKey}` : "DeepSeek 已连接";
    badge.className = "key-badge ok";
    banner.classList.add("hidden");
  } else {
    badge.textContent = "未配置 Key（点击配置）";
    badge.className = "key-badge warn";
    banner.classList.remove("hidden");
  }
}

function ensureKey() {
  if (!state.hasKey) {
    openKeyModal();
    return false;
  }
  return true;
}

// ---------- 配 Key 弹窗 ----------
function openKeyModal() {
  renderKeyModal();
  $("#key-modal").classList.remove("hidden");
  $("#key-input").focus();
}

function closeKeyModal() {
  $("#key-modal").classList.add("hidden");
}

function renderKeyModal() {
  const status = $("#key-modal-status");
  const input = $("#key-input");
  input.value = "";
  if (state.keySource === "env") {
    status.textContent = `已通过环境变量 DEEPSEEK_API_KEY 配置（${state.maskedKey}），无法在此界面修改。`;
    $("#save-key").disabled = true;
    $("#clear-key").disabled = true;
  } else {
    status.textContent = state.hasKey
      ? `当前已配置（${state.maskedKey}）。输入新 Key 覆盖，或点「清除」移除。`
      : "尚未配置。粘贴你的 DeepSeek Key（sk-...）后点「保存」。";
    $("#save-key").disabled = false;
    $("#clear-key").disabled = !state.hasKey;
  }
}

async function saveKey() {
  const key = $("#key-input").value.trim();
  try {
    const res = await fetch("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "保存失败");
    await checkKey();
    if (key) closeKeyModal();
  } catch (e) {
    alert("保存 Key 失败：" + e.message);
  }
}

async function clearKey() {
  if (!confirm("确定清除已保存的 DeepSeek Key？")) return;
  try {
    const res = await fetch("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: "" }),
    });
    if (!res.ok) throw new Error("清除失败");
    await checkKey();
  } catch (e) {
    alert("清除 Key 失败：" + e.message);
  }
}

// ---------- 事件绑定 ----------
function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });
  $("#refresh-rss").addEventListener("click", refreshNews);
  $("#run-verify").addEventListener("click", runVerify);
  $("#run-comment").addEventListener("click", runComment);
  $("#run-complaint").addEventListener("click", runComplaint);
  $("#export-report").addEventListener("click", exportReport);
  $("#clear-log").addEventListener("click", clearLog);
  $("#key-status").addEventListener("click", openKeyModal);
  $("#open-key-modal").addEventListener("click", openKeyModal);
  $("#save-key").addEventListener("click", saveKey);
  $("#clear-key").addEventListener("click", clearKey);
  $("#close-key-modal").addEventListener("click", closeKeyModal);
  $("#key-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveKey();
  });
  $("#file-input").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) importFile(file);
  });
  $("#hide-irrelevant").addEventListener("change", (e) => {
    state.hideIrrelevant = e.target.checked;
    localStorage.setItem(LS_HIDE_IRRELEVANT, state.hideIrrelevant ? "1" : "0");
    renderNews();
  });
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name)
  );
  document.querySelectorAll(".panel").forEach((p) =>
    p.classList.toggle("active", p.id === "panel-" + name)
  );
  if (name === "report") renderReport();
}

// ---------- 通用请求 ----------
async function postDeepseek(task, payload) {
  const res = await fetch("/api/deepseek", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, payload }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.detail || `请求失败（HTTP ${res.status}）`);
  }
  return data.result;
}

// ---------- ① 舆情采集：RSS ----------
async function refreshNews() {
  const list = $("#news-list");
  list.innerHTML = '<li class="empty">正在加载 RSS 新闻…</li>';
  try {
    const res = await fetch("/api/rss");
    const data = await res.json();
    state.news = (data.items || []).map((n) => ({
      id: n.link || n.title,
      title: n.title,
      rawTitle: "",
      tag: null,
      brand: null,
      sentiment: n.sentiment || "中性",
      sentimentBy: n.sentimentBy || "规则判定",
      source: n.source,
      platform: null,
      country: null,
      author: null,
      language: null,
      time: n.time || "",
      link: n.link || "",
      desc: n.desc || "",
      isIrrelevant: false,
    }));
    state.newsSource = "rss";
    if (state.news.length === 0) {
      list.innerHTML = '<li class="empty">未获取到新闻，请稍后重试。</li>';
      return;
    }
    await annotateSentiment();
    renderNews();
  } catch (e) {
    list.innerHTML = `<li class="empty">RSS 加载失败：${escapeHtml(e.message)}</li>`;
  }
}

async function annotateSentiment() {
  const titles = state.news.map((n) => n.title);
  try {
    const labels = await postDeepseek("sentiment", { titles });
    if (Array.isArray(labels) && labels.length === titles.length) {
      state.news.forEach((n, i) => {
        n.sentiment = labels[i];
        n.sentimentBy = "AI 判定";
      });
      state.sentimentSource = "ai";
      return;
    }
    throw new Error("情感结果长度不匹配");
  } catch (e) {
    // 降级关键词规则，并明确标注「规则判定」（不冒充 AI）
    state.news.forEach((n) => {
      n.sentiment = ruleSentiment(n.title);
      n.sentimentBy = "规则判定";
    });
    state.sentimentSource = "rule";
  }
}

function ruleSentiment(title) {
  const neg = /裁员|暴跌|事故|亏损|维权|投诉|暴雷|造假|召回|危机|死亡|罚款|下架|崩盘|丑闻|诉讼|处罚/;
  const pos = /增长|突破|融资|上市|获奖|利好|创新|盈利|翻倍|回暖|签约|新品|合作|研发/;
  if (neg.test(title)) return "负面";
  if (pos.test(title)) return "正面";
  return "中性";
}

// ---------- ① 舆情采集：导入 Excel ----------
async function importFile(file) {
  const list = $("#news-list");
  $("#import-info").textContent = `正在导入 ${file.name} …`;
  list.innerHTML = '<li class="empty">正在解析 Excel，请稍候…</li>';
  try {
    const res = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      throw new Error(data.detail || `导入失败（HTTP ${res.status}）`);
    }
    state.news = (data.items || []).map(mapMention);
    state.newsSource = "import";
    renderImportInfo(file.name);
    renderNews();
  } catch (e) {
    list.innerHTML = `<li class="empty">导入失败：${escapeHtml(e.message)}</li>`;
    renderImportInfo(null, e.message);
  } finally {
    $("#file-input").value = "";
  }
}

// 后端归一化条目 → 前端统一条目结构
function mapMention(m) {
  const rawTitle = m.title || "";
  const snippet = m.snippet || "";
  const tag = m.tag || "";
  const isIrrelevant = tag === "无关";
  const manual = m.sentiment_manual || "";
  const machine = SENT_MAP[(m.sentiment || "").toLowerCase()] || "";
  const sentiment = manual || machine || "中性";
  const sentimentBy = manual ? "人工标注" : machine ? "机器判定" : "";
  const parts = [];
  if (rawTitle) parts.push(rawTitle);
  if (snippet && snippet !== rawTitle) parts.push(snippet);
  return {
    id: m.index || m.url || rawTitle,
    title: isIrrelevant ? rawTitle : tag || rawTitle,
    rawTitle,
    tag,
    brand: m.brand || "",
    sentiment,
    sentimentBy,
    source: m.domain || m.platform || "",
    platform: m.platform || "",
    country: m.country || "",
    author: m.author || "",
    language: m.language || "",
    time: m.time || "",
    link: m.url || "",
    desc: parts.join("\n\n"),
    isIrrelevant,
  };
}

function renderImportInfo(fileName, err) {
  const info = $("#import-info");
  if (err) {
    info.textContent = "导入失败";
    info.className = "import-info error";
    return;
  }
  if (!fileName) {
    info.textContent = "尚未导入数据";
    info.className = "import-info";
    return;
  }
  const total = state.news.length;
  const irr = state.news.filter((n) => n.isIrrelevant).length;
  info.textContent = `已导入 ${fileName}（共 ${total} 条 · 相关 ${total - irr} 条 · 无关 ${irr} 条）`;
  info.className = "import-info";
}

// ---------- 渲染列表 ----------
function renderNews() {
  const list = $("#news-list");
  if (state.news.length === 0) {
    list.innerHTML = '<li class="empty">暂无数据，请「刷新 RSS」或「导入舆情 Excel」。</li>';
    return;
  }
  const visible = state.news.filter((n) => !state.hideIrrelevant || !n.isIrrelevant);
  if (visible.length === 0) {
    list.innerHTML = '<li class="empty">当前全部为「无关」条目（已隐藏），取消勾选「隐藏无关」可查看。</li>';
    return;
  }
  list.innerHTML = visible.map((n) => renderNewsItem(n)).join("");
  list.querySelectorAll("button[data-id]").forEach((btn) => {
    btn.addEventListener("click", () => selectTarget(btn.dataset.id));
  });
}

function renderNewsItem(n) {
  const sent = n.sentiment || "中性";
  const isTarget = state.target && state.target.id && state.target.id === n.id;
  const brand = n.brand ? `<span class="brand">${escapeHtml(n.brand)}</span>` : "";
  const tag = n.tag && n.tag !== "无关" ? `<span class="tag">${escapeHtml(n.tag)}</span>` : "";
  const meta = [n.source, n.platform, n.country, n.author, n.time]
    .filter((x) => x)
    .map((x) => escapeHtml(x));
  const subText = n.rawTitle && n.rawTitle !== n.title ? n.rawTitle : n.desc && n.desc !== n.title ? n.desc : "";
  return `
    <li class="news-item ${isTarget ? "selected" : ""}">
      <div class="news-main">
        <span class="sentiment sent-${sent}">${sent}</span>
        <div class="news-body">
          <div class="news-title">${escapeHtml(n.title)} ${brand} ${tag}</div>
          ${subText ? `<div class="news-sub">${escapeHtml(truncate(subText, 140))}</div>` : ""}
        </div>
      </div>
      <div class="news-meta">
        ${meta.map((m) => `<span>${m}</span>`).join("")}
        ${n.sentimentBy ? `<span class="sentiment-by">${escapeHtml(n.sentimentBy)}</span>` : ""}
      </div>
      <div class="news-actions">
        <button class="btn small" data-id="${escapeHtml(n.id)}">
          ${isTarget ? "已选为研判对象" : "选为研判对象"}
        </button>
      </div>
    </li>`;
}

function selectTarget(id) {
  const item = state.news.find((n) => n.id === id);
  if (!item) return;
  state.target = item;
  localStorage.setItem(LS_TARGET, JSON.stringify(state.target));
  renderNews();
  renderTargets();
}

function renderTargets() {
  let label;
  if (!state.target) {
    label = "尚未选择研判对象，请先在「舆情采集」中选择一条。";
  } else {
    const meta = [];
    if (state.target.brand) meta.push(`品牌：${state.target.brand}`);
    if (state.target.tag && state.target.tag !== "无关") meta.push(`标签：${state.target.tag}`);
    meta.push(`来源：${state.target.source || "未知"}`);
    label = `研判对象：${state.target.title}（${meta.join(" · ")}）`;
  }
  $("#verify-target").textContent = label;
  $("#comment-target").textContent = label;
}

// ---------- ② AI 核查 ----------
async function runVerify() {
  if (!state.target) {
    alert("请先在「舆情采集」选择一条作为研判对象");
    return;
  }
  if (!ensureKey()) return;
  setBusy("#run-verify", true);
  try {
    const result = await postDeepseek("verify", {
      title: state.target.title,
      content: state.target.desc || "",
    });
    renderVerifyResult(result);
    appendLog("核查", { 标题: state.target.title, 内容: state.target.desc || "" }, result);
  } catch (e) {
    $("#verify-result").innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;
  } finally {
    setBusy("#run-verify", false);
  }
}

function renderVerifyResult(r) {
  const verdict = r && r.verdict ? r.verdict : "—";
  const risk = r && r.risk ? r.risk : "—";
  const evidence = (r && r.evidence) || [];
  $("#verify-result").innerHTML = `
    <div class="result-grid">
      <div class="field">
        <span class="label">核查结论</span>
        <span class="value verdict-${verdictKey(verdict)}">${escapeHtml(verdict)}</span>
      </div>
      <div class="field">
        <span class="label">风险等级</span>
        <span class="value risk-${escapeHtml(risk)}">${escapeHtml(risk)}</span>
      </div>
    </div>
    <div class="field">
      <span class="label">证据链</span>
      <ul class="evidence">${evidence.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>
    </div>
    <div class="field">
      <span class="label">处置建议</span>
      <p class="value">${escapeHtml((r && r.conclusion) || "—")}</p>
    </div>`;
}

function verdictKey(v) {
  if (v === "真") return "true";
  if (v === "假") return "false";
  return "doubt";
}

// ---------- ③ AI 事实评论 ----------
async function runComment() {
  if (!state.target) {
    alert("请先在「舆情采集」选择一条作为研判对象");
    return;
  }
  if (!ensureKey()) return;
  const style = $("#comment-style").value;
  setBusy("#run-comment", true);
  try {
    const result = await postDeepseek("comment", { event: state.target.title, style });
    $("#comment-result").innerHTML = `<div class="comment-text">${escapeHtml(result)}</div>`;
    appendLog("评论", { 事件: state.target.title, 风格: style }, result);
  } catch (e) {
    $("#comment-result").innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;
  } finally {
    setBusy("#run-comment", false);
  }
}

// ---------- ④ AI 投诉处置 ----------
async function runComplaint() {
  if (!ensureKey()) return;
  const text = $("#complaint-input").value.trim();
  if (!text) {
    alert("请输入投诉文本");
    return;
  }
  setBusy("#run-complaint", true);
  try {
    const result = await postDeepseek("complaint", { text });
    $("#complaint-result").innerHTML = `
      <div class="result-grid">
        <div class="field"><span class="label">分类</span><span class="value">${escapeHtml(result.type || "—")}</span></div>
        <div class="field"><span class="label">优先级</span><span class="value">${escapeHtml(result.priority || "—")}</span></div>
        <div class="field"><span class="label">转办部门</span><span class="value">${escapeHtml(result.dept || "—")}</span></div>
      </div>
      <div class="field"><span class="label">回复话术</span><p class="value">${escapeHtml(result.reply || "—")}</p></div>`;
    appendLog("投诉", { 投诉内容: text }, result);
  } catch (e) {
    $("#complaint-result").innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;
  } finally {
    setBusy("#run-complaint", false);
  }
}

// ---------- ⑤ 处置报告 & 留痕 ----------
function getLog() {
  try {
    return JSON.parse(localStorage.getItem(LS_LOG) || "[]");
  } catch (e) {
    return [];
  }
}

function appendLog(module, input, result) {
  const log = getLog();
  log.push({ ts: Date.now(), module, input, result });
  localStorage.setItem(LS_LOG, JSON.stringify(log));
}

function clearLog() {
  if (!confirm("确定清空所有处置留痕？")) return;
  localStorage.removeItem(LS_LOG);
  renderReport();
}

function buildReport() {
  const log = getLog();
  const lines = [];
  lines.push("# 舆情处置报告");
  lines.push("");
  lines.push(`- 生成时间：${new Date().toLocaleString()}`);
  lines.push(`- 研判对象：${state.target ? state.target.title : "（无）"}`);
  lines.push(`- 处置记录数：${log.length}`);
  lines.push("");
  lines.push("## 处置过程");
  lines.push("");
  if (log.length === 0) {
    lines.push("（暂无处置记录）");
  }
  log.forEach((entry, i) => {
    lines.push(`### ${i + 1}. ${entry.module} —— ${new Date(entry.ts).toLocaleString()}`);
    lines.push("");
    lines.push("**输入**：");
    lines.push("");
    lines.push("```json");
    lines.push(JSON.stringify(entry.input, null, 2));
    lines.push("```");
    lines.push("");
    lines.push("**结果**：");
    lines.push("");
    const isText = typeof entry.result === "string";
    lines.push("```" + (isText ? "" : "json"));
    lines.push(isText ? entry.result : JSON.stringify(entry.result, null, 2));
    lines.push("```");
    lines.push("");
  });
  return lines.join("\n");
}

function renderReport() {
  $("#report-preview").textContent = buildReport();
}

function exportReport() {
  const md = buildReport();
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `舆情处置报告_${new Date().toISOString().slice(0, 10)}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------- 工具 ----------
function setBusy(selector, busy) {
  const el = $(selector);
  if (busy) {
    el.dataset.orig = el.textContent;
    el.textContent = "处理中…";
    el.disabled = true;
  } else {
    el.textContent = el.dataset.orig || el.textContent;
    el.disabled = false;
  }
}

function truncate(str, n) {
  return String(str).length > n ? String(str).slice(0, n) + "…" : String(str);
}

function escapeHtml(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
