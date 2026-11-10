/**
 * ecom copilot — Frontend Application State & Client Logic
 */

const STATE = {
  token: localStorage.getItem("ecom_token") || null,
  currentUser: null,
  activeSessionId: null,
  isTraceOpen: false,
  availableUsers: [],
};

// ─── DOM References ──────────────────────────────────────────────────────────
const dom = {
  app: document.getElementById("app"),
  userName: document.getElementById("userName"),
  userRole: document.getElementById("userRole"),
  switchUserBtn: document.getElementById("switchUserBtn"),
  themeToggleBtn: document.getElementById("themeToggleBtn"),
  traceToggleBtn: document.getElementById("traceToggleBtn"),
  newChatBtn: document.getElementById("newChatBtn"),
  sessionsList: document.getElementById("sessionsList"),
  adminPanel: document.getElementById("adminPanel"),
  reembedBtn: document.getElementById("reembedBtn"),
  pendingRefundsBadge: document.getElementById("pendingRefundsBadge"),
  pendingRefundsList: document.getElementById("pendingRefundsList"),
  chatMessages: document.getElementById("chatMessages"),
  chatForm: document.getElementById("chatForm"),
  messageInput: document.getElementById("messageInput"),
  sendBtn: document.getElementById("sendBtn"),
  traceDrawer: document.getElementById("traceDrawer"),
  closeTraceBtn: document.getElementById("closeTraceBtn"),
  metricLatency: document.getElementById("metricLatency"),
  metricCost: document.getElementById("metricCost"),
  metricPromptTokens: document.getElementById("metricPromptTokens"),
  metricCompTokens: document.getElementById("metricCompTokens"),
  traceId: document.getElementById("traceId"),
  traceStatus: document.getElementById("traceStatus"),
  stepsList: document.getElementById("stepsList"),
  userModal: document.getElementById("userModal"),
  closeModalBtn: document.getElementById("closeModalBtn"),
  customersList: document.getElementById("customersList"),
  adminsList: document.getElementById("adminsList"),
};

// ─── API Client Helper ────────────────────────────────────────────────────────
async function api(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (STATE.token) {
    headers["Authorization"] = `Bearer ${STATE.token}`;
  }

  const res = await fetch(endpoint, { ...options, headers });
  if (res.status === 401) {
    console.warn("Session unauthorized. Clearing token.");
    localStorage.removeItem("ecom_token");
    STATE.token = null;
    await performDefaultLogin();
    return null;
  }
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

// ─── Authentication & User Switching ──────────────────────────────────────────
async function performLogin(email, password = "user123") {
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error("Login failed");
    const data = await res.json();
    STATE.token = data.access_token;
    localStorage.setItem("ecom_token", STATE.token);
    STATE.currentUser = data.user;
    updateUserUI();
    await loadSessions();
    if (STATE.currentUser.role === "admin") {
      await loadPendingRefunds();
    }
  } catch (err) {
    console.error("Login error:", err);
  }
}

async function performDefaultLogin() {
  await performLogin("alice@email.com", "user123");
}

async function loadCurrentUser() {
  if (!STATE.token) {
    await performDefaultLogin();
    return;
  }
  try {
    const user = await api("/api/auth/me");
    if (!user) return;
    STATE.currentUser = user;
    updateUserUI();
    await loadSessions();
    if (STATE.currentUser.role === "admin") {
      await loadPendingRefunds();
    }
  } catch (err) {
    console.warn("Could not load current user, defaulting:", err);
    await performDefaultLogin();
  }
}

function updateUserUI() {
  if (!STATE.currentUser) return;
  dom.userName.textContent = STATE.currentUser.name;
  dom.userRole.textContent = STATE.currentUser.role;
  dom.userRole.className = `role-pill ${STATE.currentUser.role}`;

  if (STATE.currentUser.role === "admin") {
    dom.adminPanel.classList.remove("hidden");
  } else {
    dom.adminPanel.classList.add("hidden");
  }
}

async function loadAvailableUsers() {
  try {
    const users = await api("/api/auth/users");
    STATE.availableUsers = users || [];
    renderUsersModal();
  } catch (err) {
    console.error("Failed to fetch user list:", err);
  }
}

function renderUsersModal() {
  dom.customersList.innerHTML = "";
  dom.adminsList.innerHTML = "";

  STATE.availableUsers.forEach((u) => {
    const btn = document.createElement("button");
    btn.className = "user-option-btn";
    btn.innerHTML = `
      <div>
        <div class="user-opt-name">${u.name}</div>
        <div class="user-opt-email">${u.email}</div>
      </div>
      <span class="role-pill ${u.role}">${u.role}</span>
    `;
    btn.onclick = async () => {
      dom.userModal.classList.add("hidden");
      const defaultPass = u.role === "admin" ? "admin123" : "user123";
      await performLogin(u.email, defaultPass);
      startNewChat();
    };

    if (u.role === "admin") {
      dom.adminsList.appendChild(btn);
    } else {
      dom.customersList.appendChild(btn);
    }
  });
}

