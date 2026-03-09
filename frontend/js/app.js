/**
 * Presti Process Input Agent — frontend
 * Vanilla JS SPA with hash routing: #/, #/history, #/rerun/{run_id}
 */

// ─── Use Case Presets ────────────────────────────────────────────────────────
const USE_CASES = [
  {
    key: "uc1_normalize_urls",
    title: "Normalize URL Inputs",
    description: "Split and clean messy URL cells — one URL per output row.",
    output_columns: [
      { name: "source_row_ref", description: "Original row identifier from the input dataset." },
      { name: "normalized_url", description: "Exactly one URL per row. Split rows when multiple URLs exist in one source cell." },
      { name: "normalization_comment", description: "Short note only when a URL could not be parsed cleanly." },
    ],
    additional_instructions: "Treat separators like comma, semicolon, pipe, and line breaks as possible URL separators. Keep only valid HTTP/HTTPS URLs.",
  },
  {
    key: "uc2_packshot_dimensions",
    title: "Product Packshot & Dimensions",
    description: "Extract main product image and dimensions from a product URL.",
    output_columns: [
      { name: "Product Label", description: "The label / name of the product." },
      { name: "product_page_url", description: "Input product page URL." },
      { name: "main_packshot_url", description: "Main product image URL (packshot)." },
      { name: "width_cm", description: "Product width in cm if found, otherwise blank." },
      { name: "depth_cm", description: "Product depth in cm if found, otherwise blank." },
      { name: "height_cm", description: "Product height in cm if found, otherwise blank." },
      { name: "dimensions_text_raw", description: "Original dimensions text snippet used as source evidence." },
    ],
    additional_instructions: "When dimensions are missing, keep the numeric columns empty and keep a short reason in dimensions_text_raw.",
  },
  {
    key: "uc3_product_multi_images",
    title: "Product Multi-Image Extraction",
    description: "Extract all product images from a product page URL.",
    output_columns: [
      { name: "product_page_url", description: "Input product page URL." },
      { name: "image_url_1", description: "First product image URL. If more images exist, create image_url_2, image_url_3, etc." },
      { name: "total_images_found", description: "Total number of images extracted for the product." },
    ],
    additional_instructions: "Return product images only when possible. If the page mixes lifestyle and product visuals, prioritize product visuals.",
  },
  {
    key: "uc4_match_tables_chairs",
    title: "Table & Chair Matching",
    description: "Find the best matching chair for each table from a catalog.",
    output_columns: [
      { name: "table_ean", description: "EAN identifier of the table." },
      { name: "table_url", description: "Table product page URL." },
      { name: "best_chair_ean", description: "EAN identifier of the best matching chair." },
      { name: "best_chair_url", description: "URL of the best matching chair." },
      { name: "matching_reason", description: "Short explanation of why this chair matches this table." },
    ],
    additional_instructions: "The first input file is the table list. The second input file is the chair catalog. Prioritize style and color compatibility from available product information.",
  },
  {
    key: "uc5_complementary_products",
    title: "Complementary Products",
    description: "Find products that complement a given product URL.",
    output_columns: [
      { name: "product_url", description: "Input product URL from the dataset." },
      { name: "recommended_product_url_1", description: "Best first complementary product URL from the same site." },
      { name: "recommended_product_url_2", description: "Second complementary product URL from the same site." },
      { name: "recommended_product_url_3", description: "Third complementary product URL from the same site." },
      { name: "recommended_product_types", description: "Short comma-separated list of recommended product types (e.g., rug, lamp, side table)." },
      { name: "recommendation_reason", description: "Short reason based on style, color, room usage, and product type compatibility." },
    ],
    additional_instructions: "Infer the input product type from the page and choose complementary categories accordingly. Do not assume all rows are the same product type.",
  },
  {
    key: "uc6_inspiration_lifestyle_images",
    title: "Lifestyle Inspiration Images",
    description: "Collect lifestyle inspiration image URLs for a seed query.",
    output_columns: [
      { name: "search_seed", description: "Input inspiration query text." },
      { name: "lifestyle_image_url_1", description: "First lifestyle image URL. Add lifestyle_image_url_2, lifestyle_image_url_3, etc. as needed." },
      { name: "source_page_url", description: "Source page where the image was found." },
      { name: "collection_note", description: "Short note if URL is placeholder or if extraction is limited." },
    ],
    additional_instructions: "Prefer real lifestyle scenes over product cutouts. This dataset includes placeholder target sections for later completion.",
  },
];

