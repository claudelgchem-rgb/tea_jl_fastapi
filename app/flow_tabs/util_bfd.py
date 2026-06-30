"""Block-flow-diagram utilities (FastAPI port of ``util_bfd_Copy4.py``).

Three responsibilities, ported from the Streamlit original:

1. **Flow management** -- ``get_node_feature`` / ``add_node`` / ``delete_node`` /
   ``initialize_flowstate`` now operate on the plain ``FlowState`` model and a
   ``state`` argument instead of ``st.session_state``.

2. **Node form schemas** -- every ``render_*_widgets`` function (which emitted
   Streamlit widgets) is replaced by a ``*_schema`` builder that returns a
   declarative description of the form (groups of number/text/select/table
   fields).  The browser renders the form from this schema and posts the edited
   values back, so no UI logic lives on the server any more.

3. **Data processing** -- the ``process_*_data`` functions are kept faithfully;
   they convert the submitted table rows (``_*_df`` keys) into the stored
   composition dicts, applying ``fill_water3`` exactly as before.
"""

from __future__ import annotations

import copy
import time

import pandas as pd

try:  # nanoid is a deployment dependency; fall back to stdlib.
    from nanoid import generate as nanoid  # type: ignore
except Exception:  # noqa: BLE001
    import secrets
    import string as _string

    def nanoid(size: int = 4) -> str:  # type: ignore
        alphabet = _string.ascii_letters + _string.digits
        return "".join(secrets.choice(alphabet) for _ in range(size))

# fill_water3 comes from the aux_compat resolver (real aux_chemical if present,
# else a local shim).
from .aux_compat import fill_water3

from ..flow_models import FlowEdge, FlowNode, FlowState


# ===========================================================================
# Emoji helpers (used for node labels in the browser)
# ===========================================================================

def get_emoji(node_type):
    node_db = {
        "연속 피드": "⚙️",
        "배치 피드": "⚙️",
        "Product Stream": "⭐",
        "폐기물": "⚙️",
        "발효/정제 분리선": "✅",
        "발효기": "⚗️",
        "믹싱 탱크": "🌀",
        "원심분리기": "✂️",
        "증발기": "💨",
        "동결건조기": "❄️",
        "SMB_Chromatography": "📊",
        "DiaFiltration": "📊",
        "Heater": "🔥",
        "Distillation": "🔃",
        "IEX column": "🪫",
        "HIC column": "🪫",
        "Protease/HCl/NaOH 처리": "🧪",
        "gel_filtration": "🫧",
        "Gypsum filtration": "📊",
        "용액처리기": "🧪",
        "highlight": "⚙️",
    }
    return node_db.get(node_type, "⚙️")


# ===========================================================================
# Flow features / styles
# ===========================================================================

def get_node_feature(state):  # Declare features needed for each unit
    features = copy.deepcopy(state.all_unit_defaults.get("node_features", {}))
    chem_list = state.get("chemical_list", ["Water", "Glucose", "Biomass"])
    for unit in features:
        if "split" in features[unit]:
            features[unit]["split"] = {i: 0.2 for i in chem_list}
    return features


def get_node_style(state):
    return copy.deepcopy(state.all_unit_defaults.get("node_style", {}))


def fast_copy(obj):
    if hasattr(obj, "asdict") and callable(obj.asdict):
        return obj.__class__.from_dict(copy.deepcopy(obj.asdict()))
    return copy.deepcopy(obj)


# ===========================================================================
# Flow management
# ===========================================================================

def add_node(state, node_type_input):
    NODE_TYPES = get_node_feature(state)
    node_data_value = fast_copy(NODE_TYPES.get(node_type_input, {}))
    count = len(state.flow_state.nodes)
    node_label = f"{node_type_input} {count + 1}"
    node_id = "Node_" + node_label + "_" + nanoid(size=4)
    if node_type_input == "발효/정제 분리선":
        node_label = "발효 ➔ 정제"

    new_node = FlowNode(
        id=node_id,
        pos=(count * 5 + 300, count * 50 + 250),
        data={
            "content": node_label,
            "node_type": node_type_input,
            "Value": node_data_value,
            "custom_value": node_label,
            "emoji": get_emoji(node_type_input),
        },
    )
    state.flow_state.nodes.append(new_node)
    state.flow_state.timestamp = time.time()
    state.flow_state.flow_rev += 1
    state.flow_rev = state.flow_state.flow_rev
    state.proceed3 = False
    return new_node


def delete_node(state, selected_node_id):
    if not selected_node_id:
        return
    fs = state.flow_state
    fs.nodes = [n for n in fs.nodes if n.id != selected_node_id]
    fs.edges = [e for e in fs.edges if e.source != selected_node_id and e.target != selected_node_id and e.id != selected_node_id]
    fs.selected_id = None
    state.selected_id_old = None
    state.node_select = None
    fs.timestamp = time.time()
    fs.flow_rev += 1
    state.flow_rev = fs.flow_rev
    state.proceed3 = False


def add_edge(state, source, target):
    fs = state.flow_state
    edge_id = f"edge_{source}_{target}_{nanoid(size=4)}"
    fs.edges.append(FlowEdge(id=edge_id, source=source, target=target))
    fs.timestamp = time.time()
    fs.flow_rev += 1
    state.flow_rev = fs.flow_rev
    state.proceed3 = False
    return edge_id


