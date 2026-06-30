"""Fallback shims for deployment-provided helpers.

The original Streamlit project imported a number of helpers from
``pages.flow_tabs.aux_chemical`` and a set of custom unit operations from
``pages.flow_tabs.Biosteam_custom_unit``.  Those modules were never part of
this repository -- they live in the deployment environment alongside the
``biosteam`` install and the scenario data files.

The ported FastAPI modules import the *real* modules when they are available
and fall back to the shims in this file otherwise, so the web UI can boot and
be developed without the full process-simulation stack.  When the genuine
modules are present they take precedence and these shims are never used.
"""

from __future__ import annotations

from typing import Dict


def fill_water3(composition: Dict[str, float], volume: float) -> Dict[str, float]:
    """Best-effort re-implementation of ``aux_chemical.fill_water3``.

    Ensures a ``Water`` entry exists and tops it up so the total mass matches
    ``volume`` (interpreted with a water density of 1000 kg/m3 / 1 kg/L).
    This mirrors how the original code used the helper -- balancing a
    composition dict against a known volume -- but the authoritative
    implementation ships with the deployment ``aux_chemical`` module.
    """
    comp = {k: float(v) for k, v in composition.items() if k}
    non_water = sum(mass for chem, mass in comp.items() if chem != "Water")
    target_mass = float(volume) * 1000.0
    comp["Water"] = max(0.0, target_mass - non_water)
    return comp


def process_chemical_data(chem_data):
    """Best-effort re-implementation of ``aux_chemical.process_chemical_data``.

    Accepts the stored chemical table (a dict-of-columns, e.g.
    ``{'Price (USD/kg)': {'Water': 0.0, ...}, 'Formula': {...}, ...}``) and
    returns ``(chemicals, chem_data)``.

    When ``thermosteam`` is available we build genuine ``Chemical`` objects
    (resolving known chemicals from the database, creating sensible blanks for
    unknowns such as ``Biomass``/``Collagen``) and register them as the default
    thermo, so the biosteam pipeline can create streams.  When it is not
    available we fall back to lightweight ``ID``-only stand-ins.

    The deployment ``aux_chemical`` module supplies the authoritative version.
    """
    price_col = chem_data.get("Price (USD/kg)", {}) if isinstance(chem_data, dict) else {}
    formula_col = chem_data.get("Formula", {}) if isinstance(chem_data, dict) else {}
    phase_col = chem_data.get("Phase", {}) if isinstance(chem_data, dict) else {}
    ids = list(price_col.keys())

    try:
        import thermosteam as tmo
    except Exception:  # noqa: BLE001 - thermosteam not installed
        class _Chem:
            def __init__(self, cid: str):
                self.ID = cid

            def __repr__(self) -> str:  # pragma: no cover
                return f"<Chemical {self.ID}>"

        return [_Chem(cid) for cid in ids], chem_data

    chemicals = []
    for cid in ids:
        phase = phase_col.get(cid, "l") or "l"
        formula = formula_col.get(cid) or None
        try:
            chem = tmo.Chemical(cid)
        except Exception:  # noqa: BLE001 - not in the database; create a blank
            try:
                chem = tmo.Chemical(
                    cid, search_db=False, default=True, phase=phase,
                    formula=formula, MW=1.0 if not formula else None,
                )
                chem.at_state(phase=phase)
            except Exception:  # noqa: BLE001 - last resort: minimal blank
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
    """Placeholder for a custom biosteam unit that is unavailable.

    Instantiating it raises a clear error pointing at the missing dependency,
    rather than failing with an opaque ``NameError`` deep inside the pipeline.
    """

    def __init__(self, name: str):
        self._name = name

    def __call__(self, *args, **kwargs):
        raise RuntimeError(
            f"Custom unit operation '{self._name}' is not available: the "
            "'Biosteam_custom_unit' module (and biosteam/thermosteam) must be "
            "installed in the deployment environment to run a calculation."
        )


# Custom unit operations referenced by util_biosteam.run_biosteam2.
BatchHeatExchanger = _MissingUnit("BatchHeatExchanger")
CustomSplitter = _MissingUnit("CustomSplitter")
Custom_fermenter3 = _MissingUnit("Custom_fermenter3")
MVR = _MissingUnit("MVR")
FreezeDryer2 = _MissingUnit("FreezeDryer2")
HIC_Column = _MissingUnit("HIC_Column")
IEX_Column = _MissingUnit("IEX_Column")
Diafiltration = _MissingUnit("Diafiltration")
gel_filtration = _MissingUnit("gel_filtration")
SMB_Column = _MissingUnit("SMB_Column")
sol_processor = _MissingUnit("sol_processor")
custom_distillation = _MissingUnit("custom_distillation")
