import biosteam as bst, thermosteam as tmo
import numpy as np, pandas as pd
import streamlit as st #onlyused for test checking

class MVR(bst.Unit):
    """
    Mechanical Vapor Recompression (MVR) Evaporator.
    
    Parameters
    ----------
    V : float
        Fraction of evaporating_chemical in the feed that is evaporated.
    T : float
        Evaporator boiling temperature in Kelvin.
    dT : float
        Temperature driving force (K) between the condensing compressed
        vapor and the boiling liquid in the evaporator.
    U_overall : float
        Overall heat transfer coefficient (kW/m^2-K) for the evaporator.
    compressor_isentropic_efficiency : float
        Isentropic efficiency of the compressor.
    motor_efficiency : float
        Efficiency of the motor driving the compressor and pumps.
    pump_efficiency : float
        Efficiency of the liquid product discharge pump.
    pump_head : float
        Discharge head (m) for the liquid product pump.
    P_drop : float. optional
        Pressure drop (Pa) required to drive the compressed vapor through
        the heat exchanger section of the evaporator. This accounts for
        pressure losses on the heating side.
"""
    line = 'MVR Evaporator'
    _N_ins = 1
    _N_outs = 2 # 0: Condensate (from compressed vapor), 1: Concentrate (liquid product)
    _ins_size_is_fixed = False
    auxiliary_unit_names = ('Evaporator', 'Compressor', 'Pump')
    _F_BM_default = {'Evaporator': 2.45, 'Compressor': 2.5, 'Pump': 2.2}
    _units = {
        'Area': 'm^2', 'Volume': 'm^3',
        'Evaporator area': 'm^2',
        'Compressor power': 'kW',
        'Pump power': 'kW',}

    def _init(self, ID=None, ins=[], outs=[], V=0.5, T=80, dT=7, U_overall=2.0, P_drop=5000, 
              compressor_isentropic_efficiency=0.75, motor_efficiency=0.9, pump_efficiency=0.7, pump_head=20, chemical='Water',**kwargs):
        #super()._init(ID, ins, outs)
        
        self.V = V/100 # fraction of evaporating_chemical evaporated
        self.T = T if T>200 else T+273.15 # operating T
        self.dT = dT #T difference in evaporation
        self.U_overall = U_overall  # kW/m2-K
        self.compressor_isentropic_efficiency = compressor_isentropic_efficiency
        self.motor_efficiency = motor_efficiency
        self.pump_efficiency = pump_efficiency
        self.pump_head = pump_head # m
        self.P_drop = P_drop # Pa
        self.chemical = chemical

    def _run(self):
        feed = bst.Stream(phase='l')
        feed.mix_from(self.ins)
        #feed = self.ins[0]
        
        condensate, concentrate = self.outs
        evaporating_chemical = self.chemicals[self.chemical]
        self.P = evaporating_chemical.Psat(self.T)
            
        # 2. Split the feed based on V
        mol_evaporated = feed.imol[self.chemical] * self.V
        vapor_evaporated = bst.Stream(f"{self.ID}_vapor", phase='g')
        concentrate.copy_like(feed)
        
        try:
            concentrate.imol[self.chemical] -= mol_evaporated
        except:
            concentrate.imol['l',self.chemical] -= mol_evaporated
        vapor_evaporated.imol[self.chemical] = mol_evaporated
        vapor_evaporated.T = concentrate.T = self.T
        vapor_evaporated.P = concentrate.P = self.P
        concentrate.phase = 'l'
        
        # 4. Compress the evaporated vapor
        self.T_condensing = self.T + self.dT
        self.P_condensing = evaporating_chemical.Psat(self.T_condensing)
        condensate.copy_flow(vapor_evaporated)
        condensate.T = self.T_condensing
        condensate.P = self.P_condensing
        condensate.phase = 'l'

        self.vapor_evaporated = vapor_evaporated
        
        #auxiliary_unit_names = ('Evaporator', 'Compressor', 'Pump')
        self.auxiliary('Evaporator', bst.Unit, ins=[], outs=[])
        self.auxiliary('Compressor', bst.Unit, ins=[], outs=[])
        self.auxiliary('Pump', bst.Unit, ins=[], outs=[])

    def _design(self):
        Design = self.design_results
        feed = self.ins[0]
        condensate, concentrate = self.outs # Outs are already calculated in _run
        evaporating_chemical = self.chemicals[self.chemical]
        
        # Recalculate Q_evaporation_rate for design consistency (using the same logic as _run)
        vapor_evaporated_design = self.vapor_evaporated 
        H_feed = feed.H * feed.F_mol
        H_products_flash = vapor_evaporated_design.H * vapor_evaporated_design.F_mol + concentrate.H * concentrate.F_mol
        Q_evaporation_rate = H_products_flash - H_feed
        if Q_evaporation_rate <= 0:
            Q_evaporation_rate = 1e-6 # Safeguard against division by zero

        # Heat transfer area calculation
        Design['Evaporator area'] = Q_evaporation_rate / (self.U_overall * self.dT)
        
        # Compressor power
        P_comp_discharge = self.P_condensing + self.P_drop
        P_comp_inlet = self.P
        
        isentropic_discharge_stream = bst.Stream('isentropic_discharge_design', phase='g')
        isentropic_discharge_stream.copy_flow(vapor_evaporated_design)
        isentropic_discharge_stream.S = vapor_evaporated_design.S
        isentropic_discharge_stream.P = P_comp_discharge

        delta_H = isentropic_discharge_stream.H - vapor_evaporated_design.H
        Design['Compressor power'] = delta_H / self.compressor_isentropic_efficiency * vapor_evaporated_design.F_mol
        
        # Pump power
        m_concentrate = self.outs[1].F_mass
        evaporating_chemical = self.chemicals[self.chemical]
        try:
            rho_concentrate = evaporating_chemical.rho('l', concentrate.T, concentrate.P) 
            q_vol = m_concentrate / rho_concentrate if rho_concentrate else 0
            p_pump_kw = (q_vol * rho_concentrate * 9.81 * self.pump_head) / (self.pump_efficiency * 1000)
        except:
            st.write(f"Warning: Could not calculate pump power for concentrate. Error: {e}")
            p_pump_kw = 0
        Design['Pump power'] = p_pump_kw


    def _cost(self):
        # Utility cost should be done in cost not run
        base_CE_index = 567.5
        Design = self.design_results
        self.power_utility.consumption = (Design['Pump power'] + Design['Compressor power']) / self.motor_efficiency

        # Evaporator cost (Turton et al., 4th Ed., Table 16.1, Floating Head Shell-and-Tube Heat Exchanger, Carbon Steel)
        ln_area = np.log(max(1.0, Design['Evaporator area']))
        self.purchase_costs['Evaporator'] = np.exp(11.3264 + 0.8702 * ln_area - 0.0992 * (ln_area)**2) * (bst.CE / base_CE_index)

        # Compressor cost (Turton et al., 4th Ed., Table 16.1, Centrifugal Compressor)
        compressor_hp = Design['Compressor power'] * 1.341 # kW to hp
        ln_comp_hp = np.log(max(450.0, compressor_hp)) # Ensure log input is >= 1
        self.purchase_costs['Compressor'] = np.exp(7.58 + 0.8 * ln_comp_hp) * (bst.CE / base_CE_index)
        #q_cfm = self.vapor_evaporated.F_vol * 3600 * 35.3147 # m^3/s to CFM
        #Cp_2007 = 10**(2.2891 + 1.4000 * np.log10(q_cfm) - 0.1050 * (np.log10(q_cfm))**2)
        #self.purchase_costs['Compressor'] = N * Cp_2007 * (bst.CE / 525.4)

        # Pump cost (Turton et al., 4th Ed., Table 16.1, Centrifugal Pump + additional term)
        lnp = np.log(max(1.0, Design['Pump power'] * 1.341))
        #q_gpm = self.outs[1].F_vol * 3.6661541383181 #self.outs[1].F_vol - m3/hr
        #S = max(np.log(q_gpm * np.sqrt(65.6)), 6.0)
        #self.purchase_costs['Pump'] = (np.exp(12.1656 - 1.1448*S + 0.0862*S**2) + np.exp(5.9332 + 0.16829*lnp - 0.110056*lnp**2 + 0.071413*lnp**3 - 0.0063788*lnp**4)) * (bst.CE / 567)
        self.purchase_costs['Pump'] = np.exp(5.9332 + 0.16829*lnp - 0.110056*lnp**2 + 0.071413*lnp**3 - 0.0063788*lnp**4) * (bst.CE / base_CE_index)

        
        # No external heat utilities are typically consumed by MVR
        self.heat_utilities.clear()
