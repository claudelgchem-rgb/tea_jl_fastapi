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

DATA_DIR = os.environ.get("TEA_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)


# Where the packaged ``initial_val.json`` lives (app/data/), preferred over the
# built-in defaults in default_data.py.
APP_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_all_unit_defaults() -> Dict[str, Any]:
    """Read the real ``initial_val.json`` (app/data/ or the scenario data dir),
    falling back to the built-in defaults in default_data.py."""
    for path in (os.path.join(DATA_DIR, "initial_val.json"),
                 os.path.join(APP_DATA_DIR, "initial_val.json")):
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    return default_data.all_unit_defaults()


_BASE_COLS = ["Name", "Formula", "Price (USD/kg)", "Phase"]


def _rows_to_chem_data(rows) -> Dict[str, Dict[str, Any]]:
    """Convert a list of chemical row-dicts into the dict-of-columns table."""
    cd = {c: {} for c in _BASE_COLS}
    for r in rows or []:
        name = r.get("Name") or r.get("name")
        if not name:
            continue
        cd["Name"][name] = name
        cd["Formula"][name] = r.get("Formula", r.get("formula", "")) or ""
        cd["Price (USD/kg)"][name] = float(r.get("Price (USD/kg)", r.get("price", 0)) or 0)
        cd["Phase"][name] = r.get("Phase", r.get("phase", "l")) or "l"
    return cd


def load_chem_data() -> Dict[str, Dict[str, Any]]:
    """Load the chemical table from a JSON file if one is provided, else use the
    built-in starter set.

    Search order: ``$TEA_CHEM_FILE``, then ``app/data/chemicals.json`` /
    ``chem_data.json`` (and the same names under the scenario data dir).

    Accepted JSON shapes:
      * dict-of-columns  -> ``{"Name": {...}, "Price (USD/kg)": {...}, ...}``
      * ``{"chemicals": [ {name, formula, price, phase}, ... ]}``
      * a bare list of chemical row-dicts
      * ``{name: {price, formula, phase}, ...}`` mapping
    """
    candidates = []
    env = os.environ.get("TEA_CHEM_FILE")
    if env:
        candidates.append(env)
    for d in (APP_DATA_DIR, DATA_DIR):
        candidates += [os.path.join(d, "chemicals.json"), os.path.join(d, "chem_data.json")]

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:  # noqa: BLE001 - fall through to the next candidate
            continue
        if isinstance(raw, dict) and "Price (USD/kg)" in raw:
            return raw  # already dict-of-columns
        if isinstance(raw, dict) and isinstance(raw.get("chemicals"), list):
            return _rows_to_chem_data(raw["chemicals"])
        if isinstance(raw, list):
            return _rows_to_chem_data(raw)
        if isinstance(raw, dict):  # {name: {price, formula, phase}} mapping
            rows = [{"name": n, **(props if isinstance(props, dict) else {"price": props})}
                    for n, props in raw.items()]
            return _rows_to_chem_data(rows)
    return default_data.starter_chem_data()


def load_solutions() -> List[Dict[str, Any]]:
    """Load the default solution list from a JSON file if one is provided.

    Mirrors ``load_chem_data`` / ``initial_val.json``: a ``solutions.json`` under
    ``app/data/`` (or the scenario data dir, or ``$TEA_SOLUTIONS_FILE``) supplies
    the starting solutions for a fresh session, editable until the user saves.

    Accepted shapes:
      * ``{"solutions": [ {user_name, autoclave, components:[{name, concentration_g_per_l}]}, ... ]}``
      * a bare list of the same solution dicts
    """
    candidates = []
    env = os.environ.get("TEA_SOLUTIONS_FILE")
    if env:
        candidates.append(env)
    for d in (APP_DATA_DIR, DATA_DIR):
        candidates.append(os.path.join(d, "solutions.json"))

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        sols = raw.get("solutions") if isinstance(raw, dict) else raw
        if not isinstance(sols, list):
            continue
        out = []
        for i, s in enumerate(sols):
            if not isinstance(s, dict):
                continue
            name = s.get("user_name") or s.get("name")
            if not name:
                continue
            comps = []
            for c in s.get("components", []) or []:
                cn = c.get("name")
                if not cn:
                    continue
                try:
                    conc = float(c.get("concentration_g_per_l", 0) or 0)
                except (TypeError, ValueError):
                    conc = 0.0
                comps.append({"name": cn, "concentration_g_per_l": conc})
            out.append({
                "id": s.get("id") or f"sol_default_{i}",
                "user_name": name,
                "autoclave": bool(s.get("autoclave", True)),
                "components": comps,
            })
        return out
    return []


def load_utilities() -> Dict[str, float]:
    """Load the default utility / sub-material price table (heat_utility).

    Like ``chemicals.json`` / ``solutions.json``: a ``utilities.json`` under
    ``app/data/`` (or the scenario data dir, or ``$TEA_UTILITIES_FILE``) supplies
    the starting utility + sub-material unit prices, editable until saved.

    Accepted shapes:
      * ``{"utilities": {id: price, ...}, "submaterials": {id: price, ...}}``
        (the two-table split shown in the UI; merged into one heat_utility dict)
      * a flat ``{id: price, ...}`` mapping

    Falls back to ``initial_val.json``'s ``heat_utility`` (then the built-in
    defaults) when no file is present.
    """
    candidates = []
    env = os.environ.get("TEA_UTILITIES_FILE")
    if env:
        candidates.append(env)
    for d in (APP_DATA_DIR, DATA_DIR):
        candidates.append(os.path.join(d, "utilities.json"))

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(raw, dict):
            continue
        merged: Dict[str, float] = {}
        if "utilities" in raw or "submaterials" in raw:
            for section in ("utilities", "submaterials"):
                for k, v in (raw.get(section) or {}).items():
                    try:
                        merged[str(k)] = float(v)
                    except (TypeError, ValueError):
                        merged[str(k)] = 0.0
        else:  # flat {id: price}
            for k, v in raw.items():
                try:
                    merged[str(k)] = float(v)
                except (TypeError, ValueError):
                    merged[str(k)] = 0.0
        if merged:
            return merged
    return json.loads(json.dumps(load_all_unit_defaults().get("heat_utility", {})))


def load_util_categories() -> Dict[str, str]:
    """Optional ``{id: category}`` map from ``utilities.json`` (``categories``
    section).  Missing ids are inferred from the id keyword by the API layer."""
    candidates = []
    env = os.environ.get("TEA_UTILITIES_FILE")
    if env:
        candidates.append(env)
    for d in (APP_DATA_DIR, DATA_DIR):
        candidates.append(os.path.join(d, "utilities.json"))
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(raw, dict) and isinstance(raw.get("categories"), dict):
            return {str(k): str(v) for k, v in raw["categories"].items()}
        return {}
    return {}


def set_chemicals(state, chem_data: Dict[str, Dict[str, Any]], build_thermo: bool = False) -> None:
    """Store the chemical table and derived lists (replaces ``upload_chemical2``).

    ``build_thermo=False`` (default) just records the table -- fast and free of
    the biosteam/thermosteam import cost, which is what session init and the
    chemical-DB endpoints need.  ``build_thermo=True`` additionally builds the
    thermosteam chemicals and registers the default thermo; only the simulation
    path needs that.
    """
    state.chem_data = chem_data
    state.chemical_list = list(chem_data.get("Price (USD/kg)", {}).keys())
    state.chemicals = []
    if build_thermo:
        from .flow_tabs.aux_compat import process_chemical_data
        chemicals, chem_data = process_chemical_data(chem_data)
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
    state.heat_utility = load_utilities()
    state.util_categories = load_util_categories()
    state.gmp = True
    state.electricity_price = tmp.get("electricity_price", 0.128)
    state.od_to_dcw = tmp.get("od_to_dcw", 0.22)
    state.target_amount = tmp.get("target_amount", 0.1)

    # Starter chemicals + default solutions.
    set_chemicals(state, load_chem_data())
    state.solutions = {"Water": {"Water": 1000}}
    state.autoclave = {"Water": False}
    state.prices = {"Water": float(state.chem_data.get("Price (USD/kg)", {}).get("Water", 0.0) or 0.0)}

    cl = state.chemical_list
    def _idx(key, default_name):
        i = tmp.get(key)
        if isinstance(i, int) and 0 <= i < len(cl):
            return cl[i]
        return default_name if default_name in cl else (cl[0] if cl else "")

    state.main_product = _idx("product_index", "Collagen")
    state.main_source = _idx("source_index", "Glucose")

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
    cl = state.chemical_list

    def _idx(key, default_name):
        i = state.tmp.get(key)
        if isinstance(i, int) and 0 <= i < len(cl):
            return cl[i]
        return default_name if default_name in cl else (cl[0] if cl else "")

    state.main_product = raw.get("main_product") or _idx("product_index", "Collagen")
    state.main_source = raw.get("main_source") or _idx("source_index", "Glucose")
    state.target_amount = raw.get("target_amount", state.tmp["target_amount"])
    state.gmp = raw.get("gmp", state.get("gmp", True))
    state.operating_hours = raw.get("operating_hours", state.tmp.get("operating_hours", 7920))
    state.electricity_price = raw.get("electricity_price", state.tmp.get("electricity_price", 0.128))
    state.proceed = True
    state.proceed2 = True
