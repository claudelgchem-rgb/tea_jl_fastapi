import numpy as np, pandas as pd, json, copy
import biosteam as bst, thermosteam as tmo
import streamlit as st
import biosteam.units.design_tools as design
#import biosteam.units.design_tools.specification_factors as sf

class custom_distillation(bst.Unit):
    _ins_size_is_fixed = False
    _N_outs = 2
    _graphics = tmo._graphics.vertical_column_graphics
    auxiliary_unit_names = ('Column', 'Pump', 'Condenser', 'Reboiler')

    _units = {
        'Number of Stages': '',
        'Column volume': 'm3',
        'Pump power': 'kW',
        'Cooling duty': 'kJ/hr',
        'Total electricity': 'kW',
        'Reflux': 'ratio',
        'Rmin':'ratio',
        '': '',
    }
    _F_BM_default = {
        'Tower': 4.3,
        'Pump': 2.2,
        'Trays': 4.3,
        'Vacuum system': 1,
        'Condenser':1,
    }
    _bounds = {'Diameter': (3., 24.),
               'Height': (27., 170.),
               'Weight': (9000., 2.5e6)
              }

    dT=5
    vessel_material = 'Stainless steel'
    tray_material = 'Stainless steel'
    tray_type='Sieve'
    


    def _init(self, ID='', ins=[], outs=[],
              k=2, split={}, product_phase='distillate', 
              P=101325, T_reboiler=240, T_condenser=187.2,
              tray_efficiency=80, condenser_efficiency=80, heat_transfer_efficiency=80, 
              wastewater_id = 'wastewater',
              H_vap={}, alpha={}, 
              tray_spacing=0.45, vap_velocity = 3,
              **kwargs):
    
        self.k = k
        self.split = split
        self.P = P
        self.T_reboiler = T_reboiler+273.15 if T_reboiler < 300 else T_reboiler
        self.T_condenser = T_condenser+273.15 if T_condenser < 300 else T_condenser
        self.product_phase = product_phase
        self.H_vap = H_vap
        self.alpha = alpha
        self.tray_efficiency = tray_efficiency / 100
        self.condenser_efficiency = condenser_efficiency / 100
        self.tray_spacing = tray_spacing
        self.vap_velocity = vap_velocity
        self.heat_transfer_efficiency = heat_transfer_efficiency / 100
        self.wastewater_id = wastewater_id

        self.heating_steam = bst.HeatUtility()
        self.cooling_water = bst.HeatUtility()
        self.hu_waste_treatment = bst.HeatUtility()
        self.heat_utilities = [self.heating_steam, self.cooling_water, self.hu_waste_treatment]
    
    def _run(self):
        self.heat_utilities = [self.heating_steam, self.cooling_water, self.hu_waste_treatment]
        self.feed_tmp = bst.Stream()
        feed = self.feed_tmp
        feed.mix_from(self.ins)
        feed = self.feed_tmp
        if self.product_phase == 'distillate':
            distillate, bottoms = self.outs
        else:
            bottoms, distillate = self.outs

        bottoms.copy_flow(feed)
        for chem, mass in self.split.items():
            distillate.imass[chem] = mass * feed.imass[chem]
            bottoms.imass[chem] -= mass * feed.imass[chem]

        self.distillate = distillate
        self.bottoms = bottoms



    def _underwood_newtonian(self):
        feed = self.feed_tmp
        n_iter=0
        tol = 1e-3
        err = 1
        prev_theta = (min(self.alpha.values()) + max(self.alpha.values())) / 2
        
        while err > tol:
            n_iter+=1
            f_theta = 0
            derv_theta = 0
            for chem in self.alpha:
                f_theta += feed.imol[chem] / feed.F_mol * self.alpha[chem] / (self.alpha[chem] - prev_theta)
                derv_theta += feed.imol[chem] / feed.F_mol * self.alpha[chem] / (self.alpha[chem] - prev_theta) / (self.alpha[chem] - prev_theta)
            prev_theta -= f_theta / derv_theta
            
            err = abs(f_theta / derv_theta)
            
            if prev_theta > max(self.alpha.values()):
                prev_theta = max(self.alpha.values()) - tol *2
            elif prev_theta < min(self.alpha.values()):
                prev_theta = min(self.alpha.values()) + tol *2
            if n_iter > 100:
                print('Max iteration reached')
                break

        self.R_min = -1
        for chem in self.split:
            self.R_min += feed.imol[chem] * self.split[chem] / self.distillate.F_mol * self.alpha[chem] / (self.alpha[chem] - prev_theta)
        if self.R_min <=0:
            print('Error Negative R_min')
        self.R = self.k * self.R_min

    def _compute_Gilliland_theoretical_stage(self, Nm):
        X=  (self.R - self.R_min) / (self.R + 1)
        Y = 1. - np.exp((1. + 54.4*X) / (11. + 117.2*X) * (X - 1.) / X**0.5)
        N = (Y + Nm) / (1. - Y)
        return np.ceil(N / self.tray_efficiency)

    def _fenske_min_stage(self):
        feed = self.feed_tmp

        hk = min(self.alpha,key=self.alpha.get)
        lk = max(self.alpha,key=self.alpha.get)
        lhk_ratio = feed.imol[lk] * self.split[lk] / feed.imol[hk] / self.split[hk]
        hlk_ratio = feed.imol[hk] * (1-self.split[hk]) / feed.imol[lk] / (1-self.split[lk])
        N = np.log10(lhk_ratio * hlk_ratio) / np.log10(max(self.alpha.values()))
        
        return N

    def _run_condenser_and_reboiler(self):
        feed = self.feed_tmp
        distillate = self.distillate
        total_hvap = 0
        tmp_chem = [chem.ID for chem in distillate.vle_chemicals]
        tmp_chem.extend(list(self.H_vap.keys()))
        tmp_chem = list(set(tmp_chem))
        for chem in tmp_chem:
            if chem in self.H_vap and not np.isnan(self.H_vap[chem]):
                total_hvap += distillate.imass[chem] * self.H_vap[chem]
            else:
                try:
                    total_hvap += distillate.imol[chem] * distillate.chemicals[chem].Hvap(T=self.T_condenser)
                except:
                    pass
                    
        condenser_duty = total_hvap * (1 + self.design_results['Reflux'])
        tmp = bst.Stream()
        tmp.copy_like(feed)
        tmp.T = self.T_reboiler
        heat_duty = tmp.Hnet - feed.Hnet + condenser_duty

        heat_duty /= self.heat_transfer_efficiency
        condenser_duty /= self.condenser_efficiency
        steam_usage = heat_duty / 2250
        cooling_water_usage = condenser_duty / 4.18 / 5
        
        self.auxiliary('Pump',bst.units.Pump)
        self.Pump.ins[0].copy_like(feed)
        self.Pump.simulate()

        T_lmtd = (self.dT - (self.T_reboiler - feed.T))/np.log(self.dT / (self.T_reboiler - feed.T))

        Design = self.design_results
        

        self.auxiliary('Reboiler', bst.heat_exchange.HXutility)
        self.auxiliary('Condenser', bst.heat_exchange.HXutility)

        if self.T_reboiler <= 273.15 + 150: # use low_pressure steam
            Design['Reboiler HT Area'] = heat_duty / 1 / 0.5 / (273.15 + 150 - self.T_reboiler)
            heating_steam_id = 'low_pressure_steam'
        elif self.T_reboiler <= 273.15 + 185: # use low_pressure steam
            Design['Reboiler HT Area'] = heat_duty / 1 / 0.5 / (273.15 + 185 - self.T_reboiler)
            heating_steam_id = 'medium_pressure_steam'
        else: # use low_pressure steam
            Design['Reboiler HT Area'] = heat_duty / 1 / 0.5 / (273.15 + 300 - self.T_reboiler)
            heating_steam_id = 'high_pressure_steam'

        Design['Reboiler HT Area']
        Design['Condenser HT Area'] = condenser_duty / 0.5 / (self.T_condenser - 305)

        #self.add_heat_utility(unit_duty=heat_duty, T_in=feed.T, T_out=self.T_reboiler, 
        #                      heat_transfer_efficiency=self.heat_transfer_efficiency)
        #self.add_heat_utility(unit_duty=-condenser_duty, T_in=self.T_condenser, 
        #                      heat_transfer_efficiency=self.heat_transfer_efficiency)
        
        self.heating_steam.load_agent(bst.HeatUtility.get_agent(heating_steam_id))
        self.heating_steam.flow = steam_usage
        self.heating_steam.duty = steam_usage
        self.heating_steam.cost = steam_usage * bst.HeatUtility.get_agent(heating_steam_id).regeneration_price
        
        self.cooling_water.load_agent(bst.HeatUtility.get_agent('cooling_water'))
        self.cooling_water.flow = cooling_water_usage
        self.cooling_water.duty = cooling_water_usage
        self.cooling_water.cost = cooling_water_usage * bst.HeatUtility.get_agent('cooling_water').regeneration_price        
        


    
    def _design_distillation_column(self):
        Design = self.design_results
        R = Design['Reflux']
        distillate = self.distillate
        vap = distillate.copy()
        vap.phase = 'g'
        bottoms = self.bottoms

        L = distillate.F_mass* (1+R)
        V = L * (1+R) / R
        rho_V = vap.rho
        rho_L = distillate.rho
        F_LV = design.compute_flow_parameter(L, V, rho_V, rho_L)
        C_sbf = design.compute_max_capacity_parameter(self.tray_spacing, F_LV)
        A_dn = design.compute_downcomer_area_fraction(F_LV)
        R_diameter = design.compute_tower_diameter(distillate.F_vol * (1+R), self.vap_velocity, 1, A_dn)
        

        Design['Height'] = H = (Design['Number of stages'] * self.tray_spacing + 4.2672) #m
        Design['Diameter'] = Di = R_diameter #m
        Design['Wall thickness'] = tv = design.compute_tower_wall_thickness(self.P/6895, Di*3.28, H*3.28) #in
        Design['Weight'] = design.compute_tower_weight(Di*3.28, H*3.28, tv, 0.289) #lb


    def _design(self):
        feed = self.feed_tmp
        Design = self.design_results
        self._underwood_newtonian()
        Nm = self._fenske_min_stage()
        N = self._compute_Gilliland_theoretical_stage(Nm)
        
        Design['R_min'] = self.R_min
        Design['Reflux'] = self.R
        Design['Number of stages'] = N

        self._run_condenser_and_reboiler()
        self._design_distillation_column()


    def _cost(self):
        Design = self.design_results
        Cost = self.baseline_purchase_costs
        F_M = self.F_M
        N_T = Design['Number of stages']
        Di = Design['Diameter'] * 3.28 #ft
        W = Design['Weight'] #lb
        H = Design['Height']*3.28 #ft
        
        F_M['Trays'] = 1.401 + 0.073 * Di
        Cost['Trays'] = design.compute_purchase_cost_of_trays(N_T, Di)
        Cost['Tower'] = design.compute_empty_tower_cost(W)
        Cost['Platform and ladders'] = design.compute_plaform_ladder_cost(Di, H)

        Cost['Reboiler'] = np.exp(7.2718 + 0.16*np.log(Design['Reboiler HT Area']))*bst.CE/567
        Cost['Condenser'] = np.exp(7.2718 + 0.16*np.log(Design['Condenser HT Area']))*bst.CE/567
        
        self.hu_waste_treatment.load_agent(bst.HeatUtility.get_agent(self.wastewater_id))
        waste_vol = self.outs[1].F_vol
        self.hu_waste_treatment.flow = waste_vol
        self.hu_waste_treatment.duty = waste_vol
        self.hu_waste_treatment.cost = waste_vol * bst.HeatUtility.get_agent(self.wastewater_id).regeneration_price
        
