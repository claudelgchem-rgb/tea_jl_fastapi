"""Calculation pipeline + techno-economic cost analysis.

Port of the ``Calculate`` block of the original ``main_app.py`` (the biosteam
run, scale-up, and the OPEX/CAPEX dataframe build).  Instead of rendering
Streamlit dataframes/charts it returns plain JSON-serialisable structures that
the browser renders into tables and a flow diagram.
"""

from __future__ import annotations

import math
from typing import Any, Dict

import numpy as np
import pandas as pd

from .flow_tabs import util_biosteam as ub

lang_factor = 3.14285714285


def _records(df: pd.DataFrame) -> list:
    """JSON-safe ``DataFrame`` -> list-of-row-dicts (index columns included)."""
    df = df.reset_index()
    df = df.replace({np.nan: None})
    out = []
    for row in df.to_dict("records"):
        clean = {}
        for k, val in row.items():
            key = " / ".join(str(x) for x in k) if isinstance(k, tuple) else str(k)
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                val = None
            clean[key] = val
        out.append(clean)
    return out


def run_calculation(state) -> Dict[str, Any]:
    """Run the full simulation + cost analysis for the current session state."""
    state.messages = []

    # --- Assemble nodes/edges dicts from the flow state (main_app lines 393-409)
    nodes: Dict[str, Any] = {}
    edges: Dict[str, list] = {}
    for n in state.flow_state.nodes:
        nodes[n.id] = n.data
        if "custom_value" in n.data:
            nodes[n.id]["content"] = n.data["custom_value"]
    for e in state.flow_state.edges:
        edges.setdefault(e.source, []).append(e.target)

    ub._require_biosteam()
    bst = ub.bst
    bst.main_flowsheet.clear()

    # Electricity price (set at the '다음' step in the original UI).
    try:
        bst.PowerUtility.price = float(state.tmp.get("electricity_price", state.get("electricity_price", 0.128)))
    except Exception:  # noqa: BLE001
        pass

    batch_time = ub.get_batch_time(nodes)
    solutions = [state.autoclave, state.solutions, state.prices]
    ferm_sys = ub.run_biosteam2(state, nodes, edges, solutions=solutions, batch_time=batch_time, feat_data={})

    target_amount = float(state.target_amount) * 1000
    scaled_system = ub.scale_up_system(state, ferm_sys, state.main_product, target_amount, nodes)
    scaled_system = ub.price_system(state, scaled_system)
    scaled_system.simulate()
    state.scaled_system = scaled_system

    diagram = ""
    try:
        diagram = scaled_system.diagram(display=False)
    except Exception:  # noqa: BLE001
        diagram = ""

    result = _analyze_costs(state, scaled_system, target_amount, batch_time)
    result["diagram"] = diagram
    result["batch_time"] = batch_time
    result["messages"] = list(state.get("messages", []))
    return result


