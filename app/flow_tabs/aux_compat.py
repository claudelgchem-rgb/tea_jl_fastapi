"""Resolver, adapters and fallback shims for deployment-provided helpers.

The original Streamlit project imported helpers from ``aux_chemical`` (``fill_water3``,
``process_chemical_data``, ``upload_chemical2``) and custom unit operations from
``Biosteam_custom_unit``.

This module is the **single source of truth** for those symbols.  It:

1. makes the real ``aux_chemical`` importable in a headless (non-Streamlit)
   process by stubbing its hard ``streamlit`` / ``chempy`` imports when those
   packages are absent (so we do not drag Streamlit back into the FastAPI app);
2. resolves a real ``aux_chemical`` module from every plausible location and
   wraps its functions so the rest of the app keeps its existing data contract:

   * the real ``process_chemical_data(data)`` takes a *pandas DataFrame* and
     returns ``(chemicals, DataFrame)``; the app works with a *dict-of-columns*
     ``chem_data`` (``chem_data['Price (USD/kg)'][name]``), so the wrapper
     converts in both directions and guarantees a ``Water`` entry;
   * the real ``fill_water3(in_mass, vol)`` solves for the water mass that hits a
     target volume using a biosteam ``Stream`` (needs thermo configured);
3. resolves ``Biosteam_custom_unit`` and re-exports each custom unit class;
4. falls back to local shims for anything that cannot be resolved, and also
   falls back per-call if a real function raises.

Note: the real ``process_chemical_data2`` is intentionally *not* used — it
references an undefined ``_SIG_COLS`` and would raise.  The v1
``process_chemical_data`` is the headless-safe entry point.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Dict, Optional

import pandas as pd

_BASE_COLS = ["Name", "Formula", "Price (USD/kg)", "Phase"]


# ---------------------------------------------------------------------------
# Make a real (Streamlit-authored) aux_chemical importable headlessly
# ---------------------------------------------------------------------------

def _install_streamlit_stub() -> None:
    """Provide a no-op ``streamlit`` so modules that ``import streamlit`` load.

    Only installed when the real package is absent; decorators pass through and
    UI calls are no-ops, so non-UI helpers (process_chemical_data, fill_water3)
    run unchanged while the UI helpers simply do nothing.
    """
    try:
        import streamlit  # noqa: F401
        return
    except Exception:  # noqa: BLE001
        pass

    st = types.ModuleType("streamlit")

    def _decorator(*args, **kwargs):
        # supports both @st.fragment and @st.cache_resource(ttl=...)
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def wrap(fn):
            return fn

        return wrap

    st.fragment = _decorator
    st.cache_resource = _decorator
    st.cache_data = _decorator

    class _SessionState(dict):
        def __getattr__(self, k):
            try:
                return self[k]
            except KeyError as exc:
                raise AttributeError(k) from exc

        def __setattr__(self, k, v):
            self[k] = v

    st.session_state = _SessionState()
    for _fn in ("write", "button", "file_uploader", "data_editor", "rerun",
                "warning", "info", "error", "text_input", "number_input",
                "selectbox", "checkbox", "columns", "expander", "form",
                "form_submit_button", "divider", "subheader", "header"):
        setattr(st, _fn, lambda *a, **k: None)
    st.column_config = types.SimpleNamespace(
        TextColumn=lambda *a, **k: None, NumberColumn=lambda *a, **k: None,
        SelectboxColumn=lambda *a, **k: None, CheckboxColumn=lambda *a, **k: None,
    )
    sys.modules["streamlit"] = st


def _install_chempy_stub() -> None:
    """Provide a minimal ``chempy`` stub (only ``Substance`` is referenced)."""
    try:
        import chempy  # noqa: F401
        return
    except Exception:  # noqa: BLE001
        pass
    chempy = types.ModuleType("chempy")
    chempy.Substance = object
    sys.modules["chempy"] = chempy


_install_streamlit_stub()
_install_chempy_stub()


# ---------------------------------------------------------------------------
# Resolve real modules
# ---------------------------------------------------------------------------

_AUX_MODULES = (
    "app.flow_tabs.aux_chemical",
    "flow_tabs.aux_chemical",
    "aux_chemical",
    "pages.flow_tabs.aux_chemical",
)
_UNIT_MODULES = (
    "app.flow_tabs.Biosteam_custom_unit",
    "flow_tabs.Biosteam_custom_unit",
    "Biosteam_custom_unit",
    "pages.flow_tabs.Biosteam_custom_unit",
)


def _load_first(modnames):
    for name in modnames:
        try:
            return importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
    return None


_aux = _load_first(_AUX_MODULES)
_units = _load_first(_UNIT_MODULES)

REAL_AUX_MODULE: Optional[str] = getattr(_aux, "__name__", None)
REAL_UNIT_MODULE: Optional[str] = getattr(_units, "__name__", None)

_real_pcd = getattr(_aux, "process_chemical_data", None) if _aux is not None else None
_real_fill = getattr(_aux, "fill_water3", None) if _aux is not None else None


# ---------------------------------------------------------------------------
# Shim implementations (used when the real module / a real call is unavailable)
# ---------------------------------------------------------------------------

def _shim_fill_water3(composition: Dict[str, float], volume: float) -> Dict[str, float]:
    """Mass-balance fallback: top up ``Water`` to reach ``volume`` (1 kg/L)."""
    comp = {k: float(v) for k, v in composition.items() if k}
    non_water = sum(mass for chem, mass in comp.items() if chem != "Water")
    comp["Water"] = max(0.0, float(volume) * 1000.0 - non_water)
    return comp


def _shim_process_chemical_data(chem_data):
    """Build thermosteam chemicals + set thermo (or ID-only stand-ins)."""
    chem_data = _to_dict_columns(chem_data)
    price_col = chem_data.get("Price (USD/kg)", {})
    formula_col = chem_data.get("Formula", {})
    phase_col = chem_data.get("Phase", {})
    ids = list(price_col.keys())
    try:
        import thermosteam as tmo
    except Exception:  # noqa: BLE001
        class _Chem:
            def __init__(self, cid):
                self.ID = cid

        return [_Chem(c) for c in ids], chem_data

    chemicals = []
    for cid in ids:
        phase = phase_col.get(cid, "l") or "l"
        formula = formula_col.get(cid) or None
        try:
            chem = tmo.Chemical(cid)
        except Exception:  # noqa: BLE001
            try:
                chem = tmo.Chemical(cid, search_db=False, default=True, phase=phase,
                                    formula=formula, MW=1.0 if not formula else None)
                chem.at_state(phase=phase)
            except Exception:  # noqa: BLE001
                chem = tmo.Chemical(cid, search_db=False, default=True, phase=phase, MW=1.0)
        chemicals.append(chem)
    mix = tmo.Chemicals(chemicals)
    try:
        mix.compile()
    except Exception:  # noqa: BLE001
        pass
    tmo.settings.set_thermo(mix)
    return list(mix), chem_data


class _MissingUnit:
    """Placeholder custom unit op; calling it raises a clear error."""

    def __init__(self, name):
        self._name = name

    def __call__(self, *args, **kwargs):
        raise RuntimeError(
            f"Custom unit operation '{self._name}' is not available: provide a "
            "'Biosteam_custom_unit' module (drop it in app/flow_tabs/, the repo "
            "root, flow_tabs/, or pages/flow_tabs/) to run a calculation."
        )


# ---------------------------------------------------------------------------
# Data-shape adapters (DataFrame <-> dict-of-columns)
# ---------------------------------------------------------------------------

def _to_dict_columns(table):
    """Normalise a chemical table to dict-of-columns: ``{col: {name: value}}``."""
    if isinstance(table, pd.DataFrame):
        df = table
        if "Name" in df.columns:
            df = df.set_index("Name", drop=False)
        return {c: df[c].to_dict() for c in df.columns}
    if isinstance(table, dict):
        return table
    if isinstance(table, list):  # list of row-dicts
        df = pd.DataFrame(table)
        if "Name" in df.columns:
            df = df.set_index("Name", drop=False)
        return {c: df[c].to_dict() for c in df.columns}
    return dict(table)


def _to_dataframe(table) -> pd.DataFrame:
    """Normalise a chemical table to a DataFrame with the base columns present."""
    if isinstance(table, pd.DataFrame):
        df = table.copy()
    elif isinstance(table, dict):
        df = pd.DataFrame(table)
    elif isinstance(table, list):
        df = pd.DataFrame(table)
    else:
        df = pd.DataFrame(table)
    if "Name" not in df.columns:
        df.insert(0, "Name", list(df.index))
    for col in _BASE_COLS:
        if col not in df.columns:
            df[col] = "" if col in ("Formula", "Phase", "Name") else 0.0
    df = df.reset_index(drop=True)
    return df


def _water_price(df: pd.DataFrame) -> float:
    try:
        row = df[df["Name"] == "Water"]
        if len(row):
            return float(row.iloc[0]["Price (USD/kg)"])
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _ensure_water(chem_data: dict, price: float) -> None:
    chem_data.setdefault("Name", {}).setdefault("Water", "Water")
    chem_data.setdefault("Formula", {}).setdefault("Water", "H2O")
    chem_data.setdefault("Phase", {}).setdefault("Water", "l")
    chem_data.setdefault("Price (USD/kg)", {}).setdefault("Water", float(price))


# ---------------------------------------------------------------------------
# Public bindings
# ---------------------------------------------------------------------------

def process_chemical_data(table):
    """Build chemicals from a chemical table, preferring the real aux_chemical.

    Accepts a DataFrame, a dict-of-columns or a list of row-dicts.  Returns
    ``(chemicals, chem_data)`` where ``chem_data`` is always a dict-of-columns
    (so ``chem_data['Price (USD/kg)'][name]`` works) and always contains
    ``Water``.  Falls back to the shim if the real function is absent or raises.
    """
    if callable(_real_pcd):
        try:
            df = _to_dataframe(table)
            wprice = _water_price(df)
            # The real v1 prepends its own 'Water'; drop incoming Water rows and
            # de-duplicate so we never build duplicate chemicals.
            df = df[df["Name"] != "Water"].drop_duplicates(subset=["Name"]).reset_index(drop=True)
            chemicals, processed = _real_pcd(df)
            chem_data = processed.to_dict() if isinstance(processed, pd.DataFrame) else _to_dict_columns(processed)
            _ensure_water(chem_data, wprice)
            return chemicals, chem_data
        except Exception:  # noqa: BLE001 - fall back to the shim
            pass
    return _shim_process_chemical_data(table)


def fill_water3(in_mass, vol):
    """Fill water to a target volume, preferring the real aux_chemical.

    The real implementation needs a configured thermo (set up by
    ``process_chemical_data``); on any failure it falls back to the mass-balance
    shim.  A copy of ``in_mass`` is passed because the real function mutates it.
    """
    if callable(_real_fill):
        try:
            return _real_fill(dict(in_mass), vol)
        except Exception:  # noqa: BLE001
            pass
    return _shim_fill_water3(in_mass, vol)


# ``upload_chemical2`` was a Streamlit fragment; the FastAPI port handles
# chemical registration via /api/chemicals, so it is only re-exported if present.
upload_chemical2 = getattr(_aux, "upload_chemical2", None)

# Custom unit operations referenced by util_biosteam.
_UNIT_NAMES = (
    "BatchHeatExchanger", "CustomSplitter", "Custom_fermenter3", "MVR",
    "FreezeDryer2", "HIC_Column", "IEX_Column", "Diafiltration",
    "gel_filtration", "SMB_Column", "sol_processor", "custom_distillation",
)
for _uname in _UNIT_NAMES:
    _impl = getattr(_units, _uname, None) if _units is not None else None
    globals()[_uname] = _impl if _impl is not None else _MissingUnit(_uname)
