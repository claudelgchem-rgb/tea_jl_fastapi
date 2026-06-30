import numpy as np, pandas as pd, sys, os, json, copy, string, pickle, math
import streamlit as st

import biosteam as bst
from biosteam import Unit, Stream, settings, main_flowsheet
import thermosteam as tmo

from .Biosteam_custom_unit import *
from .aux_chemical import *
bst.Stream.display_units.flow = 'kg/hr'

# 2. Set global preference to kg/hr (optional but recommended for your case)

# --- Base variables ---
base_dir='/home/sbf/JLee/test/data/biosteam/'
hd = ['Name', 'Formula', 'Price (USD/kg)', 'Cp (J/g/K)', 'Phase', 'Density (kg/m3)', 'MW', 'Hf (J/mol)', 'Tm (K)', 'Tb (K)', 'Tt (K)','Pt (Pa)']
optional_col = {'Tm (K)':273.15,'Tb (K)':373.12, 'Tt (K)':273.16, 'Pt (Pa)':611.65 ,'Cp (J/g/K)':4.1806, 'Hf (J/mol)':-2.8582e5, 'Density (kg/m3)':1000, 'Phase':'l'}

def fast_copy(obj):
    if hasattr(obj, 'asdict'):
        return obj.__class__.from_dict(json.loads(json.dumps(obj.asdict())))
    return json.loads(json.dumps(obj))
    

def session_state_to_spec_data(input_var, nodes):
    st.session_state.spec_data = {}
    for i, node in nodes.items():
        st.session_state.spec_data[i] = {'type':node['node_type'], 'data':copy.deepcopy(input_var[node['node_type']])}
        st.session_state.spec_data[i]['data'].update(add_spec_data(node))
    
def add_spec_data(node):
    unit_data = {}
    if node['node_type'] in ['연속 피드', '배치 피드']:
        unit_data['T'] = float(node['Value']['Temperature [C]'])+273.15
        unit_data['P'] = float(node['Value']['Pressure (Pa)'])
        
    elif node['node_type']=='발효기':
        unit_data['ferm_T'] = float(node['Value']['Temperature [C]'])+273.15
        unit_data['tau'] = float(node['Value']['Time [h]'])
        unit_data['init_OD'] = float(node['Value']['init_OD'])
        unit_data['final_OD'] = float(node['Value']['final_OD'])
        #unit_data['reactions'] = tmo.Reaction(node['Value']['Reaction'], reactant=node['Value']['Main reactant'], X=float(node['Value']['Conversion rate']))
        try:
            del unit_data['ID']
        except:
            pass

        #unit_data['chemical'] = float(node['Value']['Solvent'])
        try:
            unit_data['chemical'] = st.session_state.chemicals[node['Value']['Solvent']]
        except:
            unit_data['chemical'] = tmo.Chemical('Water')

    #elif node['node_type']=='동결건조기':
    #    unit_data['T'] = float(node['Value']['Temperature [C]'])+273.15
    #    unit_data['condenser_T'] = float(node['Value']['Condense_Temperature [C]'])+273.15
    #    unit_data['P'] = float(node['Value']['Pressure (Pa)'])
    #    unit_data['holdup_time'] = float(node['Value']['Time [h]'])
    #    unit_data['surge_time'] = float(node['Value']['CIP Time [h]']) 
    #    unit_data['sample_thickness'] = float(node['Value']['sample_thickness [cm]'])/100

    return unit_data

