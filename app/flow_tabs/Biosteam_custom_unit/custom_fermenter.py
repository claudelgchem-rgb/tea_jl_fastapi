import biosteam as bst, thermosteam as tmo
try:
    from biosteam.units.stirred_tank_reactor import StirredTankReactor
except ModuleNotFoundError:  # biosteam >= 2.5x moved/renamed this module
    from biosteam.units.abstract_stirred_tank_reactor import StirredTankReactor
import numpy as np

import streamlit as st


class CustomFermenter2(StirredTankReactor):
    k = 1.4 #k (Cp/Cv)
    R = 0.287 #R (kJ/kg-K)
    dT = 5 # Utility temperature difference 
    _N_outs = 2
    _N_ins=2
    stage = 2 # Assume intercooling
    
    _ins_size_is_fixed = False
    _units = {**StirredTankReactor._units,
        'Agitator power': 'kW',
        'Compressor power': 'kW',
        'Pump power': 'kW',
        'Total electricity': 'kW',
        'Energy per batch': 'kWh',}

    def _init(self, reactions:str, ID=None, ins=[], outs=[], thermo=None, T=305, P=101325, tau=24, tau_cip=2, tau_add=2, tau_sip=2, batch_time = 24, batch_time2 = 38, tau_cool = 0, 
              sip_stream_rate=50, agitation_efficiency=0.8, vvm=0.5, P_drop=200000, compressor_isentropic_efficiency=0.7, 
              motor_efficiency=0.9, chill_to_cool_ratio=0, V_wf=0.7, V_max=100, **kwargs):
        super()._init(tau=tau, T=T, P=P, batch=True, adiabatic=True)
        self.ID = ID
        self.reactions = reactions
        self.ID = ID
        self.T = T
        self.P = P
        self.tau = tau
        self.tau_cip = tau_cip
        self.tau_add = tau_add
        self.tau_sip = tau_sip
        self.tau_cool = tau_cool
        self.sip_stream_rate = sip_stream_rate
        self.agitation_efficiency = agitation_efficiency
        self.vvm = vvm
        self.V_wf = V_wf
        self.P_drop = P_drop
        self.compressor_isentropic_efficiency = compressor_isentropic_efficiency
        self.motor_efficiency = motor_efficiency
        self.chill_to_cool_ratio = chill_to_cool_ratio
        self.batch_time = tau_cip+tau_add+tau_sip+tau+tau_cool
        self.batch_time2 = batch_time2
        self.V_max = V_max

        self.hu_cip = bst.HeatUtility()
        self.hu_sip = bst.HeatUtility()
        self.hu_cw  = bst.HeatUtility()
        self.hu_chw = bst.HeatUtility()
        self.hu_waste = bst.HeatUtility()
        self.hu_cip_base = bst.HeatUtility()
        self.hu_cip_water = bst.HeatUtility()
        self.heat_utilities = [self.hu_cip, self.hu_sip, self.hu_cw, self.hu_chw, self.hu_waste, self.hu_cip_base, self.hu_cip_water]
        

    def _run(self):
        self.heat_utilities = [self.hu_cip, self.hu_sip, self.hu_cw, self.hu_chw, self.hu_waste, self.hu_cip_base, self.hu_cip_water]
        vent,effluent = self.outs
        effluent.copy_like(self.ins[0])
        #effluent.mix_from(self.ins, energy_balance=False)
        self.reactions(effluent)
        effluent.T = vent.T = self.T
        effluent.P=vent.P=self.P
        vent.phase='g'
        vent.empty()
        vent.receive_vent(effluent, energy_balance=False)

        water = bst.Stream(self.ID, Water=1)
        water.F_vol = effluent.F_vol*12 / self.V_wf*100
        

    def _design(self):
        Design = self.design_results
        #ins_F_vol = sum([i.F_vol for i in self.ins if i.phase != 'g'])
        ins_F_vol = self.outs[1].F_vol
        P_psi = self.P * 0.000145038 # Pa to psi
        length_to_diameter = self.length_to_diameter = 2.5

        V_T = ins_F_vol * self.batch_time / self.V_wf*100 * (self.batch_time2/self.batch_time)
        N = int(np.ceil(V_T / self.V_max))
        V_i = V_T / N
        D = (4 * V_i / np.pi / 2.5)**(1/3) * 3.28084 # Convert from m to ft
        L = D * 2.5
        Design['Single Reactor volume'] = V_i
        Design['Reactor volume'] = V_T
        Design['Residence time'] = self.tau
        Design['Total time'] = self.batch_time
        Design.update(self._vessel_design(float(P_psi), float(D), float(L)))
        self.parallel['self'] = N

        V_Working = Design['Single Reactor volume'] * self.V_wf/100 * N
        #st.write("\n\n")
        #st.write()
        #st.write('Fermentation time:', self.tau, ' // Batch time', self.batch_time)
        #st.write('Reactor volume:',V_T, ' // Working Volume:', V_Working)
        #st.write('Agitator Power:', self.agitation_efficiency * V_Working)

        

        # Air flow per unit
        air_flow = V_Working * self.vvm / 60 * 101325 / (self.R * 1000 * 298.15) # kg/s
        P_ratio = (self.P_drop + self.P)/self.P
        r_stage = P_ratio ** (1/self.stage)
        exp_factor = (self.k-1) / self.k
        compressor_work = self.stage / exp_factor * self.R * 298.15 * (r_stage **exp_factor-1) #Isentropic work (kJ/kg)
        #p_comp_kw = air_flow * compressor_work / self.compressor_isentropic_efficiency #Shaft power (kW)
        p_comp_kw = air_flow * compressor_work

        #st.write('air flow[kg/s]: ',air_flow, 'V_Working * self.vvm / 60 * 101325 / (self.R * 1000 * 298.15)')
        #st.write('compressor work: ', compressor_work, 'self.stage / exp_factor * self.R * 298.15 * (r_stage **exp_factor-1)')
        #st.write('P_ratio = (self.P_drop + self.P)/self.P; r_stage = P_ratio ** (1/self.stage); exp_factor = (self.k-1) / self.k')
        #st.write('Compressor power[kW]: ',p_comp_kw, 'p_comp_kw = air_flow * compressor_work')
        
        

        
        
        # Pump power per unit
        q_m3_s = (V_Working / 3600) # 1 hr turnover
        p_pump_kw = (q_m3_s * 1000 * 9.81 * 20) / (0.6 * 1000)
        # Agitator power per unit
        p_agit_kw = self.agitation_efficiency * V_Working
        
        # 3. Store results
        Design['Agitator power'] = p_agit_kw
        Design['Compressor power'] = p_comp_kw
        Design['Pump power'] = p_pump_kw
        
        # 4. Total Electricity for the whole operation (All N units)
        #total_kw = (p_agit_kw * self.tau + p_comp_kw * self.tau + (2 * p_pump_kw) * self.tau_add) * N / self.batch_time
        total_kw = (p_agit_kw * self.batch_time + p_comp_kw * self.tau) * N / self.batch_time2
        ##st.write(V_Working, N, Design['Agitator power'], Design['Compressor power'], Design['Pump power'], self.batch_time)
        
        
        #st.write('Average Electricity[kW]: ', (p_agit_kw * self.batch_time + p_comp_kw * self.tau) * N / self.batch_time2, 'total_kw = (p_agit_kw * self.batch_time + p_comp_kw * self.fermentation_time) / self.batch_time')

        #st.write('Heat generated = Electricity heat')
        #st.write('m_dot', (p_agit_kw * self.batch_time + p_comp_kw * self.tau) * N / self.batch_time/4.186/5, 'kW/4.186/5')
        #st.write('cooling water flow per batch', (p_agit_kw * self.batch_time + p_comp_kw * self.tau) * N / self.batch_time/4.186/5*3.6*self.batch_time2, 'm_dot * 3.6 * batch_time')

        Design['Total electricity'] = total_kw
        ##st.write(V_Working, N, Design['Agitator power'], Design['Compressor power'], Design['Pump power'], self.batch_time)

        # Design heat exchanger
        # Load 1: Cooling
        Q_cooling_kw = p_agit_kw + p_comp_kw # Per unit
        LMTD_cooling = 15 # Assumed average driving force for 35C control
        U_cooling = 0.6 # kW/m2-K
        area_cooling = Q_cooling_kw / (U_cooling * LMTD_cooling)
        # Load 2: SIP (Sterilization)
        #W_vessel_kg = Design['Vessel weight'] * 0.4535
        W_vessel_kg = Design['Reactor volume'] * 1.32 # lb
        Q_sip_active_kw = (W_vessel_kg * 0.5 * (121 - 25)) / (self.tau_sip * 3600)
        LMTD_sip = 50 # Higher driving force with Steam
        area_sip = Q_sip_active_kw / (U_cooling * LMTD_sip)
        
        # Use the larger area requirement
        Design['Heat exchanger area'] = max(area_cooling, area_sip)

    def _cost(self):
        super()._cost() # Calculate Tank and agitator Capex

        Design = self.design_results
        V_Working = Design['Reactor volume'] * self.V_wf/100
        N = self.parallel['self']

        self.purchase_costs['Heat exchanger surface'] = (3000 * Design['Heat exchanger area']**0.6) * 2.5

        # Pumps (2 units)
        q_gpm = V_Working * 264.17 / 60
        p_hp = Design['Pump power'] * 1.341
        lnp = np.log(max(1.0, p_hp))
        S = max(np.log(q_gpm * np.sqrt(65.6)),6.0) # 65.6 ft head
        C_base = (np.exp(12.1656 - 1.1448*S + 0.0862*S**2) + np.exp(5.9332 + 0.16829*lnp - 0.110056*lnp**2 + 0.071413*lnp**3 - 0.0063788*lnp**4))
        self.purchase_costs['Pumps'] = N * 2 * C_base * (bst.CE / 567) * 2.2

        # Compressor
        q_cfm = V_Working * self.vvm * 0.0353 * 60 / N
        lnp_c = np.log(max(450.0, Design['Compressor power'] * 1.341))
        C_comp_base = np.exp(7.58 + 0.8 * lnp_c)
        self.purchase_costs['Compressor'] = N * C_comp_base * (bst.CE / 567) * 2.5

        # Utility
        self.power_utility.consumption = Design['Total electricity']
        self.auxiliary_units[0].power_utility.consumption=0 #kill agitator power
        
        # CIP Acid (Calculated on total flow)
        m_acid_total = Design['Single Reactor volume'] * N * 1000 *2
        self.hu_cip.load_agent(bst.HeatUtility.get_agent('cip_acid_agent'))
        self.hu_cip.duty = m_acid_total / self.batch_time2
        self.hu_cip.flow = self.hu_cip.duty
        self.hu_cip.cost = self.hu_cip.flow * bst.HeatUtility.get_agent('cip_acid_agent').regeneration_price

        self.hu_cip_base.load_agent(bst.HeatUtility.get_agent('cip_base_agent'))
        self.hu_cip_base.duty = m_acid_total / self.batch_time2
        self.hu_cip_base.flow = self.hu_cip_base.duty
        self.hu_cip_base.cost = self.hu_cip_base.flow * bst.HeatUtility.get_agent('cip_base_agent').regeneration_price

        if 'cip_water' not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent('cip_water', regeneration_price = 0.000001, T=298, Water=1))
            self.hu_cip_water.load_agent(bst.HeatUtility.get_agent('cip_water'))
            

        self.hu_cip_water.load_agent(bst.HeatUtility.get_agent('cip_water'))
        self.hu_cip_water.duty = m_acid_total / self.batch_time2
        self.hu_cip_water.flow = self.hu_cip_water.duty
        self.hu_cip_water.cost = self.hu_cip_water.flow * bst.HeatUtility.get_agent('cip_water').regeneration_price


        
        
        # SIP Steam (Calculated for ALL vessels)
        self.hu_sip.load_agent(bst.HeatUtility.get_agent('low_pressure_steam'))
        steam_mass_per_reactor_per_cycle = V_Working * self.sip_stream_rate * self.tau_sip # kg steam
        #total_average_steam_flow_kg_s = (steam_mass_per_reactor_per_cycle * N) / (self.batch_time * 3600)
        #self.hu_sip.flow = total_average_steam_flow_kg_s/16
        total_average_steam_flow_kg_s = (steam_mass_per_reactor_per_cycle * N) / (self.batch_time * 3600)
        #self.hu_sip.flow = total_average_steam_flow_kg_s

        self.hu_sip.flow = Design['Single Reactor volume'] * self.sip_stream_rate * N * self.tau_sip / self.batch_time
        self.hu_sip.duty = self.hu_sip.flow *2200
        self.hu_sip.cost = self.hu_sip.flow * bst.HeatUtility.get_agent('low_pressure_steam').regeneration_price

        #st.write('Steam Usage [kg/hr]', self.hu_sip.flow, 'Reactor volume * SIP_rate * SIP_time / batch_time', ' // Steam Usage per batch', self.hu_sip.flow*self.batch_time)
        #st.write('CIP usage [kg/batch]', m_acid_total, 'Reactor volume * CIP ratio[0.8=0.4+0.2+0.2]')
        #st.write('')
        

        
        # Cooling water
        # Assume 0.5C increase of temperature by metabolic reaction
        #metabolic_heat = V_Working * 0.58
        metabolic_heat = 0
        #heat_kW = (Design['Agitator power'] + Design['Compressor power'] + metabolic_heat) * N * self.tau / self.batch_time
        heat_kW = (Design['Total electricity'] + metabolic_heat) * N
        
        heat_water_flow = heat_kW/4.186/self.dT*3.6 #kg/hr
        ##st.write(Design['Total electricity'], heat_kW, heat_water_flow)
        self.hu_cw.load_agent(bst.HeatUtility.get_agent('cooling_water'))
        self.hu_cw.duty = -heat_kW * (1 - self.chill_to_cool_ratio)
        self.hu_cw.flow = heat_water_flow * (1 - self.chill_to_cool_ratio)
        self.hu_cw.cost = self.hu_cw.flow * bst.HeatUtility.get_agent('cooling_water').regeneration_price
        self.hu_chw.load_agent(bst.HeatUtility.get_agent('chilled_water'))
        self.hu_chw.duty = -heat_kW * self.chill_to_cool_ratio
        self.hu_chw.flow = heat_water_flow * self.chill_to_cool_ratio
        self.hu_chw.cost = self.hu_chw.flow * bst.HeatUtility.get_agent('chilled_water').regeneration_price

        try:
            self.hu_waste.load_agent(bst.HeatUtility.get_agent('wastewater'))
            self.hu_waste.duty = self.hu_cip.flow * 3
            self.hu_waste.flow = self.hu_cip.flow * 3
            self.hu_waste.cost = self.hu_waste.flow * bst.HeatUtility.get_agent('wastewater').regeneration_price
        except:
            pass
        


# Alias: the pipeline (util_biosteam.run_biosteam2) constructs "Custom_fermenter3".
Custom_fermenter3 = CustomFermenter2
