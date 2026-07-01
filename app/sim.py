"""Node-type metadata + stateless BioSTEAM simulation for the v9 UI.

The TEA-Agent v9 frontend posts a self-contained payload (chemicals, solutions,
BFD nodes/edges, run options) to ``/api/biosteam/simulate``.  This module turns
that payload into the data structures the original pipeline expects and drives
``util_biosteam`` (run_biosteam2 -> scale_up_system -> price_system) exactly as
the Streamlit app did, then aggregates the result into the ``$/MT`` cost
categories the UI displays.
"""

from __future__ import annotations

import copy
import traceback
from typing import Any, Dict, List

from . import data, default_data
from .flow_models import FlowEdge, FlowNode, FlowState
from .flow_tabs import util_bfd
from .flow_tabs import util_biosteam as ub
from .session import SessionState

# --- Node palette metadata --------------------------------------------------

NODE_COLORS = {
    "연속 피드": "#3b82f6", "배치 피드": "#6366f1", "발효기": "#22c55e",
    "증발기": "#f59e0b", "동결건조기": "#8b5cf6", "원심분리기": "#ec4899",
    "믹싱 탱크": "#14b8a6", "Product Stream": "#a16207", "폐기물": "#6b7280",
    "MVR": "#0ea5e9", "발효/정제 분리선": "#64748b", "HIC column": "#d946ef",
    "IEX column": "#d946ef", "DiaFiltration": "#10b981", "gel_filtration": "#06b6d4",
    "SMB_Chromatography": "#d946ef", "용액처리기": "#f97316", "Distillation": "#0ea5e9",
}

# Per-unit default Value dicts (the editable params surfaced in the UI).
_UNIT_DEFAULTS = {
    "발효기": default_data.FERMENTER_DEFAULT,
    "증발기": default_data.MVR_DEFAULT,
    "MVR": default_data.MVR_DEFAULT,
    "동결건조기": default_data.FREEZE_DRYER_DEFAULT2,
    "원심분리기": default_data.CENTRIFUGE_DEFAULT,
    "HIC column": default_data.HIC_DEFAULT,
    "IEX column": default_data.IEX_DEFAULT,
    "DiaFiltration": default_data.DIAFILTRATION_DEFAULT,
    "gel_filtration": default_data.GEL_FILTRATION_DEFAULT,
    "SMB_Chromatography": default_data.SMB_DEFAULT,
    "용액처리기": default_data.SOL_PROCESSOR_DEFAULT,
    "Distillation": default_data.DISTILLATION_DEFAULT,
    "연속 피드": {"Concentration [g/L]": {}, "Flow [L/hr]": 0.0},
    "배치 피드": {"Concentration [g/L]": {}, "Flow [L/hr]": 0.0},
    "Product Stream": {},
    "폐기물": {},
    "믹싱 탱크": {},
    "발효/정제 분리선": {},
}


def _param_type(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, dict):
        return "dict"
    if isinstance(v, list):
        return "list"
    return "text"


def node_types() -> Dict[str, Any]:
    """Return {type: {icon, color, params:{key:{type, default}}}} for the palette."""
    out: Dict[str, Any] = {}
    for ntype, defaults in _UNIT_DEFAULTS.items():
        params = {}
        for k, v in defaults.items():
            params[k] = {"type": _param_type(v), "default": copy.deepcopy(v)}
        out[ntype] = {
            "icon": util_bfd.get_emoji(ntype),
            "color": NODE_COLORS.get(ntype, "#94a3b8"),
            "params": params,
        }
    return out


def default_node_params(ntype: str) -> Dict[str, Any]:
    return copy.deepcopy(_UNIT_DEFAULTS.get(ntype, {}))


# --- Simulation -------------------------------------------------------------

_CARBON_SOURCES = ["Glucose", "Glycerol", "Methanol"]
_STEAM_IDS = {"low_pressure_steam", "medium_pressure_steam", "natural_gas"}
_COOL_IDS = {"cooling_water", "chilled_water"}
_WASTE_IDS = {"wastewater", "sludge", "solid_waste"}