def initialize_flowstate(state):
    NODE_TYPES = get_node_feature(state)

    node_fermenter = FlowNode(
        id="Node_메인 발효기_" + nanoid(size=4),
        pos=(100, 100),
        data={"content": "메인 발효기", "node_type": "발효기", "custom_value": "메인 발효기",
              "emoji": get_emoji("발효기"), "Value": fast_copy(NODE_TYPES["발효기"])},
    )
    node_final = FlowNode(
        id="Node_Product Stream_" + nanoid(size=4),
        pos=(100, 600),
        data={"content": "공정 완료", "node_type": "Product Stream", "custom_value": "공정 완료",
              "emoji": get_emoji("Product Stream"), "Value": fast_copy(NODE_TYPES["Product Stream"])},
    )
    node_sep = FlowNode(
        id="Node_발효/정제 분리선_" + nanoid(size=4),
        pos=(10, 300),
        data={"content": "발효 ➔ 정제", "node_type": "발효/정제 분리선", "custom_value": "발효 ➔ 정제",
              "emoji": get_emoji("발효/정제 분리선"), "Value": fast_copy(NODE_TYPES["발효/정제 분리선"])},
    )

    nodes = [node_fermenter, node_sep, node_final]
    edges = [FlowEdge(f"edge_{node_fermenter.id}_{node_sep.id}", node_fermenter.id, node_sep.id)]

    state.flow_state = FlowState(nodes=nodes, edges=edges)
    state.selected_id_old = None
    state.flow_rev = 0
    state.node_select = None


# ===========================================================================
# DataFrame helpers (kept from the original; used by process_* functions)
# ===========================================================================

def _get_df_from_dict_list(data_dict_input, columns):
    """Convert various dict/list structures into a DataFrame with ``columns``."""
    if not data_dict_input:
        return pd.DataFrame(columns=columns)
    elif isinstance(data_dict_input, dict) and all(isinstance(v, list) for v in data_dict_input.values()):
        processed_data = {}
        for k, v in data_dict_input.items():
            if v and all(isinstance(x, list) and len(x) == 1 for x in v):
                processed_data[k] = [x[0] for x in v]
            else:
                processed_data[k] = v
        num_rows = len(next(iter(processed_data.values()))) if processed_data else 0
        for col in columns:
            if col not in processed_data:
                processed_data[col] = [""] * num_rows
        return pd.DataFrame(processed_data)
    elif isinstance(data_dict_input, list):
        # list of row-dicts (from the browser) or list of [k, v] pairs
        if data_dict_input and isinstance(data_dict_input[0], dict):
            df = pd.DataFrame(data_dict_input)
            for col in columns:
                if col not in df.columns:
                    df[col] = ""
            return df[[c for c in columns if c in df.columns]]
        data_for_df = []
        for row_list in data_dict_input:
            row = list(row_list)
            if len(columns) > len(row):
                row.extend([""] * (len(columns) - len(row)))
            data_for_df.append(row)
        return pd.DataFrame(data_for_df, columns=columns)
    elif isinstance(data_dict_input, dict):
        data_for_df = []
        for material, conc in data_dict_input.items():
            row = [material, conc]
            if len(columns) > len(row):
                row.extend([""] * (len(columns) - len(row)))
            data_for_df.append(row)
        return pd.DataFrame(data_for_df, columns=columns)
    return pd.DataFrame(columns=columns)


def _rows(value, key, columns):
    """Build a list of row-dicts (for the browser) from a stored composition."""
    df = _get_df_from_dict_list(value.get(key, {}), columns)
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


# Field-descriptor constructors -------------------------------------------

def _num(key, label, value):
    return {"kind": "number", "key": key, "label": label, "value": float(value or 0)}


def _int(key, label, value):
    return {"kind": "int", "key": key, "label": label, "value": int(value or 0)}


def _txt(key, label, value):
    return {"kind": "text", "key": key, "label": label, "value": "" if value is None else str(value)}


def _sel(key, label, options, value):
    options = list(options)
    if value not in options and options:
        value = options[0]
    return {"kind": "select", "key": key, "label": label, "options": options, "value": value}


def _table(key, label, columns, rows):
    return {"kind": "table", "key": key, "label": label, "columns": columns, "rows": rows}


def _conc_cols(chem_list):
    return [
        {"name": "물질", "type": "select", "options": chem_list},
        {"name": "농도 [g/L]", "type": "number"},
    ]


def _group(title, fields, advanced=False):
    return {"title": title, "advanced": advanced, "fields": fields}


# ===========================================================================
# Per-unit schema builders (replace the render_*_widgets functions)
# ===========================================================================

