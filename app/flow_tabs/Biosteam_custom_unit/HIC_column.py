import numpy as np, pandas as pd, json, copy
import biosteam as bst, thermosteam as tmo
import flexsolve as flx
import streamlit as st


class HIC_Column(bst.Unit):
    line = 'Column Chromatography'
    _N_ins = 6 # feed, wash, equilibrate, elute, rinse, regeneration
    _N_outs = 2
    auxiliary_unit_names = ('Column', 'Pump')
    _F_BM_default = {
        'Column': 1,
        'Pump': 2.2,
    }
    _units = {
        'Total resin': 'L',
        'Pump power': 'kW',
        'Total Time':'hr'
    }
    
    def _init(self, volume_product=0.2, P_drop=300000, 
        flowrate_wash=1, flowrate_equilibrate=1, flowrate_elute=1, flowrate_rinse=1, flowrate_regeneration=1, 
        tau_loading=1, tau_wash=1, tau_equilibrate=1, tau_elute=1, tau_rinse=1, tau_regeneration=1, 
        conc_product={'Water':1000}, conc_wash={'Water':1000}, conc_equilibrate={'Water':1000}, conc_elute={'Water':1000}, conc_rinse={'Water':1000}, conc_regeneration={'Water':1000}, 
        pump_efficiency=0.7, motor_efficiency=0.9, packing_factor=0.75, resin_lifetime_cycles=100, resin_price = 400, 
        column_price=7000, binding_capacity=20.0, binding_material='Water',
        resin_id ='hic_resin', wastewater_id='wastewater', **kwargs):
        
        self.flowrate_wash = flowrate_wash
        self.flowrate_equilibrate = flowrate_equilibrate
        self.flowrate_elute = flowrate_elute
        self.flowrate_rinse = flowrate_rinse
        self.flowrate_regeneration = flowrate_regeneration
        self.volume_product = volume_product * flowrate_elute * tau_elute
        self.tau_loading = tau_loading #h
        self.tau_wash = tau_wash
        self.tau_equilibrate = tau_equilibrate
        self.tau_elute = tau_elute
        self.tau_rinse = tau_rinse
        self.tau_regeneration = tau_regeneration
        self.conc_wash = conc_wash #[g/L]
        self.conc_equilibrate = conc_equilibrate
        self.conc_elute = conc_elute
        self.conc_rinse = conc_rinse
        self.conc_regeneration = conc_regeneration
        self.conc_product = conc_product
        self.P_drop = P_drop
        self.pump_efficiency = pump_efficiency
        self.motor_efficiency = motor_efficiency
        self.resin_lifetime_cycles = resin_lifetime_cycles
        self.resin_price = resin_price #USD/L
        self.column_price = column_price # Empty column price. USD/Column
        self.binding_material = binding_material
        self.binding_capacity = binding_capacity
        self.resin_id = resin_id
        self.wastewater_id = wastewater_id

        self.batch_time = (tau_loading + tau_wash + tau_equilibrate + tau_elute + tau_rinse + tau_regeneration)

        # Define utilities for consumable solutions and resin
        self.hu_hic_resin = bst.HeatUtility()
        self.hu_waste_treatment = bst.HeatUtility()
        self.heat_utilities = [self.hu_hic_resin, self.hu_waste_treatment]

    def _run(self):
        feed, wash, equilibrate, elute, rinse, regeneration = self.ins
        product, waste = self.outs
        self.heat_utilities = [self.hu_hic_resin, self.hu_waste_treatment]

        # Scale up value
        binding_mass = feed.imass[self.binding_material] * self.tau_loading
        self.bed_volume = binding_mass / self.binding_capacity * 1000
        
        for chem,conc in self.conc_product.items(): 
            product.imass[chem] = conc / 1000 # Assume 1L
        product.F_vol *= self.bed_volume * self.volume_product / self.batch_time # scale up and convert batch to continuous
        # Assume all else goes to waste

        for chem,conc in self.conc_wash.items(): 
            wash.imass[chem] = conc / 1000 # kg/L
        wash.F_vol *= self.bed_volume * self.flowrate_wash * self.tau_wash / self.batch_time # Convert back to m3
        for chem,conc in self.conc_equilibrate.items(): 
            equilibrate.imass[chem] = conc / 1000 # Assume 1L
        equilibrate.F_vol *= self.bed_volume * self.flowrate_equilibrate * self.tau_equilibrate / self.batch_time
        for chem,conc in self.conc_rinse.items(): 
            rinse.imass[chem] = conc / 1000 # Assume 1L
        rinse.F_vol *= self.bed_volume * self.flowrate_rinse * self.tau_rinse / self.batch_time
        for chem,conc in self.conc_elute.items(): 
            elute.imass[chem] = conc / 1000 # Assume 1L
        elute.F_vol *= self.bed_volume * self.flowrate_elute * self.tau_elute / self.batch_time
        for chem,conc in self.conc_regeneration.items(): 
            regeneration.imass[chem] = conc / 1000 # Assume 1L
        regeneration.F_vol *= self.bed_volume * self.flowrate_regeneration * self.tau_regeneration / self.batch_time


        #auxiliary_unit_names = ('Column', 'Feed Tank', 'Wash Tank','Equilibrate Tank', 'Eluent Tank', 'Rinse Tank','Product Tank', 'Pump')
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
        max_v = max(flowrate_loading, self.flowrate_wash, self.flowrate_equilibrate, self.flowrate_elute, self.flowrate_rinse, self.flowrate_regeneration)
        pump_kW = (max_v/1000)/3600 * self.P_drop / self.pump_efficiency/1000 * self.bed_volume
        design['Pump power'] = pump_kW

    def _cost(self):
        Design = self.design_results
        # Base CE index for Turton et al. (4th Ed., 2013) correlations
        base_CE_index = 567.5

        # 1. Column Purchase Cost (for all columns)
        #self.purchase_costs['Column'] = N * self.column_price
        self.purchase_costs['Column'] =(self.column_price * (Design['Total resin'])**0.544) * (bst.CE / base_CE_index)

        # 2. Pump Purchase Cost (for all pumps)
        # C = exp(C1 + C2*ln(P) + C3*(ln(P))^2 + C4*(ln(P))^3 + C5*(ln(P))^4) * (CE_current / CE_base)
        pump_hp = Design['Pump power'] * 1.341 # kW to hp
        lnp = np.log(max(1.0, pump_hp)) # Ensure log input is >= 1
        cost_pump = np.exp(5.9332 + 0.16829*lnp - 0.110056*lnp**2 + 0.071413*lnp**3 - 0.0063788*lnp**4) * (bst.CE / base_CE_index)
        self.purchase_costs['Pump'] = cost_pump

        # 3. Tank Purchase Costs (Using a general volume-based correlation)
        def cost_tank(volume_m3):
            if volume_m3 <= 0: return 0
            ln_size_factor = np.log(max(1000.0, 150.0 * (volume_m3**0.7)))
            return np.exp(9.100 + 0.2889*ln_size_factor + 0.0457*(ln_size_factor**2)) * (bst.CE / base_CE_index)
        
        # 4. Utility Costs
        self.power_utility.consumption = Design['Pump power'] / self.motor_efficiency
        # Add utility if not present
        if self.resin_id not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(self.resin_id, regeneration_price = self.resin_price, T=298, Water=1))
        if self.wastewater_id not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(self.wastewater_id, regeneration_price = 0.01, T=298, Water=1))

        self.hu_hic_resin.load_agent(bst.HeatUtility.get_agent(self.resin_id))
        # Resin consumption rate (L/hr) = Total resin volume (L) / (Lifetime in cycles * Batch time per cycle (hr))
        resin_consumption_L_hr = Design['Total resin'] / (self.resin_lifetime_cycles * self.batch_time)
        self.hu_hic_resin.flow = resin_consumption_L_hr
        self.hu_hic_resin.duty = resin_consumption_L_hr
        self.hu_hic_resin.cost = self.hu_hic_resin.duty * self.resin_price

        self.hu_waste_treatment.load_agent(bst.HeatUtility.get_agent(self.wastewater_id))
        waste_vol = -self.outs[0].F_vol
        for i in self.ins:
            waste_vol +=i.F_vol
        self.hu_waste_treatment.flow = waste_vol
        self.hu_waste_treatment.duty = waste_vol
        self.hu_waste_treatment.cost = waste_vol * bst.HeatUtility.get_agent(self.wastewater_id).regeneration_price
