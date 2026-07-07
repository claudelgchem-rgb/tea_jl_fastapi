import numpy as np, pandas as pd, sys, os, json, copy, string, pickle, math
import biosteam as bst, thermosteam as tmo
from biosteam import Unit, Stream, settings, main_flowsheet
from biosteam.units import design_tools as design
from .BatchHeatExchanger import BatchHeatExchanger

import streamlit as st


class FreezeDryer2(bst.Unit, design.PressureVessel):

    _ins_size_is_fixed = False
    _N_outs = 2 # 0: Dried product, 1: Condensed ice/water

    # --- Design and Costing Constants ---
    _SHELF_COST_FACTOR = 70000  # USD/m^2^0.6, CE_PCI=600
    _SHELF_PACKING_FACTOR = 6.0  # Assumed geometric packing efficiency for shelves
    _SAMPLE_PACKING_FACTOR = 0.9 # Fraction of shelf area used by product containers

    # Air Filter Costing Defaults
    _AIR_FILTER_BASE_COST_USD = 1500 # Base cost for a 100 m3/hr filter, CEPCI=600
    _AIR_FILTER_BASE_FLOW_M3_HR = 100 # m3/hr
    _AIR_FILTER_SCALING_EXPONENT = 0.5 # Typical for filters
    _AIR_FILTER_BASE_CEPCI = 600 # CEPCI when base cost was estimated
    _AIR_FILTER_LIFESPAN_HOURS = 7800 # Replace filter elements every X batches
    _AIR_FILTER_ELEMENT_FRACTION_OF_TOTAL_COST = 0.5 # Element cost is 50% of total filter unit cost

    # Condenser Costing Defaults (Heuristic for 2.14)
    _CONDENSER_BASE_COST_USD = 50000 # Base cost for a 100 m2 condenser, CEPCI=600
    _CONDENSER_BASE_AREA_M2 = 100 # m2
    _CONDENSER_SCALING_EXPONENT = 0.6 # Typical for heat exchangers
    _U_CONDENSER = 25 # W/m2/K, assumed overall heat transfer coefficient for freeze dryer condenser
    diameter_to_length_ratio = 0.5


    _units = {'Length': 'ft', 'Diameter': 'ft', 'Weight': 'lb',
              'Wall thickness': 'in', 'Total volume': 'ft3', 'Shelf Area (per vessel)': 'm2'}
    _F_BM_default = {
        'Liquid-ring pump': 1.0,
        'Shelves': 1.0,
        'Condenser': 1.0,
        'Air filter': 1.0,
        'Shelf heater/cooler': 1.0,
        'Vacuum System': 1.0,
        **design.PressureVessel._F_BM_default
    }

    auxiliary_unit_names = ('vacuum_system', 'air_filter_unit')


    def _init(self, ID="", ins=None, outs=(),
        freeze_T = -40,
        P = 101325,
        tau_loading = .5,
        tau_sublimation = 1.5,
        target_final_moisture_content = 0.0,
        tau_etc = 0.0,
        
        sublimation_rate = 1,
        sample_thickness = 0.015,
        steam_specific_amount = 2.0,
        specific_power = 0.3,
        
        max_area_per_vessel=100.0,      # [m2] Maximum total shelf area per physical vessel
        wastewater_id='wastewater',
        heat_id='low_pressure_steam',
        _SHELF_PACKING_FACTOR = 6.0,  # Assumed geometric packing efficiency for shelves
        _SAMPLE_PACKING_FACTOR = 0.9, # Fraction of shelf area used by product containers
        **kwargs):

        self.freeze_T = freeze_T + 273.15 if freeze_T < 150 else freeze_T
        self.target_final_moisture_content = target_final_moisture_content
        self.sample_thickness = sample_thickness
        self.tau_loading = tau_loading
        self.tau_sublimation = tau_sublimation
        self.tau_etc = tau_etc
        self.steam_specific_amount = steam_specific_amount
        self.specific_power = specific_power
        self.max_area_per_vessel = max_area_per_vessel
        self._SHELF_PACKING_FACTOR = _SHELF_PACKING_FACTOR
        self._SAMPLE_PACKING_FACTOR = _SAMPLE_PACKING_FACTOR
        self.sublimation_P = P / 6895

        self.vessel_material = 'Stainless steel 316'
        self.vacuum_system_preference = 'Liquid-ring pump'
        self.ID = ID

        self.batch_time = self.tau_loading + self.tau_sublimation + self.tau_etc

        # Store utility agent and material IDs
        self.wastewater_id = wastewater_id
        self.heat_id = heat_id
        self.wastewater = bst.HeatUtility()
        self.steam = bst.HeatUtility()

        # Collect all heat utilities for easy clearing/access
        self.heat_utilities = [self.wastewater, self.steam]

    def _calculate_water_removal(self, feed_stream):
        # Calculate dry mass. If feed is empty, dry_mass is 0.
        dry_mass = (feed_stream.F_mass - feed_stream.imass['Water']) if feed_stream.F_mass > 0 else 0

        # If there's no dry mass, or target moisture content is 100%, no water needs to be removed relative to dry mass.
        if dry_mass == 0 or self.target_final_moisture_content >= 1.0:
            return feed_stream.imass['Water'] # Remove all water if no dry product or 100% water target

        # Calculate total mass after drying based on dry mass and target final moisture content
        if (1 - self.target_final_moisture_content) == 0: # Avoid division by zero if target_final_moisture_content is 1
            after_drying_total_mass = dry_mass # All water removed, only dry mass remains
        else:
            after_drying_total_mass = dry_mass / (1 - self.target_final_moisture_content)
        
        # Calculate water remaining in the product after drying
        product_water_mass = after_drying_total_mass - dry_mass
        # Calculate water that must be removed
        required_water_to_remove = feed_stream.imass['Water'] - product_water_mass
        return max(0, required_water_to_remove) # Ensure non-negative removal


    def _calculate_vessel_count(self, feed_stream):
        # Calculate total plant continuous throughput values
        water_to_remove_continuous = self._calculate_water_removal(feed_stream) # kg/hr

        # Calculate total mass processed by the entire plant in one batch cycle duration
        total_feed_mass_per_batch_plant = feed_stream.F_mass * self.batch_time # kg
        total_water_removed_per_batch_plant = water_to_remove_continuous * self.batch_time # kg

        # Handle no feed case
        if total_feed_mass_per_batch_plant == 0:
            self.N_vessel = 1
            self._shelf_area_per_vessel = self.max_area_per_vessel # Default to max for costing a single unit
            self.parallel['self'] = self.N_vessel
            return
        
        # --- Calculate shelf area required for product loading (plant-wide) ---
        # Volume of feed per batch for the entire plant
        volume_feed_per_batch_plant = total_feed_mass_per_batch_plant / 1000 # m3
        total_shelf_area_required = (volume_feed_per_batch_plant / self.sample_thickness) / self._SAMPLE_PACKING_FACTOR
        st.write(total_feed_mass_per_batch_plant, feed_stream.F_mass, self.batch_time)

        # Determine number of vessels and area per vessel
        self.N_vessel = math.ceil(total_shelf_area_required / self.max_area_per_vessel)
        if self.N_vessel == 0: self.N_vessel = 1 # Ensure at least one vessel
        self._shelf_area_per_vessel = total_shelf_area_required / self.N_vessel
        
        self.parallel['self'] = self.N_vessel # For Biosteam's parallel unit costing

    def _run(self):
        self.heat_utilities = [self.wastewater, self.steam]
        feed = bst.Stream()
        feed.mix_from(self.ins) # This is the total continuous feed to the plant
        condensed_water_out, dried_product_out = self.outs

        # Calculate N_vessel and _shelf_area_per_vessel based on continuous feed
        self._calculate_vessel_count(feed)

        # If no feed, empty outputs and return
        if feed.F_mass == 0:
            return

        # --- Continuous Mass Balance for the entire plant ---
        # Calculate water to be removed continuously (kg/hr)
        water_to_remove_continuous = self._calculate_water_removal(feed)

        # Assign components and flow rates to output streams
        dried_product_out.copy_like(feed)
        dried_product_out.imass['Water'] -= water_to_remove_continuous
        dried_product_out.T = 273+15
        dried_product_out.P = 101325 # Atmospheric pressure for dried product discharge

        condensed_water_out.imass['Water'] = water_to_remove_continuous
        # Ensure only water in condensed_water_out (if other components were mixed in feed)
        for chem_ID in condensed_water_out.chemicals.IDs:
            if chem_ID != 'Water':
                condensed_water_out.imass[chem_ID] = 0

    def _design(self):
        
        """Design the pressure vessel, shelves, and auxiliary equipment."""
        # Design main vessel (diameter and length) based on total shelf area required per vessel
        d_m = 2 * (self._shelf_area_per_vessel / (self._SHELF_PACKING_FACTOR * math.pi))**0.5
        self.D = max(4.0, design.ceil_half_step(d_m * 3.28084)) # D in ft
        self.L = self.D / self.diameter_to_length_ratio # L in ft

        # Calculate vessel dimensions and weight using Biosteam's PressureVessel design tool
        # Removed vessel_material keyword argument for 2.14 compatibility
        self.vessel_type = 'Horizontal'
        self.design_results.update(self._vessel_design(self.sublimation_P, self.D, self.L))
        self.design_results['Shelf Area (per vessel)'] = self._shelf_area_per_vessel
        self.design_results['Number of vessels'] = self.N_vessel
        vessel_volume_m3 = (math.pi * (self.D*0.3048/2)**2 * (self.L*0.3048)) # m3
        self.design_results['Vessel Volume (m3)'] = vessel_volume_m3

    def _cost(self):
        self.P = 101325
        """Calculate the purchase cost of the freeze dryer system and its utilities."""
        vessel_design = self.design_results
        
        # --- Capital Expenditure (CAPEX) ---
        #self, pressure, diameter, length, annular_diameter=0
        # 1. Main Freeze-Dryer Vessel Cost (scaled by self.parallel automatically)
        # Removed vessel_material keyword argument for 2.14 compatibility
        self.baseline_purchase_costs.update(self._vessel_purchase_cost(
            weight=vessel_design['Weight'], diameter=vessel_design['Diameter'], length=vessel_design['Length']))
        
        # 2. Shelves Cost (scaled by self.parallel automatically)
        self.baseline_purchase_costs['Shelves'] = (self._SHELF_COST_FACTOR * self._shelf_area_per_vessel**0.6 * (bst.CE / 600))

        # 3. Condenser Cost (calculated directly based on area for 2.14)
        condenser_area_per_vessel_m2 = 0.014
        if condenser_area_per_vessel_m2 == 0: condenser_area_per_vessel_m2 = self._CONDENSER_BASE_AREA_M2 # Avoid 0 for scaling
        
        condenser_cost_per_unit = (
            self._CONDENSER_BASE_COST_USD *
            (condenser_area_per_vessel_m2 / self._CONDENSER_BASE_AREA_M2)**self._CONDENSER_SCALING_EXPONENT) * (bst.CE / 600)
        self.baseline_purchase_costs['Condenser'] = condenser_cost_per_unit



        # 5. Shelf Heater/Cooler Cost (scaled by self.parallel automatically)
        self.baseline_purchase_costs['Shelf heater/cooler'] = 0.2 * self.baseline_purchase_costs['Shelves'] # Heuristic

        # --- Operational Expenditure (OPEX) - Utilities ---

        self.power_utility.rate += self._shelf_area_per_vessel * self.specific_power * self.N_vessel * (self.tau_sublimation / self.batch_time)
        
        # Assign steam duty
        self.steam.load_agent(bst.HeatUtility.get_agent(self.heat_id))
        self.steam.flow = self.outs[0].F_mass / self.N_vessel * self.steam_specific_amount
        self.steam.duty = self.steam.flow * 2200 / 3600 # steam
        self.steam.cost = self.steam.flow * bst.HeatUtility.get_agent(self.heat_id).regeneration_price
        
        self.wastewater.load_agent(bst.HeatUtility.get_agent(self.wastewater_id))
        self.wastewater.flow = self.outs[0].F_mass / self.N_vessel
        self.wastewater.duty = self.outs[0].F_mass / self.N_vessel
        self.wastewater.cost = self.wastewater.flow * bst.HeatUtility.get_agent(self.wastewater_id).regeneration_price