def _fermenter_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("fermenter_default", {}))
    d["Main reactant"] = state.main_source
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    sol_list = list(state.get("solutions", {}).keys())
    conc3 = [
        {"name": "물질", "type": "select", "options": chem_list},
        {"name": "농도 [g/L]", "type": "number"},
        {"name": "용액", "type": "select", "options": sol_list},
    ]
    advanced = [
        _num("P", "압력 [Pa]", v.get("P", 0)),
        _num("V_wf", "Working Volume [%]", v.get("V_wf", 0)),
        _num("V_max", "발효기 최대 부피 [m3]", v.get("V_max", 0)),
        _num("tau_add", "투입시간 [hr]", v.get("tau_add", 0)),
        _num("tau_cool", "추가 cooling [hr]", v.get("tau_cool", 0)),
        _num("tau_sip", "SIP 시간 [hr]", v.get("tau_sip", 0)),
        _num("tau_cip", "CIP 시간 [hr]", v.get("tau_cip", 0)),
        _num("sip_stream_rate", "스팀 속도 [kg/hr/m3]", v.get("sip_stream_rate", 0)),
        _num("agitation_efficiency", "Agitator 효율", v.get("agitation_efficiency", 0)),
        _num("P_drop", "Pressure drop [Pa]", v.get("P_drop", 0)),
        _num("compressor_isentropic_efficiency", "컴프레서 효율", v.get("compressor_isentropic_efficiency", 0)),
        _num("motor_efficiency", "모터 효율", v.get("motor_efficiency", 0)),
        _num("chill_to_cool_ratio", "Chilled_water ratio", v.get("chill_to_cool_ratio", 0)),
        _sel("Main reactant", "주 탄소원", chem_list, v.get("Main reactant")),
    ]
    main = [
        _num("tau", "발효 시간", v.get("tau", 0)),
        _num("T", "발효 온도 [C]", v.get("T", 0)),
        _num("vvm", "공기 투입량 [vvm]", v.get("vvm", 0)),
        _num("init_OD", "시작 OD", v.get("init_OD", 0)),
        _num("final_OD", "최종 OD", v.get("final_OD", 0)),
        _num("initial_vol", "Lab 기준 시작 투입량 [L]", v.get("initial_vol", 0)),
        _table("_initial_conc_df", "시작 투입 농도 [g/L]", conc3, _rows(v, "initial_conc", ["물질", "농도 [g/L]", "용액"])),
        _num("feed_vol", "Lab 기준 총 피드 투입량 [L]", v.get("feed_vol", 0)),
        _table("_feed_conc_df", "피드 투입 농도 [g/L]", conc3, _rows(v, "feed_conc", ["물질", "농도 [g/L]", "용액"])),
        _num("final_vol", "Lab 기준 최종 부피 [L]", v.get("final_vol", 0)),
        _table("_final_conc_df", "최종 농도 [g/L]", _conc_cols(chem_list), _rows(v, "final_conc", ["물질", "농도 [g/L]"])),
    ]
    return [_group("고급 설정", advanced, advanced=True), _group("옵션", main)]


def process_fermenter_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    chem_list = state.get("chemical_list", [])
    solution_list = list(state.get("solutions", {}).keys())

    initial_conc_df = processed_values.pop("_initial_conc_df", pd.DataFrame(columns=["물질", "농도 [g/L]", "용액"]))
    feed_conc_df = processed_values.pop("_feed_conc_df", pd.DataFrame(columns=["물질", "농도 [g/L]", "용액"]))
    final_conc_df = processed_values.pop("_final_conc_df", pd.DataFrame(columns=["물질", "농도 [g/L]"]))
    for _df, _cols in ((initial_conc_df, ["물질", "농도 [g/L]", "용액"]),
                       (feed_conc_df, ["물질", "농도 [g/L]", "용액"]),
                       (final_conc_df, ["물질", "농도 [g/L]"])):
        for _c in _cols:
            if _c not in _df.columns:
                _df[_c] = []

    processed_values["initial_conc"] = initial_conc_df.to_dict("list")
    processed_values["feed_conc"] = feed_conc_df.to_dict("list")
    processed_values["final_conc"] = final_conc_df.to_dict("list")

    in_mass = {c: 0.0 for c in chem_list}
    out_mass = {c: 0.0 for c in chem_list}

    total_in_vol = (processed_values["initial_vol"] + processed_values["feed_vol"]) / 1000
    for _, row in initial_conc_df.iterrows():
        if row["물질"] in in_mass:
            in_mass[row["물질"]] += float(row["농도 [g/L]"]) * processed_values["initial_vol"] / 1000
    for _, row in feed_conc_df.iterrows():
        if row["물질"] in in_mass:
            in_mass[row["물질"]] += float(row["농도 [g/L]"]) * processed_values["feed_vol"] / 1000
    in_mass = fill_water3(in_mass, total_in_vol)

    for _, row in final_conc_df.iterrows():
        if row["물질"] in out_mass:
            out_mass[row["물질"]] = float(row["농도 [g/L]"]) * processed_values["final_vol"] / 1000
    out_mass = fill_water3(out_mass, processed_values["final_vol"] / 1000)

    all_conc_df = pd.concat([initial_conc_df, feed_conc_df])
    if "용액" in all_conc_df.columns:
        valid_solutions_df = all_conc_df[all_conc_df["용액"].notna() & (all_conc_df["용액"] != "")]
        stream_composition = valid_solutions_df.groupby("용액")["물질"].unique().apply(list).to_dict()
    else:
        stream_composition = {}

    stream_flow = {s: {} for s in solution_list}
    water_mass_remaining = in_mass.get("Water", 0.0)

    for s in stream_composition:
        if s in state.get("solutions", {}):
            chem = stream_composition[s][0]
            if chem in in_mass and chem in state["solutions"][s]:
                if state["solutions"][s][chem] != 0:
                    vol_req = in_mass[chem] / (state["solutions"][s][chem])
                    stream_flow[s] = {j: mass * vol_req for j, mass in state["solutions"][s].items()}
                    water_mass_remaining -= vol_req * state["solutions"][s].get("Water", 0.0)
    stream_flow["Water"] = {"Water": max(0.0, water_mass_remaining)}

    processed_values["stream_flow"] = stream_flow
    processed_values["in_mass"] = in_mass
    processed_values["out_mass"] = out_mass
    return processed_values


