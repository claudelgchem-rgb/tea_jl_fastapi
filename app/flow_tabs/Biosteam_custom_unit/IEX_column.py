import numpy as np, pandas as pd, json, copy
import biosteam as bst, thermosteam as tmo
import flexsolve as flx
import streamlit as st


class IEX_Column(bst.Unit):
    line = 'Column Chromatography'
    _N_ins = 5 # feed, wash, wash2, elute, regeneration
    _N_outs = 2
    auxiliary_unit_names = ('Column', 'Pump')
    _F_BM_default = {
        'Column': 1, # Factor for pressure vessel/specialized column
        'Pump': 2.2,}
    _units = {
        'Total resin': 'L',
        'Pump power': 'kW',
        'Total Time':'hr'
    }

    column_price = 7000
    def _init(self, volume_product=0.2, P_drop=300000, 
        flowrate_wash1=1, flowrate_wash2=1, flowrate_elute=1, flowrate_regeneration=1, 
        tau_loading=1, tau_wash1=1, tau_wash2=1, tau_elute=1, tau_regeneration=1, 
        conc_product={'Water':1000}, conc_wash1={'Water':1000}, conc_wash2={'Water':1000}, conc_elute={'Water':1000}, conc_regeneration={'Water':1000}, 
        pump_efficiency=0.7, motor_efficiency=0.9, packing_factor=0.75, resin_lifetime_cycles=100, resin_price = 400, 
        binding_capacity=20.0, binding_material='Water', column_price=500,
        resin_id ='iex_resin', wastewater_id='wastewater', **kwargs):
        
        self.flowrate_wash1 = flowrate_wash1
        self.flowrate_wash2 = flowrate_wash2
        self.flowrate_elute = flowrate_elute
        self.flowrate_regeneration = flowrate_regeneration
        self.volume_product = volume_product * flowrate_elute * tau_elute # Amount of product from lab scale
        self.tau_loading = tau_loading #h
        self.tau_wash1 = tau_wash1
        self.tau_wash2 = tau_wash2
        self.tau_elute = tau_elute
        self.tau_regeneration = tau_regeneration
        self.conc_wash1 = conc_wash1 #[g/L]
        self.conc_wash2 = conc_wash2
        self.conc_elute = conc_elute
        self.conc_regeneration = conc_regeneration
        self.conc_product = conc_product
        self.P_drop = P_drop
        self.pump_efficiency = pump_efficiency
        self.motor_efficiency = motor_efficiency
        self.resin_lifetime_cycles = resin_lifetime_cycles
        self.resin_price = resin_price #USD/L
        self.column_price = column_price # Empty column price. USD/Column
        self.resin_id = resin_id
        self.binding_material = binding_material
        self.binding_capacity = binding_capacity
        self.wastewater_id = wastewater_id

        self.batch_time = (tau_loading + tau_wash1 + tau_wash2 + tau_elute + tau_regeneration)

        # Define utilities for consumable solutions and resin
        self.hu_iex_resin = bst.HeatUtility()
        self.hu_waste_treatment = bst.HeatUtility()
        self.heat_utilities = [self.hu_iex_resin, self.hu_waste_treatment]

    def _run(self):
        feed, wash1, wash2, elute, regeneration = self.ins
        product, waste = self.outs
        self.heat_utilities = [self.hu_iex_resin, self.hu_waste_treatment]

        # Scale up value
        binding_mass = feed.imass[self.binding_material] * 1000 * self.tau_loading
        self.bed_volume = binding_mass / self.binding_capacity

        for chem,conc in self.conc_product.items(): 
            product.imass[chem] = conc / 1000 # Assume 1L
        product.F_vol *= self.bed_volume * self.volume_product / self.batch_time # scale up and convert batch to continuous
        # Assume all else goes to waste
        for chem,conc in self.conc_wash1.items(): 
            wash1.imass[chem] = conc / 1000 # Assume 1L
        wash1.F_vol *= self.bed_volume * self.flowrate_wash1 * self.tau_wash1 / self.batch_time # Convert back to m3
        for chem,conc in self.conc_wash2.items(): 
            wash2.imass[chem] = conc / 1000 # Assume 1L
        wash2.F_vol *= self.bed_volume * self.flowrate_wash2 * self.tau_wash2 / self.batch_time
        for chem,conc in self.conc_elute.items(): 
            elute.imass[chem] = conc / 1000 # Assume 1L
        elute.F_vol *= self.bed_volume * self.flowrate_elute * self.tau_elute / self.batch_time
        for chem,conc in self.conc_regeneration.items(): 
            regeneration.imass[chem] = conc / 1000 # Assume 1L
        regeneration.F_vol *= self.bed_volume * self.flowrate_regeneration * self.tau_regeneration / self.batch_time

        self.auxiliary('Column', bst.Unit, ins=[], outs=[])
        self.auxiliary('Pump', bst.Unit, ins=[], outs=[])

        waste.mix_from(self.ins)
        for chem in self.chemicals:
            waste.imass[chem.ID] -= product.imass[chem.ID]


    def _design(self):
        design = self.design_results
        feed = self.ins[0]
        design['Total resin'] = self.bed_volume
        design['Total Time'] = self.batch_time

        flowrate_loading = self.ins[0].F_vol / self.bed_volume * 1000
        max_v = max(flowrate_loading, self.flowrate_wash1, self.flowrate_wash2, self.flowrate_elute, self.flowrate_regeneration)
        pump_kW = (max_v/1000)/3600 * self.P_drop / self.pump_efficiency/1000 * self.bed_volume
        design['Pump power'] = pump_kW

    def _cost(self):
        Design = self.design_results
        # Base CE index for Turton et al. (4th Ed., 2013) correlations
        base_CE_index = 567.5
        #N = Design['Number of columns']

        # 1. Column Purchase Cost (for all columns)
        # Using a simplified cost per liter of resin volume for the column vessel.
        #self.purchase_costs['Column'] = N * self.column_price
        self.purchase_costs['Column'] =(self.column_price * (Design['Total resin'])**0.544) * (bst.CE / base_CE_index)

        # 2. Pump Purchase Cost (for all pumps)
        # C = exp(C1 + C2*ln(P) + C3*(ln(P))^2 + C4*(ln(P))^3 + C5*(ln(P))^4) * (CE_current / CE_base)
        pump_hp_per_column = Design['Pump power'] * 1.341 # kW to hp
        lnp = np.log(max(1.0, pump_hp_per_column)) # Ensure log input is >= 1
        cost_per_pump = np.exp(5.9332 + 0.16829*lnp - 0.110056*lnp**2 + 0.071413*lnp**3 - 0.0063788*lnp**4) * (bst.CE / base_CE_index)
        #self.purchase_costs['Pump'] = N * cost_per_pump
        self.purchase_costs['Pump'] = cost_per_pump
        
        # 4. Utility Costs
        self.power_utility.consumption = Design['Pump power'] / self.motor_efficiency
        # Add utility if not present
        if self.resin_id not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(self.resin_id, regeneration_price = self.resin_price, T=298, Water=1))
        if self.wastewater_id not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(self.wastewater_id, regeneration_price = 0.01, T=298, Water=1))

        self.hu_iex_resin.load_agent(bst.HeatUtility.get_agent(self.resin_id))
        # Resin consumption rate (L/hr) = Total resin volume (L) / (Lifetime in cycles * Batch time per cycle (hr))
        resin_consumption_L_hr = Design['Total resin'] / (self.resin_lifetime_cycles * self.batch_time)
        self.hu_iex_resin.flow = resin_consumption_L_hr
        self.hu_iex_resin.duty = resin_consumption_L_hr
        self.hu_iex_resin.cost = self.hu_iex_resin.duty * self.resin_price

        self.hu_waste_treatment.load_agent(bst.HeatUtility.get_agent(self.wastewater_id))
        waste_vol = -self.outs[0].F_vol
        for i in self.ins:
            waste_vol +=i.F_vol
        self.hu_waste_treatment.flow = waste_vol
        self.hu_waste_treatment.duty = waste_vol
        self.hu_waste_treatment.cost = waste_vol * bst.HeatUtility.get_agent(self.wastewater_id).regeneration_price
