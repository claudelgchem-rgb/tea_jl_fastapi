"""FastAPI backend for the TEA-Agent v9 UI.

Serves the single-page UI and the JSON API it calls: chemical DB, solution
manager, BFD editor, project save/load, and the BioSTEAM simulation (wired to
the original ``util_biosteam`` / ``aux_chemical`` pipeline via ``app.sim``).
"""

from __future__ import annotations

import io
import json
import os
import time
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import data, default_data, sim
from .flow_models import FlowNode
from .flow_tabs import util_bfd
from .flow_tabs import util_biosteam as ub
from .session import store

BASE = os.path.dirname(__file__)
PROJECT_DIR = os.path.join(data.DATA_DIR, "projects")
os.makedirs(PROJECT_DIR, exist_ok=True)

app = FastAPI(title="TEA-Agent Platform v9.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

COOKIE = "tea_sid"


def _seed_ui(state) -> None:
    """Seed the v9 UI-state containers from the session defaults."""
    if "ui_seeded" in state:
        return
    cd = state.chem_data
    state.ui_chemicals = [
        {"name": n, "formula": cd.get("Formula", {}).get(n, ""),
         "price": float(cd.get("Price (USD/kg)", {}).get(n, 0) or 0),
         "phase": cd.get("Phase", {}).get(n, "l")}
        for n in state.chemical_list
    ]
    state.ui_solutions = data.load_solutions()
    state.bfd_nodes = []
    state.bfd_edges = []
    state.ui_seeded = True


def get_state(request: Request, response: Response):
    sid = request.cookies.get(COOKIE)
    sid, state = store.get_or_create(sid)
    if "uploader_key" not in state:
        data.init_session(state)
    _seed_ui(state)
    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
    return state


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def _asset_ver() -> str:
    """Cache-busting token = newest mtime of the static bundle, so browsers
    always refetch app.js/tailwind.css after a deploy instead of serving a
    stale cached copy."""
    latest = 0.0
    for name in ("app.js", "tailwind.css"):
        p = os.path.join(BASE, "static", name)
        try:
            latest = max(latest, os.path.getmtime(p))
        except OSError:
            pass
    return str(int(latest))


@app.get("/")
def index(request: Request, response: Response, state=Depends(get_state)):
    return templates.TemplateResponse(request, "index.html", {"asset_ver": _asset_ver()})


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Chemicals
# ---------------------------------------------------------------------------

class ChemicalIn(BaseModel):
    name: str
    formula: str = ""
    price: float = 0.0
    phase: str = "l"


def _sync_chem_data(state) -> None:
    """Rebuild chem_data + thermo from the UI chemical list."""
    cols = ["Name", "Formula", "Price (USD/kg)", "Phase"]
    chem_data = {c: {} for c in cols}
    for c in state.ui_chemicals:
        chem_data["Name"][c["name"]] = c["name"]
        chem_data["Formula"][c["name"]] = c.get("formula", "")
        chem_data["Price (USD/kg)"][c["name"]] = float(c.get("price", 0) or 0)
        chem_data["Phase"][c["name"]] = c.get("phase", "l")
    if chem_data["Price (USD/kg)"]:
        try:
            data.set_chemicals(state, chem_data)
        except Exception:  # noqa: BLE001 - thermo build is best-effort here
            state.chem_data = chem_data
            state.chemical_list = list(chem_data["Price (USD/kg)"].keys())


@app.get("/api/chemicals")
def chemicals_list(state=Depends(get_state)):
    return {"chemicals": state.ui_chemicals}


@app.post("/api/chemicals")
def chemicals_add(chem: ChemicalIn, state=Depends(get_state)):
    state.ui_chemicals = [c for c in state.ui_chemicals if c["name"] != chem.name]
    state.ui_chemicals.append({"name": chem.name, "formula": chem.formula,
                               "price": chem.price, "phase": chem.phase})
    _sync_chem_data(state)
    return {"ok": True, "chemicals": state.ui_chemicals}


@app.put("/api/chemicals/{name}")
def chemicals_update(name: str, chem: ChemicalIn, state=Depends(get_state)):
    for c in state.ui_chemicals:
        if c["name"] == name:
            c.update({"name": chem.name, "formula": chem.formula,
                      "price": chem.price, "phase": chem.phase})
            break
    else:
        state.ui_chemicals.append({"name": chem.name, "formula": chem.formula,
                                   "price": chem.price, "phase": chem.phase})
    _sync_chem_data(state)
    return {"ok": True, "chemicals": state.ui_chemicals}


@app.delete("/api/chemicals/{name}")
def chemicals_delete(name: str, state=Depends(get_state)):
    state.ui_chemicals = [c for c in state.ui_chemicals if c["name"] != name]
    _sync_chem_data(state)
    return {"ok": True, "chemicals": state.ui_chemicals}


@app.post("/api/chemicals/upload")
async def chemicals_upload(file: UploadFile = File(...), state=Depends(get_state)):
    raw = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
    except Exception:  # noqa: BLE001
        return {"success": False}
    cols = {c.lower().strip(): c for c in df.columns}
    name_c = cols.get("name"); price_c = cols.get("price (usd/kg)") or cols.get("price")
    formula_c = cols.get("formula"); phase_c = cols.get("phase")
    if not name_c:
        return {"success": False}
    for _, row in df.iterrows():
        nm = str(row[name_c]).strip()
        if not nm or nm == "nan":
            continue
        state.ui_chemicals = [c for c in state.ui_chemicals if c["name"] != nm]
        state.ui_chemicals.append({
            "name": nm,
            "formula": str(row[formula_c]) if formula_c and pd.notna(row[formula_c]) else "",
            "price": float(row[price_c]) if price_c and pd.notna(row[price_c]) else 0.0,
            "phase": str(row[phase_c]) if phase_c and pd.notna(row[phase_c]) else "l",
        })
    _sync_chem_data(state)
    return {"success": True, "chemicals": state.ui_chemicals}


# ---------------------------------------------------------------------------
# Solutions
# ---------------------------------------------------------------------------

class SolutionsIn(BaseModel):
    solutions: List[Dict[str, Any]]


def _clean_solution(state, sol: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalise one solution before storing:

    * drop rows missing a chemical name OR a positive concentration (#6)
    * clamp negative concentrations to 0 (they are then dropped) (#5)
    * run ``fill_water3`` so the composition is expressed for 1 L, with the
      remainder filled as water (#8)
    """
    from .flow_tabs.aux_compat import fill_water3

    comps = []
    for c in sol.get("components", []) or []:
        name = (c.get("name") or "").strip()
        try:
            conc = float(c.get("concentration_g_per_l", 0) or 0)
        except (TypeError, ValueError):
            conc = 0.0
        if conc < 0:
            conc = 0.0
        if not name or conc <= 0 or name == "Water":
            continue  # missing name/conc, or the water row we will recompute
        comps.append({"name": name, "concentration_g_per_l": conc})

    # Fill water so the 1 L composition balances.
    mass = {c["name"]: c["concentration_g_per_l"] for c in comps}
    try:
        filled = fill_water3(dict(mass), 1)
        water = float(filled.get("Water", 0) or 0)
    except Exception:  # noqa: BLE001
        water = max(0.0, 1000.0 - sum(mass.values()))
    if water > 0:
        comps.append({"name": "Water", "concentration_g_per_l": round(water, 4)})

    out = dict(sol)
    out["components"] = comps
    return out


@app.get("/api/solutions")
def solutions_get(state=Depends(get_state)):
    return {"solutions": state.ui_solutions}


@app.post("/api/solutions")
def solutions_save(body: SolutionsIn, state=Depends(get_state)):
    # Keep solutions that still have at least one real component after cleaning.
    cleaned = []
    for sol in body.solutions:
        c = _clean_solution(state, sol)
        if any(x["name"] != "Water" for x in c["components"]):
            cleaned.append(c)
    state.ui_solutions = cleaned
    return {"ok": True, "solutions": cleaned}


# ---------------------------------------------------------------------------
# Utilities / sub-materials (heat_utility split into two editable tables)
# ---------------------------------------------------------------------------

# A heat-utility agent is a *sub-material* (resin/filter/membrane/CIP chemical)
# rather than a true utility (steam/water/fuel/waste) when its id matches these.
_SUBMATERIAL_KEYWORDS = ("resin", "filter", "membrane", "cip")

# Category each item can carry; the first four mean it belongs to the 부재료
# (sub-material) table, the rest to the utility table.
UTIL_CATEGORIES = ["resin", "membrane", "wastewater", "filter", "cip", "steam", "cooling", "fuel", "기타"]
SUBMATERIAL_CATEGORIES = {"resin", "membrane", "filter", "cip"}


def _is_submaterial(uid: str) -> bool:
    u = (uid or "").lower()
    return any(k in u for k in _SUBMATERIAL_KEYWORDS)


def _default_category(uid: str) -> str:
    u = (uid or "").lower()
    if "resin" in u:
        return "resin"
    if "membrane" in u:
        return "membrane"
    if "waste" in u or "sludge" in u:
        return "wastewater"
    if "filter" in u:
        return "filter"
    if "cip" in u:
        return "cip"
    if "steam" in u or "gas" in u or "propane" in u or "propylene" in u or "ethylene" in u:
        return "fuel" if ("gas" in u or "propane" in u or "propylene" in u or "ethylene" in u) else "steam"
    if "cool" in u or "chill" in u or "water" in u:
        return "cooling"
    return "기타"


def _categories_for(state) -> Dict[str, str]:
    """Per-item category map, seeding any missing id from keyword inference."""
    cats = dict(state.get("util_categories", {}) or {})
    for k in state.heat_utility:
        cats.setdefault(k, _default_category(k))
    # Drop stale ids no longer in the table.
    return {k: v for k, v in cats.items() if k in state.heat_utility}


def _split_utilities(hu: Dict[str, float], cats: Optional[Dict[str, str]] = None):
    """Split into the two tables by *category* (not id keyword) so an item's
    table membership is what the user set: category in {resin,membrane,filter,cip}
    -> 부재료 table, otherwise -> utility table.  Falls back to keyword inference
    for items with no category yet."""
    cats = cats or {}
    utilities, submaterials = {}, {}
    for k, v in (hu or {}).items():
        cat = cats.get(k) or _default_category(k)
        (submaterials if cat in SUBMATERIAL_CATEGORIES else utilities)[k] = v
    return utilities, submaterials


def _refresh_utilities(state) -> None:
    """Reload the persisted utilities/categories into the session so node
    dropdowns and the tab reflect the saved 유틸리티/부재료 table regardless of
    which session/worker handled the save (in-memory state alone is not shared
    across uvicorn workers)."""
    hu = data.load_utilities()
    if hu:
        state.heat_utility = hu
    cats = data.load_util_categories()
    if cats:
        state.util_categories = cats


class UtilitiesIn(BaseModel):
    utilities: Dict[str, float] = {}
    submaterials: Dict[str, float] = {}
    categories: Dict[str, str] = {}


@app.get("/api/utilities")
def utilities_get(state=Depends(get_state)):
    _refresh_utilities(state)
    cats = _categories_for(state)
    state.util_categories = cats
    utilities, submaterials = _split_utilities(state.heat_utility, cats)
    return {"utilities": utilities, "submaterials": submaterials,
            "categories": cats, "category_options": UTIL_CATEGORIES}


@app.post("/api/utilities")
def utilities_save(body: UtilitiesIn, state=Depends(get_state)):
    # Recombine into the single heat_utility dict biosteam consumes.
    merged: Dict[str, float] = {}
    for src in (body.utilities, body.submaterials):
        for k, v in src.items():
            k = (k or "").strip()
            if not k:
                continue
            try:
                merged[k] = float(v)
            except (TypeError, ValueError):
                merged[k] = 0.0
    state.heat_utility = merged
    # Categories: user-supplied wins, else keep/infer.
    cats = {}
    for k in merged:
        c = (body.categories or {}).get(k)
        cats[k] = c if c in UTIL_CATEGORIES else _default_category(k)
    state.util_categories = cats
    utilities, submaterials = _split_utilities(merged, cats)
    # Persist to the writable data dir so every session/worker + node schema
    # reads the same table (in-memory session state is not shared across workers).
    try:
        data.save_utilities_file(utilities, submaterials, cats)
    except Exception:  # noqa: BLE001 - persistence best-effort; session still updated
        pass
    return {"ok": True, "utilities": utilities, "submaterials": submaterials,
            "categories": cats, "category_options": UTIL_CATEGORIES}


# ---------------------------------------------------------------------------
# BFD
# ---------------------------------------------------------------------------

class NodeIn(BaseModel):
    node_type: str
    label: str = ""
    x: float = 100.0
    y: float = 100.0


class EdgeIn(BaseModel):
    source: str
    target: str


class BFDSaveIn(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


@app.get("/api/bfd/node-types")
def bfd_node_types():
    return {"nodeTypes": sim.node_types()}


@app.get("/api/bfd")
def bfd_get(state=Depends(get_state)):
    return {"nodes": state.bfd_nodes, "edges": state.bfd_edges}


@app.post("/api/bfd/node")
def bfd_add_node(node: NodeIn, state=Depends(get_state)):
    nid = f"n_{int(time.time()*1000)}_{len(state.bfd_nodes)}"
    new = {"id": nid, "node_type": node.node_type, "label": node.label or node.node_type,
           "x": node.x, "y": node.y, "params": sim.default_node_params(node.node_type)}
    state.bfd_nodes.append(new)
    return {"node": new}


def _sync_solutions(state) -> None:
    """Build ``state.solutions`` / ``autoclave`` / ``prices`` from the v9
    ``ui_solutions`` list, so node schemas (solution dropdowns) and the v1
    ``process_*_data`` functions (fill_water3, fermenter stream_flow) see the
    user's registered solutions.
    """
    from .flow_tabs.aux_compat import fill_water3

    solutions, autoclave, prices = {}, {}, {}
    price_col = state.chem_data.get("Price (USD/kg)", {}) if isinstance(state.chem_data, dict) else {}
    for sol in state.get("ui_solutions", []) or []:
        name = sol.get("user_name") or sol.get("name")
        if not name:
            continue
        comp = {c.get("name"): float(c.get("concentration_g_per_l", 0) or 0)
                for c in sol.get("components", []) or [] if c.get("name")}
        comp = fill_water3(comp, 1)
        solutions[name] = comp
        autoclave[name] = bool(sol.get("autoclave", True))
        prices[name] = sum(m * float(price_col.get(ch, 0) or 0) for ch, m in comp.items())
    solutions.setdefault("Water", {"Water": 1000})
    autoclave.setdefault("Water", False)
    prices.setdefault("Water", float(price_col.get("Water", 0) or 0))
    state.solutions, state.autoclave, state.prices = solutions, autoclave, prices


def _v9_node_to_flownode(n) -> FlowNode:
    return FlowNode(id=n["id"], pos=(n.get("x", 0), n.get("y", 0)),
                    data={"node_type": n.get("node_type"), "content": n.get("label"),
                          "custom_value": n.get("label"), "Value": n.get("params", {}) or {}})


def _find_v9_node(state, node_id):
    for n in state.bfd_nodes:
        if n["id"] == node_id:
            return n
    raise HTTPException(404, "node not found")


class NodeEditIn(BaseModel):
    name: str
    value: Dict[str, Any]


@app.get("/api/bfd/node/{node_id}/schema")
def bfd_node_schema(node_id: str, state=Depends(get_state)):
    """Rich v1 form schema (groups/number/select/table fields) for a node."""
    _sync_solutions(state)
    _refresh_utilities(state)   # resin/wastewater/membrane dropdowns = saved 유틸리티 table
    fn = _v9_node_to_flownode(_find_v9_node(state, node_id))
    return util_bfd.build_node_schema(state, fn)


@app.post("/api/bfd/node/{node_id}")
def bfd_edit_node(node_id: str, req: NodeEditIn, state=Depends(get_state)):
    """Save a node edit through v1's ``process_*_data`` (computes in_mass /
    out_mass / stream_flow, fills water, etc.) and store the processed Value."""
    _sync_solutions(state)
    n = _find_v9_node(state, node_id)
    fn = _v9_node_to_flownode(n)
    if "flow_state" not in state:
        from .flow_models import FlowState
        state.flow_state = FlowState()
    util_bfd.apply_node_edit(state, fn, req.name, req.value)
    n["label"] = req.name
    n["params"] = fn.data["Value"]
    return {"node": n}


@app.delete("/api/bfd/node/{node_id}")
def bfd_delete_node(node_id: str, state=Depends(get_state)):
    state.bfd_nodes = [n for n in state.bfd_nodes if n["id"] != node_id]
    state.bfd_edges = [e for e in state.bfd_edges if e["source"] != node_id and e["target"] != node_id]
    return {"nodes": state.bfd_nodes, "edges": state.bfd_edges}


@app.post("/api/bfd/clear")
def bfd_clear(state=Depends(get_state)):
    state.bfd_nodes = []
    state.bfd_edges = []
    return {"ok": True}


@app.post("/api/bfd/save")
def bfd_save(body: BFDSaveIn, state=Depends(get_state)):
    state.bfd_nodes = body.nodes
    state.bfd_edges = body.edges
    return {"ok": True}


@app.post("/api/bfd/edge")
def bfd_add_edge(edge: EdgeIn, state=Depends(get_state)):
    eid = f"e_{int(time.time()*1000)}_{len(state.bfd_edges)}"
    new = {"id": eid, "source": edge.source, "target": edge.target}
    state.bfd_edges.append(new)
    return {"edge": new}


@app.delete("/api/bfd/edge/{edge_id}")
def bfd_delete_edge(edge_id: str, state=Depends(get_state)):
    state.bfd_edges = [e for e in state.bfd_edges if e["id"] != edge_id]
    return {"edges": state.bfd_edges}


# ---------------------------------------------------------------------------
# BioSTEAM
# ---------------------------------------------------------------------------

@app.get("/api/biosteam/status")
def biosteam_status():
    """Report whether biosteam can actually be imported.

    ``installed`` = the package is on sys.path (cheap ``find_spec``).
    ``available`` = it imports cleanly (authoritative; may take ~20s the first
    time due to numba warmup).  When installed but not available, ``error``
    carries the import traceback so the UI can show *why*.
    """
    installed = ub.biosteam_installed()
    available = ub.biosteam_available()
    return {"available": available, "installed": installed, "error": ub.IMPORT_ERROR}


@app.get("/api/biosteam/defaults")
def biosteam_defaults():
    return {"nodeTypes": sim.node_types(), "heat_utility": default_data.HEAT_UTILITY_DEFAULT}


@app.post("/api/biosteam/simulate")
async def biosteam_simulate(request: Request):
    payload = await request.json()
    return JSONResponse(sim.simulate(payload))


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def _project_path(name: str) -> str:
    safe = "".join(ch for ch in name if ch not in '/\\:*?"<>|').strip() or "project"
    return os.path.join(PROJECT_DIR, safe + ".json")


@app.get("/api/project/list")
def project_list():
    names = [f[:-5] for f in os.listdir(PROJECT_DIR) if f.endswith(".json")]
    return {"projects": sorted(names)}


@app.post("/api/project/save")
async def project_save(request: Request):
    body = await request.json()
    name = body.get("name") or "project"
    with open(_project_path(name), "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    return {"ok": True}


@app.get("/api/project/load/{name}")
def project_load(name: str):
    path = _project_path(name)
    if not os.path.exists(path):
        return {"error": "프로젝트를 찾을 수 없습니다."}
    with open(path, "r", encoding="utf-8") as f:
        return {"data": json.load(f)}


@app.delete("/api/project/{name}")
def project_delete(name: str):
    path = _project_path(name)
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Misc: chat, exchange rate, generic upload
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    msgs = body.get("messages", [])
    last = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
    ctx = body.get("context", {})
    reply = (
        "AI 어시스턴트는 외부 LLM 연동이 구성되지 않은 환경에서 동작 중입니다.\n"
        f"질문: `{last}`\n\n"
        f"현재 프로젝트: {ctx.get('project', {}).get('name', '(미지정)')} · "
        f"시나리오 {ctx.get('scenarioCount', 0)}개 · 화학물질 {ctx.get('chemCount', 0)}종.\n"
        "환율은 좌측 하단의 '현재 환율' 버튼으로 적용할 수 있습니다."
    )
    return {"content": reply, "data": None}


@app.get("/api/exchange-rate")
def exchange_rate():
    # Static fallback (no outbound dependency); the UI rounds and applies it.
    return {"rate": 1380, "source": "default (offline)"}


@app.post("/api/upload")
async def generic_upload(file: UploadFile = File(...)):
    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw), header=None)
            rows = df.values.tolist()
        else:
            text = raw.decode("utf-8", errors="ignore")
            rows = [ln.split("\t") if "\t" in ln else ln.split(",")
                    for ln in text.splitlines() if ln.strip()]
        proj_map = {"프로젝트이름": "name", "제품명": "product", "분석자": "analyst",
                    "환율": "exchangeRate", "할인율": "discountRate", "법인세율": "taxRate",
                    "분석기간": "analysisYears", "건설기간": "constructionYears"}
        sc_map = {"시나리오이름": "name", "생산량": "capacity", "capacity": "capacity",
                  "투자비": "capex", "capex": "capex", "원재료비": "rawMaterial",
                  "부재료": "subMaterial", "스팀": "steam", "전기": "electricity",
                  "냉각": "cooling", "폐기물": "waste", "인원수": "headcount",
                  "판매가": "sellingPrice"}
        parsed: Dict[str, Any] = {"project": {}, "scenarios": []}
        for row in rows:
            if len(row) < 2:
                continue
            key = str(row[0]).strip().lower().replace(" ", "").replace("_", "")
            val = str(row[1]).strip()
            try:
                num = float(val.replace(",", ""))
            except ValueError:
                num = None
            if key in proj_map:
                parsed["project"][proj_map[key]] = num if num is not None else val
            elif key in sc_map:
                if not parsed["scenarios"]:
                    parsed["scenarios"].append({})
                parsed["scenarios"][0][sc_map[key]] = num if num is not None else val
        return {"success": True, "data": parsed}
    except Exception:  # noqa: BLE001
        return {"success": False}
