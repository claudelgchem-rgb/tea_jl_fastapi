"""Session initialisation, chemical management and scenario persistence.

Ports the data-handling parts of ``main_app.py`` (the session-state bootstrap,
``load_data`` / Save Data, and the chemical registration that originally lived
in the external ``upload_chemical2`` helper).

Scenario files are stored under ``TEA_DATA_DIR`` (default ``./data``) instead of
the original hard-coded ``/home/sbf/JLee/test/data/scenario/`` path.
"""

from __future__ import annotations

import json
import os
import pickle
from typing import Any, Dict, List

from . import default_data
from .flow_models import FlowEdge, FlowNode, FlowState
from .flow_tabs import util_bfd
from .flow_tabs import util_biosteam as ub

DATA_DIR = os.environ.get("TEA_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)


def load_all_unit_defaults() -> Dict[str, Any]:
    """Read ``initial_val.json`` from the data dir, else use built-in defaults."""
    path = os.path.join(DATA_DIR, "initial_val.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default_data.all_unit_defaults()


def set_chemicals(state, chem_data: Dict[str, Dict[str, Any]]) -> None:
    """Store the chemical table and derived lists (replaces ``upload_chemical2``)."""
    chemicals, chem_data = ub.process_chemical_data(chem_data)
    state.chemicals = chemicals
    state.chem_data = chem_data
    state.chemical_list = list(chem_data.get("Price (USD/kg)", {}).keys())


def add_chemical(state, name: str, formula: str = "", price: float = 0.0, phase: str = "l") -> None:
    chem_data = state.chem_data
    chem_data.setdefault("Name", {})[name] = name
    chem_data.setdefault("Formula", {})[name] = formula
    chem_data.setdefault("Price (USD/kg)", {})[name] = float(price)
    chem_data.setdefault("Phase", {})[name] = phase
    set_chemicals(state, chem_data)


def init_session(state) -> None:
    """Initialise a fresh session (mirrors main_app lines 124-153)."""
    if "uploader_key" in state:
        return
    state.all_unit_defaults = load_all_unit_defaults()
    state.uploader_key = 0
    state.proceed = False
    state.proceed2 = False
    state.proceed3 = False
    state.run_biosteam = False
    state.scaled_system = {}
    state.simulation_ran = False
    state.reactions = {}
    state.node_select = None
    state.solutions = {}
    state.autoclave = {}
    state.prices = {}
    state.messages = []
    state.save_scenario = {}

    tmp = state.all_unit_defaults["tmp"]
    state.tmp = json.loads(json.dumps(tmp))  # deep copy
    state.currency = tmp.get("currency", 1500)
    state.operating_hours = tmp.get("operating_hours", 7920)
    state.heat_utility = json.loads(json.dumps(state.all_unit_defaults["heat_utility"]))
    state.gmp = True
    state.electricity_price = tmp.get("electricity_price", 0.128)
    state.od_to_dcw = tmp.get("od_to_dcw", 0.22)
    state.target_amount = tmp.get("target_amount", 0.1)

    # Starter chemicals + default solutions.
    set_chemicals(state, default_data.starter_chem_data())
    state.solutions = {"Water": {"Water": 1000}}
    state.autoclave = {"Water": False}
    state.prices = {"Water": float(state.chem_data["Price (USD/kg)"]["Water"])}

    cl = state.chemical_list
    state.main_product = cl[tmp["product_index"]] if tmp["product_index"] < len(cl) else cl[0]
    state.main_source = cl[tmp["source_index"]] if tmp["source_index"] < len(cl) else cl[0]

    util_bfd.initialize_flowstate(state)


# --- Scenario persistence ----------------------------------------------------

def list_scenarios() -> List[str]:
    return sorted(f[:-4] for f in os.listdir(DATA_DIR) if f.endswith(".pkl"))


def save_scenario(state, template: str) -> None:
    raw_data = {
        "chem_data": state.chem_data,
        "solutions": state.solutions,
        "autoclave": state.autoclave,
        "prices": state.prices,
        "nodes": [n.asdict() for n in state.flow_state.nodes],
        "edges": [e.asdict() for e in state.flow_state.edges],
        "tmp": state.tmp,
        "heat_utility": state.heat_utility,
        "gmp": state.get("gmp", True),
        "electricity_price": state.get("electricity_price", 0.128),
        "od_to_dcw": state.get("od_to_dcw", 0.22),
        "operating_hours": state.get("operating_hours", 7920),
        "target_amount": state.get("target_amount", 0.1),
        "main_product": state.get("main_product", "Collagen"),
        "main_source": state.get("main_source", "Glucose"),
        "currency": state.get("currency", 1500),
    }
    with open(os.path.join(DATA_DIR, template + ".pkl"), "wb") as f:
        pickle.dump(raw_data, f)


def load_scenario(state, template: str) -> None:
    """Load a scenario (mirrors main_app ``load_data``)."""
    with open(os.path.join(DATA_DIR, template + ".pkl"), "rb") as f:
        raw = pickle.load(f)

    state.tmp = raw["tmp"]
    nodes = [FlowNode.from_dict(n) for n in raw["nodes"]]
    edges = [FlowEdge.from_dict(e) for e in raw["edges"]]
    state.flow_state = FlowState(nodes=nodes, edges=edges)
    state.flow_rev = raw.get("flow_rev", 0)
    state.flow_state.flow_rev = state.flow_rev
    state.solutions = raw.get("solutions", {})
    state.autoclave = raw.get("autoclave", {})
    state.prices = raw.get("prices", {})
    state.proceed3 = False
    set_chemicals(state, raw["chem_data"])
    state.heat_utility = raw.get("heat_utility", {})
    state.currency = state.tmp.get("currency", 1500)
    state.main_product = raw.get("main_product", state.chemical_list[state.tmp["product_index"]])
    state.main_source = raw.get("main_source", state.chemical_list[state.tmp["source_index"]])
    state.target_amount = raw.get("target_amount", state.tmp["target_amount"])
    state.gmp = raw.get("gmp", state.get("gmp", True))
    state.operating_hours = raw.get("operating_hours", state.tmp.get("operating_hours", 7920))
    state.electricity_price = raw.get("electricity_price", state.tmp.get("electricity_price", 0.128))
    state.proceed = True
    state.proceed2 = True