def _analyze_costs(state, scaled_system, target_amount, batch_time) -> Dict[str, Any]:
    """Build the OPEX/CAPEX tables (main_app lines 431-575)."""
    bst = ub.bst

    total_feed_amount = ub.get_chem_price(state, scaled_system.ins)
    upstream_amount, upstream_c_amount = ub.get_c_source(
        total_feed_amount, source=["Glucose", "Glycerol", "Methanol", state.main_source]
    )
    downstream_amount: Dict[str, Any] = {}

    etc = {"": [None, None]}

    capex_cost = scaled_system.installed_cost * lang_factor * 1.15
    currency = float(state.get("currency", 1) or 1)
    if currency > 1:
        labor_cost = 1440000000 / target_amount / currency
    else:
        labor_cost = 1440000000 / target_amount
    if state.get("gmp", True):
        capex_cost *= 5

    depreciation_cost = capex_cost * 0.082 / target_amount
    repair_cost = capex_cost * 0.05 / target_amount

    pd_up_c_feed = ub.chem_dict_to_pd(state, upstream_c_amount, target_amount)
    pd_up_feed = ub.chem_dict_to_pd(state, upstream_amount, target_amount)
    pd_down_feed = ub.chem_dict_to_pd(state, downstream_amount, target_amount)

    operating_hours = float(state.operating_hours)
    utility = {
        "전기": [
            scaled_system.power_utility.power * operating_hours / target_amount,
            bst.PowerUtility.price,
            scaled_system.power_utility.cost * operating_hours / target_amount * 1000,
        ]
    }
    for hu in scaled_system.heat_utilities:
        if hu.flow > 0:
            if hu.ID in ["low_pressure_steam", "medium_pressure_steam", "wastewater", "sludge",
                         "solid_waste", "chilled_water", "cooling_water", "natural_gas"]:
                utility[hu.agent.ID] = [
                    hu.flow * operating_hours / target_amount,
                    hu.cost / hu.flow,
                    hu.cost * operating_hours / target_amount * 1000,
                ]
            elif hu.ID == "cip_water":
                pd_up_feed["원단위"]["Water"] += hu.flow * operating_hours / target_amount
                pd_up_feed["제조원가"]["Water"] += hu.flow * float(state.chem_data["Price (USD/kg)"]["Water"]) * operating_hours / target_amount * 1000
            else:
                pd_up_feed.loc[hu.agent.ID] = [
                    hu.flow * operating_hours / target_amount,
                    hu.cost / hu.flow,
                    hu.cost * operating_hours / target_amount * 1000,
                ]

    pd_util = pd.DataFrame.from_dict(utility, orient="index", columns=["원단위", "단가", "제조원가"])
    pd_etc = pd.DataFrame.from_dict(etc, orient="index", columns=["원단위", "제조원가"])
    merged_opex_pd = pd.concat(
        [pd_up_c_feed, pd_up_feed, pd_down_feed, pd_util], axis=0,
        keys=["발효 원재료", "발효 부재료", "정제 재료", "유틸리티"],
    )

    capex_pd = pd.DataFrame.from_dict(
        {"감가비": [depreciation_cost, depreciation_cost * 1000],
         "인건비": [labor_cost, labor_cost * 1000],
         "수선비": [repair_cost, repair_cost * 1000],
         "기타": [0, 0]},
        orient="index", columns=["원단위", "제조원가"],
    )
    capex_pd["재료"] = ""
    capex_pd = capex_pd.set_index("재료", append=True)

    merge_price_df = pd.concat([merged_opex_pd, capex_pd], axis=0, keys=["변동비", "고정비"]) * currency
    merge_price_df["원단위"] = merge_price_df["원단위"] / currency
    total_sum = float(np.nansum(merge_price_df["제조원가"]))
    merge_price_df["비중"] = merge_price_df["제조원가"] / np.nansum(merge_price_df["제조원가"])

    # Average (rolled-up) table grouped by category (index level 1).
    avt_tmp = merge_price_df.groupby(level=1).sum()
    output_index = merge_price_df.index.droplevel(level=2).drop_duplicates()
    avg_price_df = pd.DataFrame(index=output_index, columns=merge_price_df.columns, dtype=float)
    for col in merge_price_df.columns:
        avg_price_df[col] = avg_price_df.index.get_level_values(level=1).map(avt_tmp[col])

    # Summary block.
    sum_price = {
        "Capex": float(capex_cost * currency),
        "Capacity [MT]": target_amount / 1000,
        f"{state.main_source} 단가 [/MT]": float(state.chem_data["Price (USD/kg)"][state.main_source]) * 1000 * currency,
        "제조 원가 [/MT]": float(list(avg_price_df.sum(axis=0))[2]),
    }

    avg_price_df = avg_price_df.drop(columns=["단가"])

    # Installed-cost detail (for the 감가비 drill-down).
    installed_cost = {i.ID: float(i.installed_cost) for i in scaled_system.units if i.installed_cost > 0}

    return {
        "currency": currency,
        "total_manufacturing_cost": total_sum,
        "summary": sum_price,
        "detail_rows": _records(merge_price_df),
        "avg_rows": _records(avg_price_df),
        "installed_cost": installed_cost,
    }
