/**
 * P24 Agent - Manual Run UI
 * Vanilla JS frontend for the data processing agent API.
 */

const MODEL_OPTIONS = [
  "google_genai:gemini-3-pro-preview",
  "anthropic:claude-opus-4-6",
  "anthropic:claude-sonnet-4-6",
];
const SUBAGENT_OPTIONS = [
  "openai:gpt-5.4",
  "openai:gpt-4o",
  "anthropic:claude-sonnet-4-6",
];

let schemaRows = [];

function init() {
  renderModelSelectors();
  renderSchemaSection();
  document.getElementById("addColumn").addEventListener("click", addColumn);
  document.getElementById("removeColumn").addEventListener("click", removeColumn);
  document.getElementById("runButton").addEventListener("click", runAgent);
  document.getElementById("useInstructions").addEventListener("change", toggleInstructions);
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

async function runAgent() {
  const fileInput = document.getElementById("fileInput");
  const files = fileInput.files;
  if (!files || files.length === 0) {
    alert("Please upload at least one file.");
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
  for (let i = 0; i < files.length; i++) {
    formData.append("files", files[i]);
  }
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