// ─── State ───────────────────────────────────────────────────────────────────
let schemaRows = [];
let presetRun = null;
let selectedUseCase = null;

// ─── Init ────────────────────────────────────────────────────────────────────
function init() {
  renderUseCaseCards();
  renderSchemaSection();
  setupDropzone();

  document.getElementById("addColumn").addEventListener("click", addColumn);
  document.getElementById("runButton").addEventListener("click", () => runAgent(false));
  document.getElementById("rerunButton").addEventListener("click", () => runAgent(true));
  document.getElementById("clearRerunBtn").addEventListener("click", clearRerunPreset);
  document.getElementById("clearMessagesBtn").addEventListener("click", clearMessages);

  window.addEventListener("hashchange", route);
  document.querySelectorAll(".nav-link").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      window.location.hash = a.getAttribute("href").slice(1);
    });
  });

  route();
}

// ─── Use Case Cards ──────────────────────────────────────────────────────────
function renderUseCaseCards() {
  const grid = document.getElementById("useCaseCards");
  grid.innerHTML = "";
  USE_CASES.forEach((uc) => {
    const btn = document.createElement("button");
    btn.className = "usecase-card" + (selectedUseCase === uc.key ? " selected" : "");
    btn.type = "button";
    btn.innerHTML = `
      <div class="usecase-card-title">${escapeHtml(uc.title)}</div>
      <div class="usecase-card-desc">${escapeHtml(uc.description)}</div>
    `;
    btn.addEventListener("click", () => applyUseCase(uc));
    grid.appendChild(btn);
  });
}

function applyUseCase(uc) {
  selectedUseCase = selectedUseCase === uc.key ? null : uc.key;
  if (selectedUseCase) {
    schemaRows = uc.output_columns.map((c) => ({ name: c.name, description: c.description }));
    document.getElementById("additionalInstructions").value = uc.additional_instructions || "";
  } else {
    schemaRows = [];
    document.getElementById("additionalInstructions").value = "";
  }
  renderUseCaseCards();
  renderSchemaSection();
}

// ─── Routing ─────────────────────────────────────────────────────────────────
function getRoute() {
  const hash = (window.location.hash || "#/").slice(1);
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "rerun" && parts[1]) return { page: "rerun", runId: parts[1] };
  if (parts[0] === "history") return { page: "history" };
  return { page: "run" };
}

function route() {
  const r = getRoute();
  document.getElementById("runPage").hidden = r.page !== "run" && r.page !== "rerun";
  document.getElementById("historyPage").hidden = r.page !== "history";

  document.querySelectorAll(".nav-link").forEach((a) => {
    const rt = a.dataset.route || a.getAttribute("href").slice(2);
    a.classList.toggle(
      "active",
      (rt === "/" && (r.page === "run" || r.page === "rerun")) ||
        (rt === "/history" && r.page === "history")
    );
  });

  if (r.page === "history") loadRuns();
  else if (r.page === "rerun" && r.runId) loadRunForRerun(r.runId);
  else clearRerunPreset();
}

// ─── Dropzone ────────────────────────────────────────────────────────────────
function setupDropzone() {
  const zone = document.getElementById("dropzone");
  const input = document.getElementById("fileInput");
  const browseBtn = document.getElementById("browseBtn");

  browseBtn.addEventListener("click", () => input.click());
  zone.addEventListener("click", (e) => {
    if (e.target !== browseBtn) input.click();
  });

  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    handleFiles(e.dataTransfer.files);
  });

  input.addEventListener("change", () => handleFiles(input.files));
}

