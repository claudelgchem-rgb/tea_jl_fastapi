import numpy as np, pandas as pd, json, copy
import biosteam as bst, thermosteam as tmo
import biosteam.units.design_tools.pressure_vessel
import streamlit as st

class sol_processor(bst.Unit, bst.units.design_tools.PressureVessel):
    line = 'MixTank'
    _N_ins = 2
    _N_outs = 2
    auxiliary_unit_names = ('Mix Tank', 'Heat Exchanger')
    _F_BM_default = {
        'Feed Tank': 2.45, # Factor for atmospheric storage tank
        'Heat Exchanger': 1
    }
    _units = {
        'Total volume': 'm^3',
        'Heat Exchange Area': 'm^2',
        'Residence time': 'hr',
        'Temperature': 'K'
    }
    auxiliary_unit_names = ('agitator','heat_exchanger') 
    _vessel_type = 'Vertical'
    _vessel_material = 'Stainless steel 316'

    def _init(self, sol_vol=0, sol_conc={}, tau=1, T=298, waste_vol=0, kW_per_m3=0.0985, V_wf=0.8, wastewater_id='wastewater', heat_id='low_pressure_steam', **kwargs):

        self.sol_vol = sol_vol
        self.sol_conc = sol_conc
        self.tau = tau
        self.T = T if T>200 else T+273.15
        self.waste_vol = waste_vol
        self.kW_per_m3 = kW_per_m3
        self.V_wf = V_wf

        self.wastewater_id = wastewater_id
        self.hu_waste_treatment = bst.HeatUtility()
        self.heat_utilities = [self.hu_waste_treatment]

    def _run(self):
        self.heat_utilities = [self.hu_waste_treatment]
        feed, process_sol = self.ins
        product, waste = self.outs

        for chem,conc in self.sol_conc.items():
            process_sol.imass[chem] = conc / 1000
        process_sol.F_vol = feed.F_vol * self.sol_vol
        mix_sol = bst.Stream()
        mix_sol.mix_from(self.ins)
        product.copy_like(mix_sol)
        waste.copy_like(mix_sol)
        product.F_vol = feed.F_vol * (1-self.waste_vol)
        product.T = self.T
        waste.F_vol = feed.F_vol * self.waste_vol
        self.vol = mix_sol.F_vol

        self.heat_exchanger = bst.HXutility(T=self.T, ins=mix_sol)
        self.heat_exchanger.simulate()
        

    def _design(self):
        design = self.design_results
        
        design['Residence time'] = self.tau
        design['Temperature'] = self.T
        design['Total volume'] = self.vol * self.tau / self.V_wf
        # V = 3.14 * D^2/4 * D #D:H=1:1
        # D = (V * 4 / 3.14)**(1/3)
        D = (design['Total volume'] * 4 / 3.14)**(1/3)
        dct = self._vessel_design(101325/6895, D, D)
        design.update(dct)

        kW = self.kW_per_m3 * design['Total volume'] * self.V_wf
        self.agitator = bst.Agitator(kW)


    def _cost(self):
        super()._cost()
        design_results = self.design_results
        self.hu_waste_treatment.load_agent(bst.HeatUtility.get_agent(self.wastewater_id))
        self.baseline_purchase_costs.update(self._vessel_purchase_cost(
                        design_results['Weight'], design_results['Diameter'], design_results['Length'], ))
            
        if self.waste_vol >0:
            waste_vol = self.outs[1].F_vol
            self.hu_waste_treatment.flow = waste_vol
            self.hu_waste_treatment.duty = waste_vol
            self.hu_waste_treatment.cost = waste_vol * bst.HeatUtility.get_agent(self.wastewater_id).regeneration_price

        
