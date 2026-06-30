"""Built-in default configuration.

The original Streamlit app loaded ``initial_val.json`` and scenario ``*.pkl``
files from a deployment path (``/home/sbf/JLee/test/data/...``).  Those files
are not part of this repository.  To keep the converted FastAPI app runnable
out of the box, this module provides a coherent default set with the same
shape the code expects: ``all_unit_defaults`` (node features/styles + per-unit
defaults + ``tmp`` + ``heat_utility``) and a starter chemical table.

If a real ``initial_val.json`` is present in the data directory it takes
precedence (see ``data.load_all_unit_defaults``).
"""

from __future__ import annotations

import copy
from typing import Any, Dict


# --- Per-unit default parameter dicts (merged into each node's ``Value``) ----

FERMENTER_DEFAULT = {
    "P": 101325.0, "V_wf": 0.8, "V_max": 250.0, "tau": 48.0, "tau_add": 0.0,
    "tau_cool": 0.0, "tau_sip": 1.0, "tau_cip": 2.0, "sip_stream_rate": 10.0,
    "agitation_efficiency": 0.8, "P_drop": 0.0, "compressor_isentropic_efficiency": 0.7,
    "motor_efficiency": 0.9, "chill_to_cool_ratio": 0.5, "T": 30.0, "vvm": 1.0,
    "init_OD": 1.0, "final_OD": 100.0, "initial_vol": 1.0, "feed_vol": 0.0,
    "final_vol": 1.0, "initial_conc": {}, "feed_conc": {}, "final_conc": {},
    "Main reactant": "Glucose", "stream_flow": {}, "in_mass": {}, "out_mass": {},
}

MVR_DEFAULT = {
    "U_overall": 1.0, "motor_efficiency": 0.9, "compressor_isentropic_efficiency": 0.7,
    "pump_efficiency": 0.7, "pump_head": 10.0, "P_drop": 0.0, "chemical": "Water",
    "T": 60.0, "V": 40.0,
}

_CHROM_COMMON = {
    "column_price": 7000.0, "P_drop": 0.0, "motor_efficiency": 0.9,
    "compressor_isentropic_efficiency": 0.7, "pump_efficiency": 0.7,
    "wastewater_id": "wastewater", "resin_id": "resin", "resin_price": 0.0,
    "binding_capacity": 20.0, "resin_lifetime_cycle": 100.0,
}

HIC_DEFAULT = dict(_CHROM_COMMON, tau_loading=2.0, flowrate_wash=2.0, tau_wash=1.0,
                   conc_wash={}, flowrate_equilibrate=2.0, tau_equilibrate=1.0, conc_equilibrate={},
                   flowrate_elute=2.0, tau_elute=1.0, conc_elute={}, flowrate_rinse=2.0,
                   tau_rinse=1.0, conc_rinse={}, flowrate_regenerate=2.0, tau_regenerate=1.0,
                   conc_regenerate={}, volume_product=1.0, conc_product={})

IEX_DEFAULT = dict(_CHROM_COMMON, tau_loading=2.0, flowrate_wash1=2.0, tau_wash1=1.0,
                   conc_wash1={}, flowrate_wash2=2.0, tau_wash2=1.0, conc_wash2={},
                   flowrate_elute=2.0, tau_elute=1.0, conc_elute={}, flowrate_regenerate=2.0,
                   tau_regenerate=1.0, conc_regenerate={}, volume_product=1.0, conc_product={})

GEL_FILTRATION_DEFAULT = dict(_CHROM_COMMON, tau_loading=2.0, flowrate_wash=2.0, tau_wash=1.0,
                              conc_wash={}, flowrate_equilibrate=2.0, tau_equilibrate=1.0,
                              conc_equilibrate={}, flowrate_elute=2.0, tau_elute=1.0,
                              conc_elute={}, volume_product=1.0, conc_product={})

SMB_DEFAULT = dict(_CHROM_COMMON, binding_capacity=2.0, N_columns=8, flowrate_desorbent=0.02,
                   conc_desorbent={}, flowrate_regenerant=0.0, conc_regenerant={},
                   volume_product=0.0, conc_product={})

DIAFILTRATION_DEFAULT = {
    "tau_cip": 1.0, "cip_flowrate": 2.0, "n_cip": 1, "cip_id": "cip_water",
    "wastewater_id": "wastewater", "membrane_id": "membrane", "membrane_cost": 0.0,
    "membrane_life": 8000.0, "tau": 2.0, "split": {}, "separation": {},
}

CENTRIFUGE_DEFAULT = {"base_kW": 0.0, "split": {}, "Product": "Solid"}

FREEZE_DRYER_DEFAULT2 = {
    "steam_specific_amount": 1.5, "specific_power": 0.3, "max_area_per_vessel": 30.0,
    "_SHELF_PACKING_FACTOR": 0.7, "_SAMPLE_PACKING_FACTOR": 0.7, "heat_id": "low_pressure_steam",
    "wastewater_id": "wastewater", "target_final_moisture_content": 5.0,
    "sample_thickness": 0.01, "tau_loading": 2.0, "tau_sublimation": 24.0, "tau_etc": 2.0,
    "P": 50.0,
}