function handleFiles(fileList) {
  // Merge with existing files in input
  const input = document.getElementById("fileInput");
  const dt = new DataTransfer();
  // Add existing
  for (let i = 0; i < (input.files || []).length; i++) dt.items.add(input.files[i]);
  // Add new
  for (let i = 0; i < fileList.length; i++) {
    const f = fileList[i];
    // avoid duplicates by name
    let dup = false;
    for (let j = 0; j < dt.files.length; j++) { if (dt.files[j].name === f.name) { dup = true; break; } }
    if (!dup) dt.items.add(f);
  }
  input.files = dt.files;
  renderFileChips();
  renderInputPreview();
}

function removeFile(name) {
  const input = document.getElementById("fileInput");
  const dt = new DataTransfer();
  for (let i = 0; i < input.files.length; i++) {
    if (input.files[i].name !== name) dt.items.add(input.files[i]);
  }
  input.files = dt.files;
  renderFileChips();
  renderInputPreview();
}

function renderFileChips() {
  const input = document.getElementById("fileInput");
  const chips = document.getElementById("fileChips");
  chips.innerHTML = "";
  for (let i = 0; i < input.files.length; i++) {
    const f = input.files[i];
    const chip = document.createElement("div");
    chip.className = "file-chip";
    chip.innerHTML = `
      <span class="file-chip-icon">${fileIcon(f.name)}</span>
      <span>${escapeHtml(f.name)}</span>
      <button class="file-chip-remove" title="Remove" data-name="${escapeHtml(f.name)}">×</button>
    `;
    chip.querySelector(".file-chip-remove").addEventListener("click", () => removeFile(f.name));
    chips.appendChild(chip);
  }
}

function fileIcon(name) {
  const ext = name.split(".").pop().toLowerCase();
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) return "🖼️";
  if (ext === "csv") return "📊";
  if (["xlsx", "xls"].includes(ext)) return "📗";
  if (ext === "pdf") return "📄";
  if (ext === "zip") return "🗜️";
  return "📁";
}

function renderInputPreview() {
  const input = document.getElementById("fileInput");
  const preview = document.getElementById("inputPreview");
  preview.innerHTML = "";

  const images = [];
  const csvFiles = [];

  for (let i = 0; i < input.files.length; i++) {
    const f = input.files[i];
    const ext = f.name.split(".").pop().toLowerCase();
    if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) images.push(f);
    else if (ext === "csv") csvFiles.push(f);
  }

  // Image thumbnails
  if (images.length > 0) {
    const block = document.createElement("div");
    block.className = "preview-block";
    block.innerHTML = `<div class="preview-label">Images (${images.length})</div><div class="preview-images" id="previewImgContainer"></div>`;
    preview.appendChild(block);
    const container = block.querySelector("#previewImgContainer");
    images.forEach((f) => {
      const img = document.createElement("img");
      img.className = "preview-thumb";
      img.alt = f.name;
      img.src = URL.createObjectURL(f);
      container.appendChild(img);
    });
  }

  // CSV previews
  csvFiles.forEach((f) => {
    const block = document.createElement("div");
    block.className = "preview-block";
    block.innerHTML = `<div class="preview-label">${escapeHtml(f.name)} — first rows</div><div class="preview-table-wrap" id="preview_${escapeHtml(f.name).replace(/[^a-z0-9]/gi, '_')}"></div>`;
    preview.appendChild(block);
    const wrap = block.querySelector("[id^='preview_']");
    readCsvPreview(f, wrap);
  });
}

function readCsvPreview(file, container) {
  const reader = new FileReader();
  reader.onload = (e) => {
    const text = e.target.result;
    const rows = text.trim().split("\n").slice(0, 6); // header + 5 rows
    if (rows.length === 0) return;
    const headers = parseCSVLine(rows[0]);
    const data = rows.slice(1).map((r) => parseCSVLine(r));
    let html = `<table class="preview-table"><thead><tr>`;
    headers.forEach((h) => (html += `<th>${escapeHtml(h)}</th>`));
    html += `</tr></thead><tbody>`;
    data.forEach((row) => {
      html += "<tr>";
      row.forEach((cell) => (html += `<td title="${escapeHtml(cell)}">${escapeHtml(cell)}</td>`));
      html += "</tr>";
    });
    html += "</tbody></table>";
    container.innerHTML = html;
  };
  reader.readAsText(file);
}