// ─── Sessions & Chat History ──────────────────────────────────────────────────
async function loadSessions() {
  try {
    const sessions = await api("/api/chat/sessions");
    dom.sessionsList.innerHTML = "";
    if (!sessions || sessions.length === 0) {
      dom.sessionsList.innerHTML = `<div class="empty-state-sm">No conversations yet</div>`;
      return;
    }

    sessions.forEach((s) => {
      const item = document.createElement("div");
      item.className = `session-item ${s.id === STATE.activeSessionId ? "active" : ""}`;
      item.textContent = s.title || "Untitled Session";
      item.onclick = () => selectSession(s.id);
      dom.sessionsList.appendChild(item);
    });
  } catch (err) {
    console.error("Failed to load sessions:", err);
  }
}

async function selectSession(sessionId) {
  STATE.activeSessionId = sessionId;
  document.querySelectorAll(".session-item").forEach((el) => el.classList.remove("active"));
  await loadSessions();

  try {
    const messages = await api(`/api/chat/sessions/${sessionId}/messages`);
    dom.chatMessages.innerHTML = "";
    if (messages && messages.length > 0) {
      messages.forEach((m) => renderMessage(m.role, m.content, m.tool_calls));
      scrollChatToBottom();
    }
  } catch (err) {
    console.error("Failed to load messages:", err);
  }
}

function startNewChat() {
  STATE.activeSessionId = null;
  document.querySelectorAll(".session-item").forEach((el) => el.classList.remove("active"));
  dom.chatMessages.innerHTML = `
    <div class="welcome-hero">
      <div class="hero-icon">🛍️</div>
      <h2>How can I help you today?</h2>
      <p>I can track your shipments, check catalog inventory, evaluate return windows, and process refunds according to store policies.</p>
      
      <div class="suggestions-grid">
        <button class="suggestion-chip" data-prompt="Where is my order ORD-2024-001 and when was it delivered?">
          📦 Track order ORD-2024-001
        </button>
        <button class="suggestion-chip" data-prompt="Can I return the Wireless Bluetooth Headphones from order ORD-2024-001?">
          🔄 Check return eligibility for ORD-2024-001
        </button>
        <button class="suggestion-chip" data-prompt="Do you have any 4K webcams in stock, and how long is their warranty?">
          🔍 Check 4K webcam stock & warranty
        </button>
        <button class="suggestion-chip" data-prompt="What happens if a package shows delivered but I haven't received it?">
          📋 What is your lost package policy?
        </button>
      </div>
    </div>
  `;
  attachSuggestionListeners();
}