def _mvr_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("mvr_default", {}))
    v = {**d, **value}
    advanced = [
        _num("U_overall", "U_overall [kW/m.K]", v.get("U_overall", 0)),
        _num("motor_efficiency", "Motor Efficiency", v.get("motor_efficiency", 0)),
        _num("compressor_isentropic_efficiency", "compressor_isentropic_efficiency", v.get("compressor_isentropic_efficiency", 0)),
        _num("pump_efficiency", "Pump Efficiency", v.get("pump_efficiency", 0)),
        _num("pump_head", "Pump head", v.get("pump_head", 0)),
        _num("P_drop", "Pressure drop [Pa]", v.get("P_drop", 0)),
        _txt("chemical", "증류 chemical", v.get("chemical", "Water")),
    ]
    main = [
        _num("T", "온도 [C]", v.get("T", 0)),
        _num("V", "증발 비율 [%]", v.get("V", 40)),
    ]
    return [_group("고급 설정", advanced, advanced=True), _group("옵션", main)]


def process_MVR_data(state, submitted_widget_data: dict):
    return submitted_widget_data.copy()


def _chromatography_advanced(v, util_list, prefix, wastewater_index):
    return [
        _num("column_price", "Empty column 가격 [USD/L resin]", v.get("column_price", 7000.0)),
        _num("P_drop", "Pressure drop [Pa]", v.get("P_drop", 0)),
        _num("motor_efficiency", "Motor Efficiency", v.get("motor_efficiency", 0)),
        _num("compressor_isentropic_efficiency", "compressor_isentropic_efficiency", v.get("compressor_isentropic_efficiency", 0)),
        _num("pump_efficiency", "Pump Efficiency", v.get("pump_efficiency", 0)),
        _sel("wastewater_id", "Wastewater 종류", util_list, v.get("wastewater_id")),
    ]


def _hic_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("hic_default", {}))
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    util_list = list(state.get("heat_utility", {}).keys())
    v["binding_material"] = v.get("binding_material", state.main_product)
    cc = _conc_cols(chem_list)
    resin = [
        _sel("resin_id", "Resin 종류", util_list, v.get("resin_id")),
        _num("resin_price", "Resin 가격 [USD/L]", state.get("heat_utility", {}).get(v.get("resin_id"), v.get("resin_price", 0.0))),
        _sel("binding_material", "Binding Chemical", chem_list, v.get("binding_material")),
        _num("binding_capacity", "Binding Capacity [g/L]", v.get("binding_capacity", 20.0)),
        _num("resin_lifetime_cycle", "레진 수명 [cycle]", v.get("resin_lifetime_cycle", 0)),
    ]
    steps = [
        _num("tau_loading", "로딩 시간 [h]", v.get("tau_loading", 0)),
        _num("flowrate_wash", "wash volume [BV/hr]", v.get("flowrate_wash", 0)),
        _num("tau_wash", "wash 시간 [h]", v.get("tau_wash", 0)),
        _table("_conc_wash_df", "wash 농도 [g/L]", cc, _rows(v, "conc_wash", ["물질", "농도 [g/L]"])),
        _num("flowrate_equilibrate", "equilibrate volume [BV/hr]", v.get("flowrate_equilibrate", 0)),
        _num("tau_equilibrate", "equilibrate 시간 [h]", v.get("tau_equilibrate", 0)),
        _table("_conc_equilibrate_df", "equilibrate 농도 [g/L]", cc, _rows(v, "conc_equilibrate", ["물질", "농도 [g/L]"])),
        _num("flowrate_elute", "elute volume [BV/hr]", v.get("flowrate_elute", 0)),
        _num("tau_elute", "elute 시간 [h]", v.get("tau_elute", 0)),
        _table("_conc_elute_df", "elute 농도 [g/L]", cc, _rows(v, "conc_elute", ["물질", "농도 [g/L]"])),
        _num("flowrate_rinse", "rinse volume [BV/hr]", v.get("flowrate_rinse", 0)),
        _num("tau_rinse", "rinse 시간 [h]", v.get("tau_rinse", 0)),
        _table("_conc_rinse_df", "rinse 농도 [g/L]", cc, _rows(v, "conc_rinse", ["물질", "농도 [g/L]"])),
        _num("flowrate_regenerate", "regenerate volume [BV/hr]", v.get("flowrate_regenerate", 0)),
        _num("tau_regenerate", "regenerate 시간 [h]", v.get("tau_regenerate", 0)),
        _table("_conc_regenerate_df", "Regenerate 농도 [g/L]", cc, _rows(v, "conc_regenerate", ["물질", "농도 [g/L]"])),
        _num("volume_product", "Product Volume / Elute volume", v.get("volume_product", 0)),
        _table("_conc_product_df", "product 농도 [g/L]", cc, _rows(v, "conc_product", ["물질", "농도 [g/L]"])),
    ]
    return [_group("고급 설정", _chromatography_advanced(v, util_list, "HIC", 0), advanced=True),
            _group("레진 정보", resin), _group("용액 투입량", steps)]


def _df_to_dict(df, value_col, key_col="물질"):
    """Robustly turn a (possibly empty / column-less) table into ``{name: value}``."""
    if df is None or len(df) == 0 or key_col not in getattr(df, "columns", []):
        return {}
    out = {}
    for _, row in df.iterrows():
        name = row.get(key_col)
        if name not in (None, ""):
            out[name] = row.get(value_col, 0)
    return out


def _conc_proc(processed_values, *keys):
    for k in keys:
        df = processed_values.pop(f"_{k}_df", None)
        processed_values[k] = fill_water3(_df_to_dict(df, "농도 [g/L]"), 1)


def process_HIC_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    _conc_proc(processed_values, "conc_wash", "conc_equilibrate", "conc_elute", "conc_rinse", "conc_regenerate", "conc_product")
    resin_id = processed_values.get("resin_id")
    if resin_id and resin_id in state.get("heat_utility", {}):
        processed_values["resin_price"] = float(state["heat_utility"][resin_id])
    return processed_values


