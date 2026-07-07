import numpy as np, pandas as pd, json, copy
import biosteam as bst, thermosteam as tmo
import streamlit as st


class SMB_Column(bst.Unit):
    """
    Create a Simulated Moving Bed (SMB) Chromatography unit.

    Parameters
    ----------
    N_columns : int, optional
        Total number of columns in the SMB system. The default is 8.
    switching_time : float, optional
        Time in minutes for a column to switch from one zone to the next.
        The default is 15.
    binding_material : str, optional
        The ID of the chemical component that is the target product to be
        recovered in the extract stream. The default is 'Product'.
    binding_capacity : float, optional
        Binding capacity of the resin for the `binding_material` in g/L resin.
        Used for overall sizing consideration, but primary separation is via splits.
        The default is 20.0.
    P_drop : float, optional
        Total pressure drop across the SMB system in Pascals. The default is 300000.
    pump_efficiency : float, optional
        Efficiency of the pump (0-1). The default is 0.7.
    motor_efficiency : float, optional
        Efficiency of the pump motor (0-1). The default is 0.9.
    resin_lifetime_hours : float, optional
        Assumed operational lifetime of the resin before replacement, in hours.
    column_price_per_volume : float, optional
        Base price factor for the empty column body in USD/m^3.
        The default is 7000. This is scaled by total column volume.

    resin_id : str, optional
        ID for the resin utility agent. The default is 'smb_resin'.
    wastewater_id : str, optional
        ID for the wastewater utility agent. The default is 'wastewater'.
    """

    line = 'Simulated Moving Bed Chromatography'
    _N_ins = 3 # feed, desorbent, regenerant
    _N_outs = 2 # extract (product), raffinate (waste)
    auxiliary_unit_names = ('Column', 'Pump', 'ValveManifold', 'ControlSystem', 'InternalRecyclePumps')
    _F_BM_default = {
        'Column': 1.5, # Factor for column body
        'Pump': 2.2, # Factor for pump
        'ValveManifold': 3.0, # High installation factor for complex valving
        'ControlSystem': 1.0, # Control systems often have a lower F_BM
        'InternalRecyclePumps': 2.2,
    }
    _units = {
        'Total resin': 'L',
        'N_columns': '',
        'Pump power': 'kW',
        'Bed_Volume_per_Column': 'L',
    }

    _internal_pump_ratio = 0.5
    def _init(self, ID='',ins=[], outs=[], N_columns=8, 
             binding_material='Water', binding_capacity=20.0, # g/L resin for binding_material (used for overall sizing consideration),  component to purify
             flowrate_desorbent=0.43, conc_desorbent={'Water':1000},
             flowrate_regenerant=0.43, conc_regenerant={'Water':1000},
             flowrate_product=0.1, conc_product={'Water':1000},
             P_drop=300000, pump_efficiency=0.7, motor_efficiency=0.9, #pa
             resin_lifetime_hours=15000, column_price_per_volume=7000, # USD/m^3 of column body
             resin_id='smb_resin', wastewater_id='wastewater',
             **kwargs):

        self.N_columns = N_columns
        self.binding_material = binding_material
        self.binding_capacity = binding_capacity # g/h product / L resin
        self.flowrate_desorbent = flowrate_desorbent
        self.conc_desorbent = conc_desorbent
        self.flowrate_regenerant = flowrate_regenerant
        self.conc_regenerant = conc_regenerant
        self.flowrate_product = flowrate_product
        self.conc_product = conc_product
        self.P_drop = P_drop
        self.pump_efficiency = pump_efficiency
        self.motor_efficiency = motor_efficiency
        self.resin_lifetime_hours = resin_lifetime_hours
        self.column_price_per_volume = column_price_per_volume
        self.resin_id = resin_id
        self.wastewater_id = wastewater_id

        # Define utilities for consumable solutions and resin
        self.hu_resin = bst.HeatUtility()
        self.hu_wastewater = bst.HeatUtility()
        self.heat_utilities = [self.hu_resin, self.hu_wastewater]


    def _run(self):
        self.heat_utilities = [self.hu_resin, self.hu_wastewater]
        feed, desorbent_in, regenerant_in = self.ins
        extract, raffinate = self.outs

        # --- Separation Logic ---
        binding_mass = feed.imass[self.binding_material]
        self.bed_volume = binding_mass / self.binding_capacity * 1000

        for chem,mass in self.conc_desorbent.items():
            desorbent_in.imass[chem] = mass / 1000
        desorbent_in.F_vol *= self.bed_volume * self.flowrate_desorbent
        for chem,mass in self.conc_regenerant.items():
            regenerant_in.imass[chem] = mass / 1000
        regenerant_in.F_vol *= self.bed_volume * self.flowrate_regenerant

        for chem,mass in self.conc_product.items():
            extract.imass[chem] = mass / 1000
        extract.F_vol = feed.F_vol * self.flowrate_product
        raffinate.mix_from(self.ins)
        for chem,mass in self.conc_product.items():
            raffinate.imass[chem] -= extract.imass[chem]

        self.auxiliary('Column', bst.Unit, ins=[], outs=[])
        self.auxiliary('Pump', bst.Unit, ins=[], outs=[])
        self.auxiliary('ValveManifold', bst.Unit, ins=[], outs=[])
        self.auxiliary('ControlSystem', bst.Unit, ins=[], outs=[])
        self.auxiliary('InternalRecyclePumps', bst.Unit, ins=[], outs=[])

    def _design(self):
        design = self.design_results
        design['Total resin'] = self.bed_volume # L (for consistency with HIC)
        design['N_columns'] = self.N_columns
        design['Bed_Volume_per_Column'] = self.bed_volume / self.N_columns # L

        # Total flow for pump sizing: Sum of all external inputs
        # A more rigorous SMB pump calculation would consider internal recycle flows,
        # which are often much larger than external flows. For this basic model,
        # we'll assume the external flows dictate the main pump size.
        # If specific zone flows (e.g., QII) are known and are higher, they should be used.
        total_external_flow = self.ins[0].F_vol + self.ins[1].F_vol + self.ins[2].F_vol # m^3/hr

        # Convert to m^3/s for power calculation: P = Q * dP / eff
        pump_kW = (total_external_flow / 3600) * self.P_drop / self.pump_efficiency / 1000 # (m^3/s * Pa) / (efficiency * 1000) = kW
        design['Pump power'] = pump_kW

    def _cost(self):
        Design = self.design_results
        base_CE_index = 567.5 # Biosteam's default CE index for Turton et al. (4th Ed., 2013)

        # 1. Column Purchase Cost
        # Scaling based on total column body volume (m^3)
        # Using a simple power law, similar to vessels, or linear with volume.
        # Given `column_price_per_volume` as a base, we can just multiply by volume.
        # This is a base cost for the empty column hardware.
        self.purchase_costs['Column'] = self.N_columns * (self.column_price_per_volume * Design['Bed_Volume_per_Column']**0.544) * (bst.CE / base_CE_index)
        
        # 2. Pump Purchase Cost
        pump_hp = Design['Pump power'] * 1.34102 # kW to hp
        lnp = np.log(max(1.0, pump_hp)) # Ensure log input is >= 1 to avoid math domain error
        cost_pump = np.exp(5.9332 + 0.16829*lnp - 0.110056*lnp**2 + 0.071413*lnp**3 - 0.0063788*lnp**4) * (bst.CE / base_CE_index)
        self.purchase_costs['Pump'] = cost_pump

        internal_pump_power = Design['Pump power'] * self._internal_pump_ratio # A factor, or calculated more rigorously
        lnp_internal = np.log(max(1.0, internal_pump_power * 1.34102))
        cost_internal_pumps = np.exp(5.9332 + 0.16829*lnp_internal - 0.110056*lnp_internal**2 + 0.071413*lnp_internal**3 - 0.0063788*lnp_internal**4) * (bst.CE / base_CE_index)
        self.purchase_costs['InternalRecyclePumps'] = cost_internal_pumps
        self.purchase_costs['ValveManifold'] = 50000 * (Design['Total resin']/1000)**0.5 * (bst.CE / base_CE_index) # Placeholder correlation
        self.purchase_costs['ControlSystem'] = (30000 + 5000 * self.N_columns) * (bst.CE / base_CE_index) # Placeholder correlation

        # 3. Utility Costs
        self.power_utility.consumption = Design['Pump power'] * (1 + self._internal_pump_ratio) / self.motor_efficiency # kW

        # Resin consumption
        # Annual resin replacement cost: Total resin volume * price / resin_lifetime_hours
        # To get flow (L/hr) for the utility, divide annual consumption by operating hours/year
        resin_consumption_L_per_hr = Design['Total resin'] / self.resin_lifetime_hours # L/year
        
        self.hu_resin.load_agent(bst.HeatUtility.get_agent(self.resin_id))
        self.hu_resin.flow = resin_consumption_L_per_hr
        self.hu_resin.duty = resin_consumption_L_per_hr # Biosteam uses duty for costing agent flow
        self.hu_resin.cost = self.hu_resin.duty * bst.HeatUtility.get_agent(self.resin_id).regeneration_price

        # Wastewater treatment
        self.hu_wastewater.load_agent(bst.HeatUtility.get_agent(self.wastewater_id))
        # Wastewater flow is the raffinate volumetric flow rate (m^3/hr)
        self.hu_wastewater.flow = self.outs[1].F_vol
        self.hu_wastewater.duty = self.outs[1].F_vol
        self.hu_wastewater.cost = self.hu_wastewater.duty * bst.HeatUtility.get_agent(self.wastewater_id).regeneration_price