def run_biosteam2(nodes, edges, solutions, feat_data, batch_time):
    """
    1. Create Solutions stream, tank and heat exchanger
    2. Create streams for fermenter
    3. Rescale fermeters based on OD
    4. Connect other units
    """
    bst.main_flowsheet.clear()
    Stream_data={}
    Solution_data = {}
    Unit_data = {}
    chem_data = st.session_state.chem_data
    chem_mass = {}

    for hu, price in st.session_state.heat_utility.items():
        if hu not in [a.ID for a in bst.HeatUtility.heating_agents]:
            bst.HeatUtility.heating_agents.append(bst.UtilityAgent(hu, regeneration_price = price, T=298, Water=1))
        bst.HeatUtility.get_agent(hu).regeneration_price = price

    #1. Create solutions
    autoclave, solutions0, price_data = solutions

    sol_mass = {i:{} for i in solutions0}
    for i,sol in solutions0.items():
        solx = fill_water3(sol,1)
        Solution_data[f"{i}_raw"] = bst.Stream(f"{i}_raw",units='kg/hr', T=298, P=101325, phase='l')
        for chem,mass in sol.items():
            Solution_data[f"{i}_raw"].imass[chem] = mass
        Solution_data[f"{i}_tank"] = bst.units.StorageTank(f"{i}_tank", ins=Solution_data[f"{i}_raw"], tau = batch_time, kW_per_m3=0)
        if autoclave[i]:
            Unit_data[f"{i}_heat_exchanger"] = BatchHeatExchanger(f"{i}_heat_exchanger", ins = Solution_data[f"{i}_tank"].outs[0], scale_factor = batch_time, T=Solution_data[f"{i}_tank"].outs[0].T)
            Solution_data[f"{i}_split"] = CustomSplitter(f"{i}_split", ins=Unit_data[f"{i}_heat_exchanger"].outs[0])
        else:
            Solution_data[f"{i}_split"] = CustomSplitter(f"{i}_split", ins=Solution_data[f"{i}_tank"].outs[0])

    #2. Rescale fermenter (아직 fermenter unit 만들기 전이지만 미리 stream_flow에 대해 scaling 작업 진행)
        # 1) Edge source와 target이 전부 fermenter인 경우 -dilution이 필요한 경우- 찾기
        # 2) 1에 대해 previous biomass와 post biomass를 계산하고 이에 따라 int/out mass 조절
        # 차가 0이 될때까지 2 반복
    dilution_units = []
    for edge_source, edge_target2 in edges.items():
        for edge_target in edge_target2:
            if nodes[edge_source]['node_type']=='발효기' and nodes[edge_target]['node_type']=='발효기':
                dilution_units.append([edge_source, edge_target])

    diff = len(dilution_units)
    iterx = 0
    while abs(diff) > 1e-5:
        diff = 0
        iterx += 1
        for edge_source,edge_target in dilution_units:
            final_prev_od_amount = nodes[edge_source]['Value']['final_vol'] * nodes[edge_source]['Value']['final_OD']
            initial_post_od_amount = (nodes[edge_target]['Value']['initial_vol'] + nodes[edge_source]['Value']['final_vol']) * nodes[edge_target]['Value']['init_OD']
            diff +=abs(initial_post_od_amount / final_prev_od_amount -1)
            scale_factor = nodes[edge_target]['Value']['initial_vol'] * nodes[edge_target]['Value']['init_OD']/nodes[edge_source]['Value']['final_vol'] / (nodes[edge_source]['Value']['final_OD'] - nodes[edge_target]['Value']['init_OD'])
            # scale down both in / out mass and volume
            nodes[edge_source]['Value']['final_vol'] *= scale_factor
            nodes[edge_source]['Value']['initial_vol'] *= scale_factor
            nodes[edge_source]['Value']['feed_vol'] *= scale_factor
            for s in nodes[edge_source]['Value']['stream_flow']:
                for chem in nodes[edge_source]['Value']['stream_flow'][s]:
                    nodes[edge_source]['Value']['stream_flow'][s][chem] *= scale_factor
            for chem in nodes[edge_source]['Value']['in_mass']:
                nodes[edge_source]['Value']['in_mass'][chem] *= scale_factor
                nodes[edge_source]['Value']['out_mass'][chem] *= scale_factor
        if iterx==100:
            diff=0
            st.write('max reached')
    #for edge_source,edge_target in dilution_units:
    #    st.write('source', nodes[edge_source]['Value']['initial_vol'], nodes[edge_source]['Value']['final_vol'], nodes[edge_target]['Value']['initial_vol'])
        

    #3. Make units
    for i,node in nodes.items():
        if node['node_type']=='연속 피드':
            Stream_data[i] = bst.Stream(ID=node['content'], units='kg/hr', T=298, P=101325)
            for chem,flow in node['Value']['Concentration [g/L]'].items():
                Stream_data[i].imass['l',chem] = float(flow)/1000 * float(node['Value']['Flow [L/hr]'])
                Stream_data[i].price += float(Stream_data[i].imass[chem]) * chem_data['Price (USD/kg)'][chem]
            Stream_data[i].price /= Stream_data[i].F_mass
        elif node['node_type']=='폐기물':
            Stream_data[i] = bst.MultiStream(node['content'], units='kg/hr', T=298, P=101325, phases=['l','s','g']) #Convert it to wastewater treatment or waste treatment
        elif node['node_type']=='Product Stream': 
            Stream_data[i] = bst.Stream(node['content'], units='kg/hr', T=298, P=101325)
            
        # Units
        elif node['node_type']=='발효기':
            # Stream 데이터와 연결하기
            Unit_data[f"{i}_mixer"] = bst.units.Mixer(ID=f"{i}_mixer", ins=[])
            # 없으면 reaction string 만들기
            if i not in st.session_state.reactions:
                st.session_state.reactions[i] = ''
            #Unit_data[i] = Custom_fermenter3(ID=f"{i}_fermenter", ins=[Unit_data[f"{i}_mixer"].outs[0]], out_mass = node['Value']['out_mass'], in_mass = node['Value']['in_mass'], initial_vol=node['Value']['initial_vol'], final_vol=node['Value']['final_vol'], reactions=st.session_state.reactions[i], main_reactant=node['Value']['Main reactant'], batch_time=batch_time,**feat_data[i]['data'], )
            Unit_data[i] = Custom_fermenter3(ID=node['content'], ins=[Unit_data[f"{i}_mixer"].outs[0]], **node['Value'])
            for s, chem_mass in node['Value']['stream_flow'].items():
                sol_mass[s][i] = 0
                Solution_data[f"{i}_{s}_stream"] = bst.Stream(f"{i}_{s}",units='kg/hr', T=298, P=101325)
                Solution_data[f"{s}_split"].outs.append(Solution_data[f"{i}_{s}_stream"])
                for k in chem_mass:
                    sol_mass[s][i] += chem_mass[k] # Add mass required
                
                Unit_data[f"{i}_mixer"].ins.append(Solution_data[f"{i}_{s}_stream"])
            
        elif node['node_type']=='발효/정제 분리선': # Blank unit to specify End of fermentation
            Unit_data[i] = bst.units.Mixer(ID='발효/정제 분리선', ins=[], outs=[])
        elif node['node_type']=='증발기':
            Unit_data[i] = MVR(node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='동결건조기':
            Unit_data[i] = FreezeDryer2(node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='믹싱 탱크':
            Unit_data[i] = bst.units.MixTank(node['content'], ins=[])
        elif node['node_type']=='원심분리기':
            Unit_data[i] = bst.units.SolidsCentrifuge(node['content'], split=node['Value']['split'])
        elif node['node_type']=='MVR':
            Unit_data[i] = MVR(ID=node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='HIC column':
            Unit_data[i] = HIC_Column(ID=node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='IEX column':
            Unit_data[i] = IEX_Column(ID=node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='DiaFiltration':
            Unit_data[i] = Diafiltration(ID=node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='gel_filtration':
            Unit_data[i] = gel_filtration(ID=node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='SMB_Chromatography':
            Unit_data[i] = SMB_Column(ID=node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='용액처리기':
            Unit_data[i] = sol_processor(ID=node['content'], ins=[], outs=[], **node['Value'])
        elif node['node_type']=='Distillation':
            Unit_data[i] = custom_distillation(ID=node['content'], ins=[], outs=[], **node['Value'])
        
            
    for edge_source, edge_target2 in edges.items():
        for edge_target in edge_target2:
            if edge_source in Stream_data.keys():
                Unit_data[edge_target].ins.append(Stream_data[edge_source])
            elif nodes[edge_target]['node_type'] in ['Product Stream']:
                if nodes[edge_source]['node_type'] in ['발효기', '동결건조기','MVR', '증발기']:
                    Unit_data[edge_source].outs[1] = Stream_data[edge_target]
                elif nodes[edge_source]['node_type'] in ['발효/정제 분리선','믹싱 탱크','Heater', 'Mixer','HIC column', 'IEX column', 'DiaFiltration','gel_filtration', '용액처리기','Distillation']:
                    Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                elif nodes[edge_source]['node_type'] in ['원심분리기']:
                    if nodes[edge_source]['Value']['Product'] == 'Solid':
                        Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                    else:
                        Unit_data[edge_source].outs[1] = Stream_data[edge_target]
                else:
                    st.write(nodes[edge_source], nodes[edge_source]['node_type'],'Unknown type')
            elif nodes[edge_target]['node_type'] in ['폐기물']:
                if nodes[edge_source]['node_type'] in ['동결건조기']:
                    Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                elif nodes[edge_source]['node_type'] in ['원심분리기']:
                    if nodes[edge_source]['Value']['Product'] == 'Solid':
                        Unit_data[edge_source].outs[1] = Stream_data[edge_target]
                    else:
                        Unit_data[edge_source].outs[0] = Stream_data[edge_target]
                else:
                    st.write(nodes[edge_source], nodes[edge_source]['node_type'], 'waste goes to nowhere')

            # 2nd output from fermenter go to unit (1st is gas)
            elif nodes[edge_source]['node_type'] in ['발효기', '동결건조기','MVR', '증발기']:
                #Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[1])
                if nodes[edge_target]['node_type'] in ['Heater','HIC column','IEX column', 'DiaFiltration','gel_filtration','SMB_Chromatography', '용액처리기', 'Distillation']:
                    Unit_data[edge_target].ins[0]=Unit_data[edge_source].outs[1]
                else:
                    #st.write(nodes[edge_target]['content'])
                    Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[1])
            # 1st output from evaporator go to unit
            elif nodes[edge_source]['node_type'] in ['발효/정제 분리선', '믹싱 탱크', 'Heater', 'HIC column', 'IEX column', 'DiaFiltration', 'gel_filtration', 'SMB_Chromatography', '용액처리기', 'Distillation']:
                if nodes[edge_target]['node_type'] in ['Heater', 'HIC column', 'IEX column', 'DiaFiltration', 'gel_filtration', 'SMB_Chromatography', '용액처리기', 'Distillation']:
                    Unit_data[edge_target].ins[0]=Unit_data[edge_source].outs[0]
                else:
                    #st.write(nodes[edge_target]['content'])
                    Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[0])
        
            # Waste and product stream should have gone in previous line
            # Assume all output from 원심분리기 goes to other unit at this point
            elif nodes[edge_source]['node_type'] in ['원심분리기']:
                if nodes[edge_source]['Value']['Product'] == 'Solid':
                    if nodes[edge_target]['node_type'] in ['Heater', 'MVR', 'HIC column', 'IEX column', 'DiaFiltration', 'gel_filtration', 'SMB_Chromatography', '용액처리기', 'Distillation']:
                        Unit_data[edge_target].ins[0]=Unit_data[edge_source].outs[0]
                    else:
                        #st.write(nodes[edge_target]['content'])
                        Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[0])
                else:
                    if nodes[edge_target]['node_type'] in ['Heater', 'MVR', 'HIC column', 'IEX column', 'DiaFiltration', 'gel_filtration', 'SMB_Chromatography', '용액처리기', 'Distillation']:
                        Unit_data[edge_target].ins[0]=Unit_data[edge_source].outs[1]
                    else:
                        #st.write(nodes[edge_target]['content'])
                        Unit_data[edge_target].ins.append(Unit_data[edge_source].outs[1])
            else:
                st.write(nodes[edge_source], 'leads to nowhere')

    # update solution data
    f_vol = 0
    for i in sol_mass:
        mass = 0
        tmp = []
        for s in sol_mass[i]:
            mass += sol_mass[i][s]
            tmp.append(sol_mass[i][s])
        if mass>1e-6:
            #Solution_data[f"{i}_raw"].F_mass = mass
            Solution_data[f"{i}_raw"].F_mass = mass / batch_time
            Solution_data[f"{i}_raw"].price = price_data[i] * Solution_data[f"{i}_raw"].F_mass
            Solution_data[f"{i}_split"].split_ratio = tmp
            f_vol += mass / batch_time
        else:
            Solution_data[f"{i}_raw"].F_mass = mass / batch_time
            Solution_data[f"{i}_raw"].price = price_data[i] * Solution_data[f"{i}_raw"].F_mass
            Solution_data[f"{i}_split"].split_ratio = tmp

    # clean tank
    #Stream_data['tank_cleaner'] = bst.Water('water_for_waste', Water=1)
    #Stream_data['tank_cleaner'].F_mass = f_vol * 1.2
    #Unit_data['tank_cleaner'] = waste_unit('waste_unit', ins=Stream_data['wastewater'])
            
    ferm_sys = bst.main_flowsheet.create_system('ferm_sys')
    ferm_sys.simulate()
    ferm_sys.operating_hours = float(st.session_state.operating_hours)
    st.session_state.ferm_sys = ferm_sys
    for i in ferm_sys.units:
        if hasattr(i,'reactions'):
            st.session_state.reactions[i.ID[:-10]] = i.reactions
    return ferm_sys

def scale_up_system(ferm_sys,main_product, target_amount, nodes):
    # 1. Define product stream
    
    pid = [node['content'] for i, node in nodes.items() if node['node_type']=='Product Stream']
    product_stream = [bst.main_flowsheet.stream[i] for i in pid]
    # 2. Get target amount
    product_amount = sum([s.imass[st.session_state.main_product] * float(st.session_state.operating_hours) for s in product_stream])
    if product_amount==0:
        product_amount = 0.00001
    scale_factor = target_amount / product_amount
    # 3. Scale every input
    for i in ferm_sys.ins:
        i.scale(scale_factor)
    st.write('scale factor', scale_factor)
    for unit in bst.main_flowsheet.unit:
    # Reset power (kW)
        unit.power_utility.empty()
    # Reset all heat utilities (Duty, Flow, Cost)
    for hu in unit.heat_utilities:
        hu.empty()
    
    ferm_sys.simulate()
    return ferm_sys


def get_upstream_feeds(ferm_system):
    target_unit = bst.main_flowsheet.unit['발효/정제 분리선']
    strictly_upstream_units = set()
    visited_units_for_traversal = set()
    def _find_predecessors(current_unit):
        if current_unit.ID in visited_units_for_traversal:
            return
        visited_units_for_traversal.add(current_unit.ID)

        for s_in in current_unit.ins:
            if s_in.source: # If the input stream comes from another unit
                source_unit = s_in.source
                strictly_upstream_units.add(source_unit)
                _find_predecessors(source_unit)

    for s_in_target in target_unit.ins:
        if s_in_target.source:
            _find_predecessors(s_in_target.source)

    external_feeds = set()
    for unit in strictly_upstream_units:
        for s_in in unit.ins:
            if s_in.source is None: # It's a system input (no unit source)
                external_feeds.add(s_in)
            elif s_in.source not in strictly_upstream_units:
                external_feeds.add(s_in)
                
    stream_price = get_chem_price(external_feeds)
    upstream_price, upstream_c_price = get_c_source(stream_price, source=['Glucose','Glycerol','Methanol', st.session_state.main_source])

    return upstream_price, upstream_c_price, strictly_upstream_units

    
def get_upstream(ferm_sys):
    # 1. Find End of fermentation point
    unit = bst.main_flowsheet.unit['발효/정제 분리선']
    system = bst.main_flowsheet.create_system('upstream', ends=[unit])
    stream_amount = get_chem_price(system.ins)
    #st.write('upstream',system.ins)
    upstream_amount, upstream_c_amount = get_c_source(stream_price, source=['Glucose','Glycerol','Methanol', st.session_state.main_source])
    
    return upstream_price, upstream_c_price

def get_chem_price(streams,chem={}, operating_hours=7820):
    if chem=={}:
        chem = st.session_state.chem_data
    chem_amount = {i:0 for i in st.session_state.chemical_list}
    for s in streams:
        for c in chem_amount:
            #chem_amount[c] += s.imass[c] * float(operating_hours) * float(chem['Price (USD/kg)'][c])
            chem_amount[c] += s.imass[c] * float(st.session_state.operating_hours)
    return chem_amount

def get_c_source(chem_data, source=['Glucose','Glycerol','Methanol']):
    c_stream={}
    non_c_stream = {}
    for i,data in chem_data.items():
        if i in source:
            c_stream[i] = data
        else:
            non_c_stream[i] = data
    return non_c_stream, c_stream

def chem_dict_to_pd(chem,target_amount):
    data = {i:{} for i in ['원단위','단가','제조원가']}
    chem_data = st.session_state.chem_data
    for i,amount in chem.items():
        if amount!=0:
            #data['원단위'][i]=price/target_amount*1000
            data['원단위'][i] = amount/target_amount
            data['제조원가'][i] = amount * float(chem_data['Price (USD/kg)'][i])/target_amount*1000
            data['단가'][i] = chem_data['Price (USD/kg)'][i]

    data = pd.DataFrame(data)
    return data


def get_batch_time(nodes):
    batch_time = 0
    for i,node in nodes.items():
        batch_unit = 0
        for j in node['Value'].keys():
            if 'tau' in j:
                batch_unit +=node['Value'][j]
        if batch_unit >=batch_time:
            batch_time = batch_unit
    return batch_time


def price_system(ferm_sys):
    chem_data = st.session_state.chem_data
    for stream in ferm_sys.ins:
        stream.price = 0
        for chem in stream.chemicals:
            stream.price +=stream.imass[chem.ID] * chem_data['Price (USD/kg)'][chem.ID]
    return ferm_sys