def _iex_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("iex_default", {}))
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    util_list = list(state.get("heat_utility", {}).keys())
    v["binding_material"] = v.get("binding_material", state.main_product)
    cc = _conc_cols(chem_list)
    resin = [
        _sel("resin_id", "Resin 종류", util_list, v.get("resin_id")),
        _num("resin_price", "Resin 가격 [USD/L]", state.get("heat_utility", {}).get(v.get("resin_id"), v.get("resin_price", 0.0))),
        _sel("binding_material", "Binding Chemical", chem_list, v.get("binding_material")),
        _num("binding_capacity", "Binding Capacity [g/L]", v.get("binding_capacity", 20.0)),
        _num("resin_lifetime_cycle", "레진 수명 [cycle]", v.get("resin_lifetime_cycle", 0)),
    ]
    steps = [
        _num("tau_loading", "로딩 시간 [h]", v.get("tau_loading", 0)),
        _num("flowrate_wash1", "wash-1 volume [BV/hr]", v.get("flowrate_wash1", 0)),
        _num("tau_wash1", "wash-1 시간 [h]", v.get("tau_wash1", 0)),
        _table("_conc_wash1_df", "wash-1 농도 [g/L]", cc, _rows(v, "conc_wash1", ["물질", "농도 [g/L]"])),
        _num("flowrate_wash2", "wash-2 volume [BV/hr]", v.get("flowrate_wash2", 0)),
        _num("tau_wash2", "wash-2 시간 [h]", v.get("tau_wash2", 0)),
        _table("_conc_wash2_df", "wash-2 농도 [g/L]", cc, _rows(v, "conc_wash2", ["물질", "농도 [g/L]"])),
        _num("flowrate_elute", "elute volume [BV/hr]", v.get("flowrate_elute", 0)),
        _num("tau_elute", "elute 시간 [h]", v.get("tau_elute", 0)),
        _table("_conc_elute_df", "elute 농도 [g/L]", cc, _rows(v, "conc_elute", ["물질", "농도 [g/L]"])),
        _num("flowrate_regenerate", "regenerate volume [BV/hr]", v.get("flowrate_regenerate", 0)),
        _num("tau_regenerate", "regenerate 시간 [h]", v.get("tau_regenerate", 0)),
        _table("_conc_regenerate_df", "Regenerate 농도 [g/L]", cc, _rows(v, "conc_regenerate", ["물질", "농도 [g/L]"])),
        _num("volume_product", "Product volume / Elute volume", v.get("volume_product", 0)),
        _table("_conc_product_df", "product 농도 [g/L]", cc, _rows(v, "conc_product", ["물질", "농도 [g/L]"])),
    ]
    return [_group("고급 설정", _chromatography_advanced(v, util_list, "IEX", 0), advanced=True),
            _group("레진 정보", resin), _group("용액 투입량", steps)]


def process_IEX_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    _conc_proc(processed_values, "conc_wash1", "conc_wash2", "conc_elute", "conc_regenerate", "conc_product")
    resin_id = processed_values.get("resin_id")
    if resin_id and resin_id in state.get("heat_utility", {}):
        processed_values["resin_price"] = float(state["heat_utility"][resin_id])
    return processed_values


def _gel_filtration_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("gel_filtration_default", {}))
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    util_list = list(state.get("heat_utility", {}).keys())
    v["binding_material"] = v.get("binding_material", state.main_product)
    cc = _conc_cols(chem_list)
    resin = [
        _sel("resin_id", "Resin 종류", util_list, v.get("resin_id")),
        _num("resin_price", "Resin 가격 [USD/L]", state.get("heat_utility", {}).get(v.get("resin_id"), v.get("resin_price", 0.0))),
        _sel("binding_material", "Binding Chemical", chem_list, v.get("binding_material")),
        _num("binding_capacity", "Binding Capacity [g/L]", v.get("binding_capacity", 20.0)),
        _num("resin_lifetime_cycle", "레진 수명 [cycle]", v.get("resin_lifetime_cycle", 0)),
    ]
    steps = [
        _num("tau_loading", "로딩 시간 [h]", v.get("tau_loading", 0.0)),
        _num("flowrate_wash", "wash volume [BV/hr]", v.get("flowrate_wash", 0.0)),
        _num("tau_wash", "wash 시간 [h]", v.get("tau_wash", 0.0)),
        _table("_conc_wash_df", "wash 농도 [g/L]", cc, _rows(v, "conc_wash", ["물질", "농도 [g/L]"])),
        _num("flowrate_equilibrate", "equilibrate volume [BV/hr]", v.get("flowrate_equilibrate", 0)),
        _num("tau_equilibrate", "equilibrate 시간 [h]", v.get("tau_equilibrate", 0)),
        _table("_conc_equilibrate_df", "equilibrate 농도 [g/L]", cc, _rows(v, "conc_equilibrate", ["물질", "농도 [g/L]"])),
        _num("flowrate_elute", "elute volume [BV/hr]", v.get("flowrate_elute", 0)),
        _num("tau_elute", "elute 시간 [h]", v.get("tau_elute", 0)),
        _table("_conc_elute_df", "elute 농도 [g/L]", cc, _rows(v, "conc_elute", ["물질", "농도 [g/L]"])),
        _num("volume_product", "Product volume / Elute volume", v.get("volume_product", 0)),
        _table("_conc_product_df", "product 농도 [g/L]", cc, _rows(v, "conc_product", ["물질", "농도 [g/L]"])),
    ]
    return [_group("고급 설정", _chromatography_advanced(v, util_list, "GF", 0), advanced=True),
            _group("레진 정보", resin), _group("용액 투입량", steps)]