def _build_state(payload: Dict[str, Any]) -> SessionState:
    state = SessionState()
    data.init_session(state)

    # Chemicals -> chem_data (dict-of-columns) -> set_chemicals (registers thermo).
    cols = ["Name", "Formula", "Price (USD/kg)", "Phase"]
    chem_data = {c: {} for c in cols}
    for c in payload.get("chemicals", []) or []:
        name = c.get("name")
        if not name:
            continue
        chem_data["Name"][name] = name
        chem_data["Formula"][name] = c.get("formula", "")
        chem_data["Price (USD/kg)"][name] = float(c.get("price", 0) or 0)
        chem_data["Phase"][name] = c.get("phase", "l") or "l"
    if chem_data["Price (USD/kg)"]:
        data.set_chemicals(state, chem_data, build_thermo=True)

    # Solutions.
    try:
        from .flow_tabs.aux_compat import fill_water3
    except Exception:  # noqa: BLE001
        fill_water3 = lambda d, v: d  # noqa: E731
    solutions, autoclave, prices = {}, {}, {}
    price_col = state.chem_data["Price (USD/kg)"] if "Price (USD/kg)" in state.chem_data else {}
    for sol in payload.get("solutions", []) or []:
        name = sol.get("user_name") or sol.get("name")
        if not name:
            continue
        comp = {}
        for c in sol.get("components", []) or []:
            cname = c.get("name")
            if cname:
                comp[cname] = float(c.get("concentration_g_per_l", 0) or 0)
        comp = fill_water3(comp, 1)
        solutions[name] = comp
        autoclave[name] = bool(sol.get("autoclave", True))
        prices[name] = sum(m * float(price_col.get(ch, 0) or 0) for ch, m in comp.items())
    solutions.setdefault("Water", {"Water": 1000})
    autoclave.setdefault("Water", False)
    prices.setdefault("Water", float(price_col.get("Water", 0) or 0))
    state.solutions, state.autoclave, state.prices = solutions, autoclave, prices

    # Run options.
    state.main_product = payload.get("main_product") or (state.chemical_list[0] if state.chemical_list else "")
    state.main_source = payload.get("main_source") or "Glucose"
    state.operating_hours = float(payload.get("operating_hours", 7920) or 7920)
    state.gmp = bool(payload.get("gmp", True))
    state.od_to_dcw = float(payload.get("od_to_dcw", 0.22) or 0.22)
    state.target_amount = float(payload.get("target_amount", 100) or 100)
    state.electricity_price = float(payload.get("electricity_price", 0.128) or 0.128)
    state.currency = 1  # UI works in USD; cost rows are $/MT.
    hu = payload.get("heat_utility") or {}
    if hu:
        state.heat_utility.update(hu)

    # BFD -> flow_state.
    bfd = payload.get("bfd") or {}
    nodes = []
    for n in bfd.get("nodes", []) or []:
        nodes.append(FlowNode(
            id=n["id"],
            pos=(n.get("x", 0), n.get("y", 0)),
            data={
                "node_type": n.get("node_type"),
                "content": n.get("label") or n.get("id"),
                "custom_value": n.get("label") or n.get("id"),
                "Value": n.get("params", {}) or {},
            },
        ))
    edges = [FlowEdge(id=e.get("id", f"e{i}"), source=e["source"], target=e["target"])
             for i, e in enumerate(bfd.get("edges", []) or [])]
    state.flow_state = FlowState(nodes=nodes, edges=edges)
    return state


def _stream_view(stream) -> Dict[str, Any]:
    comps = {}
    try:
        for chem in stream.chemicals:
            m = float(stream.imass[chem.ID])
            if abs(m) > 1e-9:
                comps[chem.ID] = m
    except Exception:  # noqa: BLE001
        pass
    return {"stream": getattr(stream, "ID", "?"), "total_kg_hr": float(getattr(stream, "F_mass", 0.0)), "components": comps}