SOL_PROCESSOR_DEFAULT = {
    "kW_per_m3": 0.0985, "V_wf": 0.8, "wastewater_id": "wastewater", "tau": 1.0,
    "T": 25.0, "sol_vol": 0.2, "sol_conc": {}, "waste_vol": 0.0,
}

DISTILLATION_DEFAULT = {
    "P": 101325.0, "tray_efficiency": 80.0, "tray_spacing": 0.45,
    "heat_transfer_efficiency": 100.0, "condenser_efficiency": 100.0,
    "wastewater_id": "wastewater", "product_idx": 0, "product_phase": "Distillate",
    "k": 1.2, "split": {}, "alpha": {}, "H_vap": {}, "T_reboiler": 200.0,
    "T_condenser": 150.0, "vap_velocity": 3.0,
}

# --- Node features: the initial ``Value`` for each addable node type ----------

NODE_FEATURES: Dict[str, Dict[str, Any]] = {
    "발효기": copy.deepcopy(FERMENTER_DEFAULT),
    "발효/정제 분리선": {},
    "Product Stream": {},
    "연속 피드": {"Concentration [g/L]": {}, "Flow [L/hr]": 0.0},
    "배치 피드": {"Concentration [g/L]": {}, "Flow [L/hr]": 0.0},
    "폐기물": {},
    "믹싱 탱크": {},
    "원심분리기": copy.deepcopy(CENTRIFUGE_DEFAULT),
    "증발기": copy.deepcopy(MVR_DEFAULT),
    "MVR": copy.deepcopy(MVR_DEFAULT),
    "동결건조기": copy.deepcopy(FREEZE_DRYER_DEFAULT2),
    "HIC column": copy.deepcopy(HIC_DEFAULT),
    "IEX column": copy.deepcopy(IEX_DEFAULT),
    "DiaFiltration": copy.deepcopy(DIAFILTRATION_DEFAULT),
    "gel_filtration": copy.deepcopy(GEL_FILTRATION_DEFAULT),
    "SMB_Chromatography": copy.deepcopy(SMB_DEFAULT),
    "용액처리기": copy.deepcopy(SOL_PROCESSOR_DEFAULT),
    "Distillation": copy.deepcopy(DISTILLATION_DEFAULT),
}

NODE_STYLE: Dict[str, Any] = {
    "highlight": {"backgroundColor": "#ffffff", "color": "black"},
}

TMP_DEFAULT = {
    "product_index": 5,
    "source_index": 1,
    "target_amount": 0.1,
    "operating_hours": 7920,
    "od_to_dcw": 0.22,
    "currency": 1500,
    "electricity_price": 0.128,
}

HEAT_UTILITY_DEFAULT = {
    "low_pressure_steam": 0.0118,
    "medium_pressure_steam": 0.0146,
    "cooling_water": 0.00045,
    "chilled_water": 0.005,
    "wastewater": 0.003,
    "cip_water": 0.001,
    "resin": 200.0,
    "membrane": 1000.0,
    "hepa_filter": 50.0,
}


def all_unit_defaults() -> Dict[str, Any]:
    return {
        "node_features": copy.deepcopy(NODE_FEATURES),
        "node_style": copy.deepcopy(NODE_STYLE),
        "fermenter_default": copy.deepcopy(FERMENTER_DEFAULT),
        "mvr_default": copy.deepcopy(MVR_DEFAULT),
        "hic_default": copy.deepcopy(HIC_DEFAULT),
        "iex_default": copy.deepcopy(IEX_DEFAULT),
        "gel_filtration_default": copy.deepcopy(GEL_FILTRATION_DEFAULT),
        "diafiltration_default": copy.deepcopy(DIAFILTRATION_DEFAULT),
        "centrifuge_defaults": copy.deepcopy(CENTRIFUGE_DEFAULT),
        "freeze_dryer_defaults2": copy.deepcopy(FREEZE_DRYER_DEFAULT2),
        "sol_processor_default": copy.deepcopy(SOL_PROCESSOR_DEFAULT),
        "smb_defaults": copy.deepcopy(SMB_DEFAULT),
        "distillation_defaults": copy.deepcopy(DISTILLATION_DEFAULT),
        "tmp": copy.deepcopy(TMP_DEFAULT),
        "heat_utility": copy.deepcopy(HEAT_UTILITY_DEFAULT),
    }


# --- Starter chemical table (``chem_data`` is a dict-of-columns) --------------

_STARTER_CHEMICALS = [
    # (Name, Formula, Price USD/kg, Phase)
    ("Water", "H2O", 0.0, "l"),
    ("Glucose", "C6H12O6", 0.45, "s"),
    ("Glycerol", "C3H8O3", 0.9, "l"),
    ("Methanol", "CH4O", 0.4, "l"),
    ("Biomass", "", 0.0, "s"),
    ("Collagen", "", 100.0, "s"),
    ("NaOH", "NaOH", 0.5, "s"),
    ("HCl", "ClH", 0.3, "l"),
]


def starter_chem_data() -> Dict[str, Dict[str, Any]]:
    cols = ["Name", "Formula", "Price (USD/kg)", "Phase"]
    data: Dict[str, Dict[str, Any]] = {c: {} for c in cols}
    for name, formula, price, phase in _STARTER_CHEMICALS:
        data["Name"][name] = name
        data["Formula"][name] = formula
        data["Price (USD/kg)"][name] = price
        data["Phase"][name] = phase
    return data
