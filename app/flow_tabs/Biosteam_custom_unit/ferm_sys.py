import biosteam as bst, thermosteam as tmo
try:
    from biosteam.units.stirred_tank_reactor import StirredTankReactor
except ModuleNotFoundError:  # biosteam >= 2.5x moved/renamed this module
    from biosteam.units.abstract_stirred_tank_reactor import StirredTankReactor
import numpy as np, pandas as pd

import streamlit as st
from .custom_fermenter import CustomFermenter2  # class lives in custom_fermenter.py

class Custom_fermenter3(bst.Unit):
    """
    System that defines input stream, reaction and fermenter
    """
    _ins_size_is_fixed = False
    _N_outs = 2

    def _init(self, reactions='', init_OD=0.1, final_OD=20, 
              tau=24, batch_time=48, tau_cip=2, tau_sip=2, tau_add=2, tau_cool = 0, batch_time2 = 38,
              T=35, P=101325, V_wf=0.7, V_max=100, vvm=0.5, 
              sip_stream_rate=0.5, agitation_efficiency = 3, P_drop=200000, compressor_isentropic_efficiency=0.9, motor_efficiency=1.0, chill_to_cool_ratio=0.0, cip_acid_ratio=0.8, 
              out_mass = {}, in_mass = {}, initial_vol=1, final_vol=1, main_reactant='', **kwargs):

        self.T = T + 273.15 if T < 200 else T
        self.tau = tau
        self.tau_add = tau_add
        self.tau_cip = tau_cip
        self.tau_sip = tau_sip
        self.tau_cool = tau_cool
        self.batch_time = tau + tau_cip + tau_sip + tau_add + tau_cool
        self.batch_time2 = batch_time2 # Total cycle time for whole system
        self.P = P  # Pa
        self.init_OD = init_OD
        self.final_OD = final_OD
        self.V_wf = V_wf
        self.V_max = V_max
        self.vvm = vvm
        self.main_reactant = main_reactant
        self.sip_stream_rate = sip_stream_rate
        self.agitation_efficiency = agitation_efficiency
        self.P_drop = P_drop
        self.compressor_isentropic_efficiency = compressor_isentropic_efficiency
        self.motor_efficiency = motor_efficiency
        self.chill_to_cool_ratio = chill_to_cool_ratio
        self.cip_acid_ratio = cip_acid_ratio

        self.initial_vol = initial_vol
        self.final_vol = final_vol

        self.out_mass = out_mass
        self.in_mass = in_mass

        self.reactions = reactions
        self.baseline_purchase_costs = {}
        self._calculate_fermentation_stages(step=20)
        
        self.reactors = []; self.liquid_mixer = [];
        #self.auxiliary_units=(self.reactors, self.liquid_mixer,)
        self.hu_cip = bst.HeatUtility()
        self.hu_sip = bst.HeatUtility()
        self.hu_cw  = bst.HeatUtility()
        self.hu_chw = bst.HeatUtility()
        self.hu_waste = bst.HeatUtility()
        self.hu_cip_base = bst.HeatUtility()
        self.hu_cip_water = bst.HeatUtility()
        self.heat_utilities = [self.hu_cip, self.hu_sip, self.hu_cw, self.hu_chw, self.hu_waste, self.hu_cip_base, self.hu_cip_water]
        
    def _conc_to_reaction(self):
        # Sum all ins and subtract outs
        # Get reaction from it
        in_mass_total = 0; out_mass_total = 0; in_mass = {}; chem_mass = {}
        #in_mass = {c.ID: sum(i.imass[c.ID] for i in self.ins) for c in self.chemicals}
        in_mass = self.in_mass
        #chem_mass = {c.ID: self.out_mass[c.ID]/self.batch_time - in_mass[c.ID] for c in self.chemicals}
        chem_mass = {c.ID: self.out_mass[c.ID] - in_mass[c.ID] for c in self.chemicals}

        rate_limiting = ['Glycerol',0]
        for c in self.chemicals:
            if chem_mass[c.ID] < 0:
                ttmp = 1 - self.out_mass[c.ID] / in_mass[c.ID]
                if ttmp >= rate_limiting[1]:
                    rate_limiting = [c.ID,ttmp]

        #X = 1 - self.out_mass[self.main_reactant] / in_mass[self.main_reactant]
        # Convert OD to biomass
        in_mass['Biomass'] = self.initial_vol * self.init_OD * st.session_state.od_to_dcw
        self.out_mass['Biomass'] = self.final_vol * self.final_OD * st.session_state.od_to_dcw
        chem_mass['Biomass'] = (self.out_mass['Biomass'] - in_mass['Biomass'])/1000
        #st.write(chem_mass)
        #self.reactions = tmo.Reaction(chem_mass, reactant=self.main_reactant, X=X, basis='wt')
        self.reactions = tmo.Reaction(chem_mass, reactant=rate_limiting[0], X=rate_limiting[1], basis='wt')
        
        

    def _calculate_fermentation_stages(self, step=20):
        growth_ratio = self.final_OD / self.init_OD
        growth_ratio2 = self.final_OD / self.init_OD
        self.N_stages = int(np.ceil(np.log(growth_ratio)/np.log(20)))
        k = np.log(growth_ratio) / self.tau
        self.split_ratios = [growth_ratio for i in range(self.N_stages)]
        self.tau2 = [0 for i in range(self.N_stages)]
        for i in range(self.N_stages):
            self.split_ratios[i]  = step**(i+1)/self.split_ratios[i] if growth_ratio2 > step**(i+1) else growth_ratio2/self.split_ratios[i]
            growth_ratio2 -= step**(i+1)
            self.tau2[i] = np.log(step)/k if sum(self.tau2)+np.log(step)/k <= self.tau else self.tau-sum(self.tau2)

        self.split_ratios=[1]
        self.N_stages = 1

    def _setup(self):
        super()._setup()
        self.auxiliary_units.clear()
        self.reactors.clear(); self.liquid_mixer.clear()
        self.power_utility.empty()
        for hu in self.heat_utilities: hu.empty() # clear list from previous result
            
        self.feed_indices = []
        previous_reactor_outlet = None
        for i in range(self.N_stages):
            lm = self.auxiliary(f'{self.ID}_liq_mix_s{i}', bst.Mixer, ins=[])
            if i>0:
                lm.ins.append(self.reactors[i-1].outs[1])
            is_last_stage = (i == self.N_stages - 1)
            r = self.auxiliary(
                f'{self.ID}_reactor_s{i}',  CustomFermenter2,
                ins=[lm.outs[0]], outs=(f'{self.ID}_gas_s{i}', self.outs[1] if is_last_stage else f'{self.ID}_liq_s{i}'),
                #reactions=self.reactions, T=self.T, P=self.P, tau=self.tau2[i], tau_cip=self.tau_cip, tau_sip=self.tau_sip, tau_add=self.tau_add,
                reactions=self.reactions, T=self.T, P=self.P, tau=self.tau, tau_cip=self.tau_cip, tau_sip=self.tau_sip, tau_add=self.tau_add,
                sip_stream_rate=self.sip_stream_rate, agitation_efficiency=self.agitation_efficiency, vvm=self.vvm, V_wf=self.V_wf, P_drop=self.P_drop,
                compressor_isentropic_efficiency=self.compressor_isentropic_efficiency, motor_efficiency=self.motor_efficiency, chill_to_cool_ratio=self.chill_to_cool_ratio,
                cip_acid_ratio=self.cip_acid_ratio, batch_time=self.batch_time, batch_time2 = self.batch_time2, tau_cool = self.tau_cool, V_max=self.V_max)
            previous_reactor_outlet = r.outs[1]

            self.reactors.append(r)
            self.liquid_mixer.append(lm)
        self.mixer = self.auxiliary('mixer', bst.Mixer, ins=[r.outs[0] for r in self.reactors], outs=self.outs[0])

    def _run(self):
        self.heat_utilities = [self.hu_cip, self.hu_sip, self.hu_cw, self.hu_chw, self.hu_waste, self.hu_cip_base, self.hu_cip_water]
        streams = {}
        if self.reactions=='':
            self._conc_to_reaction()
        self.scale_ferm_by_batch = self.tau / self.batch_time
        for i in range(self.N_stages):
            #st.subheader(self.ID)
            lm = self.liquid_mixer[i]; r = self.reactors[i];
            #for j in self.ins:
            for j in self.ins[:1]:
                streams[f"{self.ID}_{i}_{j}"] = j.copy()
                streams[f"{self.ID}_{i}_{j}"].scale(self.split_ratios[i])
                lm.ins.append(streams[f"{self.ID}_{i}_{j}"])
            r.reactions = self.reactions
            
            lm.run()
            r.simulate()
            #st.write(self.ID,r.ins[0].F_vol, r.outs[1].F_vol, r.batch_time)
        self.mixer.simulate()
        

        #st.write(self.ID,'out',self.outs[1].F_vol, self.outs[1].F_mass,self.outs[1].imass['Collagen'])

    def _design(self):
        super()._design()
        Design = self.design_results
        total_v = 0
        Design['Number of reactors'] = self.N_stages
        for i in range(self.N_stages):
            r = self.reactors[i]
            r.simulate()
            total_v += r.design_results['Reactor volume']
        Design['Total Reactor volume'] = total_v
        #st.write('total_volume', total_v, self.batch_time)

        

    def _cost(self):
        super()._cost()
        total_pc = 0
        
        self.hu_cip.load_agent(bst.HeatUtility.get_agent('cip_acid_agent'))
        self.hu_cip_base.load_agent(bst.HeatUtility.get_agent('cip_base_agent'))
        self.hu_sip.load_agent(bst.HeatUtility.get_agent('low_pressure_steam'))
        self.hu_cw.load_agent(bst.HeatUtility.get_agent('cooling_water'))
        self.hu_chw.load_agent(bst.HeatUtility.get_agent('chilled_water'))
        self.hu_waste.load_agent(bst.HeatUtility.get_agent('wastewater'))
        self.hu_cip_water.load_agent(bst.HeatUtility.get_agent('cip_water'))
        
        for i, r in enumerate(self.reactors):
            if not r.design_results: continue
            r.simulate()
            self.purchase_costs[f"Reactor {i+1}"] = r.installed_cost
            self.power_utility.consumption += r.power_utility.consumption
            #st.write(self.ID, r.power_utility.consumption, self.power_utility.consumption)
           

            self.hu_chw.duty += r.hu_chw.duty
            self.hu_chw.flow += r.hu_chw.flow
            self.hu_chw.cost += r.hu_chw.cost
            self.hu_cw.duty += r.hu_cw.duty
            self.hu_cw.flow += r.hu_cw.flow
            self.hu_cw.cost += r.hu_cw.cost
            self.hu_cip.duty += r.hu_cip.duty
            self.hu_cip.flow += r.hu_cip.flow
            self.hu_cip.cost += r.hu_cip.cost
            self.hu_cip_base.duty += r.hu_cip_base.duty
            self.hu_cip_base.flow += r.hu_cip_base.flow
            self.hu_cip_base.cost += r.hu_cip_base.cost
            self.hu_sip.duty += r.hu_sip.duty
            self.hu_sip.flow += r.hu_sip.flow
            self.hu_sip.cost += r.hu_sip.cost
            self.hu_waste.duty += r.hu_waste.duty
            self.hu_waste.flow += r.hu_waste.flow
            self.hu_waste.cost += r.hu_waste.cost
            self.hu_cip_water.duty += r.hu_cip_water.duty
            self.hu_cip_water.flow += r.hu_cip_water.flow
            self.hu_cip_water.cost += r.hu_cip_water.cost
            
            total_pc += sum(r.baseline_purchase_costs.values())
        self.baseline_purchase_costs['System Total Equipment'] = total_pc
        #st.write('power', self.power_utility.consumption)
        
        
