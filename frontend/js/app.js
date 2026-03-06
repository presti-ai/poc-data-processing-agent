/**
 * P24 Agent - Manual Run UI
 * Vanilla JS frontend with hash routing: #/, #/history, #/rerun/{run_id}
 */

const AGENT_EXTENSIONS = [".csv", ".xlsx", ".xls", ".txt"];

let schemaRows = [];
let presetRun = null;

function init() {
  renderSchemaSection();
  document.getElementById("addColumn").addEventListener("click", addColumn);
  document.getElementById("removeColumn").addEventListener("click", removeColumn);
  document.getElementById("runButton").addEventListener("click", () => runAgent(false));
  document.getElementById("rerunButton").addEventListener("click", () => runAgent(true));
  document.getElementById("clearRerunBtn").addEventListener("click", clearRerunPreset);
  document.getElementById("useInstructions").addEventListener("change", toggleInstructions);

  window.addEventListener("hashchange", route);
  document.querySelectorAll(".nav-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      window.location.hash = a.getAttribute("href").slice(1);
    });
  });

  route();
}

function getRoute() {
  const hash = (window.location.hash || "#/").slice(1);
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "rerun" && parts[1]) return { page: "rerun", runId: parts[1] };
  if (parts[0] === "history") return { page: "history" };
  return { page: "run" };
}

function route() {
  const r = getRoute();
  const runPage = document.getElementById("runPage");
  const historyPage = document.getElementById("historyPage");

  runPage.hidden = r.page !== "run" && r.page !== "rerun";
  historyPage.hidden = r.page !== "history";

  document.querySelectorAll(".nav-link").forEach((a) => {
    const route = a.dataset.route || a.getAttribute("href").slice(2);
    a.classList.toggle("active", (route === "/" && (r.page === "run" || r.page === "rerun")) || (route === "/history" && r.page === "history"));
  });

  if (r.page === "history") {
    loadRuns();
  } else if (r.page === "rerun" && r.runId) {
    loadRunForRerun(r.runId);
  } else {
    clearRerunPreset();
  }
}

async function loadRunForRerun(runId) {
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!res.ok) {
      clearRerunPreset();
      window.location.hash = "#/";
      return;
    }
    const run = await res.json();
    applyRerunPreset(run);
  } catch (e) {
    clearRerunPreset();
    window.location.hash = "#/";
  }
}

function applyRerunPreset(run) {
  presetRun = run;
  const section = document.getElementById("rerunPresetSection");
  const infoEl = document.getElementById("rerunPresetInfo");
  const runBtn = document.getElementById("runButton");
  const rerunBtn = document.getElementById("rerunButton");

  const inputs = (run.inputs || []).map((i) => i.name || "?").join(", ");
  const params = run.params || {};
  infoEl.innerHTML = `
    <p><strong>Inputs:</strong> ${escapeHtml(inputs || "—")}</p>
    <p><strong>Duration:</strong> ${run.duration_seconds ?? "—"}s | <strong>Status:</strong> ${escapeHtml(run.status || "—")}</p>
    <p><strong>Model:</strong> ${escapeHtml(params.model_name || "—")}</p>
  `;

  if (params.output_columns && Array.isArray(params.output_columns)) {
    schemaRows = params.output_columns.map((c) => ({
      name: c.name || "",
      description: c.description || "",
    }));
    renderSchemaSection();
  }
  if (params.model_name) {
    const sel = document.getElementById("modelName");
    if (sel.querySelector(`option[value="${params.model_name}"]`)) sel.value = params.model_name;
  }
  if (params.subagent_model_name) {
    const sel = document.getElementById("subagentModelName");
    if (sel.querySelector(`option[value="${params.subagent_model_name}"]`)) sel.value = params.subagent_model_name;
  }
  document.getElementById("useInstructions").checked = !!(params.additional_instructions && params.additional_instructions.trim());
  document.getElementById("additionalInstructions").value = params.additional_instructions || "";
  document.getElementById("additionalInstructions").disabled = !document.getElementById("useInstructions").checked;

  section.hidden = false;
  runBtn.hidden = true;
  rerunBtn.hidden = false;
}

function clearRerunPreset() {
  presetRun = null;
  document.getElementById("rerunPresetSection").hidden = true;
  document.getElementById("runButton").hidden = false;
  document.getElementById("rerunButton").hidden = true;
  if (getRoute().page === "rerun") {
    window.location.hash = "#/";
  }
}

