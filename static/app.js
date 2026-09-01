"use strict";

// 舆情全链路智能处置工作台 · 前端逻辑
// 处置留痕存 localStorage（key: handling_log）；研判对象存 current_target

const $ = (sel) => document.querySelector(sel);

const LS_LOG = "handling_log";
const LS_TARGET = "current_target";

const state = {
  hasKey: false,
  target: null, // 当前研判对象 { title, source, time, link, desc, sentiment, sentimentBy }
  news: [],
  sentimentSource: "ai", // 'ai' | 'rule'
};

// ---------- 初始化 ----------
window.addEventListener("DOMContentLoaded", init);

async function init() {
  state.target = JSON.parse(localStorage.getItem(LS_TARGET) || "null");
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
  } catch (e) {
    state.hasKey = false;
  }
  renderKeyStatus();
}

function renderKeyStatus() {
  const badge = $("#key-status");
  const banner = $("#no-key-banner");
  if (state.hasKey) {
    badge.textContent = "DeepSeek 已连接";
    badge.className = "key-badge ok";
    banner.classList.add("hidden");
  } else {
    badge.textContent = "未配置 Key";
    badge.className = "key-badge warn";
    banner.classList.remove("hidden");
  }
}

function ensureKey() {
  if (!state.hasKey) {
    showModal(true);
    return false;
  }
  return true;
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
  $("#open-key-modal").addEventListener("click", () => showModal(true));
  $("#close-key-modal").addEventListener("click", () => showModal(false));
  $("#recheck-key").addEventListener("click", async () => {
    await checkKey();
    if (state.hasKey) showModal(false);
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

function showModal(show) {
  $("#key-modal").classList.toggle("hidden", !show);
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

// ---------- ① 舆情采集 ----------
async function refreshNews() {
  const list = $("#news-list");
  list.innerHTML = '<li class="empty">正在加载 RSS 新闻…</li>';
  try {
    const res = await fetch("/api/rss");
    const data = await res.json();
    state.news = data.items || [];
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

function renderNews() {
  const list = $("#news-list");
  list.innerHTML = state.news
    .map((n, i) => {
      const sent = n.sentiment || "中性";
      const isTarget = state.target && state.target.title === n.title;
      return `
        <li class="news-item ${isTarget ? "selected" : ""}">
          <div class="news-main">
            <span class="sentiment sent-${sent}">${sent}</span>
            <span class="news-title">${escapeHtml(n.title)}</span>
          </div>
          <div class="news-meta">
            <span>${escapeHtml(n.source)}</span>
            <span>${escapeHtml(n.time || "")}</span>
            <span class="sentiment-by">${n.sentimentBy || "规则判定"}</span>
          </div>
          <div class="news-actions">
            <button class="btn small" data-index="${i}">
              ${isTarget ? "已选为研判对象" : "选为研判对象"}
            </button>
          </div>
        </li>`;
    })
    .join("");

  list.querySelectorAll("button[data-index]").forEach((btn) => {
    btn.addEventListener("click", () => selectTarget(Number(btn.dataset.index)));
  });
}

function selectTarget(index) {
  state.target = state.news[index];
  localStorage.setItem(LS_TARGET, JSON.stringify(state.target));
  renderNews();
  renderTargets();
}

function renderTargets() {
  const label = state.target
    ? `研判对象：${state.target.title}（来源：${state.target.source}）`
    : "尚未选择研判对象，请先在「舆情采集」中选择一条。";
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

function escapeHtml(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