def process_gel_filtration_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    _conc_proc(processed_values, "conc_wash", "conc_equilibrate", "conc_elute", "conc_product")
    resin_id = processed_values.get("resin_id")
    if resin_id and resin_id in state.get("heat_utility", {}):
        processed_values["resin_price"] = float(state["heat_utility"][resin_id])
    return processed_values


def _diafiltration_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("diafiltration_default", {}))
    if "separation" not in d or not d["separation"]:
        d["separation"] = {i: 0.2 for i in state.chemical_list}
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    util_list = list(state.get("heat_utility", {}).keys())
    advanced = [
        _num("tau_cip", "CIP 시간 [h]", v.get("tau_cip", 0)),
        _num("cip_flowrate", "CIP volume [BV/hr]", v.get("cip_flowrate", 0)),
        _int("n_cip", "CIP Run 횟수", v.get("n_cip", 0)),
        _sel("cip_id", "CIP 용액 종류", util_list, v.get("cip_id")),
        _sel("wastewater_id", "Wastewater 종류", util_list, v.get("wastewater_id")),
    ]
    sep_cols = [
        {"name": "물질", "type": "select", "options": chem_list},
        {"name": "Rate In Solids", "type": "number"},
    ]
    main = [
        _sel("membrane_id", "Membrane 종류", util_list, v.get("membrane_id")),
        _num("membrane_cost", "Membrane 가격 [USD]", state.get("heat_utility", {}).get(v.get("membrane_id"), v.get("membrane_cost", 0.0))),
        _num("membrane_life", "membrane 수명 [hr]", v.get("membrane_life", 0)),
        _num("tau", "시간 [h]", v.get("tau", 0)),
        _table("_separation_df", "분리 효율 (0-1)", sep_cols, _rows(v, "split", ["물질", "Rate In Solids"])),
    ]
    return [_group("고급 설정", advanced, advanced=True), _group("Membrane 정보", main)]


def process_diafiltration_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    membrane_id = processed_values.get("membrane_id")
    if membrane_id and membrane_id in state.get("heat_utility", {}):
        processed_values["membrane_cost"] = float(state["heat_utility"][membrane_id])
    separation_df = processed_values.pop("_separation_df", None)
    processed_values["separation"] = _df_to_dict(separation_df, "Rate In Solids")
    return processed_values


def _freeze_dryer_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("freeze_dryer_defaults2", {}))
    v = {**d, **value}
    util_list = list(state.get("heat_utility", {}).keys())
    advanced = [
        _num("steam_specific_amount", "Steam kg / Evap kg", v.get("steam_specific_amount", 0)),
        _num("specific_power", "kW / shelf m2", v.get("specific_power", 0.3)),
        _num("max_area_per_vessel", "Vessel 당 max shelf 넓이 [m2]", v.get("max_area_per_vessel", 0)),
        _num("_SHELF_PACKING_FACTOR", "Vessel 내 tray 집적도", v.get("_SHELF_PACKING_FACTOR", 0)),
        _num("_SAMPLE_PACKING_FACTOR", "Tray 내 Sample 집적도 (m2/m2)", v.get("_SAMPLE_PACKING_FACTOR", 0.7)),
        _sel("heat_id", "Heat source", util_list, v.get("heat_id")),
        _sel("wastewater_id", "폐기물 종류", util_list, v.get("wastewater_id")),
    ]
    main = [
        _num("target_final_moisture_content", "최종 수분 농도 (%)", v.get("target_final_moisture_content", 0)),
        _num("sample_thickness", "샘플 두께 [m]", v.get("sample_thickness", 0)),
        _num("tau_loading", "setup 시간 [h]", v.get("tau_loading", 0)),
        _num("tau_sublimation", "건조 시간 [h]", v.get("tau_sublimation", 0)),
        _num("tau_etc", "그 외 시간 [h]", v.get("tau_etc", 0)),
        _num("P", "Pressure [Pa]", v.get("P", 0)),
    ]
    return [_group("고급 설정", advanced, advanced=True), _group("옵션", main)]


def process_freeze_dryer_data2(state, submitted_widget_data: dict):
    return submitted_widget_data.copy()


def _centrifuge_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("centrifuge_defaults", {}))
    if "split" not in d or not d["split"]:
        d["split"] = {i: 0.2 for i in state.chemical_list}
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    sep_cols = [
        {"name": "물질", "type": "select", "options": chem_list},
        {"name": "Rate In Solids", "type": "number"},
    ]
    advanced = [_num("base_kW", "기본 전력 소비 (kW)", v.get("base_kW", 0))]
    main = [
        _table("_separation_df", "분리 효율 (0-1)", sep_cols, _rows(v, "split", ["물질", "Rate In Solids"])),
        _sel("Product", "주요 제품상", ["Liquid", "Solid"], v.get("Product", "Liquid")),
    ]
    return [_group("고급 설정", advanced, advanced=True), _group("분리 효율", main)]


def process_centrifuge_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    separation_df = processed_values.pop("_separation_df", None)
    processed_values["split"] = _df_to_dict(separation_df, "Rate In Solids")
    return processed_values


