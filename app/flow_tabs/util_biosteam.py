"""Biosteam simulation core (FastAPI port of ``util_biosteam_Copy1.py``).

This is a faithful port of the original module: the process-engineering logic
is unchanged.  The only differences are mechanical:

* ``st.session_state`` -> an explicit ``state`` argument (a ``SessionState``).
* ``st.write(...)`` diagnostics -> ``_log(state, ...)`` which appends to
  ``state.messages`` so the browser can show them.
* ``biosteam`` / ``thermosteam`` and the custom unit operations are imported
  lazily/defensively so the web app boots even when they are absent; a clear
  error is raised only when a calculation actually needs them.
"""

from __future__ import annotations

import json
import copy

# --- Heavy dependencies are imported LAZILY -------------------------------
# Importing biosteam/thermosteam costs ~20s of numba JIT warmup.  Doing it at
# module load makes the web app slow to start and can trip a hosting platform's
# startup window into a "connecting to backend" restart loop.  So we import it
# only when a calculation actually runs (see ``_ensure_biosteam``).
import importlib.util as _ilu

from . import aux_compat  # cheap: aux_compat resolves its heavy deps lazily too
from .aux_compat import fill_water3, process_chemical_data  # cheap function refs

bst = None  # populated by _ensure_biosteam()
tmo = None
BIOSTEAM_AVAILABLE = None  # None = not yet checked
IMPORT_ERROR = None  # traceback string when the import actually failed


def biosteam_installed() -> bool:
    """Light check (no import cost): is the package present on sys.path?"""
    try:
        return _ilu.find_spec("biosteam") is not None and _ilu.find_spec("thermosteam") is not None
    except Exception:  # noqa: BLE001
        return False


def biosteam_available() -> bool:
    """Authoritative check: can biosteam actually be imported?

    Runs the real import (cached) so the UI badge reflects reality instead of
    just "the package directory exists".  If the import raises, the reason is
    captured in ``IMPORT_ERROR`` so the frontend can show *why* it failed.
    """
    return _ensure_biosteam()


def _ensure_biosteam() -> bool:
    """Import biosteam/thermosteam on first use; cache the result."""
    global bst, tmo, BIOSTEAM_AVAILABLE, IMPORT_ERROR
    if BIOSTEAM_AVAILABLE is not None:
        return BIOSTEAM_AVAILABLE
    try:
        import biosteam as _b
        import thermosteam as _t
        try:
            _b.Stream.display_units.flow = "kg/hr"
        except Exception:  # noqa: BLE001
            pass
        bst, tmo, BIOSTEAM_AVAILABLE, IMPORT_ERROR = _b, _t, True, None
    except Exception:  # noqa: BLE001
        import traceback as _tb
        bst, tmo, BIOSTEAM_AVAILABLE = None, None, False
        IMPORT_ERROR = _tb.format_exc()
    return BIOSTEAM_AVAILABLE


def _log(state, *args):
    """Replacement for ``st.write`` diagnostics: collect messages on the state."""
    msg = " ".join(str(a) for a in args)
    if "messages" not in state:
        state.messages = []
    state.messages.append(msg)


def _require_biosteam():
    if not _ensure_biosteam():
        raise RuntimeError(
            "biosteam/thermosteam are not installed in this environment; "
            "the calculation pipeline cannot run. Install the process "
            "simulation dependencies to enable /api/calculate."
        )


def fast_copy(obj):
    if hasattr(obj, "asdict"):
        return obj.__class__.from_dict(json.loads(json.dumps(obj.asdict())))
    return json.loads(json.dumps(obj))


def session_state_to_spec_data(state, input_var, nodes):
    state.spec_data = {}
    for i, node in nodes.items():
        state.spec_data[i] = {"type": node["node_type"], "data": copy.deepcopy(input_var[node["node_type"]])}
        state.spec_data[i]["data"].update(add_spec_data(state, node))


