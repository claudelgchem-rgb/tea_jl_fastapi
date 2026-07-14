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


def _node_feature_defaults() -> Dict[str, Any]:
    """Addable-node initial Values, preferring the real initial_val.json
    (node_features) and falling back to the built-in per-unit defaults."""
    nf = data.load_all_unit_defaults().get("node_features") or {}
    return nf if nf else dict(_UNIT_DEFAULTS)


def node_types() -> Dict[str, Any]:
    """Return {type: {icon, color, params:{key:{type, default}}}} for the palette."""
    out: Dict[str, Any] = {}
    for ntype, defaults in _node_feature_defaults().items():
        defaults = defaults or {}
        params = {k: {"type": _param_type(v), "default": copy.deepcopy(v)} for k, v in defaults.items()}
        out[ntype] = {
            "icon": util_bfd.get_emoji(ntype),
            "color": NODE_COLORS.get(ntype, "#94a3b8"),
            "params": params,
        }
    return out


def default_node_params(ntype: str) -> Dict[str, Any]:
    nf = _node_feature_defaults()
    if ntype in nf:
        return copy.deepcopy(nf[ntype] or {})
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
    _process_all_nodes(state)
    return state


def _widget_from_schema(groups) -> Dict[str, Any]:
    """Flatten a ``build_node_schema`` group list into the flat widget dict the
    ``process_*_data`` functions expect (table fields become ``_*_df`` row
    lists, everything else is ``key -> value``)."""
    widget: Dict[str, Any] = {}

    def walk(fields):
        for f in fields or []:
            if isinstance(f, dict) and f.get("fields") is not None:  # nested group
                walk(f["fields"])
                continue
            key = f.get("key")
            if not key:
                continue
            widget[key] = f.get("rows", []) if f.get("kind") == "table" else f.get("value")

    for g in groups or []:
        walk(g.get("fields", []))
    return widget