def _sol_processor_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("sol_processor_default", {}))
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    util_list = list(state.get("heat_utility", {}).keys())
    advanced = [
        _num("kW_per_m3", "Agitator kW [kW/m3]", v.get("kW_per_m3", 0.0985)),
        _num("V_wf", "Tank void factor", v.get("V_wf", 0.8)),
        _sel("wastewater_id", "Wastewater 종류", util_list, v.get("wastewater_id")),
    ]
    main = [
        _num("tau", "Mix 시간 [hr]", v.get("tau", 1)),
        _num("T", "온도 [C]", v.get("T", 0)),
        _num("sol_vol", "Feed 당 용액양 [L/L feed]", v.get("sol_vol", 0.2)),
        _table("_conc_sol_df", "Process 용액 농도 [g/L]", _conc_cols(chem_list), _rows(v, "sol_conc", ["물질", "농도 [g/L]"])),
        _num("waste_vol", "Feed 당 Waste 양 [L/L feed]", v.get("waste_vol", 0.0)),
    ]
    return [_group("고급 설정", advanced, advanced=True), _group("옵션", main)]


def process_sol_processor_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    processed_values["conc_sol"] = fill_water3(_df_to_dict(processed_values.pop("_conc_sol_df", None), "농도 [g/L]"), 1)
    return processed_values


def _smb_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("smb_defaults", {}))
    v = {**d, **value}
    chem_list = state.get("chemical_list", [])
    util_list = list(state.get("heat_utility", {}).keys())
    v["binding_material"] = v.get("binding_material", state.main_product)
    cc = _conc_cols(chem_list)
    resin = [
        _sel("resin_id", "Resin 종류", util_list, v.get("resin_id")),
        _sel("binding_material", "Binding Chemical", chem_list, v.get("binding_material")),
        _num("binding_capacity", "Binding Capacity [g/hr binding_material / L resin]", v.get("binding_capacity", 2.0)),
        _int("N_columns", "Number of columns", v.get("N_columns", 8)),
        _num("flowrate_desorbent", "Desorbent flowrate [BV/hr]", v.get("flowrate_desorbent", 0.02)),
        _table("_conc_desorbent_df", "Process 용액 농도 [g/L]", cc, _rows(v, "conc_desorbent", ["물질", "농도 [g/L]"])),
        _num("flowrate_regenerant", "Regenerant flowrate [BV/hr]", v.get("flowrate_regenerant", 0)),
        _table("_conc_regenerant_df", "Regenerant 농도 [g/L]", cc, _rows(v, "conc_regenerant", ["물질", "농도 [g/L]"])),
        _num("volume_product", "Product flowrate / Feed flowrate []", v.get("volume_product", 0)),
        _table("_conc_product_df", "product 농도 [g/L]", cc, _rows(v, "conc_product", ["물질", "농도 [g/L]"])),
    ]
    return [_group("고급 설정", _chromatography_advanced(v, util_list, "SMB", 0), advanced=True),
            _group("레진 정보", resin)]


def process_smb_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    _conc_proc(processed_values, "conc_desorbent", "conc_regenerant", "conc_product")
    resin_id = processed_values.get("resin_id")
    if resin_id and resin_id in state.get("heat_utility", {}):
        processed_values["resin_price"] = float(state["heat_utility"][resin_id])
    return processed_values


def _distillation_schema(state, value):
    d = copy.deepcopy(state.all_unit_defaults.get("distillation_defaults", {}))
    v = {**d, **value}
    v["product_idx"] = v.get("product_idx", 0)
    v["wastewater_id"] = v.get("wastewater_id", "wastewater")
    chem_list = state.get("chemical_list", [])
    util_list = list(state.get("heat_utility", {}).keys())
    advanced = [
        _num("P", "Pressure [Pa]", v.get("P", 101325)),
        _num("tray_efficiency", "Tray 효율 [%]", v.get("tray_efficiency", 80)),
        _num("tray_spacing", "Tray간 간격[m]", v.get("tray_spacing", 0.45)),
        _num("heat_transfer_efficiency", "Reboiler 효율 [%]", v.get("heat_transfer_efficiency", 100.0)),
        _num("condenser_efficiency", "Condenser 효율 [%]", v.get("condenser_efficiency", 100.0)),
        _sel("wastewater_id", "Wastewater 종류", util_list, v.get("wastewater_id")),
    ]
    # Merge split / alpha / H_vap into one table keyed '_distill_df'.
    split_df = _get_df_from_dict_list(v.get("split", {}), ["물질", "Distillate로 가는 비율[%]"])
    alpha_df = _get_df_from_dict_list(v.get("alpha", {}), ["물질", "Alpha"])
    hvap_df = _get_df_from_dict_list(v.get("H_vap", {}), ["물질", "Hvap [kJ/kg]"])
    merged = split_df.merge(alpha_df, on="물질", how="outer").merge(hvap_df, on="물질", how="outer")
    distill_cols = [
        {"name": "물질", "type": "select", "options": chem_list},
        {"name": "Distillate로 가는 비율[%]", "type": "number"},
        {"name": "Alpha", "type": "number"},
        {"name": "Hvap [kJ/kg]", "type": "number"},
    ]
    main = [
        _sel("product_phase", "Product phase", ["Distillate", "Bottoms"], v.get("product_phase", "Distillate")),
        _num("k", "R/Rmin", v.get("k", 1.2)),
        _table("_distill_df", "Distillate 정보", distill_cols, merged.astype(object).where(pd.notna(merged), None).to_dict("records")),
        _num("T_reboiler", "Reboiler 온도 [C]", v.get("T_reboiler", 200.0)),
        _num("T_condenser", "Condenser 온도 [C]", v.get("T_condenser", 150.0)),
        _num("vap_velocity", "Vapor velocity [m/s]", v.get("vap_velocity", 3.0)),
    ]
    return [_group("고급 설정", advanced, advanced=True), _group("옵션", main)]


