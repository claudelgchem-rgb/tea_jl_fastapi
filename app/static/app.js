"use strict";

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const kid of kids) n.append(kid?.nodeType ? kid : document.createTextNode(kid ?? ""));
  return n;
};
const svgEl = (tag, attrs = {}) => {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 2600);
}
async function api(path, body) {
  const opts = { method: body ? "POST" : "GET", headers: {} };
  if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch("/api" + path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return r.json();
}

let STATE = null;

// ---------------------------------------------------------------------------
// Render: full state -> UI
// ---------------------------------------------------------------------------
function render(s) {
  STATE = s;
  const badge = $("#biosteam-badge");
  badge.textContent = s.biosteam_available ? "biosteam ✓" : "biosteam 미설치 (계산 비활성)";
  badge.className = "badge " + (s.biosteam_available ? "ok" : "warn");

  renderChemicals(s);
  renderConfig(s);
  renderUtilities(s);
  renderSolutions(s);
  renderPalette(s);
  renderFlow(s);
  renderScenarios(s);
}

// --- Chemicals ---
function renderChemicals(s) {
  const tb = $("#chem-table tbody");
  tb.innerHTML = "";
  for (const c of s.chemicals) tb.append(chemRow(c));
}
function chemRow(c = { Name: "", Formula: "", "Price (USD/kg)": 0, Phase: "l" }) {
  const tr = el("tr");
  tr.append(
    el("td", {}, el("input", { type: "text", value: c.Name })),
    el("td", {}, el("input", { type: "text", value: c.Formula })),
    el("td", {}, el("input", { type: "number", step: "any", value: c["Price (USD/kg)"] })),
    el("td", {}, el("input", { type: "text", value: c.Phase })),
    el("td", {}, el("button", { class: "ghost", onclick: () => tr.remove() }, "×")),
  );
  return tr;
}

// --- Config ---
function fillSelect(sel, options, value) {
  sel.innerHTML = "";
  for (const o of options) sel.append(el("option", { value: o, ...(o === value ? { selected: "selected" } : {}) }, o));
}
function renderConfig(s) {
  fillSelect($("#cfg-product"), s.chemical_list, s.config.main_product);
  fillSelect($("#cfg-source"), s.chemical_list, s.config.main_source);
  $("#cfg-target").value = s.config.target_amount;
  $("#cfg-hours").value = s.config.operating_hours;
  $("#cfg-od").value = s.config.od_to_dcw;
  $("#cfg-elec").value = s.config.electricity_price;
  $("#cfg-currency").value = s.config.currency;
  $("#cfg-gmp").checked = !!s.config.gmp;
}
function renderUtilities(s) {
  const tb = $("#util-table tbody");
  tb.innerHTML = "";
  for (const [k, v] of Object.entries(s.heat_utility)) {
    tb.append(el("tr", {},
      el("td", {}, el("input", { type: "text", value: k, "data-util-name": "1" })),
      el("td", {}, el("input", { type: "number", step: "any", value: v, "data-util-price": "1" })),
    ));
  }
}

// --- Solutions ---
function renderSolutions(s) {
  const wrap = $("#solutions-list");
  wrap.innerHTML = "";
  const names = Object.keys(s.solutions).filter((n) => n !== "Water");
  if (names.length === 0) addSolutionBlock(s, "용액 1", {}, true);
  for (const name of names) addSolutionBlock(s, name, s.solutions[name], s.autoclave[name]);
}
function addSolutionBlock(s, name, comp = {}, autoclave = true) {
  const wrap = $("#solutions-list");
  const block = el("div", { class: "solution" });
  const nameInput = el("input", { type: "text", value: name, "data-sol-name": "1" });
  const acInput = el("input", { type: "checkbox", ...(autoclave ? { checked: "checked" } : {}) });
  const tbody = el("tbody");
  const table = el("table", { class: "grid" },
    el("thead", {}, el("tr", {}, el("th", {}, "물질"), el("th", {}, "농도 [g/L]"), el("th", {}))),
    tbody);
  const addRow = (chem = "", conc = 0) => {
    const sel = el("select", { "data-sol-chem": "1" });
    fillSelect(sel, s.chemical_list, chem);
    const tr = el("tr", {},
      el("td", {}, sel),
      el("td", {}, el("input", { type: "number", step: "any", value: conc, "data-sol-conc": "1" })),
      el("td", {}, el("button", { class: "ghost", onclick: () => tr.remove() }, "×")));
    tbody.append(tr);
  };
  for (const [chem, conc] of Object.entries(comp)) if (chem !== "Water") addRow(chem, conc);
  if (tbody.children.length === 0) addRow();
  block.append(
    el("div", { class: "row" }, el("label", {}, "이름 ", nameInput),
      el("label", { class: "check" }, acInput, " 멸균(Autoclave)"),
      el("button", { class: "ghost", onclick: () => block.remove() }, "용액 삭제")),
    table,
    el("div", { class: "row" }, el("button", { class: "ghost", onclick: () => addRow() }, "+ 물질")),
  );
  block._collect = () => {
    const rows = [];
    tbody.querySelectorAll("tr").forEach((tr) => {
      const chem = tr.querySelector("[data-sol-chem]")?.value;
      const conc = parseFloat(tr.querySelector("[data-sol-conc]")?.value || "0");
      if (chem) rows.push({ Name: chem, "Concentration [g/L]": conc });
    });
    return { name: nameInput.value, autoclave: acInput.checked, rows };
  };
  wrap.append(block);
}

// --- Node palette ---
function renderPalette(s) {
  const pal = $("#node-palette");
  pal.innerHTML = "";
  for (const nt of s.node_types) {
    pal.append(el("button", { onclick: () => addNode(nt) }, nt));
  }
}

// ---------------------------------------------------------------------------
// Flow editor (SVG) — replaces the streamlit_flow React component
// ---------------------------------------------------------------------------
const NODE_W = 130, NODE_H = 56;
let dragState = null;     // moving a node
let linkState = null;     // drawing an edge

function renderFlow(s) {
  const svg = $("#flow-canvas");
  svg.innerHTML = "";
  // arrow marker
  const defs = svgEl("defs");
  const marker = svgEl("marker", { id: "arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
    markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
  marker.append(svgEl("path", { d: "M0,0 L10,5 L0,10 z", fill: "#98a2b3" }));
  defs.append(marker);
  svg.append(defs);

  const byId = Object.fromEntries(s.flow.nodes.map((n) => [n.id, n]));
  // edges first (under nodes)
  for (const e of s.flow.edges) {
    const a = byId[e.source], b = byId[e.target];
    if (!a || !b) continue;
    const x1 = a.pos[0] + NODE_W / 2, y1 = a.pos[1] + NODE_H;
    const x2 = b.pos[0] + NODE_W / 2, y2 = b.pos[1];
    const path = svgEl("path", {
      class: "fedge" + (b.node_type === "발효/정제 분리선" ? " sep" : ""),
      d: `M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2}`,
    });
    path.style.cursor = "pointer";
    path.addEventListener("dblclick", async () => {
      if (confirm("이 연결을 삭제할까요?")) render(await api("/edges/delete", { edge_id: e.id }));
    });
    svg.append(path);
  }
  // nodes
  for (const n of s.flow.nodes) svg.append(nodeGroup(n));

  // live link line
  svg.addEventListener("mousemove", onCanvasMove);
  svg.addEventListener("mouseup", onCanvasUp);
}

function nodeGroup(n) {
  const g = svgEl("g", { class: "fnode", transform: `translate(${n.pos[0]},${n.pos[1]})` });
  g.dataset.id = n.id;
  const rect = svgEl("rect", { width: NODE_W, height: NODE_H, rx: 10 });
  const label = svgEl("text", { x: NODE_W / 2, y: NODE_H / 2 + 4, "text-anchor": "middle" });
  label.textContent = `${n.emoji || ""} ${n.content}`.trim();
  // output handle (bottom center) to start a link
  const handle = svgEl("circle", { class: "handle", cx: NODE_W / 2, cy: NODE_H, r: 6 });
  handle.addEventListener("mousedown", (ev) => { ev.stopPropagation(); startLink(n, ev); });

  g.addEventListener("mousedown", (ev) => startDrag(n, ev));
  g.addEventListener("click", (ev) => { if (!g._moved) openEditor(n.id); });
  g.append(rect, label, handle);
  return g;
}

function svgPoint(ev) {
  const svg = $("#flow-canvas");
  const r = svg.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}
function startDrag(n, ev) {
  const p = svgPoint(ev);
  const g = ev.currentTarget;
  g._moved = false;
  dragState = { id: n.id, g, dx: p.x - n.pos[0], dy: p.y - n.pos[1] };
}
function startLink(n, ev) {
  const p = svgPoint(ev);
  const svg = $("#flow-canvas");
  const line = svgEl("path", { class: "fedge", d: `M${n.pos[0] + NODE_W / 2},${n.pos[1] + NODE_H} L${p.x},${p.y}` });
  svg.append(line);
  linkState = { source: n.id, sx: n.pos[0] + NODE_W / 2, sy: n.pos[1] + NODE_H, line };
}
function onCanvasMove(ev) {
  const p = svgPoint(ev);
  if (dragState) {
    dragState.g._moved = true;
    const x = p.x - dragState.dx, y = p.y - dragState.dy;
    dragState.g.setAttribute("transform", `translate(${x},${y})`);
    dragState.x = x; dragState.y = y;
  } else if (linkState) {
    linkState.line.setAttribute("d", `M${linkState.sx},${linkState.sy} L${p.x},${p.y}`);
  }
}
async function onCanvasUp(ev) {
  if (dragState) {
    const ds = dragState; dragState = null;
    if (ds.x !== undefined) {
      await api("/nodes/move", { node_id: ds.id, x: ds.x, y: ds.y });
      const node = STATE.flow.nodes.find((n) => n.id === ds.id);
      if (node) node.pos = [ds.x, ds.y];
    }
    setTimeout(() => { ds.g._moved = false; }, 50);
  }
  if (linkState) {
    const ls = linkState; linkState = null;
    ls.line.remove();
    const target = ev.target.closest?.(".fnode");
    if (target && target.dataset.id && target.dataset.id !== ls.source) {
      try { render(await api("/edges/add", { source: ls.source, target: target.dataset.id })); }
      catch (e) { toast(e.message); }
    }
  }
}

async function addNode(nt) { render(await api("/nodes/add", { node_type: nt })); }

// ---------------------------------------------------------------------------
// Node editor modal (forms built from server-provided schema)
// ---------------------------------------------------------------------------
let EDIT = null;
async function openEditor(nodeId) {
  const schema = await api(`/nodes/${encodeURIComponent(nodeId)}/schema`);
  EDIT = { nodeId, schema, collectors: [] };
  $("#editor-title").textContent = `${schema.node_type || "노드"} 편집`;
  $("#editor-name").value = schema.name || "";
  const box = $("#editor-fields");
  box.innerHTML = "";
  for (const grp of schema.groups) box.append(renderGroup(grp));
  $("#editor-backdrop").classList.remove("hidden");
}
function closeEditor() { $("#editor-backdrop").classList.add("hidden"); EDIT = null; }

function renderGroup(grp) {
  const d = el("details", { class: "fieldgroup", ...(grp.advanced ? {} : { open: "open" }) },
    el("summary", {}, grp.title));
  for (const f of grp.fields) {
    if (f.fields) d.append(renderGroup(f));   // nested group
    else d.append(renderField(f));
  }
  return d;
}
function renderField(f) {
  const wrap = el("div", { class: "field" });
  if (f.kind === "table") {
    wrap.append(el("label", {}, f.label));
    wrap.append(renderTable(f));
    return wrap;
  }
  const id = "fld_" + Math.random().toString(36).slice(2);
  let input;
  if (f.kind === "select") {
    input = el("select", { id });
    fillSelect(input, f.options, f.value);
    EDIT.collectors.push(() => [f.key, input.value]);
  } else if (f.kind === "bool") {
    input = el("input", { type: "checkbox", id, ...(f.value ? { checked: "checked" } : {}) });
    EDIT.collectors.push(() => [f.key, input.checked]);
  } else if (f.kind === "number" || f.kind === "int") {
    input = el("input", { type: "number", step: f.kind === "int" ? "1" : "any", id, value: f.value });
    EDIT.collectors.push(() => [f.key, f.kind === "int" ? parseInt(input.value || "0", 10) : parseFloat(input.value || "0")]);
  } else {
    input = el("input", { type: "text", id, value: f.value ?? "" });
    EDIT.collectors.push(() => [f.key, input.value]);
  }
  wrap.append(el("label", { for: id }, f.label), input);
  return wrap;
}
function renderTable(f) {
  const tb = el("tbody");
  const table = el("table", { class: "grid" },
    el("thead", {}, el("tr", {}, ...f.columns.map((c) => el("th", {}, c.name)), el("th", {}))),
    tb);
  const addRow = (row = {}) => {
    const cells = [];
    const getters = [];
    for (const c of f.columns) {
      let inp;
      if (c.type === "select") { inp = el("select"); fillSelect(inp, c.options || STATE.chemical_list, row[c.name]); }
      else if (c.type === "number") inp = el("input", { type: "number", step: "any", value: row[c.name] ?? "" });
      else inp = el("input", { type: "text", value: row[c.name] ?? "" });
      getters.push(() => [c.name, c.type === "number" ? parseFloat(inp.value || "0") : inp.value]);
      cells.push(el("td", {}, inp));
    }
    const tr = el("tr", {}, ...cells, el("td", {}, el("button", { class: "ghost", onclick: () => tr.remove() }, "×")));
    tr._get = () => Object.fromEntries(getters.map((g) => g()));
    tb.append(tr);
  };
  (f.rows || []).forEach((r) => addRow(r));
  const wrap = el("div", {}, table, el("div", { class: "row" },
    el("button", { class: "ghost", onclick: (e) => { e.preventDefault(); addRow(); } }, "+ 행 추가")));
  EDIT.collectors.push(() => {
    const rows = [];
    tb.querySelectorAll("tr").forEach((tr) => {
      const obj = tr._get();
      const first = f.columns[0].name;
      if (obj[first] !== "" && obj[first] != null) rows.push(obj);
    });
    return [f.key, rows];
  });
  return wrap;
}

async function submitEditor() {
  const value = {};
  for (const c of EDIT.collectors) { const [k, v] = c(); value[k] = v; }
  try {
    const s = await api(`/nodes/${encodeURIComponent(EDIT.nodeId)}`, { name: $("#editor-name").value, value });
    closeEditor();
    render(s);
    toast("저장됨");
  } catch (e) { toast(e.message); }
}
async function deleteCurrentNode() {
  if (!confirm("이 노드를 삭제할까요?")) return;
  const s = await api("/nodes/delete", { node_id: EDIT.nodeId });
  closeEditor();
  render(s);
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------
function renderScenarios(s) {
  const sel = $("#load-name");
  sel.innerHTML = "";
  for (const name of s.scenarios) sel.append(el("option", { value: name }, name));
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------
function tableFromRows(rows) {
  if (!rows || rows.length === 0) return el("div", { class: "hint" }, "데이터 없음");
  const cols = Object.keys(rows[0]);
  const fmt = (v) => typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(3)) : (v ?? "");
  return el("table", { class: "result" },
    el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", {}, c)))),
    el("tbody", {}, ...rows.map((r) => el("tr", {}, ...cols.map((c, i) =>
      el("td", { class: i === 0 ? "k" : "" }, String(fmt(r[c])))))))
  );
}
function renderResults(res) {
  $("#results-card").classList.remove("hidden");
  $("#result-messages").textContent = (res.messages || []).join("\n");
  const sum = res.summary || {};
  const sumRows = Object.entries(sum).map(([k, v]) => ({ "항목": k, "값": v }));
  $("#result-summary").innerHTML = "";
  $("#result-summary").append(
    el("p", {}, `총 제조원가: ${(res.total_manufacturing_cost || 0).toLocaleString()} (배치시간 ${res.batch_time})`),
    tableFromRows(sumRows));
  $("#result-avg").innerHTML = ""; $("#result-avg").append(tableFromRows(res.avg_rows));
  $("#result-detail").innerHTML = ""; $("#result-detail").append(tableFromRows(res.detail_rows));
  const inst = Object.entries(res.installed_cost || {}).map(([k, v]) => ({ "Unit": k, "Base Cost USD": v }));
  $("#result-installed").innerHTML = ""; $("#result-installed").append(tableFromRows(inst));
  $("#result-diagram").textContent = res.diagram || "(no diagram)";
  $("#results-card").scrollIntoView({ behavior: "smooth" });
}

// ---------------------------------------------------------------------------
// Wire up buttons
// ---------------------------------------------------------------------------
function collectChemicals() {
  const rows = [];
  $("#chem-table tbody").querySelectorAll("tr").forEach((tr) => {
    const [name, formula, price, phase] = [...tr.querySelectorAll("input")].map((i) => i.value);
    if (name) rows.push({ Name: name, Formula: formula, "Price (USD/kg)": parseFloat(price || "0"), Phase: phase || "l" });
  });
  return rows;
}
function collectUtilities() {
  const out = {};
  $("#util-table tbody").querySelectorAll("tr").forEach((tr) => {
    const name = tr.querySelector("[data-util-name]").value;
    const price = parseFloat(tr.querySelector("[data-util-price]").value || "0");
    if (name) out[name] = price;
  });
  return out;
}

function wire() {
  $("#chem-add-row").onclick = () => $("#chem-table tbody").append(chemRow());
  $("#chem-save").onclick = async () => {
    try { render(await api("/chemicals", { chemicals: collectChemicals() })); toast("물질 저장됨"); }
    catch (e) { toast(e.message); }
  };
  $("#cfg-save").onclick = async () => {
    const body = {
      main_product: $("#cfg-product").value, main_source: $("#cfg-source").value,
      target_amount: parseFloat($("#cfg-target").value || "0"),
      operating_hours: parseFloat($("#cfg-hours").value || "0"),
      od_to_dcw: parseFloat($("#cfg-od").value || "0"),
      electricity_price: parseFloat($("#cfg-elec").value || "0"),
      currency: parseFloat($("#cfg-currency").value || "1"),
      gmp: $("#cfg-gmp").checked, heat_utility: collectUtilities(),
    };
    try { render(await api("/config", body)); toast("조건 저장됨"); } catch (e) { toast(e.message); }
  };
  $("#sol-add").onclick = () => addSolutionBlock(STATE, `용액 ${$("#solutions-list").children.length + 1}`, {}, true);
  $("#sol-save").onclick = async () => {
    const solutions = [...$("#solutions-list").children].map((b) => b._collect());
    try { render(await api("/solutions", { solutions })); toast("용액 저장됨"); } catch (e) { toast(e.message); }
  };
  $("#flow-reset").onclick = async () => { if (confirm("흐름도를 초기화할까요?")) render(await api("/reset", {})); };
  $("#btn-calc").onclick = async () => {
    $("#btn-calc").textContent = "계산 중...";
    try { renderResults(await api("/calculate", {})); }
    catch (e) { toast("계산 오류: " + e.message); }
    finally { $("#btn-calc").textContent = "Calculate"; }
  };
  $("#editor-close").onclick = closeEditor;
  $("#editor-backdrop").addEventListener("click", (e) => { if (e.target === $("#editor-backdrop")) closeEditor(); });
  $("#editor-submit").onclick = submitEditor;
  $("#editor-delete").onclick = deleteCurrentNode;
  $("#btn-save").onclick = async () => {
    try { await api("/scenarios/save", { name: $("#save-name").value }); render(await api("/state")); toast("저장됨"); }
    catch (e) { toast(e.message); }
  };
  $("#btn-load").onclick = async () => {
    const name = $("#load-name").value;
    if (!name) return;
    try { render(await api("/scenarios/load", { name })); toast("불러옴"); } catch (e) { toast(e.message); }
  };
}

// ---------------------------------------------------------------------------
async function boot() {
  wire();
  render(await api("/state"));
}
boot();
