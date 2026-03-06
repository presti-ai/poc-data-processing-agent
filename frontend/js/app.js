/**
 * P24 Agent - Manual Run UI
 * Vanilla JS frontend for the data processing agent API.
 */

const MODEL_OPTIONS = [
  "google_genai:gemini-3.1-pro-preview",
  "anthropic:claude-opus-4-6",
  "anthropic:claude-sonnet-4-6",
];
const SUBAGENT_OPTIONS = [
  "openai:gpt-5.4",
  "openai:gpt-4o",
  "anthropic:claude-sonnet-4-6",
];

const AGENT_EXTENSIONS = [".csv", ".xlsx", ".xls", ".txt"];

let schemaRows = [];

function init() {
  renderModelSelectors();
  renderSchemaSection();
  document.getElementById("addColumn").addEventListener("click", addColumn);
  document.getElementById("removeColumn").addEventListener("click", removeColumn);
  document.getElementById("runButton").addEventListener("click", runAgent);
  document.getElementById("useInstructions").addEventListener("change", toggleInstructions);
  document.getElementById("uploadToGcsBtn").addEventListener("click", uploadToGCS);
  loadHistory();
  loadOutputs();
}

function renderModelSelectors() {
  // Options are in HTML; no need to render dynamically
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
  const btn = document.getElementById("runButton");
  const loadingEl = document.getElementById("loading");
  btn.disabled = loading;
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

function isAgentCompatible(filename) {
  const idx = filename.lastIndexOf(".");
  if (idx < 0) return false;
  const ext = filename.slice(idx).toLowerCase();
  return AGENT_EXTENSIONS.includes(ext);
}

async function uploadToGCS() {
  const input = document.getElementById("storageFileInput");
  const statusEl = document.getElementById("uploadStatus");
  if (!input.files || input.files.length === 0) {
    statusEl.textContent = "Please select a file to upload.";
    statusEl.className = "upload-status upload-error";
    return;
  }
  statusEl.textContent = "Uploading...";
  statusEl.className = "upload-status";
  const formData = new FormData();
  formData.append("file", input.files[0]);
  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      statusEl.textContent = data.error || "Upload failed.";
      statusEl.className = "upload-status upload-error";
      return;
    }
    statusEl.textContent = `Uploaded: ${data.source} (${data.files?.length || 0} files)`;
    statusEl.className = "upload-status upload-success";
    input.value = "";
    loadHistory();
  } catch (e) {
    statusEl.textContent = e.message || "Upload failed.";
    statusEl.className = "upload-status upload-error";
  }
}

async function loadHistory() {
  const listEl = document.getElementById("historyList");
  listEl.innerHTML = "<p class=\"info\">Loading...</p>";
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    const history = data.history || (Array.isArray(data) ? data : []);
    if (history.length === 0) {
      listEl.innerHTML = "<p class=\"info\">No uploads yet. Upload files above.</p>";
      return;
    }
    let html = "";
    for (const entry of history) {
      const ts = entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "—";
      const files = entry.files || [];
      const agentFiles = files.filter((f) => isAgentCompatible(f.name || ""));
      html += `<div class="history-entry"><details><summary>${escapeHtml(entry.source || "upload")} — ${ts} (${files.length} files)</summary>`;
      html += "<div class=\"history-files\">";
      for (const f of files) {
        const canUse = isAgentCompatible(f.name || "");
        const gcsUri = f.gcs_uri || "";
        html += `<label class="history-file"><input type="checkbox" data-gcs-uri="${escapeHtml(gcsUri)}" ${!canUse ? "disabled" : ""}> ${escapeHtml(f.name)}${!canUse ? " (not for agent)" : ""}</label>`;
      }
      html += "</div></details></div>";
    }
    listEl.innerHTML = html;
  } catch (e) {
    listEl.innerHTML = `<p class=\"info\">Failed to load history: ${escapeHtml(e.message)}</p>`;
  }
}

async function loadOutputs() {
  const listEl = document.getElementById("outputsList");
  listEl.innerHTML = "<p class=\"info\">Loading...</p>";
  try {
    const res = await fetch("/api/outputs");
    const data = await res.json();
    const outputs = data.outputs || [];
    if (outputs.length === 0) {
      listEl.innerHTML = "<p class=\"info\">No outputs yet. Run the agent to generate outputs.</p>";
      return;
    }
    let html = "";
    for (const o of outputs) {
      const ts = o.modified ? new Date(o.modified * 1000).toLocaleString() : "—";
      const sizeKb = o.size ? (o.size / 1024).toFixed(1) : "—";
      const url = `/api/outputs/${encodeURIComponent(o.filename)}`;
      html += `<div class="output-entry"><a href="${url}" download="${escapeHtml(o.filename)}">${escapeHtml(o.filename)}</a> — ${ts} (${sizeKb} KB)</div>`;
    }
    listEl.innerHTML = html;
  } catch (e) {
    listEl.innerHTML = `<p class=\"info\">Failed to load outputs: ${escapeHtml(e.message)}</p>`;
  }
}

function getSelectedHistoryGcsUris() {
  const uris = [];
  document.querySelectorAll("#historyList input[type=checkbox]:checked").forEach((cb) => {
    const uri = cb.dataset.gcsUri;
    if (uri) uris.push(uri);
  });
  return uris;
}

async function runAgent() {
  const fileInput = document.getElementById("fileInput");
  const files = fileInput.files;
  const historyUris = getSelectedHistoryGcsUris();
  if ((!files || files.length === 0) && historyUris.length === 0) {
    alert("Please upload at least one file or select files from history.");
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
              loadOutputs();
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