def _process_all_nodes(state) -> None:
    """Run every node through its v1 processor so derived fields (``stream_flow``,
    ``in_mass``/``out_mass``, ``initial_conc`` …) always exist — even for nodes
    the user never opened in the properties editor.  This mirrors exactly what
    saving a node in the editor does, so simulate() no longer KeyErrors on an
    unconfigured fermenter.  The builder+processor round-trip is lossless for
    already-configured nodes."""
    for fn in state.flow_state.nodes:
        node_type = fn.data.get("node_type", "Default")
        builder, _ = util_bfd.get_node_editor_functions(node_type)
        value = fn.data.get("Value", {}) or {}
        try:
            groups = builder(state, copy.deepcopy(value))
            widget = _widget_from_schema(groups)
            name = fn.data.get("content") or fn.data.get("custom_value") or fn.id
            util_bfd.apply_node_edit(state, fn, name, widget)
        except Exception as exc:  # noqa: BLE001
            label = fn.data.get("content") or fn.id
            raise RuntimeError(f"노드 '{label}' ({node_type}) 처리 실패: {exc}") from exc


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
        installed = ub.biosteam_installed()
        return {
            "success": False,
            "error": ("biosteam is installed but failed to import"
                      if installed else "biosteam/thermosteam not installed"),
            "unit_hint": ("the package imports raised an error — see 상세 below"
                          if installed else "install biosteam to enable simulation"),
            "detail": ub.IMPORT_ERROR or "",
        }
    try:
        state = _build_state(payload)
        # Custom units read a few values from streamlit's session_state; inject
        # them into the (stubbed) session so they work headless.
        from .flow_tabs import aux_compat
        aux_compat.set_session_values(
            od_to_dcw=float(state.get("od_to_dcw", 0.22) or 0.22),
            operating_hours=float(state.operating_hours),
            heat_utility=state.heat_utility,
        )
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

    def detail_rows(chem_amounts):
        """[{chemical, kg_per_mt, price, cost_per_mt}] for feeds that flow.

        ``chem_amounts`` is {chem: kg/yr}; kg_per_mt = kg feed per MT product.
        """
        rows = []
        for ch, amt in chem_amounts.items():
            if not amt:
                continue
            kg_per_mt = amt / target_amount * 1000.0
            price = float(price_col.get(ch, 0) or 0)
            rows.append({"chemical": ch, "kg_per_mt": round(kg_per_mt, 3),
                         "price": price, "cost_per_mt": round(kg_per_mt * price, 2)})
        rows.sort(key=lambda r: r["cost_per_mt"], reverse=True)
        return rows

    raw_rows = detail_rows(upstream_c)
    sub_rows = detail_rows(upstream)
    raw_material = round(sum(r["cost_per_mt"] for r in raw_rows), 4)
    sub_material = round(sum(r["cost_per_mt"] for r in sub_rows), 4)

    electricity = scaled.power_utility.cost * op / target_amount * 1000
    # Every utility, not just the three headline buckets, so the UI can show
    # exactly which utilities the process consumes and how much.
    util_rows: List[Dict[str, Any]] = []
    steam = cooling = waste = 0.0
    _agg: Dict[str, Dict[str, float]] = {}
    for huu in scaled.heat_utilities:
        if huu.flow and huu.flow > 0:
            cost_mt = huu.cost * op / target_amount * 1000
            hid = huu.ID or "utility"
            agg = _agg.setdefault(hid, {"cost_per_mt": 0.0, "duty_kJ_per_hr": 0.0, "flow": 0.0})
            agg["cost_per_mt"] += cost_mt
            agg["duty_kJ_per_hr"] += float(getattr(huu, "duty", 0) or 0)
            agg["flow"] += float(huu.flow or 0)
            if hid in _STEAM_IDS:
                steam += cost_mt
            elif hid in _COOL_IDS:
                cooling += cost_mt
            elif hid in _WASTE_IDS:
                waste += cost_mt
            else:
                sub_material += cost_mt
    for hid, agg in _agg.items():
        util_rows.append({
            "utility": hid,
            "duty_kJ_per_hr": round(agg["duty_kJ_per_hr"], 1),
            "flow": round(agg["flow"], 4),
            "cost_per_mt": round(agg["cost_per_mt"], 2),
            "category": ("스팀" if hid in _STEAM_IDS else "냉각" if hid in _COOL_IDS
                         else "폐기물" if hid in _WASTE_IDS else "기타 유틸리티"),
        })
    util_rows.append({
        "utility": "electricity", "duty_kJ_per_hr": None,
        "flow": round(float(getattr(scaled.power_utility, "rate", 0) or 0), 3),
        "cost_per_mt": round(electricity, 2), "category": "전기",
    })
    util_rows.sort(key=lambda r: r["cost_per_mt"], reverse=True)

    # Titer (g/L) back-calculated from the BioSTEAM fermenter mass balance:
    # product mass produced per batch / final broth volume.
    titer = 0.0
    prod = state.main_product
    best = 0.0
    for n in state.flow_state.nodes:
        if n.data.get("node_type") != "발효기":
            continue
        val = n.data.get("Value", {}) or {}
        out = (val.get("out_mass") or {})
        fv = float(val.get("final_vol", 0) or 0)
        pm = float(out.get(prod, 0) or 0)
        if fv > 0 and pm > best:
            best = pm
            titer = pm * 1000.0 / fv  # kg -> g, per L
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
        "raw_material_detail": raw_rows,
        "sub_material_detail": sub_rows,
        "utilities_detail": util_rows,
        "titer_g_per_L": round(titer, 3),
        "target_MT_per_yr": round(target_amount / 1000.0, 4),
        # Main carbon source (기질): unit consumption (기질 원단위, kg/MT) and its
        # price from the chemical DB, so the scenario input can auto-fill.
        "substrate": ({
            "chemical": _sub_row["chemical"],
            "kg_per_mt": _sub_row["kg_per_mt"],                 # 기질 원단위
            "price_per_kg": _sub_row["price"],                 # from chemical DB
            "price_per_mt": round(_sub_row["price"] * 1000.0, 2),
            "cost_per_mt": _sub_row["cost_per_mt"],
        } if (_sub_row := next((r for r in raw_rows if r["chemical"] == state.main_source),
                               (raw_rows[0] if raw_rows else None))) else None),
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