// ─── Message Rendering & Text Formatting ──────────────────────────────────────
function formatMessageContent(rawText) {
  let text = rawText || "";

  // Highlight Citations [Source: ...]
  text = text.replace(/\[Source:\s*([^\]]+)\]/gi, (match, src) => {
    return `<span class="citation-badge">📄 ${src.trim()}</span>`;
  });

  // Code blocks
  text = text.replace(/```([\s\S]*?)```/g, '<pre class="step-details-pre"><code>$1</code></pre>');

  // Inline backticks
  text = text.replace(/`([^`]+)`/g, '<code class="font-mono">$1</code>');

  // Bold text
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // Newlines
  text = text.replace(/\n/g, "<br>");

  return text;
}

function renderMessage(role, content, toolCalls = null) {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;

  let toolsHtml = "";
  if (toolCalls && toolCalls.length > 0) {
    toolsHtml = `<div class="tool-pill-container">`;
    toolCalls.forEach((tc) => {
      const toolName = tc.tool || (tc.function && tc.function.name) || "tool";
      toolsHtml += `<span class="tool-pill" title="Click to view tool details">🔧 ${toolName}</span>`;
    });
    toolsHtml += `</div>`;
  }

  row.innerHTML = `
    ${toolsHtml}
    <div class="message-bubble">
      ${formatMessageContent(content)}
    </div>
  `;

  dom.chatMessages.appendChild(row);
}

function showThinkingIndicator() {
  const row = document.createElement("div");
  row.id = "thinkingIndicator";
  row.className = "message-row assistant";
  row.innerHTML = `
    <div class="thinking-row">
      <div class="spinner"></div>
      <span>AI reasoning & executing tools...</span>
    </div>
  `;
  dom.chatMessages.appendChild(row);
  scrollChatToBottom();
}

function removeThinkingIndicator() {
  const el = document.getElementById("thinkingIndicator");
  if (el) el.remove();
}

function scrollChatToBottom() {
  dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;
}

// ─── Sending Messages ─────────────────────────────────────────────────────────
async function handleSendMessage(e) {
  if (e) e.preventDefault();
  const msg = dom.messageInput.value.trim();
  if (!msg) return;

  dom.messageInput.value = "";
  dom.messageInput.style.height = "auto";

  // Remove hero if first message
  const hero = dom.chatMessages.querySelector(".welcome-hero");
  if (hero) hero.remove();

  renderMessage("user", msg);
  showThinkingIndicator();

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: msg,
        session_id: STATE.activeSessionId,
      }),
    });

    removeThinkingIndicator();

    if (data) {
      STATE.activeSessionId = data.session_id;
      renderMessage("assistant", data.response, data.tool_calls);
      scrollChatToBottom();
      await loadSessions();

      if (data.trace) {
        updateTraceInspector(data.trace);
      }
    }
  } catch (err) {
    removeThinkingIndicator();
    renderMessage("assistant", `⚠️ Error: ${err.message}`);
    scrollChatToBottom();
  }
}

// ─── Trace Inspector Drawer ───────────────────────────────────────────────────
function updateTraceInspector(trace) {
  dom.traceId.textContent = trace.trace_id || "-";
  dom.metricLatency.textContent = `${trace.total_latency_ms || 0} ms`;
  dom.metricCost.textContent = `$${(trace.estimated_cost_usd || 0).toFixed(6)}`;
  dom.metricPromptTokens.textContent = trace.prompt_tokens || 0;
  dom.metricCompTokens.textContent = trace.completion_tokens || 0;

  dom.traceStatus.textContent = trace.status || "success";
  dom.traceStatus.className = `status-badge ${trace.status === "success" ? "status-success" : ""}`;

  dom.stepsList.innerHTML = "";
  if (!trace.steps || trace.steps.length === 0) {
    dom.stepsList.innerHTML = `<div class="empty-state-sm">Zero tool calls (Direct response)</div>`;
    return;
  }

  trace.steps.forEach((step) => {
    const card = document.createElement("div");
    card.className = "step-card";
    const detailsStr = JSON.stringify(step.details || {}, null, 2);
    card.innerHTML = `
      <div class="step-header">
        <span>Step ${step.step_number}: ${step.name}</span>
        <span class="step-duration">${step.duration_ms} ms</span>
      </div>
      <pre class="step-details-pre"><code>${detailsStr}</code></pre>
    `;
    dom.stepsList.appendChild(card);
  });
}

function toggleTraceDrawer() {
  STATE.isTraceOpen = !STATE.isTraceOpen;
  dom.traceDrawer.classList.toggle("open", STATE.isTraceOpen);
}

// ─── Admin Pending Refunds ───────────────────────────────────────────────────
async function loadPendingRefunds() {
  try {
    const data = await api("/api/admin/refunds/pending");
    if (!data) return;

    dom.pendingRefundsBadge.textContent = data.pending_count || 0;
    dom.pendingRefundsList.innerHTML = "";

    if (!data.refunds || data.refunds.length === 0) {
      dom.pendingRefundsList.innerHTML = `<div class="empty-state-sm">No refunds awaiting review</div>`;
      return;
    }

    data.refunds.forEach((r) => {
      const item = document.createElement("div");
      item.className = "pending-refund-item";
      item.innerHTML = `
        <div style="display:flex; justify-content:space-between;">
          <span class="font-mono"><strong>${r.refund_id}</strong> (${r.order_id})</span>
          <span class="pending-refund-amount">$${r.amount.toFixed(2)}</span>
        </div>
        <div style="color:var(--text-secondary); margin-top:2px;">${r.customer_email}</div>
        <button class="btn approve-btn" data-id="${r.refund_id}">Approve Refund</button>
      `;

      item.querySelector(".approve-btn").onclick = () => approveRefund(r.refund_id);
      dom.pendingRefundsList.appendChild(item);
    });
  } catch (err) {
    console.error("Failed to load pending refunds:", err);
  }
}

async function approveRefund(refundId) {
  try {
    const data = await api(`/api/admin/refunds/${refundId}/approve`, { method: "POST" });
    if (data) {
      alert(`Refund ${refundId} approved successfully.`);
      await loadPendingRefunds();
    }
  } catch (err) {
    alert(`Failed to approve refund: ${err.message}`);
  }
}

// ─── Suggestion Chips ─────────────────────────────────────────────────────────
function attachSuggestionListeners() {
  document.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.onclick = () => {
      const prompt = chip.getAttribute("data-prompt");
      if (prompt) {
        dom.messageInput.value = prompt;
        handleSendMessage();
      }
    };
  });
}

// ─── Event Listeners ──────────────────────────────────────────────────────────
function initEvents() {
  dom.chatForm.onsubmit = handleSendMessage;

  dom.messageInput.onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  dom.newChatBtn.onclick = startNewChat;
  dom.traceToggleBtn.onclick = toggleTraceDrawer;
  dom.closeTraceBtn.onclick = toggleTraceDrawer;

  dom.switchUserBtn.onclick = () => {
    loadAvailableUsers();
    dom.userModal.classList.remove("hidden");
  };

  dom.closeModalBtn.onclick = () => {
    dom.userModal.classList.add("hidden");
  };

  dom.themeToggleBtn.onclick = () => {
    const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
    const nextTheme = currentTheme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", nextTheme);
    dom.themeToggleBtn.textContent = nextTheme === "dark" ? "🌙" : "☀️";
  };

  attachSuggestionListeners();
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  initEvents();
  await loadCurrentUser();
});

