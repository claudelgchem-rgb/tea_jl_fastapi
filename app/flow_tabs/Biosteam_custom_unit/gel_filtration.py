import numpy as np, pandas as pd, json, copy
import biosteam as bst, thermosteam as tmo
import flexsolve as flx
import streamlit as st


class gel_filtration(bst.Unit):
    line = 'Column Chromatography'
    _N_ins = 4 # feed, wash, equilibrate, elute
    _N_outs = 1
    auxiliary_unit_names = ('Column', 'Product Tank', 'Pump')
    _F_BM_default = {
        'Column': 1, # Factor for pressure vessel/specialized column
        'Pump': 2.2,
    }
    _units = {
        'Total resin': 'L',
        'Pump power': 'kW',
        'Total Time':'hr'
    }

    column_price=7000
    def _init(self, volume_product=0.575, P_drop=300000, 
        flowrate_wash=13.8, flowrate_equilibrate=5.75, flowrate_elute=13.8, 
        tau_loading=.25, tau_wash=0.5, tau_equilibrate=0.5, tau_elute=0.333, 
        conc_product={'Water':1000}, conc_wash={'Water':1000}, conc_equilibrate={'Water':1000}, conc_elute={'Water':1000}, 
        pump_efficiency=0.7, motor_efficiency=0.9, packing_factor=0.75, resin_lifetime_cycles=100, resin_price = 400, 
        column_price=7000, binding_capacity=20.0, binding_material='Water',
        resin_id ='gel_filtration_resin', wastewater_id='wastewater', **kwargs):
        
        self.flowrate_wash = flowrate_wash
        self.flowrate_equilibrate = flowrate_equilibrate
        self.flowrate_elute = flowrate_elute
        self.volume_product = volume_product * tau_elute * flowrate_elute # Amount of product from lab scale
        self.tau_loading = tau_loading #h
        self.tau_wash = tau_wash
        self.tau_equilibrate = tau_equilibrate
        self.tau_elute = tau_elute
        self.conc_wash = conc_wash #[g/L]
        self.conc_equilibrate = conc_equilibrate
        self.conc_elute = conc_elute
        self.conc_product = conc_product
        self.P_drop = P_drop
        self.pump_efficiency = pump_efficiency
        self.motor_efficiency = motor_efficiency
        self.resin_lifetime_cycles = resin_lifetime_cycles
        self.resin_price = resin_price #USD/L
        self.column_price = column_price # Empty column price. USD/Column
        self.resin_id = resin_id
        self.wastewater_id = wastewater_id
        self.binding_material = binding_material
        self.binding_capacity = binding_capacity

        self.batch_time = (tau_loading + tau_wash + tau_equilibrate + tau_elute)

        # Define utilities for consumable solutions and resin
        self.hu_resin = bst.HeatUtility()
        self.hu_waste_treatment = bst.HeatUtility()
        self.heat_utilities = [self.hu_resin, self.hu_waste_treatment]

    def _run(self):
        feed, wash, equilibrate, elute= self.ins

        feed, wash, equilibrate, elute= self.ins
        product = self.outs[0]
        self.heat_utilities = [self.hu_resin, self.hu_waste_treatment]

        # Scale up value
        binding_mass = feed.imass[self.binding_material] * 1000 * self.tau_loading
        self.bed_volume = binding_mass / self.binding_capacity

        
        for chem,conc in self.conc_product.items(): 
            product.imass[chem] = conc / 1000 # Assume 1L
        product.F_vol *= self.bed_volume * self.volume_product / self.batch_time # scale up and convert batch to continuous
        # Assume all else goes to waste

        for chem,conc in self.conc_wash.items(): 
            wash.imass[chem] = conc / 1000 # Assume 1L
        wash.F_vol *= self.bed_volume * self.flowrate_wash * self.tau_wash / self.batch_time # Convert back to m3
        for chem,conc in self.conc_equilibrate.items(): 
            equilibrate.imass[chem] = conc / 1000 # Assume 1L
        equilibrate.F_vol *= self.bed_volume * self.flowrate_equilibrate * self.tau_equilibrate / self.batch_time

        self.auxiliary('Column', bst.Unit, ins=[], outs=[])
        self.auxiliary('Pump', bst.Unit, ins=[], outs=[])


    def _design(self):
        design = self.design_results
        feed = self.ins[0]
        design['Total resin'] = self.bed_volume
        design['Total Time'] = self.batch_time
        
        flowrate_loading = self.ins[0].F_vol / self.bed_volume * 1000
        max_v = max(flowrate_loading, self.flowrate_wash, self.flowrate_equilibrate, self.flowrate_elute)
        pump_kW = (max_v/1000)/3600 * self.P_drop / self.pump_efficiency/1000 * self.bed_volume
        design['Pump power'] = pump_kW

    def _cost(self):
        Design = self.design_results
        # Base CE index for Turton et al. (4th Ed., 2013) correlations
        base_CE_index = 567.5

        self.purchase_costs['Column'] =(self.column_price * (Design['Total resin'])**0.544) * (bst.CE / base_CE_index)

        # 2. Pump Purchase Cost (for all pumps)
        # C = exp(C1 + C2*ln(P) + C3*(ln(P))^2 + C4*(ln(P))^3 + C5*(ln(P))^4) * (CE_current / CE_base)
        pump_hp_per_column = Design['Pump power'] * 1.341 # kW to hp
        lnp = np.log(max(1.0, pump_hp_per_column)) # Ensure log input is >= 1
        cost_per_pump = np.exp(5.9332 + 0.16829*lnp - 0.110056*lnp**2 + 0.071413*lnp**3 - 0.0063788*lnp**4) * (bst.CE / base_CE_index)
        self.purchase_costs['Pump'] = cost_per_pump

        
        # 4. Utility Costs
        self.power_utility.consumption = Design['Pump power'] / self.motor_efficiency
        # Add utility if not present
        if self.resin_id not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(self.resin_id, regeneration_price = self.resin_price, T=298, Water=1))
        if self.wastewater_id not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(self.wastewater_id, regeneration_price = 0.01, T=298, Water=1))

        self.hu_resin.load_agent(bst.HeatUtility.get_agent(self.resin_id))
        # Resin consumption rate (L/hr) = Total resin volume (L) / (Lifetime in cycles * Batch time per cycle (hr))
        resin_consumption_L_hr = Design['Total resin'] / (self.resin_lifetime_cycles * self.batch_time)
        self.hu_resin.flow = resin_consumption_L_hr
        self.hu_resin.duty = resin_consumption_L_hr
        self.hu_resin.cost = self.hu_resin.duty * self.resin_price

        self.hu_waste_treatment.load_agent(bst.HeatUtility.get_agent(self.wastewater_id))
        waste_vol = -self.outs[0].F_vol
        for i in self.ins:
            waste_vol +=i.F_vol
        self.hu_waste_treatment.flow = waste_vol
        self.hu_waste_treatment.duty = waste_vol
        self.hu_waste_treatment.cost = waste_vol * bst.HeatUtility.get_agent(self.wastewater_id).regeneration_price