function renderSchemaSection() {
  const container = document.getElementById("schemaRows");
  container.innerHTML = "";
  schemaRows.forEach((row, idx) => {
    const div = document.createElement("div");
    div.className = "schema-row";
    div.innerHTML = `
      <label>Column ${idx + 1} name</label>
      <input type="text" data-col="name" data-idx="${idx}" value="${escapeHtml(row.name || "")}" placeholder="Column name" />
      <label>Column ${idx + 1} description</label>
      <input type="text" data-col="desc" data-idx="${idx}" value="${escapeHtml(row.description || "")}" placeholder="Description" />
      <hr />
    `;
    container.appendChild(div);
  });
  container.querySelectorAll("input").forEach((inp) => {
    inp.addEventListener("change", (e) => {
      const idx = parseInt(e.target.dataset.idx, 10);
      const col = e.target.dataset.col;
      if (col === "name") schemaRows[idx].name = e.target.value;
      else schemaRows[idx].description = e.target.value;
    });
  });
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function addColumn() {
  schemaRows.push({ name: "", description: "" });
  renderSchemaSection();
}

function removeColumn() {
  if (schemaRows.length > 0) {
    schemaRows.pop();
    renderSchemaSection();
  }
}

function toggleInstructions() {
  const textarea = document.getElementById("additionalInstructions");
  textarea.disabled = !document.getElementById("useInstructions").checked;
}

function getOutputColumns() {
  return schemaRows.filter((r) => r.name && r.name.trim()).map((r) => ({
    name: r.name.trim(),
    description: (r.description || "").trim(),
  }));
}

function setLoading(loading) {
  const runBtn = document.getElementById("runButton");
  const rerunBtn = document.getElementById("rerunButton");
  const loadingEl = document.getElementById("loading");
  runBtn.disabled = loading;
  rerunBtn.disabled = loading;
  loadingEl.hidden = !loading;
}

function clearMessages() {
  document.getElementById("messagesPanel").innerHTML = "";
}

function appendMessage(role, content, name) {
  const panel = document.getElementById("messagesPanel");
  const div = document.createElement("div");
  div.className = `message-block message-${role}`;
  const label = name ? `Tool: ${name}` : role;
  const short = content.length > 80 ? content.slice(0, 80) + "..." : content;
  div.innerHTML = `
    <details>
      <summary>${escapeHtml(label)} - ${escapeHtml(short)}</summary>
      <pre>${escapeHtml(content)}</pre>
    </details>
  `;
  panel.appendChild(div);
  panel.scrollTop = panel.scrollHeight;
}

function parseCSVLine(line) {
  const result = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') inQuotes = !inQuotes;
    else if (c === "," && !inQuotes) {
      result.push(current.replace(/^"|"$/g, "").trim());
      current = "";
    } else current += c;
  }
  result.push(current.replace(/^"|"$/g, "").trim());
  return result;
}

function showOutput(csv) {
  const section = document.getElementById("outputSection");
  const tableWrap = document.getElementById("outputTableWrap");
  const downloadLink = document.getElementById("downloadLink");
  const successEl = document.getElementById("outputSuccess");
  section.hidden = false;
  successEl.hidden = false;

  const rows = csv.trim().split("\n");
  if (rows.length === 0) {
    tableWrap.innerHTML = "<p>No data</p>";
    return;
  }
  const headers = parseCSVLine(rows[0]);
  const data = rows.slice(1).map((r) => parseCSVLine(r));

  let html = "<table><thead><tr>";
  headers.forEach((h) => (html += `<th>${escapeHtml(h)}</th>`));
  html += "</tr></thead><tbody>";
  data.forEach((row) => {
    html += "<tr>";
    row.forEach((cell) => (html += `<td>${escapeHtml(cell)}</td>`));
    html += "</tr>";
  });
  html += "</tbody></table>";
  tableWrap.innerHTML = html;

  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  downloadLink.href = url;
  downloadLink.download = "output.csv";
  downloadLink.hidden = false;
}

function showError(msg) {
  const panel = document.getElementById("messagesPanel");
  const div = document.createElement("div");
  div.className = "message-block message-error";
  div.innerHTML = `<strong>Error:</strong> ${escapeHtml(msg)}`;
  panel.appendChild(div);
}