// ─── Schema builder ───────────────────────────────────────────────────────────
function renderSchemaSection() {
  const container = document.getElementById("schemaRows");
  container.innerHTML = "";
  schemaRows.forEach((row, idx) => {
    const div = document.createElement("div");
    div.className = "schema-row";
    div.innerHTML = `
      <input type="text" class="schema-input" data-col="name" data-idx="${idx}"
        value="${escapeHtml(row.name || "")}" placeholder="Column name" />
      <input type="text" class="schema-input" data-col="desc" data-idx="${idx}"
        value="${escapeHtml(row.description || "")}" placeholder="Description (used as instruction for the agent)" />
      <button type="button" class="schema-remove" data-idx="${idx}" title="Remove column">×</button>
    `;
    container.appendChild(div);
  });
  container.querySelectorAll("input.schema-input").forEach((inp) => {
    inp.addEventListener("input", (e) => {
      const idx = parseInt(e.target.dataset.idx, 10);
      if (e.target.dataset.col === "name") schemaRows[idx].name = e.target.value;
      else schemaRows[idx].description = e.target.value;
    });
  });
  container.querySelectorAll(".schema-remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const idx = parseInt(e.target.dataset.idx, 10);
      schemaRows.splice(idx, 1);
      renderSchemaSection();
    });
  });
}

function addColumn() {
  schemaRows.push({ name: "", description: "" });
  renderSchemaSection();
}

function getOutputColumns() {
  return schemaRows
    .filter((r) => r.name && r.name.trim())
    .map((r) => ({ name: r.name.trim(), description: (r.description || "").trim() }));
}

// ─── Rerun preset ─────────────────────────────────────────────────────────────
async function loadRunForRerun(runId) {
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!res.ok) { clearRerunPreset(); window.location.hash = "#/"; return; }
    const run = await res.json();
    applyRerunPreset(run);
    const outputs = run.outputs || [];
    if (outputs.length > 0 && outputs[0].name) {
      try {
        const outputRes = await fetch(`/api/outputs/${encodeURIComponent(outputs[0].name)}`);
        if (outputRes.ok) showOutput(await outputRes.text());
      } catch (_) {}
    } else {
      document.getElementById("outputSection").hidden = true;
    }
  } catch (_) { clearRerunPreset(); window.location.hash = "#/"; }
}