def simulate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full pipeline and return the v9 cost breakdown (or an error)."""
    if not ub._ensure_biosteam():
        return {"success": False, "error": "biosteam/thermosteam not installed",
                "unit_hint": "install biosteam to enable simulation"}
    try:
        state = _build_state(payload)
        bst = ub.bst
        bst.main_flowsheet.clear()
        try:
            bst.PowerUtility.price = state.electricity_price
        except Exception:  # noqa: BLE001
            pass

        nodes: Dict[str, Any] = {}
        edges: Dict[str, list] = {}
        for n in state.flow_state.nodes:
            nodes[n.id] = n.data
            if "custom_value" in n.data:
                nodes[n.id]["content"] = n.data["custom_value"]
        for e in state.flow_state.edges:
            edges.setdefault(e.source, []).append(e.target)

        batch_time = ub.get_batch_time(nodes)
        solutions = [state.autoclave, state.solutions, state.prices]
        ferm_sys = ub.run_biosteam2(state, nodes, edges, solutions=solutions, batch_time=batch_time, feat_data={})

        target_amount = float(state.target_amount) * 1000  # kg/yr
        scaled = ub.scale_up_system(state, ferm_sys, state.main_product, target_amount, nodes)
        scaled = ub.price_system(state, scaled)
        scaled.simulate()

        result = _breakdown(state, scaled, target_amount)
        result["success"] = True
        result["mass_balance"] = _mass_balance(scaled)
        result["messages"] = list(state.get("messages", []))
        return result
    except Exception as exc:  # noqa: BLE001
        hint = ""
        msg = str(exc)
        if "not available" in msg and "Custom unit" in msg:
            hint = "custom biosteam unit operations (Biosteam_custom_unit) are required"
        ferms = [n.get("params", {}) for n in (payload.get("bfd", {}).get("nodes", []) or [])
                 if n.get("node_type") == "발효기"]
        return {"success": False, "error": msg, "unit_hint": hint,
                "detail": traceback.format_exc(), "_debug_fermenters": ferms[:2]}


def _breakdown(state, scaled, target_amount) -> Dict[str, Any]:
    bst = ub.bst
    lang_factor = 3.14285714285
    op = float(state.operating_hours)

    total_feed = ub.get_chem_price(state, scaled.ins)
    upstream, upstream_c = ub.get_c_source(
        total_feed, source=_CARBON_SOURCES + [state.main_source])
    price_col = state.chem_data["Price (USD/kg)"]

    def per_mt(chem_amounts):
        return sum(amt * float(price_col.get(ch, 0) or 0) / target_amount * 1000
                   for ch, amt in chem_amounts.items() if amt)

    raw_material = per_mt(upstream_c)
    sub_material = per_mt(upstream)

    electricity = scaled.power_utility.cost * op / target_amount * 1000
    steam = cooling = waste = 0.0
    for huu in scaled.heat_utilities:
        if huu.flow > 0:
            cost_mt = huu.cost * op / target_amount * 1000
            hid = huu.ID
            if hid in _STEAM_IDS:
                steam += cost_mt
            elif hid in _COOL_IDS:
                cooling += cost_mt
            elif hid in _WASTE_IDS:
                waste += cost_mt
            else:
                sub_material += cost_mt

    capex = scaled.installed_cost * lang_factor * 1.15
    if state.get("gmp", True):
        capex *= 5
    depreciation = capex * 0.082 / target_amount * 1000
    repair = capex * 0.05 / target_amount * 1000
    labor = 1440000000.0 / target_amount / 1500.0 * 1000.0

    return {
        "capex": round(capex, 0),
        "capexMn": round(capex / 1e6, 3),
        "rawMaterial": round(raw_material, 1),
        "subMaterial": round(sub_material, 1),
        "steam": round(steam, 1),
        "electricity": round(electricity, 1),
        "cooling": round(cooling, 1),
        "waste": round(waste, 1),
        "depreciation": round(depreciation, 1),
        "labor": round(labor, 1),
        "repair": round(repair, 1),
        "logic": {
            "batch_time_h": round(ub.get_batch_time({n.id: n.data for n in state.flow_state.nodes}), 2),
            "target_kg_per_yr": target_amount,
            "operating_hours": op,
            "installed_cost_usd": round(float(scaled.installed_cost), 0),
            "lang_factor": lang_factor,
            "gmp_multiplier": 5 if state.get("gmp", True) else 1,
            "main_product": state.main_product,
            "main_source": state.main_source,
        },
    }


def _mass_balance(scaled) -> Dict[str, Any]:
    units = []
    try:
        for u in scaled.units:
            units.append({
                "type": type(u).__name__,
                "name": getattr(u, "ID", "?"),
                "ins": [_stream_view(s) for s in u.ins],
                "outs": [_stream_view(s) for s in u.outs],
            })
    except Exception:  # noqa: BLE001
        pass
    return {
        "streams": {
            "inlets": [_stream_view(s) for s in scaled.ins],
            "outlets": [_stream_view(s) for s in scaled.outs],
        },
        "units": units,
    }
