"""Operator Dashboard route rendering a self-contained web interface."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Dashboard"])

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ATLAS - Autonomous Task & Lifecycle Automation System</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font);
      line-height: 1.5;
      padding: 1.5rem;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid var(--border);
      margin-bottom: 1.5rem;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .brand h1 {
      font-size: 1.5rem;
      font-weight: 700;
      letter-spacing: -0.025em;
    }
    .badge {
      display: inline-block;
      padding: 0.25rem 0.5rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }
    .badge-primary { background: rgba(56, 189, 248, 0.15); color: var(--primary); }
    .badge-success { background: rgba(34, 197, 94, 0.15); color: var(--success); }
    .badge-warning { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
    .badge-danger { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
    .auth-bar {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    input, select, button, textarea {
      font-family: inherit;
      font-size: 0.875rem;
      border-radius: 0.375rem;
      border: 1px solid var(--border);
      padding: 0.5rem 0.75rem;
      background: var(--card-bg);
      color: var(--text);
    }
    button {
      background: var(--primary);
      color: #0f172a;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: background 0.15s;
    }
    button:hover { background: var(--primary-hover); color: #fff; }
    button.btn-danger { background: var(--danger); color: #fff; }
    button.btn-success { background: var(--success); color: #0f172a; }
    button.btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1.5rem;
      margin-bottom: 1.5rem;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 0.5rem;
      padding: 1.25rem;
    }
    .card h2 {
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
      color: var(--text);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .stat-val {
      font-size: 2rem;
      font-weight: 700;
      color: var(--primary);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.875rem;
      margin-top: 0.5rem;
    }
    th, td {
      padding: 0.625rem 0.75rem;
      border-bottom: 1px solid var(--border);
    }
    th {
      color: var(--text-muted);
      font-weight: 500;
      text-transform: uppercase;
      font-size: 0.75rem;
    }
    .log-box {
      background: #020617;
      border: 1px solid var(--border);
      border-radius: 0.375rem;
      padding: 0.75rem;
      height: 220px;
      overflow-y: auto;
      font-family: monospace;
      font-size: 0.75rem;
      white-space: pre-wrap;
      color: #38bdf8;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>ATLAS Control Plane</h1>
      <span class="badge badge-primary">v0.1.0</span>
      <span class="badge badge-success" id="engine-status">ONLINE</span>
    </div>
    <div class="auth-bar">
      <input type="password" id="api-key" placeholder="API Key" value="admin-key">
      <button onclick="refreshDashboard()">Refresh</button>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>Active Tasks</h2>
      <div class="stat-val" id="stat-tasks">0</div>
    </div>
    <div class="card">
      <h2>Pending Approvals</h2>
      <div class="stat-val" id="stat-approvals" style="color: var(--warning);">0</div>
    </div>
    <div class="card">
      <h2>Active Workers</h2>
      <div class="stat-val" id="stat-workers">0</div>
    </div>
  </div>

  <div class="grid" style="grid-template-columns: 2fr 1fr;">
    <div class="card">
      <h2>Task Fleet</h2>
      <table id="tasks-table">
        <thead>
          <tr>
            <th>Task ID</th>
            <th>Objective</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="tasks-body">
          <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No tasks yet</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>Submit New Task</h2>
      <form id="task-form" onsubmit="submitTask(event)" style="display: flex; flex-direction: column; gap: 0.75rem;">
        <div>
          <label style="font-size: 0.75rem; color: var(--text-muted);">Objective</label>
          <input type="text" id="task-obj" placeholder="e.g. Navigate to example.com and verify header" required style="width: 100%;">
        </div>
        <div>
          <label style="font-size: 0.75rem; color: var(--text-muted);">Priority</label>
          <select id="task-pri" style="width: 100%;">
            <option value="NORMAL">NORMAL</option>
            <option value="HIGH">HIGH</option>
            <option value="CRITICAL">CRITICAL</option>
            <option value="LOW">LOW</option>
          </select>
        </div>
        <button type="submit">Submit Task</button>
      </form>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Human Approval Inbox</h2>
      <table id="approvals-table">
        <thead>
          <tr>
            <th>Request ID</th>
            <th>Task ID</th>
            <th>Action</th>
            <th>Risk Level</th>
            <th>Reason</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody id="approvals-body">
          <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No pending approvals</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>Event Stream Log</h2>
    <div class="log-box" id="event-log">// Ready. Waiting for task events...</div>
  </div>

  <script>
    function getKey() {
      return document.getElementById('api-key').value || 'admin-key';
    }

    function log(msg) {
      const box = document.getElementById('event-log');
      const time = new Date().toISOString().substring(11, 19);
      box.textContent += `[${time}] ${msg}\\n`;
      box.scrollTop = box.scrollHeight;
    }

    async function api(path, options = {}) {
      options.headers = options.headers || {};
      options.headers['Authorization'] = 'Bearer ' + getKey();
      if (options.body && typeof options.body === 'object') {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(options.body);
      }
      return fetch(path, options);
    }

    async function refreshDashboard() {
      try {
        const [tRes, aRes, wRes] = await Promise.all([
          api('/api/v1/tasks'),
          api('/api/v1/approvals'),
          api('/api/v1/workers')
        ]);

        if (tRes.ok) {
          const tasks = await tRes.json();
          document.getElementById('stat-tasks').innerText = tasks.length;
          renderTasks(tasks);
        }
        if (aRes.ok) {
          const approvals = await aRes.json();
          const pending = approvals.filter(a => a.status === 'PENDING');
          document.getElementById('stat-approvals').innerText = pending.length;
          renderApprovals(pending);
        }
        if (wRes.ok) {
          const workers = await wRes.json();
          document.getElementById('stat-workers').innerText = workers.length;
        }
      } catch (e) {
        log('Error refreshing dashboard: ' + e);
      }
    }

    function renderTasks(tasks) {
      const tbody = document.getElementById('tasks-body');
      if (!tasks.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No tasks yet</td></tr>';
        return;
      }
      tbody.innerHTML = tasks.map(t => `
        <tr>
          <td><code>${t.task_id}</code></td>
          <td>${t.objective}</td>
          <td><span class="badge badge-${t.status === 'COMPLETED' ? 'success' : (t.status === 'WAITING_APPROVAL' ? 'warning' : 'primary')}">${t.status}</span></td>
          <td>${t.priority}</td>
          <td>
            ${t.status === 'RUNNING' ? `<button class="btn-sm" onclick="pauseTask('${t.task_id}')">Pause</button>` : ''}
            ${t.status === 'PAUSED' ? `<button class="btn-sm btn-success" onclick="resumeTask('${t.task_id}')">Resume</button>` : ''}
            ${!['COMPLETED', 'FAILED', 'CANCELLED'].includes(t.status) ? `<button class="btn-sm btn-danger" onclick="cancelTask('${t.task_id}')">Cancel</button>` : ''}
          </td>
        </tr>
      `).join('');
    }

    function renderApprovals(approvals) {
      const tbody = document.getElementById('approvals-body');
      if (!approvals.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No pending approvals</td></tr>';
        return;
      }
      tbody.innerHTML = approvals.map(a => `
        <tr>
          <td><code>${a.request_id}</code></td>
          <td><code>${a.task_id}</code></td>
          <td><strong>${a.action_type}</strong></td>
          <td><span class="badge badge-warning">${a.risk_level}</span></td>
          <td>${a.reason}</td>
          <td>
            <button class="btn-sm btn-success" onclick="grantApproval('${a.request_id}')">Grant</button>
            <button class="btn-sm btn-danger" onclick="denyApproval('${a.request_id}')">Deny</button>
          </td>
        </tr>
      `).join('');
    }

    async function submitTask(e) {
      e.preventDefault();
      const obj = document.getElementById('task-obj').value;
      const pri = document.getElementById('task-pri').value;
      const res = await api('/api/v1/tasks?wait=false', {
        method: 'POST',
        body: { objective: obj, priority: pri }
      });
      if (res.ok) {
        const task = await res.json();
        log('Task submitted: ' + task.task_id);
        document.getElementById('task-obj').value = '';
        refreshDashboard();
      } else {
        log('Failed to submit task');
      }
    }

    async function pauseTask(taskId) {
      await api(`/api/v1/tasks/${taskId}/pause`, { method: 'POST' });
      refreshDashboard();
    }

    async function resumeTask(taskId) {
      await api(`/api/v1/tasks/${taskId}/resume`, { method: 'POST' });
      refreshDashboard();
    }

    async function cancelTask(taskId) {
      await api(`/api/v1/tasks/${taskId}/cancel`, { method: 'POST' });
      refreshDashboard();
    }

    async function grantApproval(reqId) {
      const res = await api(`/api/v1/approvals/${reqId}/grant`, { method: 'POST', body: { reason: 'Operator approved in dashboard' } });
      if (res.ok) {
        log('Granted approval ' + reqId);
        refreshDashboard();
      }
    }

    async function denyApproval(reqId) {
      const res = await api(`/api/v1/approvals/${reqId}/deny`, { method: 'POST', body: { reason: 'Operator rejected in dashboard' } });
      if (res.ok) {
        log('Denied approval ' + reqId);
        refreshDashboard();
      }
    }

    // Auto-refresh interval
    setInterval(refreshDashboard, 3000);
    refreshDashboard();
  </script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard() -> str:
    """Serve the single-page ATLAS Operator Dashboard UI."""
    return DASHBOARD_HTML
