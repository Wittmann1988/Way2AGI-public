/**
 * Way2AGI Dashboard — Frontend
 * Connects to Orchestrator at /v1/* endpoints
 */

// --- Configuration ---
const API_BASE = window.location.origin;
const WS_URL = `ws://${window.location.host}/ws`;
const POLL_INTERVAL = 5000;  // 5s fallback polling
const CHART_HISTORY = 60;    // 60 data points in chart

// --- Node definitions ---
const NODES = {
  jetson:  { name: 'YOUR_CONTROLLER_DEVICE', ip: 'YOUR_CONTROLLER_IP',  color: '#22c55e', css: 'jetson' },
  desktop: { name: 'Desktop YOUR_GPU', ip: 'YOUR_DESKTOP_IP', color: '#3b82f6', css: 'desktop' },
  zenbook: { name: 'Zenbook', ip: 'YOUR_LAPTOP_IP',          color: '#f59e0b', css: 'zenbook' },
  s24:     { name: 'S24 Tablet', ip: 'YOUR_MOBILE_IP',       color: '#a855f7', css: 's24' },
};

// --- State ---
let ws = null;
let chart = null;
let chartData = {};
let isWaiting = false;

// Initialize chart data arrays
Object.keys(NODES).forEach(k => { chartData[k] = []; });

// --- DOM refs ---
const chatMessages = document.getElementById('chat-messages');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const taskType = document.getElementById('task-type');
const sendBtn = document.getElementById('send-btn');
const connectionDot = document.getElementById('connection-dot');
const connectionStatus = document.getElementById('connection-status');
const totalCostEl = document.getElementById('total-cost');
const nodeCardsEl = document.getElementById('node-cards');
const taskListEl = document.getElementById('task-list');

// --- Initialize ---
document.addEventListener('DOMContentLoaded', () => {
  renderNodeCards();
  initChart();
  connectWebSocket();
  fetchStatus();
  setInterval(fetchStatus, POLL_INTERVAL);

  // Auto-resize textarea
  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  });

  // Submit on Enter (Shift+Enter for newline)
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event('submit'));
    }
  });

  chatForm.addEventListener('submit', handleSubmit);

  // Welcome message
  addMessage('system', 'Willkommen bei Way2AGI. Deine Nachrichten werden intelligent geroutet.');
});

// --- WebSocket ---
function connectWebSocket() {
  try {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      connectionDot.classList.add('connected');
      connectionStatus.textContent = 'Verbunden';
    };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWsMessage(data);
      } catch (e) { /* ignore non-JSON */ }
    };
    ws.onclose = () => {
      connectionDot.classList.remove('connected');
      connectionStatus.textContent = 'Getrennt';
      setTimeout(connectWebSocket, 3000);
    };
    ws.onerror = () => { ws.close(); };
  } catch (e) {
    connectionStatus.textContent = 'WS nicht verfuegbar';
    // Fallback to polling only
  }
}

function handleWsMessage(data) {
  if (data.type === 'node_status') {
    updateNodeCard(data.node, data);
  } else if (data.type === 'task_update') {
    addTaskToList(data);
  }
}

// --- Fetch Status ---
async function fetchStatus() {
  try {
    const resp = await fetch(`${API_BASE}/v1/status`);
    if (!resp.ok) return;
    const data = await resp.json();

    // Update node cards
    if (data.nodes) {
      Object.entries(data.nodes).forEach(([key, info]) => {
        updateNodeCard(key, info);
      });
    }

    // Update cost
    if (data.cloud_providers?.total_cost_usd !== undefined) {
      totalCostEl.textContent = `$${data.cloud_providers.total_cost_usd.toFixed(4)}`;
    }

    // Push to chart
    pushChartData(data.nodes || {});

  } catch (e) {
    // Server might be down
    connectionDot.classList.remove('connected');
    connectionStatus.textContent = 'Server offline';
  }
}

// --- Node Cards ---
function renderNodeCards() {
  nodeCardsEl.innerHTML = Object.entries(NODES).map(([key, node]) => `
    <div class="node-card ${node.css} offline" id="node-${key}">
      <div class="node-name">${node.name}</div>
      <div class="node-ip">${node.ip}</div>
      <span class="node-status-badge offline">Offline</span>
      <div class="node-models" id="models-${key}">-</div>
      <div class="node-load-bar">
        <div class="node-load-fill" id="load-${key}" style="width: 0%"></div>
      </div>
    </div>
  `).join('');
}

function updateNodeCard(key, info) {
  // Normalize key name
  const nodeKey = normalizeNodeKey(key);
  if (!nodeKey) return;

  const card = document.getElementById(`node-${nodeKey}`);
  if (!card) return;

  const isOnline = info.online || info.status === 'online' || info.reachable === true;

  card.classList.toggle('online', isOnline);
  card.classList.toggle('offline', !isOnline);

  const badge = card.querySelector('.node-status-badge');
  badge.className = `node-status-badge ${isOnline ? 'online' : 'offline'}`;
  badge.textContent = isOnline ? 'Online' : 'Offline';

  // Models
  const modelsEl = document.getElementById(`models-${nodeKey}`);
  if (info.models && Array.isArray(info.models)) {
    modelsEl.textContent = info.models.slice(0, 3).join(', ');
  } else if (info.model_count !== undefined) {
    modelsEl.textContent = `${info.model_count} Modelle`;
  }

  // Load
  const load = info.load || info.active_requests || 0;
  const maxLoad = 10;
  const pct = Math.min((load / maxLoad) * 100, 100);
  document.getElementById(`load-${nodeKey}`).style.width = `${pct}%`;
}

