"""FastAPI application (replaces the Streamlit ``main_app.py``).

The Streamlit single-script UI is decomposed into:

* a small set of JSON endpoints under ``/api`` that mutate the per-session
  state and run the simulation, and
* a single-page frontend (``templates/index.html`` + ``static/app.js``) that
  renders the chemical/solution forms, an interactive flow editor (replacing
  the ``streamlit_flow`` React component with a plain JS canvas), the node
  property forms (built from the schemas in ``util_bfd``) and the result
  tables / process diagram.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import data, schemas
from .compute import run_calculation
from .flow_tabs import util_bfd
from .flow_tabs import util_biosteam as ub
from .session import store

BASE = os.path.dirname(__file__)

app = FastAPI(title="TEA – Techno-Economic Analysis (FastAPI)")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

COOKIE = "tea_sid"


def get_state(request: Request, response: Response):
    sid = request.cookies.get(COOKIE)
    sid, state = store.get_or_create(sid)
    if "uploader_key" not in state:
        data.init_session(state)
    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
    return state


# --- State snapshot ----------------------------------------------------------

def _node_view(n):
    d = n.data
    return {
        "id": n.id,
        "pos": list(n.pos),
        "node_type": d.get("node_type"),
        "content": d.get("custom_value", d.get("content", n.id)),
        "emoji": d.get("emoji", util_bfd.get_emoji(d.get("node_type"))),
    }


def snapshot(state):
    fs = state.flow_state
    chem_data = state.chem_data
    chems = []
    for cid in state.chemical_list:
        chems.append({
            "Name": chem_data.get("Name", {}).get(cid, cid),
            "Formula": chem_data.get("Formula", {}).get(cid, ""),
            "Price (USD/kg)": chem_data.get("Price (USD/kg)", {}).get(cid, 0.0),
            "Phase": chem_data.get("Phase", {}).get(cid, "l"),
        })
    return {
        "biosteam_available": ub.BIOSTEAM_AVAILABLE,
        "config": {
            "main_product": state.get("main_product"),
            "main_source": state.get("main_source"),
            "target_amount": state.get("target_amount"),
            "operating_hours": state.get("operating_hours"),
            "gmp": state.get("gmp", True),
            "od_to_dcw": state.get("od_to_dcw", 0.22),
            "electricity_price": state.get("electricity_price", 0.128),
            "currency": state.get("currency", 1500),
        },
        "chemicals": chems,
        "chemical_list": state.chemical_list,
        "heat_utility": state.heat_utility,
        "solutions": state.solutions,
        "autoclave": state.autoclave,
        "prices": state.prices,
        "node_types": list(util_bfd.get_node_feature(state).keys()),
        "flow": {
            "nodes": [_node_view(n) for n in fs.nodes],
            "edges": [e.asdict() for e in fs.edges],
        },
        "proceed": state.get("proceed", False),
        "proceed2": state.get("proceed2", False),
        "scenarios": data.list_scenarios(),
    }


# --- Page --------------------------------------------------------------------

@app.get("/")
def index(request: Request, response: Response, state=Depends(get_state)):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/state")
def api_state(state=Depends(get_state)):
    return snapshot(state)


# --- Configuration step ('다음') --------------------------------------------

@app.post("/api/config")
def api_config(req: schemas.ConfigRequest, state=Depends(get_state)):
    cl = state.chemical_list
    if req.main_product not in cl or req.main_source not in cl:
        raise HTTPException(400, "main_product/main_source must be registered chemicals")
    state.main_product = req.main_product
    state.main_source = req.main_source
    state.target_amount = req.target_amount
    state.operating_hours = req.operating_hours
    state.gmp = req.gmp
    state.od_to_dcw = req.od_to_dcw
    state.electricity_price = req.electricity_price
    state.currency = req.currency
    state.tmp["product_index"] = cl.index(req.main_product)
    state.tmp["source_index"] = cl.index(req.main_source)
    state.tmp["target_amount"] = req.target_amount
    state.tmp["electricity_price"] = req.electricity_price
    state.tmp["operating_hours"] = req.operating_hours
    state.tmp["od_to_dcw"] = req.od_to_dcw
    if req.heat_utility is not None:
        state.heat_utility.update(req.heat_utility)
    if ub.BIOSTEAM_AVAILABLE:
        try:
            ub.bst.PowerUtility.price = req.electricity_price
        except Exception:  # noqa: BLE001
            pass
    state.proceed = True
    return snapshot(state)


# --- Chemicals ---------------------------------------------------------------

@app.post("/api/chemicals")
def api_chemicals(req: schemas.ChemicalsRequest, state=Depends(get_state)):
    cols = ["Name", "Formula", "Price (USD/kg)", "Phase"]
    chem_data = {c: {} for c in cols}
    for row in req.chemicals:
        chem_data["Name"][row.Name] = row.Name
        chem_data["Formula"][row.Name] = row.Formula
        chem_data["Price (USD/kg)"][row.Name] = row.Price
        chem_data["Phase"][row.Name] = row.Phase
    data.set_chemicals(state, chem_data)
    # Keep main product/source valid.
    if state.get("main_product") not in state.chemical_list and state.chemical_list:
        state.main_product = state.chemical_list[0]
    if state.get("main_source") not in state.chemical_list and state.chemical_list:
        state.main_source = state.chemical_list[0]
    return snapshot(state)


# --- Solutions ('용액 저장') -------------------------------------------------

@app.post("/api/solutions")
def api_solutions(req: schemas.SolutionsRequest, state=Depends(get_state)):
    try:
        from .flow_tabs.util_bfd import fill_water3
    except Exception:  # noqa: BLE001
        from .flow_tabs.aux_compat import fill_water3

    solutions = {}
    prices = {}
    autoclave = {}
    price_col = state.chem_data["Price (USD/kg)"]
    for item in req.solutions:
        comp = {r.Name: r.concentration for r in item.rows if r.Name}
        comp = fill_water3(comp, 1)
        solutions[item.name] = comp
        autoclave[item.name] = item.autoclave
        prices[item.name] = sum(mass * float(price_col.get(chem, 0.0)) for chem, mass in comp.items())
    # Always include the Water solution (main_app lines 278-280).
    solutions["Water"] = {"Water": 1000}
    autoclave["Water"] = False
    prices["Water"] = float(price_col.get("Water", 0.0))

    state.solutions = solutions
    state.autoclave = autoclave
    state.prices = prices
    state.proceed2 = True
    return snapshot(state)


# --- Flow: nodes / edges -----------------------------------------------------

@app.post("/api/nodes/add")
def api_add_node(req: schemas.AddNodeRequest, state=Depends(get_state)):
    util_bfd.add_node(state, req.node_type)
    return snapshot(state)


@app.post("/api/nodes/delete")
def api_delete_node(req: schemas.DeleteNodeRequest, state=Depends(get_state)):
    util_bfd.delete_node(state, req.node_id)
    return snapshot(state)


@app.post("/api/nodes/move")
def api_move_node(req: schemas.MoveNodeRequest, state=Depends(get_state)):
    for n in state.flow_state.nodes:
        if n.id == req.node_id:
            n.pos = (req.x, req.y)
            break
    return {"ok": True}


@app.post("/api/edges/add")
def api_add_edge(req: schemas.AddEdgeRequest, state=Depends(get_state)):
    ids = {n.id for n in state.flow_state.nodes}
    if req.source not in ids or req.target not in ids:
        raise HTTPException(400, "unknown node id")
    util_bfd.add_edge(state, req.source, req.target)
    return snapshot(state)


@app.post("/api/edges/delete")
def api_delete_edge(req: schemas.DeleteEdgeRequest, state=Depends(get_state)):
    fs = state.flow_state
    fs.edges = [e for e in fs.edges if e.id != req.edge_id]
    return snapshot(state)


def _find_node(state, node_id: str):
    for n in state.flow_state.nodes:
        if n.id == node_id:
            return n
    raise HTTPException(404, "node not found")


@app.get("/api/nodes/{node_id}/schema")
def api_node_schema(node_id: str, state=Depends(get_state)):
    node = _find_node(state, node_id)
    return util_bfd.build_node_schema(state, node)


@app.post("/api/nodes/{node_id}")
def api_edit_node(node_id: str, req: schemas.EditNodeRequest, state=Depends(get_state)):
    node = _find_node(state, node_id)
    util_bfd.apply_node_edit(state, node, req.name, req.value)
    return snapshot(state)


# --- Reset -------------------------------------------------------------------

@app.post("/api/reset")
def api_reset(state=Depends(get_state)):
    util_bfd.initialize_flowstate(state)
    return snapshot(state)


# --- Calculate ---------------------------------------------------------------

@app.post("/api/calculate")
def api_calculate(state=Depends(get_state)):
    try:
        result = run_calculation(state)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"{type(exc).__name__}: {exc}")
    return JSONResponse(result)


# --- Scenarios ---------------------------------------------------------------

@app.get("/api/scenarios")
def api_scenarios(state=Depends(get_state)):
    return {"scenarios": data.list_scenarios()}


@app.post("/api/scenarios/save")
def api_save(req: schemas.ScenarioRequest, state=Depends(get_state)):
    data.save_scenario(state, req.name)
    return {"ok": True, "scenarios": data.list_scenarios()}


@app.post("/api/scenarios/load")
def api_load(req: schemas.ScenarioRequest, state=Depends(get_state)):
    try:
        data.load_scenario(state, req.name)
    except FileNotFoundError:
        raise HTTPException(404, "scenario not found")
    return snapshot(state)