def process_distillation_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    separation_df = processed_values.pop("_distill_df", None)
    processed_values["split"] = _df_to_dict(separation_df, "Distillate로 가는 비율[%]")
    processed_values["alpha"] = _df_to_dict(separation_df, "Alpha")
    processed_values["H_vap"] = _df_to_dict(separation_df, "Hvap [kJ/kg]")
    return processed_values


def _generic_schema(state, value):
    chem_list = state.get("chemical_list", [])
    fields = []
    for attr, val in list(value.items()):
        if attr in ["Concentration [g/L]", "Rate In Solid"]:
            col2 = "농도 [g/L]" if attr == "Concentration [g/L]" else "Rate In Solid"
            cols = [{"name": "물질", "type": "select", "options": chem_list}, {"name": col2, "type": "number"}]
            fields.append(_table(f"_{attr}_df", attr, cols, _rows(value, attr, ["물질", col2])))
        elif attr in ["Target", "Product", "Waste type", "chemical"]:
            options = chem_list if attr == "Target" else \
                ["Liquid", "Solid"] if attr == "Product" else \
                ["Liquid", "Solid", "Gas"] if attr == "Waste type" else chem_list
            fields.append(_sel(attr, attr, options, val))
        elif isinstance(val, bool):
            fields.append({"kind": "bool", "key": attr, "label": attr, "value": val})
        elif isinstance(val, (int, float)):
            fields.append(_num(attr, attr, val))
        elif isinstance(val, dict):
            sub = []
            for sk, sv in val.items():
                if isinstance(sv, (int, float)):
                    sub.append(_num(f"{attr}.{sk}", f"{sk} ({attr})", sv))
                else:
                    sub.append(_txt(f"{attr}.{sk}", f"{sk} ({attr})", sv))
            fields.append(_group(f"Nested: {attr}", sub, advanced=True))
        else:
            fields.append(_txt(attr, attr, val))
    # Wrap loose fields in a single group; nested groups already have shape.
    flat = [f for f in fields if "kind" in f]
    groups = [g for g in fields if "fields" in g]
    out = []
    if flat:
        out.append(_group("옵션", flat))
    out.extend(groups)
    return out


def process_generic_data(state, submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    for attr, value in list(processed_values.items()):
        if attr.startswith("_") and attr.endswith("_df"):
            original_attr = attr[1:-3]
            if isinstance(value, pd.DataFrame):
                processed_values[original_attr] = dict(zip(value["물질"], value[original_attr]))
            processed_values.pop(attr)
        elif "." in attr:  # nested dict field flattened by the generic schema
            parent, child = attr.split(".", 1)
            processed_values.setdefault(parent, {})
            if isinstance(processed_values[parent], dict):
                processed_values[parent][child] = value
            processed_values.pop(attr)
    return processed_values


# ===========================================================================
# Central dispatchers
# ===========================================================================

# node_type -> (schema_builder, data_processor)
_NODE_FUNCS = {
    "발효기": (_fermenter_schema, process_fermenter_data),
    "증발기": (_mvr_schema, process_MVR_data),
    "MVR": (_mvr_schema, process_MVR_data),
    "HIC column": (_hic_schema, process_HIC_data),
    "IEX column": (_iex_schema, process_IEX_data),
    "DiaFiltration": (_diafiltration_schema, process_diafiltration_data),
    "원심분리기": (_centrifuge_schema, process_centrifuge_data),
    "gel_filtration": (_gel_filtration_schema, process_gel_filtration_data),
    "동결건조기": (_freeze_dryer_schema, process_freeze_dryer_data2),
    "용액처리기": (_sol_processor_schema, process_sol_processor_data),
    "SMB_Chromatography": (_smb_schema, process_smb_data),
    "Distillation": (_distillation_schema, process_distillation_data),
}


def get_node_editor_functions(node_type: str):
    return _NODE_FUNCS.get(node_type, (_generic_schema, process_generic_data))


def build_node_schema(state, node: FlowNode):
    """Return a declarative form schema for ``node`` (replaces ``edit_node``)."""
    value = node.data.get("Value", {}) or {}
    builder, _ = get_node_editor_functions(node.data.get("node_type", "Default"))
    groups = builder(state, copy.deepcopy(value))
    return {
        "node_id": node.id,
        "node_type": node.data.get("node_type"),
        "name": node.data.get("custom_value", node.data.get("content", node.id)),
        "groups": groups,
    }


def _dataframe_ify(value: dict) -> dict:
    """Turn ``_*_df`` row-lists posted by the browser into DataFrames."""
    out = {}
    for k, v in value.items():
        if k.startswith("_") and k.endswith("_df") and isinstance(v, list):
            out[k] = pd.DataFrame(v)
        else:
            out[k] = v
    return out


def apply_node_edit(state, node: FlowNode, name: str, submitted_value: dict):
    """Process a submitted form and write the result back onto ``node``."""
    node_type = node.data.get("node_type", "Default")
    _, processor = get_node_editor_functions(node_type)
    value = _dataframe_ify(submitted_value)
    final_value = processor(state, value)
    node.data["content"] = name
    node.data["custom_value"] = name
    node.data["Value"] = final_value
    state.flow_state.timestamp = time.time()
    state.flow_state.flow_rev += 1
    state.flow_rev = state.flow_state.flow_rev
    return node