def add_spec_data(state, node):
    unit_data = {}
    if node["node_type"] in ["연속 피드", "배치 피드"]:
        unit_data["T"] = float(node["Value"]["Temperature [C]"]) + 273.15
        unit_data["P"] = float(node["Value"]["Pressure (Pa)"])

    elif node["node_type"] == "발효기":
        unit_data["ferm_T"] = float(node["Value"]["Temperature [C]"]) + 273.15
        unit_data["tau"] = float(node["Value"]["Time [h]"])
        unit_data["init_OD"] = float(node["Value"]["init_OD"])
        unit_data["final_OD"] = float(node["Value"]["final_OD"])
        try:
            del unit_data["ID"]
        except Exception:
            pass

        try:
            unit_data["chemical"] = state.chemicals[node["Value"]["Solvent"]]
        except Exception:
            unit_data["chemical"] = tmo.Chemical("Water")

    return unit_data


def run_biosteam2(state, nodes, edges, solutions, feat_data, batch_time):
    """
    1. Create Solutions stream, tank and heat exchanger
    2. Create streams for fermenter
    3. Rescale fermeters based on OD
    4. Connect other units
    """
    _require_biosteam()
    # Resolve the custom unit operations lazily (first access imports them).
    BatchHeatExchanger = aux_compat.BatchHeatExchanger
    CustomSplitter = aux_compat.CustomSplitter
    Custom_fermenter3 = aux_compat.Custom_fermenter3
    MVR = aux_compat.MVR
    FreezeDryer2 = aux_compat.FreezeDryer2
    HIC_Column = aux_compat.HIC_Column
    IEX_Column = aux_compat.IEX_Column
    Diafiltration = aux_compat.Diafiltration
    gel_filtration = aux_compat.gel_filtration
    SMB_Column = aux_compat.SMB_Column
    sol_processor = aux_compat.sol_processor
    custom_distillation = aux_compat.custom_distillation

    bst.main_flowsheet.clear()
    Stream_data = {}
    Solution_data = {}
    Unit_data = {}
    chem_data = state.chem_data
    chem_mass = {}

    for hu, price in state.heat_utility.items():
        if hu not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(hu, regeneration_price=price, T=298, Water=1))
        bst.HeatUtility.get_agent(hu).regeneration_price = price

    # 1. Create solutions
    autoclave, solutions0, price_data = solutions

    sol_mass = {i: {} for i in solutions0}
    for i, sol in solutions0.items():
        solx = fill_water3(sol, 1)
        Solution_data[f"{i}_raw"] = bst.Stream(f"{i}_raw", units="kg/hr", T=298, P=101325, phase="l")
        for chem, mass in sol.items():
            Solution_data[f"{i}_raw"].imass[chem] = mass
        Solution_data[f"{i}_tank"] = bst.units.StorageTank(f"{i}_tank", ins=Solution_data[f"{i}_raw"], tau=batch_time, kW_per_m3=0)
        if autoclave[i]:
            Unit_data[f"{i}_heat_exchanger"] = BatchHeatExchanger(f"{i}_heat_exchanger", ins=Solution_data[f"{i}_tank"].outs[0], scale_factor=batch_time, T=Solution_data[f"{i}_tank"].outs[0].T)
            Solution_data[f"{i}_split"] = CustomSplitter(f"{i}_split", ins=Unit_data[f"{i}_heat_exchanger"].outs[0])
        else:
            Solution_data[f"{i}_split"] = CustomSplitter(f"{i}_split", ins=Solution_data[f"{i}_tank"].outs[0])

    # 2. Rescale fermenter (scale stream_flow before building fermenter units)
    dilution_units = []
    for edge_source, edge_target2 in edges.items():
        for edge_target in edge_target2:
            if nodes[edge_source]["node_type"] == "발효기" and nodes[edge_target]["node_type"] == "발효기":
                dilution_units.append([edge_source, edge_target])

    diff = len(dilution_units)
    iterx = 0
    while abs(diff) > 1e-5:
        diff = 0
        iterx += 1
        for edge_source, edge_target in dilution_units:
            final_prev_od_amount = nodes[edge_source]["Value"]["final_vol"] * nodes[edge_source]["Value"]["final_OD"]
            initial_post_od_amount = (nodes[edge_target]["Value"]["initial_vol"] + nodes[edge_source]["Value"]["final_vol"]) * nodes[edge_target]["Value"]["init_OD"]
            diff += abs(initial_post_od_amount / final_prev_od_amount - 1)
            scale_factor = nodes[edge_target]["Value"]["initial_vol"] * nodes[edge_target]["Value"]["init_OD"] / nodes[edge_source]["Value"]["final_vol"] / (nodes[edge_source]["Value"]["final_OD"] - nodes[edge_target]["Value"]["init_OD"])
            # scale down both in / out mass and volume
            nodes[edge_source]["Value"]["final_vol"] *= scale_factor
            nodes[edge_source]["Value"]["initial_vol"] *= scale_factor
            nodes[edge_source]["Value"]["feed_vol"] *= scale_factor
            for s in nodes[edge_source]["Value"]["stream_flow"]:
                for chem in nodes[edge_source]["Value"]["stream_flow"][s]:
                    nodes[edge_source]["Value"]["stream_flow"][s][chem] *= scale_factor
            for chem in nodes[edge_source]["Value"]["in_mass"]:
                nodes[edge_source]["Value"]["in_mass"][chem] *= scale_factor
                nodes[edge_source]["Value"]["out_mass"][chem] *= scale_factor
        if iterx == 100:
            diff = 0
            _log(state, "max reached")

    # 3. Make units
    for i, node in nodes.items():
        if node["node_type"] == "연속 피드":
            Stream_data[i] = bst.Stream(ID=node["content"], units="kg/hr", T=298, P=101325)
            for chem, flow in node["Value"]["Concentration [g/L]"].items():
                Stream_data[i].imass["l", chem] = float(flow) / 1000 * float(node["Value"]["Flow [L/hr]"])
                Stream_data[i].price += float(Stream_data[i].imass[chem]) * chem_data["Price (USD/kg)"][chem]
            Stream_data[i].price /= Stream_data[i].F_mass
        elif node["node_type"] == "폐기물":
            Stream_data[i] = bst.MultiStream(node["content"], units="kg/hr", T=298, P=101325, phases=["l", "s", "g"])
        elif node["node_type"] == "Product Stream":
            Stream_data[i] = bst.Stream(node["content"], units="kg/hr", T=298, P=101325)

        # Units
        elif node["node_type"] == "발효기":
            Unit_data[f"{i}_mixer"] = bst.units.Mixer(ID=f"{i}_mixer", ins=[])
            if i not in state.reactions:
                state.reactions[i] = ""
            Unit_data[i] = Custom_fermenter3(ID=node["content"], ins=[Unit_data[f"{i}_mixer"].outs[0]], **node["Value"])
            for s, chem_mass in node["Value"]["stream_flow"].items():
                sol_mass[s][i] = 0
                Solution_data[f"{i}_{s}_stream"] = bst.Stream(f"{i}_{s}", units="kg/hr", T=298, P=101325)
                Solution_data[f"{s}_split"].outs.append(Solution_data[f"{i}_{s}_stream"])
                for k in chem_mass:
                    sol_mass[s][i] += chem_mass[k]  # Add mass required

                Unit_data[f"{i}_mixer"].ins.append(Solution_data[f"{i}_{s}_stream"])

        elif node["node_type"] == "발효/정제 분리선":  # Blank unit to specify End of fermentation
            Unit_data[i] = bst.units.Mixer(ID="발효/정제 분리선", ins=[], outs=[])
        elif node["node_type"] == "증발기":
            Unit_data[i] = MVR(node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "동결건조기":
            Unit_data[i] = FreezeDryer2(node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "믹싱 탱크":
            Unit_data[i] = bst.units.MixTank(node["content"], ins=[])
        elif node["node_type"] == "원심분리기":
            Unit_data[i] = bst.units.SolidsCentrifuge(node["content"], split=node["Value"]["split"])
        elif node["node_type"] == "MVR":
            Unit_data[i] = MVR(ID=node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "HIC column":
            Unit_data[i] = HIC_Column(ID=node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "IEX column":
            Unit_data[i] = IEX_Column(ID=node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "DiaFiltration":
            Unit_data[i] = Diafiltration(ID=node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "gel_filtration":
            Unit_data[i] = gel_filtration(ID=node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "SMB_Chromatography":
            Unit_data[i] = SMB_Column(ID=node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "용액처리기":
            Unit_data[i] = sol_processor(ID=node["content"], ins=[], outs=[], **node["Value"])
        elif node["node_type"] == "Distillation":
            Unit_data[i] = custom_distillation(ID=node["content"], ins=[], outs=[], **node["Value"])

    for edge_source, edge_target2 in edges.items():
        for edge_target in edge_target2:
            if edge_source in Stream_data.keys():
                Unit_data[edge_target].ins.append(Stream_data[edge_source])
            elif nodes[edge_target]["node_type"] in ["Product Stream"]:
                if nodes[edge_source]["node_type"] in ["발효기", "동결건조기", "MVR", "증발기"]:
                    Unit_data[edge_source].outs[1] = Stream_data[edge_target]
                elif nodes[edge_source]["node_type"] in ["발효/정제 분리선", "믹싱 탱크", "Heater", "Mixer", "HIC column", "IEX column", "DiaFiltration", "gel_filtration", "용액처리기", "Distillation"]:
                    Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                elif nodes[edge_source]["node_type"] in ["원심분리기"]:
                    if nodes[edge_source]["Value"]["Product"] == "Solid":
                        Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                    else:
                        Unit_data[edge_source].outs[1] = Stream_data[edge_target]
                else:
                    _log(state, nodes[edge_source], nodes[edge_source]["node_type"], "Unknown type")
            elif nodes[edge_target]["node_type"] in ["폐기물"]:
                if nodes[edge_source]["node_type"] in ["동결건조기"]:
                    Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                elif nodes[edge_source]["node_type"] in ["원심분리기"]:
                    if nodes[edge_source]["Value"]["Product"] == "Solid":
                        Unit_data[edge_source].outs[1] = Stream_data[edge_target]
                    else:
                        Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                else:
                    _log(state, nodes[edge_source], nodes[edge_source]["node_type"], "waste goes to nowhere")

            # 2nd output from fermenter go to unit (1st is gas)
            elif nodes[edge_source]["node_type"] in ["발효기", "동결건조기", "MVR", "증발기"]:
                if nodes[edge_target]["node_type"] in ["Heater", "HIC column", "IEX column", "DiaFiltration", "gel_filtration", "SMB_Chromatography", "용액처리기", "Distillation"]:
                    Unit_data[edge_target].ins[0] = Unit_data[edge_source].outs[1]
                else:
                    Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[1])
            # 1st output from evaporator go to unit
            elif nodes[edge_source]["node_type"] in ["발효/정제 분리선", "믹싱 탱크", "Heater", "HIC column", "IEX column", "DiaFiltration", "gel_filtration", "SMB_Chromatography", "용액처리기", "Distillation"]:
                if nodes[edge_target]["node_type"] in ["Heater", "HIC column", "IEX column", "DiaFiltration", "gel_filtration", "SMB_Chromatography", "용액처리기", "Distillation"]:
                    Unit_data[edge_target].ins[0] = Unit_data[edge_source].outs[0]
                else:
                    Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[0])

            # Waste and product stream should have gone in previous line
            elif nodes[edge_source]["node_type"] in ["원심분리기"]:
                if nodes[edge_source]["Value"]["Product"] == "Solid":
                    if nodes[edge_target]["node_type"] in ["Heater", "MVR", "HIC column", "IEX column", "DiaFiltration", "gel_filtration", "SMB_Chromatography", "용액처리기", "Distillation"]:
                        Unit_data[edge_target].ins[0] = Unit_data[edge_source].outs[0]
                    else:
                        Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[0])
                else:
                    if nodes[edge_target]["node_type"] in ["Heater", "MVR", "HIC column", "IEX column", "DiaFiltration", "gel_filtration", "SMB_Chromatography", "용액처리기", "Distillation"]:
                        Unit_data[edge_target].ins[0] = Unit_data[edge_source].outs[1]
                    else:
                        Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[1])
            else:
                _log(state, nodes[edge_source], "leads to nowhere")

    # update solution data
    f_vol = 0
    for i in sol_mass:
        mass = 0
        tmp = []
        for s in sol_mass[i]:
            mass += sol_mass[i][s]
            tmp.append(sol_mass[i][s])
        if mass > 1e-6:
            Solution_data[f"{i}_raw"].F_mass = mass / batch_time
            Solution_data[f"{i}_raw"].price = price_data[i] * Solution_data[f"{i}_raw"].F_mass
            Solution_data[f"{i}_split"].split_ratio = tmp
            f_vol += mass / batch_time
        else:
            Solution_data[f"{i}_raw"].F_mass = mass / batch_time
            Solution_data[f"{i}_raw"].price = price_data[i] * Solution_data[f"{i}_raw"].F_mass
            Solution_data[f"{i}_split"].split_ratio = tmp

    ferm_sys = bst.main_flowsheet.create_system("ferm_sys")
    ferm_sys.simulate()
    ferm_sys.operating_hours = float(state.operating_hours)
    state.ferm_sys = ferm_sys
    for i in ferm_sys.units:
        if hasattr(i, "reactions"):
            state.reactions[i.ID[:-10]] = i.reactions
    return ferm_sys


def scale_up_system(state, ferm_sys, main_product, target_amount, nodes):
    _require_biosteam()
    # 1. Define product stream
    pid = [node["content"] for i, node in nodes.items() if node["node_type"] == "Product Stream"]
    product_stream = [bst.main_flowsheet.stream[i] for i in pid]
    # 2. Get target amount
    product_amount = sum([s.imass[state.main_product] * float(state.operating_hours) for s in product_stream])
    if product_amount == 0:
        product_amount = 0.00001
    scale_factor = target_amount / product_amount
    # 3. Scale every input
    for i in ferm_sys.ins:
        i.scale(scale_factor)
    _log(state, "scale factor", scale_factor)
    for unit in bst.main_flowsheet.unit:
        # Reset power (kW)
        unit.power_utility.empty()
    # Reset all heat utilities (Duty, Flow, Cost)
    for hu in unit.heat_utilities:
        hu.empty()

    ferm_sys.simulate()
    return ferm_sys


def get_upstream_feeds(state, ferm_system):
    target_unit = bst.main_flowsheet.unit["발효/정제 분리선"]
    strictly_upstream_units = set()
    visited_units_for_traversal = set()

    def _find_predecessors(current_unit):
        if current_unit.ID in visited_units_for_traversal:
            return
        visited_units_for_traversal.add(current_unit.ID)

        for s_in in current_unit.ins:
            if s_in.source:  # If the input stream comes from another unit
                source_unit = s_in.source
                strictly_upstream_units.add(source_unit)
                _find_predecessors(source_unit)

    for s_in_target in target_unit.ins:
        if s_in_target.source:
            _find_predecessors(s_in_target.source)

    external_feeds = set()
    for unit in strictly_upstream_units:
        for s_in in unit.ins:
            if s_in.source is None:  # It's a system input (no unit source)
                external_feeds.add(s_in)
            elif s_in.source not in strictly_upstream_units:
                external_feeds.add(s_in)

    stream_price = get_chem_price(state, external_feeds)
    upstream_price, upstream_c_price = get_c_source(stream_price, source=["Glucose", "Glycerol", "Methanol", state.main_source])

    return upstream_price, upstream_c_price, strictly_upstream_units


def get_chem_price(state, streams, chem=None, operating_hours=7820):
    if not chem:
        chem = state.chem_data
    chem_amount = {i: 0 for i in state.chemical_list}
    for s in streams:
        for c in chem_amount:
            chem_amount[c] += s.imass[c] * float(state.operating_hours)
    return chem_amount


def get_c_source(chem_data, source=("Glucose", "Glycerol", "Methanol")):
    c_stream = {}
    non_c_stream = {}
    for i, data in chem_data.items():
        if i in source:
            c_stream[i] = data
        else:
            non_c_stream[i] = data
    return non_c_stream, c_stream


def chem_dict_to_pd(state, chem, target_amount):
    import pandas as pd

    data = {i: {} for i in ["원단위", "단가", "제조원가"]}
    chem_data = state.chem_data
    for i, amount in chem.items():
        if amount != 0:
            data["원단위"][i] = amount / target_amount
            data["제조원가"][i] = amount * float(chem_data["Price (USD/kg)"][i]) / target_amount * 1000
            data["단가"][i] = chem_data["Price (USD/kg)"][i]

    data = pd.DataFrame(data)
    return data


def get_batch_time(nodes):
    batch_time = 0
    for i, node in nodes.items():
        batch_unit = 0
        for j in node["Value"].keys():
            if "tau" in j:
                batch_unit += node["Value"][j]
        if batch_unit >= batch_time:
            batch_time = batch_unit
    return batch_time


def price_system(state, ferm_sys):
    chem_data = state.chem_data
    for stream in ferm_sys.ins:
        stream.price = 0
        for chem in stream.chemicals:
            stream.price += stream.imass[chem.ID] * chem_data["Price (USD/kg)"][chem.ID]
    return ferm_sys