function normalizeNodeKey(key) {
  const lower = key.toLowerCase();
  if (lower.includes('jetson')) return 'jetson';
  if (lower.includes('desktop')) return 'desktop';
  if (lower.includes('zenbook')) return 'zenbook';
  if (lower.includes('s24') || lower.includes('tablet')) return 's24';
  // Direct match
  if (NODES[lower]) return lower;
  return null;
}

// --- Chart ---
function initChart() {
  const ctx = document.getElementById('utilization-chart').getContext('2d');

  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array(CHART_HISTORY).fill(''),
      datasets: Object.entries(NODES).map(([key, node]) => ({
        label: node.name,
        data: Array(CHART_HISTORY).fill(0),
        borderColor: node.color,
        backgroundColor: node.color + '20',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.4,
        fill: true,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 2,
      animation: { duration: 300 },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#8888aa',
            font: { size: 11, family: 'Inter' },
            usePointStyle: true,
            pointStyleWidth: 8,
            padding: 16,
          },
        },
      },
      scales: {
        x: { display: false },
        y: {
          beginAtZero: true,
          max: 100,
          grid: { color: 'rgba(42,42,68,0.5)' },
          ticks: {
            color: '#555577',
            font: { size: 10 },
            callback: v => v + '%',
          },
        },
      },
    },
  });
}

function pushChartData(nodes) {
  const nodeKeys = Object.keys(NODES);

  nodeKeys.forEach((key, i) => {
    let load = 0;
    // Try to find matching node data
    for (const [nodeLabel, info] of Object.entries(nodes)) {
      if (normalizeNodeKey(nodeLabel) === key) {
        const isOnline = info.online || info.status === 'online' || info.reachable === true;
        if (isOnline) {
          // Simulate utilization from active_requests or response_time
          load = info.active_requests ? Math.min(info.active_requests * 25, 100) : (info.response_time_ms ? Math.min(info.response_time_ms / 10, 80) : Math.random() * 15 + 5);
        }
        break;
      }
    }

    chartData[key].push(load);
    if (chartData[key].length > CHART_HISTORY) chartData[key].shift();
    chart.data.datasets[i].data = [...chartData[key]];
  });

  // Time labels
  const now = new Date();
  chart.data.labels.push(now.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
  if (chart.data.labels.length > CHART_HISTORY) chart.data.labels.shift();

  chart.update('none');
}

// --- Chat ---
async function handleSubmit(e) {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text || isWaiting) return;

  addMessage('user', text);
  chatInput.value = '';
  chatInput.style.height = 'auto';

  isWaiting = true;
  sendBtn.disabled = true;

  // Show typing indicator
  const typingEl = document.createElement('div');
  typingEl.className = 'typing-indicator';
  typingEl.innerHTML = '<span></span><span></span><span></span>';
  chatMessages.appendChild(typingEl);
  scrollToBottom();

  try {
    const selectedType = taskType.value || undefined;

    const resp = await fetch(`${API_BASE}/v1/orchestrate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: text,
        task_type: selectedType,
      }),
    });

    typingEl.remove();

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: 'Server-Fehler' }));
      addMessage('assistant', `Fehler: ${err.detail || resp.statusText}`, { error: true });
    } else {
      const data = await resp.json();
      const response = data.response || data.result || data.text || JSON.stringify(data);

      const meta = [];
      if (data.routed_to) meta.push(`Node: ${data.routed_to}`);
      if (data.task_type) meta.push(`Typ: ${data.task_type}`);
      if (data.model) meta.push(`Modell: ${data.model}`);
      if (data.duration_s) meta.push(`${data.duration_s.toFixed(1)}s`);
      if (data.cost_usd) meta.push(`$${data.cost_usd.toFixed(5)}`);

      addMessage('assistant', response, { meta: meta.join(' | ') });

      // Add to recent tasks
      addTaskToList({
        prompt: text.substring(0, 60),
        node: data.routed_to || 'unknown',
        task_type: data.task_type || 'default',
      });
    }

  } catch (err) {
    typingEl.remove();
    addMessage('assistant', `Verbindungsfehler: ${err.message}`, { error: true });
  }

  isWaiting = false;
  sendBtn.disabled = false;
  chatInput.focus();
}

function addMessage(role, text, opts = {}) {
  const el = document.createElement('div');
  el.className = `message ${role}`;
  if (opts.error) el.style.borderColor = '#ef4444';

  // Basic markdown-ish rendering
  let html = escapeHtml(text)
    .replace(/```([\s\S]*?)```/g, '<pre>$1</pre>')
    .replace(/`([^`]+)`/g, '<code style="background:rgba(124,92,255,0.15);padding:2px 5px;border-radius:4px;font-family:JetBrains Mono,monospace;font-size:0.85em">$1</code>')
    .replace(/\n/g, '<br>');

  el.innerHTML = html;

  if (opts.meta) {
    const metaEl = document.createElement('div');
    metaEl.className = 'meta';
    metaEl.textContent = opts.meta;
    el.appendChild(metaEl);
  }

  chatMessages.appendChild(el);
  scrollToBottom();
}

function scrollToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// --- Recent Tasks ---
function addTaskToList(task) {
  const nodeKey = normalizeNodeKey(task.node || '') || 'cloud';
  const el = document.createElement('div');
  el.className = 'task-item';
  el.innerHTML = `
    <span class="task-prompt">${escapeHtml(task.prompt || '...')}</span>
    <span class="task-node ${nodeKey}">${nodeKey}</span>
  `;

  // Prepend (newest first)
  if (taskListEl.firstChild) {
    taskListEl.insertBefore(el, taskListEl.firstChild);
  } else {
    taskListEl.appendChild(el);
  }

  // Keep max 10
  while (taskListEl.children.length > 10) {
    taskListEl.removeChild(taskListEl.lastChild);
  }
}