function applyRerunPreset(run) {
  presetRun = run;
  const section = document.getElementById("rerunPresetSection");
  const infoEl = document.getElementById("rerunPresetInfo");

  const inputs = (run.inputs || []).map((i) => i.name || "?").join(", ");
  const params = run.params || {};
  infoEl.innerHTML = `
    <p><strong>Inputs:</strong> ${escapeHtml(inputs || "—")}</p>
    <p><strong>Duration:</strong> ${run.duration_seconds ?? "—"}s &nbsp;·&nbsp; <strong>Status:</strong> ${escapeHtml(run.status || "—")}</p>
  `;

  if (params.output_columns && Array.isArray(params.output_columns)) {
    schemaRows = params.output_columns.map((c) => ({ name: c.name || "", description: c.description || "" }));
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
  if (params.additional_instructions) {
    document.getElementById("additionalInstructions").value = params.additional_instructions;
  }

  section.hidden = false;
  document.getElementById("runButton").hidden = true;
  document.getElementById("rerunButton").hidden = false;
}

function clearRerunPreset() {
  presetRun = null;
  document.getElementById("rerunPresetSection").hidden = true;
  document.getElementById("runButton").hidden = false;
  document.getElementById("rerunButton").hidden = true;
  document.getElementById("outputSection").hidden = true;
  if (getRoute().page === "rerun") window.location.hash = "#/";
}

// ─── Loading state ────────────────────────────────────────────────────────────
function setLoading(loading, statusText) {
  const runBtn = document.getElementById("runButton");
  const rerunBtn = document.getElementById("rerunButton");
  const phase2Btn = document.getElementById("phase2Button");
  const bar = document.getElementById("loading");
  const status = document.getElementById("loadingStatus");

  runBtn.disabled = loading;
  rerunBtn.disabled = loading;
  phase2Btn.disabled = loading;
  bar.hidden = !loading;
  status.hidden = !loading;
  if (statusText) status.textContent = statusText;
}

// ─── Messages ─────────────────────────────────────────────────────────────────
function clearMessages() {
  const panel = document.getElementById("messagesPanel");
  panel.innerHTML = '<p class="empty-hint">Run the agent to see live activity here.</p>';
}

function appendMessage(role, content, name) {
  const panel = document.getElementById("messagesPanel");
  // Remove empty hint
  panel.querySelector(".empty-hint")?.remove();

  const div = document.createElement("div");
  div.className = `message-block message-${role}`;
  const label = name ? `🔧 ${name}` : role === "ai" ? "🤖 Agent" : role === "system" ? "⚙️ System" : role;
  const short = content.length > 100 ? content.slice(0, 100) + "…" : content;
  div.innerHTML = `
    <details>
      <summary>${escapeHtml(label)} — ${escapeHtml(short)}</summary>
      <div class="content">${escapeHtml(content)}</div>
    </details>
  `;
  panel.appendChild(div);
  panel.scrollTop = panel.scrollHeight;
}

function showError(msg) {
  const panel = document.getElementById("messagesPanel");
  panel.querySelector(".empty-hint")?.remove();
  const div = document.createElement("div");
  div.className = "message-block message-error";
  div.innerHTML = `<div class="message-error-plain">⚠️ Error: ${escapeHtml(msg)}</div>`;
  panel.appendChild(div);
}

// ─── Output ───────────────────────────────────────────────────────────────────
function showOutput(csv, sectionId = "outputSection", tableId = "outputTableWrap", successId = "outputSuccess", downloadId = "downloadLink") {
  const section = document.getElementById(sectionId);
  const tableWrap = document.getElementById(tableId);
  const successEl = document.getElementById(successId);
  section.hidden = false;
  if (successEl) successEl.hidden = false;

  const rows = csv.trim().split("\n");
  if (rows.length === 0) { tableWrap.innerHTML = "<p>No data</p>"; return; }
  const headers = parseCSVLine(rows[0]);
  const data = rows.slice(1).map((r) => parseCSVLine(r));

  let html = "<table><thead><tr>";
  headers.forEach((h) => (html += `<th>${escapeHtml(h)}</th>`));
  html += "</tr></thead><tbody>";
  data.forEach((row) => {
    html += "<tr>";
    row.forEach((cell) => {
      const isUrl = cell.startsWith("http://") || cell.startsWith("https://");
      html += isUrl
        ? `<td><a href="${escapeHtml(cell)}" target="_blank" rel="noopener" title="${escapeHtml(cell)}">${escapeHtml(cell.length > 50 ? cell.slice(0, 50) + "…" : cell)}</a></td>`
        : `<td title="${escapeHtml(cell)}">${escapeHtml(cell)}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table>";
  tableWrap.innerHTML = html;

  if (downloadId) {
    const link = document.getElementById(downloadId);
    if (link) {
      const blob = new Blob([csv], { type: "text/csv" });
      link.href = URL.createObjectURL(blob);
      link.download = "output.csv";
      link.hidden = false;
    }
  }
}

// ─── Run agent ────────────────────────────────────────────────────────────────
async function runAgent(isRerun) {
  const fileInput = document.getElementById("fileInput");
  const files = fileInput.files;
  let historyUris = [];

  if (isRerun && presetRun && presetRun.inputs) {
    historyUris = presetRun.inputs.map((i) => i.gcs_uri).filter(Boolean);
  }

  if ((!files || files.length === 0) && historyUris.length === 0) {
    alert("Please upload at least one file.");
    return;
  }

  const outputColumns = getOutputColumns();
  const additionalInstructions = document.getElementById("additionalInstructions").value || "";
  const modelName = document.getElementById("modelName").value;
  const subagentModelName = document.getElementById("subagentModelName").value;

  const formData = new FormData();
  for (let i = 0; i < (files?.length || 0); i++) formData.append("files", files[i]);
  formData.append("history_file_ids", JSON.stringify(historyUris));
  formData.append("output_columns", JSON.stringify(outputColumns));
  formData.append("additional_instructions", additionalInstructions);
  formData.append("model_name", modelName);
  formData.append("subagent_model_name", subagentModelName);

  setLoading(true, "Processing…");
  clearMessages();
  document.getElementById("outputSection").hidden = true;

  await streamRun(formData, (csv) => {
    showOutput(csv);
  });
}

async function streamRun(formData, onDone) {
  try {
    const response = await fetch("/api/run", { method: "POST", body: formData });

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
                  ? data.content.map((c) => c.text || c || "").join("")
                  : (data.content || "");
                const toolCalls = data.tool_calls || [];
                if (content) appendMessage("ai", content, null);
                for (const tc of toolCalls) appendMessage("ai", `Tool call: ${tc.name}`, tc.name);
              }
            }
            if (d.tools) {
              for (const m of d.tools) {
                const data = m.data || {};
                const name = data.name || "tool";
                const content = Array.isArray(data.content)
                  ? data.content.map((c) => c.text || c || "").join("")
                  : (data.content || "");
                if (content) appendMessage("tool", content, name);
              }
            }
          } else if (ev.type === "retry") {
            appendMessage("system", ev.message || "Retrying due to rate limit…", null);
          } else if (ev.type === "done") {
            setLoading(false);
            if (ev.error) showError(ev.error);
            else if (ev.csv) onDone(ev.csv);
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    showError(e.message);
    setLoading(false);
  }
}

// ─── Run History ──────────────────────────────────────────────────────────────
async function loadRuns() {
  const wrap = document.getElementById("runsTableWrap");
  wrap.innerHTML = '<p class="empty-hint">Loading…</p>';
  try {
    const res = await fetch("/api/runs");
    const data = await res.json();
    const runs = data.runs || [];
    if (runs.length === 0) {
      wrap.innerHTML = '<p class="empty-hint">No runs yet. Run the agent to create history.</p>';
      return;
    }
    let html = `
      <table class="runs-table">
        <thead><tr>
          <th>Date</th><th>Inputs</th><th>Duration</th><th>Status</th><th></th>
        </tr></thead>
        <tbody>
    `;
    for (const r of runs) {
      const date = r.timestamp ? new Date(r.timestamp).toLocaleString() : "—";
      const inputs = (r.inputs || []).map((i) => i.name).join(", ") || "—";
      const duration = r.duration_seconds != null ? `${r.duration_seconds}s` : "—";
      const status = r.status || "unknown";
      const statusClass = status === "completed" ? "status-completed" : "status-failed";
      const runId = r.id || "";
      html += `
        <tr class="runs-row" data-run-id="${escapeHtml(runId)}">
          <td>${escapeHtml(date)}</td>
          <td>${escapeHtml(inputs)}</td>
          <td>${escapeHtml(duration)}</td>
          <td><span class="status-badge ${statusClass}">${escapeHtml(status)}</span></td>
          <td><button type="button" class="delete-run-btn" data-run-id="${escapeHtml(runId)}" title="Delete">Delete</button></td>
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
        if (!id || !confirm("Delete this run?")) return;
        try {
          const res = await fetch(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" });
          if (res.ok) loadRuns();
        } catch (_) {}
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class="empty-hint">Failed to load runs: ${escapeHtml(e.message)}</p>`;
  }
}

// ─── CSV helpers ──────────────────────────────────────────────────────────────
function parseCSVLine(line) {
  const result = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') inQuotes = !inQuotes;
    else if (c === "," && !inQuotes) { result.push(current.replace(/^"|"$/g, "").trim()); current = ""; }
    else current += c;
  }
  result.push(current.replace(/^"|"$/g, "").trim());
  return result;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = String(s);
  return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", init);