async function loadRuns() {
  const wrap = document.getElementById("runsTableWrap");
  wrap.innerHTML = "<p class=\"info\">Loading...</p>";
  try {
    const res = await fetch("/api/runs");
    const data = await res.json();
    const runs = data.runs || [];
    if (runs.length === 0) {
      wrap.innerHTML = "<p class=\"info\">No runs yet. Run the agent to create history.</p>";
      return;
    }
    let html = `
      <table class="runs-table">
        <thead><tr>
          <th>Date</th><th>Inputs</th><th>Outputs</th><th>Duration</th><th>Status</th><th>Params</th><th></th>
        </tr></thead>
        <tbody>
    `;
    for (const r of runs) {
      const date = r.timestamp ? new Date(r.timestamp).toLocaleString() : "—";
      const inputs = (r.inputs || []).map((i) => i.name).join(", ") || "—";
      const outputs = (r.outputs || []).map((o) => o.name).join(", ") || "—";
      const duration = r.duration_seconds != null ? `${r.duration_seconds}s` : "—";
      const status = r.status || "—";
      const params = r.params ? `${r.params.model_name || "—"}` : "—";
      const runId = r.id || "";
      html += `
        <tr class="runs-row" data-run-id="${escapeHtml(runId)}">
          <td>${escapeHtml(date)}</td>
          <td>${escapeHtml(inputs)}</td>
          <td>${escapeHtml(outputs)}</td>
          <td>${escapeHtml(duration)}</td>
          <td>${escapeHtml(status)}</td>
          <td>${escapeHtml(params)}</td>
          <td><button type="button" class="delete-run-btn" data-run-id="${escapeHtml(runId)}" title="Delete">×</button></td>
        </tr>
      `;
    }
    html += "</tbody></table>";
    wrap.innerHTML = html;

    wrap.querySelectorAll(".runs-row").forEach((row) => {
      row.addEventListener("click", (e) => {
        if (e.target.classList.contains("delete-run-btn")) return;
        const id = row.dataset.runId;
        if (id) window.location.hash = `#/rerun/${id}`;
      });
    });
    wrap.querySelectorAll(".delete-run-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = btn.dataset.runId;
        if (!id) return;
        if (!confirm("Delete this run?")) return;
        try {
          const res = await fetch(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" });
          if (res.ok) loadRuns();
        } catch (err) {
          console.error(err);
        }
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class=\"info\">Failed to load runs: ${escapeHtml(e.message)}</p>`;
  }
}

async function runAgent(isRerun) {
  const fileInput = document.getElementById("fileInput");
  const files = fileInput.files;
  let historyUris = [];

  if (isRerun && presetRun && presetRun.inputs) {
    historyUris = presetRun.inputs.map((i) => i.gcs_uri).filter(Boolean);
  }

  if ((!files || files.length === 0) && historyUris.length === 0) {
    alert("Please upload at least one file or select a run from history to rerun.");
    return;
  }

  const outputColumns = getOutputColumns();
  const useInstructions = document.getElementById("useInstructions").checked;
  const additionalInstructions = useInstructions
    ? document.getElementById("additionalInstructions").value
    : "";
  const modelName = document.getElementById("modelName").value;
  const subagentModelName = document.getElementById("subagentModelName").value;

  const formData = new FormData();
  for (let i = 0; i < (files?.length || 0); i++) {
    formData.append("files", files[i]);
  }
  formData.append("history_file_ids", JSON.stringify(historyUris));
  formData.append("output_columns", JSON.stringify(outputColumns));
  formData.append("additional_instructions", additionalInstructions);
  formData.append("model_name", modelName);
  formData.append("subagent_model_name", subagentModelName);

  setLoading(true);
  clearMessages();
  document.getElementById("outputSection").hidden = true;

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ error: response.statusText }));
      let msg = err.error || "Request failed";
      if (response.status === 422 && err.detail) {
        const parts = Array.isArray(err.detail)
          ? err.detail.map((d) => `${d.loc?.join(".") || "?"}: ${d.msg || ""}`)
          : [String(err.detail)];
        msg = `Validation error: ${parts.join("; ")}`;
      }
      throw new Error(msg);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const raw of events) {
        const match = raw.match(/^data:\s*(.+)$/m);
        if (!match) continue;
        try {
          const ev = JSON.parse(match[1]);
          if (ev.type === "chunk" && ev.data) {
            const d = ev.data;
            if (d.model) {
              for (const m of d.model) {
                const data = m.data || {};
                const content = Array.isArray(data.content)
                  ? data.content.map((c) => (c.text || c) || "").join("")
                  : (data.content || "");
                const toolCalls = data.tool_calls || [];
                if (content) appendMessage("ai", content, null);
                for (const tc of toolCalls) {
                  appendMessage("ai", `Tool call: ${tc.name}`, tc.name);
                }
              }
            }
            if (d.tools) {
              for (const m of d.tools) {
                const data = m.data || {};
                const name = data.name || "tool";
                const content = Array.isArray(data.content)
                  ? data.content.map((c) => (c.text || c) || "").join("")
                  : (data.content || "");
                if (content) appendMessage("tool", content, name);
              }
            }
          } else if (ev.type === "retry") {
            appendMessage("system", ev.message || "Retrying...", null);
          } else if (ev.type === "done") {
            if (ev.error) {
              showError(ev.error);
            } else if (ev.csv) {
              showOutput(ev.csv);
              if (document.getElementById("historyPage") && !document.getElementById("historyPage").hidden) {
                loadRuns();
              }
            }
          }
        } catch (e) {
          console.warn("Parse SSE event:", e);
        }
      }
    }
  } catch (e) {
    showError(e.message);
  } finally {
    setLoading(false);
  }
}

document.addEventListener("DOMContentLoaded", init);
