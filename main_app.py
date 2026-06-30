import numpy as np, pandas as pd, sys, os, json, copy, string, pickle, math
import streamlit as st

import streamlit_flow
from streamlit_flow.elements import StreamlitFlowNode, StreamlitFlowEdge
from streamlit_flow.state import StreamlitFlowState
import time

import biosteam as bst
from biosteam import Unit, Stream, settings, main_flowsheet
import thermosteam as tmo

from pages.flow_tabs.Biosteam_custom_unit import *
from pages.flow_tabs.aux_chemical import *
from pages.flow_tabs.util_bfd_Copy4 import * # This should be the name of your modified file
from pages.flow_tabs.util_biosteam_Copy1 import *

from contextlib import contextmanager
@contextmanager
def timer(label):
    t = time.perf_counter()
    yield
    print(f"⏱ {label}: {(time.perf_counter() - t)*1000:.0f} ms")


st.set_page_config(layout="wide")
st.markdown(
    """
<style>
    /* A. Your Dataframe styling */
    .dataframe table { 
        font-family: Consolas, "Courier New", monospace; 
    }
    
    /* B. TARGET ONLY THE INNERMOST CONTAINER HOLDING THE MARKER */
    div[data-testid="stVerticalBlock"]:has(div.wrap-my-buttons):not(:has(div[data-testid="stVerticalBlock"] div.wrap-my-buttons)) {
        flex-direction: row !important;
        flex-wrap: wrap !important;
        gap: 8px !important; /* Spacing between buttons */
    }

    /* Force only the direct children of this innermost container to be auto-width */
    div[data-testid="stVerticalBlock"]:has(div.wrap-my-buttons):not(:has(div[data-testid="stVerticalBlock"] div.wrap-my-buttons)) > div {
        width: auto !important;
    }
    
    /* FIX: Completely hide ONLY the first child (the marker wrapper) so it takes 0px space */
    div[data-testid="stVerticalBlock"]:has(div.wrap-my-buttons):not(:has(div[data-testid="stVerticalBlock"] div.wrap-my-buttons)) > div:first-child {
        display: none !important;
    }

    /* C. STYLE ONLY THE BUTTONS INSIDE THIS SPECIFIC CONTAINER */
    div[data-testid="stVerticalBlock"]:has(div.wrap-my-buttons):not(:has(div[data-testid="stVerticalBlock"] div.wrap-my-buttons)) button {
        border: 2px solid #4F8BF9 !important; /* 2px thickness, Blue color */
        color: #4F8BF9 !important;            /* Match text color to border */
        background-color: white !important;   /* Clean white background */
        border-radius: 8px !important;        /* Rounded corners */
        transition: all 0.2s ease-in-out;
    }

    /* Hover effect for these buttons */
    div[data-testid="stVerticalBlock"]:has(div.wrap-my-buttons):not(:has(div[data-testid="stVerticalBlock"] div.wrap-my-buttons)) button:hover {
        border-color: #FF4B4B !important;     /* Changes to red on hover */
        color: #FF4B4B !important;            /* Text changes to red on hover */
        background-color: #FFF0F0 !important; /* Soft red background on hover */
    }
</style>
""",
    unsafe_allow_html=True,
)

if 'run_biosteam' not in st.session_state:
    st.session_state.run_biosteam = False
    st.session_state.scaled_system = {}

bst.CE = 806.7
lang_factor = 3.14285714285

### Need to change where data is stored
base_dir = '/home/sbf/JLee/test/data/scenario/'
node_image_dir = '/home/sbf/JLee/test/data/node_image/'

hd = ['Name', 'Formula', 'Price (USD/kg)', 'Phase']
@st.cache_resource(ttl=3600)
def load_all_unit_defaults(base_dir):
    with open(base_dir+'initial_val.json', 'r') as f:
        init_value = json.load(f)
    return init_value

# st.cache_resource(ttl=3600) # This should be @st.cache_data for functions that return data, not resources
def load_data(template):
    with open(base_dir+template+'.pkl','rb') as f:
        raw_data = pickle.load(f)
    st.session_state.tmp = raw_data['tmp']
    st.session_state.flow_state = StreamlitFlowState(nodes=raw_data['nodes'], edges=raw_data['edges'])
    st.session_state.selected_id_old = None # This is still used for style application in the old aux_flow.py, but now the main util_bfd3.py handles selected_id directly from flow_state
    st.session_state.flow_state.selected_id = raw_data.get('selected_id', None) # Load selected_id if saved
    st.session_state.flow_rev = raw_data.get('flow_rev', 0) # Load flow_rev if saved
    st.session_state.flow_state.timestamp = raw_data.get('timestamp', 0) # Load timestamp if saved
    st.session_state.solutions = raw_data.get('solutions', {})
    st.session_state.autoclave = raw_data.get('autoclave', {})
    st.session_state.prices = raw_data.get('prices', {})
    st.session_state.proceed3 = False
    load_chem_data = raw_data['chem_data']
    st.session_state.uploader_key +=1
    st.session_state.chemicals, st.session_state.chem_data = process_chemical_data(load_chem_data)
    st.session_state.heat_utility = raw_data.get('heat_utility', {})
    st.session_state.currency = st.session_state.tmp.get('currency',1500)
        
    st.session_state.chemical_list = [i.ID for i in st.session_state.chemicals]
    st.session_state.main_product = raw_data.get('main_product', st.session_state.chemical_list[st.session_state.tmp['product_index']])
    st.session_state.main_source = raw_data.get('main_source', st.session_state.chemical_list[st.session_state.tmp['source_index']])
    st.session_state.target_amount = raw_data.get('target_amount', st.session_state.tmp['target_amount'])
    st.session_state.gmp = raw_data.get('gmp', st.session_state.get('gmp',True))

    try:
        st.session_state.electricity_price = st.session_state.tmp['electricity_price']
    except:
        pass

    st.rerun()


if 'gmp' not in st.session_state:
    st.session_state.gmp = True

# --- Session State Initialization ---
# Initialize session state variables if they don't exist.
if 'uploader_key' not in st.session_state:
    st.session_state.all_unit_defaults = load_all_unit_defaults(base_dir)        
    st.session_state.uploader_key = 0
    st.session_state.proceed = False
    st.session_state.proceed2 = False
    st.session_state.proceed3 = False
    st.session_state.simulation_ran = False
    st.session_state.reactions = {}
    st.session_state.node_select = None
    st.session_state.solutions = {} # Should be in initial_val.pkl but for placeholder
    st.session_state.autoclave = {}
    st.session_state.prices = {}
    st.session_state.flow_state = StreamlitFlowState(nodes=[], edges=[], selected_id=None) # Initialize with selected_id=None
    st.session_state.selected_id_old = None # This is a legacy state variable, keep it for now if your code relies on itF
    st.session_state.flow_rev = 0
    st.session_state.flow_state.timestamp = 0
    st.session_state.tmp = st.session_state.all_unit_defaults['tmp']
    st.session_state.currency = st.session_state.all_unit_defaults['tmp'].get('currency',1500)
    st.session_state.operating_hours = st.session_state.all_unit_defaults['tmp']['operating_hours']
    st.session_state.heat_utility = st.session_state.all_unit_defaults['heat_utility']

    initialize_flowstate()
    load_data('initial_val')

upload_chemical2()

if 'currency' not in st.session_state or st.session_state.currency==0 or st.session_state.currency == None:
    st.session_state.currency = 1.0

save_col = st.columns([.4,.4,.2])
with save_col[0]:
    template = st.text_input("Save data as", 'Data')
    if st.button("Save Data"):
        with open(base_dir + template+'.pkl','wb') as f:
            raw_data = {}

            #raw_data['chemicals'] = st.session_state.chemicals
            raw_data['chem_data'] = st.session_state.chem_data
            raw_data['solutions'] = st.session_state.solutions
            raw_data['autoclave'] = st.session_state.autoclave
            raw_data['prices'] = st.session_state.prices
            raw_data['nodes']= st.session_state.flow_state.nodes
            raw_data['edges']= st.session_state.flow_state.edges
            raw_data['tmp'] = st.session_state.tmp
            raw_data['heat_utility'] = st.session_state.heat_utility
            
            raw_data['gmp'] = st.session_state.get('gmp',True)
            raw_data['electricity_price'] = st.session_state.get('electricity_price',0.128)
            raw_data['od_to_dcw'] = st.session_state.get('od_to_dcw',0.22)
            raw_data['operating_hours'] = st.session_state.get('operating_hours',7920)
            raw_data['target_amount'] = st.session_state.get('target_amount',0.1)
            raw_data['main_product'] = st.session_state.get('main_product','Collagen')
            raw_data['main_source'] = st.session_state.get('main_source','Glucose')

            pickle.dump(raw_data,f)
            
with save_col[1]:
    tmp=[i[:-4] for i in os.listdir(base_dir) if i[-3:]=='pkl']
    map_id = st.selectbox("Data File: ",tmp)
    if st.button("Load data"):
        st.session_state.proceed = True
        st.session_state.proceed2 = True
        load_data(map_id)
        st.rerun() # Rerun after loading data and renderers
with save_col[2]:
    if st.button("Force reload default value"):
        with open(base_dir+'initial_val.json', 'r') as f:
            st.session_state.all_unit_defaults = json.load(f)
        st.rerun()


st.divider()
if 'chemical_list' not in st.session_state:
    st.header(':red[물질 등록]')
else:
    col1,col2 = st.columns([.7,.3], gap="medium", vertical_alignment="center", width="stretch")
    with col1:
        chemicals = st.session_state.chemical_list
        #main_product = st.selectbox("Target product",chemicals, index=st.session_state.tmp['product_index'], key='main_product')
        #main_source = st.selectbox("탄소원", chemicals, index=st.session_state.tmp['source_index'], key='main_source')
        #target_production = st.number_input("MT/year",value=st.session_state.tmp['target_amount'],key='target_amount')
        main_product = st.selectbox("Target product",chemicals, index=st.session_state.tmp['product_index'], key='main_product')
        main_source = st.selectbox("탄소원", chemicals, index=st.session_state.tmp['source_index'], key='main_source')
        target_production = st.number_input("MT/year",value=st.session_state.tmp['target_amount'],key='target_amount')
        
    with st.expander("Advanced options"):
        operating_hours = st.number_input('연중 운영시간', value=st.session_state.tmp['operating_hours'], key="operating_hours")
        gmp = st.checkbox('GMP 여부', value = True, key='gmp')
        od_mass = st.number_input('OD별 dry cell weight', value=st.session_state.tmp['od_to_dcw'], key="od_to_dcw")
        st.write('Utilities')
        heat_util = pd.DataFrame.from_dict(st.session_state.heat_utility, orient='index', columns=['price [USD/kg]'])
        heat_util.reset_index(inplace=True,names=['utility'])
        heat_util = st.data_editor(heat_util, num_rows="dynamic", key=f"heat_util", hide_index=True, column_config={'utility': st.column_config.TextColumn(required=True, width='small'), 'price [USD/kg]':st.column_config.NumberColumn(width='small', format="$%.3g", required=True)})

        if 'electricity_price' not in st.session_state.tmp:
            st.session_state.tmp['electricity_price'] = 0.128
        electricity_price = st.number_input('전기 가격(USD/kW)', value=st.session_state.tmp['electricity_price'], key='electricity_price')
        
    if st.button('다음',type='primary',use_container_width=True):
        st.session_state.tmp['product_index'] = chemicals.index(main_product)
        st.session_state.tmp['source_index'] = chemicals.index(main_source)
        st.session_state.tmp['target_amount'] = target_production
        st.session_state.tmp['electricity_price'] = electricity_price
        st.session_state.tmp['operating_hours'] = operating_hours
        st.session_state.tmp['od_to_dcw'] = od_mass
        st.session_state.proceed = True
        for _,row in heat_util.iterrows():
            st.session_state.heat_utility[row['utility']] = row['price [USD/kg]']
        bst.PowerUtility.price = electricity_price
                
    if st.session_state.proceed:
        st.header('용액 등록')
        if 'Water' in st.session_state.solutions:
            num_sol = len(st.session_state.solutions)-1
        else:
            num_sol = len(st.session_state.solutions)
            
        num_sol = st.number_input('용액 수', min_value=0, step=1, key='num_sol', value=max(num_sol,1))
        sol_list = [f"용액 {i+1}" for i in range(num_sol)]

        with st.expander('용액 조성'):
            with st.form("용액 조성"):
                sol_ui = {str(nn):st.columns(4) for nn in range(num_sol//4+1)}
                sol_tmp = {}
                for idx,i in enumerate(sol_list):
                    with sol_ui[str(idx//4)][idx%4]:
                        st.divider()
                        st.write(i)
                        if i not in st.session_state.solutions:
                            sol_tmp[i] = pd.DataFrame({'Name': [''], 'Concentration [g/L]': [0.0]})
                        else:
                            sol_tmp[i] = pd.DataFrame.from_dict(st.session_state.solutions[i],orient='index').reset_index()
                            sol_tmp[i].columns = ['Name', 'Concentration [g/L]']
                        
                        sol_tmp[i] = st.data_editor(
                                    sol_tmp[i], num_rows="dynamic", key=f"{i}_solution", hide_index=True, 
                            column_config={'Name': st.column_config.SelectboxColumn(options=st.session_state.chemical_list, required=True, width='small'), 'Concentration [g/L]':st.column_config.NumberColumn(width='small', format="%.2f", required=True)})
                        st.session_state.autoclave[i] = st.checkbox('멸균 (Autoclave)', value=True, key=f"{i}_autoclave")
                        
                        
                sol_calc = st.form_submit_button("용액 저장", type="primary", use_container_width=True)
                if sol_calc:
                    st.session_state.solutions = {}
                    for idx,i in enumerate(sol_list):
                        st.session_state.solutions[i] = dict(zip(sol_tmp[i]['Name'], sol_tmp[i]['Concentration [g/L]']))
                        st.session_state.solutions[i] = fill_water3(st.session_state.solutions[i],1)
                        st.session_state.prices[i] = 0
                        for chem,mass in st.session_state.solutions[i].items():
                            st.session_state.prices[i] += mass * st.session_state.chem_data['Price (USD/kg)'][chem]
                        st.session_state.solutions['Water'] = {'Water':1000}
                        st.session_state.autoclave['Water'] = False
                        st.session_state.prices['Water'] = float(st.session_state.chem_data['Price (USD/kg)']['Water'])
                        st.session_state.proceed2 = True
                    st.rerun()

if st.session_state.proceed2:
    # Initialize
    flow_cols = st.columns(4, vertical_alignment="center")
    NODE_TYPES = get_node_feature()
    node_list = list(NODE_TYPES.keys())
    with st.container(border=True, gap=None):
        st.markdown('<div class="wrap-my-buttons"></div>', unsafe_allow_html=True)
        for add_button in node_list:
            if st.button(add_button):
                add_node(add_button)
        
    #with flow_cols[0]:
    #    NODE_TYPES = get_node_feature()
    #    node_list = list(NODE_TYPES.keys())
    #    node_in = st.selectbox("Input Node",node_list)
    #    if st.button("Add node"):
    #        add_node(node_in)
    with flow_cols[1]:
        st.write(st.session_state.selected_id_old)
        if st.button('Delete node/edge'):
            delete_node(st.session_state.selected_id_old)

    with flow_cols[3]:
        if st.button('리셋'):
            initialize_flowstate()

    
    
    main_content, second_sidebar = st.columns([2, 1])

    with main_content:
        with st.container(border=True, gap=None):
            new_state = sf_tmp(str(st.session_state.flow_rev), st.session_state.flow_state)
            st.session_state.flow_state = new_state
            if new_state.selected_id is not None:
                st.session_state.selected_id_old = new_state.selected_id
            else:
                st.session_state.selected_id_old = None

    with second_sidebar:
        # 가독성 위해 node.content로 변경. node 이름 체계 바꿨으니 추후에 다시 변경
        #all_element_ids = [i.id for i in st.session_state.flow_state.nodes]
        all_element_ids_content = []
        for i in st.session_state.flow_state.nodes:
            if 'custom_value' in i.data:
                all_element_ids_content.append(i.data['custom_value'])
            else:
                all_element_ids_content.append(i.data['content'])
        #all_element_ids_content = [i.data['content'] for i in st.session_state.flow_state.nodes]
        all_element_ids_raw = [i.id for i in st.session_state.flow_state.nodes]

        selected_node_content_from_flow = None


        if st.session_state.flow_state.selected_id:
            try:
                # Find the content for the currently selected node
                selected_node_idx = all_element_ids_raw.index(st.session_state.flow_state.selected_id)
                selected_node_content_from_flow = all_element_ids_content[selected_node_idx]
            except ValueError:
                pass # Selected ID might not be in the current list of nodes

        # Set the selectbox's default value to the one selected in the flow component
        initial_selectbox_index = None
        if selected_node_content_from_flow in all_element_ids_content:
            initial_selectbox_index = all_element_ids_content.index(selected_node_content_from_flow)
        elif all_element_ids_content: # Default to the first element if nothing is selected or found
            initial_selectbox_index = 0
            
        selected_element_content = st.selectbox(
            'Select Unit', 
            options=all_element_ids_content, 
            index=initial_selectbox_index, 
            key='node_select'
        )

        selected_idx_in_flow_state = None
        current_node_to_edit = None

        if selected_element_content:
            try:
                selected_idx_in_flow_state = all_element_ids_content.index(selected_element_content)
                current_node_to_edit = copy.deepcopy(st.session_state.flow_state.nodes[selected_idx_in_flow_state])
            except ValueError:
                st.warning(f"Node '{selected_element_content}' not found in current flow state.")
        
        if current_node_to_edit:
            with st.form(key=f"edit_node_form_{current_node_to_edit.id}"):
                edited_node_data_from_widgets = edit_node(current_node_to_edit)
                
                submit_button = st.form_submit_button("변경 사항 저장", type="primary", use_container_width=True)
                
                if submit_button:
                    _, processor = get_node_editor_functions(current_node_to_edit.data['node_type'])
                    final_node_value = processor(edited_node_data_from_widgets['Value'])
                    
                    st.session_state.flow_state.nodes[selected_idx_in_flow_state].data['content'] = edited_node_data_from_widgets['content']
                    st.session_state.flow_state.nodes[selected_idx_in_flow_state].data['Value'] = final_node_value
                    st.session_state.flow_state.nodes = st.session_state.flow_state.nodes[:]
                    st.session_state.flow_state.timestamp = time.time()
                    st.session_state.flow_rev +=1
                    st.rerun()

    if st.button("Calculate", type='primary',use_container_width=True):
        st.session_state.proceed3 = True
        st.session_state.run_biosteam = True
#update_fermentation(st.session_state.ferm_option, st.session_state.ferm_data0)
    if st.session_state.proceed3:
        if st.session_state.run_biosteam == True:
            nodes = {}
            edges = {}
            for i in st.session_state.flow_state.nodes:
                nodes[i.id] = i.data

#===========================================================================================
                # Overwrite node content with label
                if 'custom_value' in i.data:
                    nodes[i.id]['content'] = i.data['custom_value']
#===========================================================================================
                    
                #st.write(i.data)
            for i in st.session_state.flow_state.edges:
                if i.source not in edges:#
                    edges[i.source]=[i.target]
                else:
                    edges[i.source].append(i.target)
        
            bst.main_flowsheet.clear()
            batch_time = get_batch_time(nodes)
            st.write('batch_time', batch_time)
            solutions=[st.session_state.autoclave, st.session_state.solutions, st.session_state.prices]
            ferm_sys = run_biosteam2(nodes, edges, solutions=solutions, batch_time=batch_time,feat_data={})
                
            target_amount = float(st.session_state.target_amount) * 1000
            scaled_system  = scale_up_system(ferm_sys,main_product, target_amount, nodes)
            scaled_system = price_system(scaled_system)
            scaled_system.simulate()
            st.session_state.scaled_system = scaled_system
            
        
        else:
            target_amount = float(st.session_state.target_amount) * 1000
            scaled_system = st.session_state.scaled_system


        st.graphviz_chart(scaled_system.diagram(display=False))
        st.session_state.run_biosteam = False
        total_feed_amount = get_chem_price(scaled_system.ins)
        upstream_amount, upstream_c_amount = get_c_source(total_feed_amount, source=['Glucose','Glycerol','Methanol', st.session_state.main_source])
        downstream_amount = {}
    
        total_cost = 0
        #scaled_system = bst.main_flowsheet.create_system('Ferm_sys')
        #scaled_system.simulate()
        # for i in scaled_system.units:
        #     st.subheader(i)
        #     for j in i.outs:
        #         st.write('Out',j, j.F_vol * st.session_state.operating_hours, 'kg/year')
        #     st.write(i.results())
        #     #st.write(i,'\t', i.installed_cost)
        #     #try:
        #     #    for j in i.reactors:
        #     #        st.write(j.design_results)
        #     #except:
        #     #    pass
        #     #pass
           
        etc = {'':[None,None]}

        
        capex_cost = scaled_system.installed_cost * lang_factor * 1.15
        if st.session_state.currency >1:
            labor_cost= 1440000000/target_amount/st.session_state.currency
        else:
            labor_cost= 1440000000/target_amount
        if st.session_state.gmp:
            capex_cost *=5

            
        #수선비=(C7*10^6*0.7/10+C7*10^6*0.3/25)/C6
        deprecation_cost = capex_cost*.082 / target_amount
        repair_cost = capex_cost * 0.05 / target_amount
        # Later read from db
        
    
        pd_up_c_feed = chem_dict_to_pd(upstream_c_amount,target_amount)
        pd_up_feed = chem_dict_to_pd(upstream_amount,target_amount)
        pd_down_feed = chem_dict_to_pd(downstream_amount,target_amount)

        
        #utility = {'전기':[scaled_system.power_utility.rate, bst.PowerUtility.price, scaled_system.power_utility.cost]}
        utility2 = {}
        utility = {'전기':[scaled_system.power_utility.power * float(st.session_state.operating_hours) / (target_amount), bst.PowerUtility.price, scaled_system.power_utility.cost * float(st.session_state.operating_hours)/target_amount*1000]}
        for hu in scaled_system.heat_utilities:
            if hu.flow>0:
                if hu.ID in ['low_pressure_steam','medium_pressure_steam','wastewater','sludge','solid_waste','chilled_water','cooling_water','natural_gas']:
                
                    #utility[hu.agent.ID] = [hu.flow*hu.agent.MW, hu.regeneration_price/hu.agent.MW, hu.cost]
                    utility[hu.agent.ID] = [hu.flow * float(st.session_state.operating_hours) / (target_amount), hu.cost/hu.flow, hu.cost * float(st.session_state.operating_hours)/target_amount*1000]
                elif hu.ID =='cip_water':
                    pd_up_feed['원단위']['Water'] += hu.flow * float(st.session_state.operating_hours) / (target_amount)
                    pd_up_feed['제조원가']['Water'] += hu.flow * float(st.session_state.chem_data['Price (USD/kg)']['Water']) * float(st.session_state.operating_hours)/target_amount*1000
                    
                else:
                    pd_up_feed.loc[hu.agent.ID]=[hu.flow * float(st.session_state.operating_hours) / (target_amount), hu.cost/hu.flow, hu.cost * float(st.session_state.operating_hours)/target_amount*1000]
                    
                    #pd_up_feed['원단위'][hu.agent.ID] = hu.flow * float(st.session_state.operating_hours) / (target_amount)
                    #st.write(pd_up_feed['원단위'][hu.agent.ID])
                    #pd_up_feed['단가'][hu.agent.ID] = hu.cost/hu.flow
                    #pd_up_feed['제조원가'][hu.agent.ID] = hu.cost * float(st.session_state.operating_hours)/target_amount*1000

        pd_util = pd.DataFrame.from_dict(utility,orient='index',columns=['원단위','단가','제조원가'])
        pd_etc = pd.DataFrame.from_dict(etc,orient='index',columns=['원단위','제조원가'])
        merged_opex_pd = pd.concat([pd_up_c_feed, pd_up_feed, pd_down_feed, pd_util], axis=0, keys = ['발효 원재료','발효 부재료','정제 재료','유틸리티'])

        
        capex_pd = pd.DataFrame.from_dict({'감가비': [deprecation_cost, deprecation_cost*1000], '인건비': [labor_cost, labor_cost*1000], '수선비': [repair_cost, repair_cost*1000], '기타':[0,0]}, orient='index', columns=['원단위','제조원가'])
    
        capex_pd['재료'] = ''
        capex_pd = capex_pd.set_index('재료', append=True)

        currency =st.number_input('환율 [₩/USD]', key="currency")
        merge_price_df = pd.concat([merged_opex_pd,capex_pd],axis=0, keys=['변동비','고정비']) * currency
        merge_price_df['원단위'] = merge_price_df['원단위']/currency
        total_sum = np.nansum(merge_price_df['제조원가'])
        merge_price_df['비중'] = merge_price_df['제조원가'] / np.nansum(merge_price_df['제조원가'])
        if currency==1:
            price_hd = [['원단위[kg/kg]','단가[USD/kg]','제조원가[USD]','비중'],[' ',' ','',f"USD {total_sum:,.2f}"],['','',"/톤",'']]
        else:
            price_hd = [['원단위[kg/kg]','단가[₩/kg]','제조원가[₩]','비중'],[' ',' ','',f"₩{total_sum:,.2f}"],['','',"/톤",'']]

        price_hd = pd.MultiIndex.from_tuples(list(zip(*price_hd)), names=["", "총 투자비","capa"])
        merge_price_df.columns=price_hd
        avt_tmp = merge_price_df.groupby(level=1).sum()
        output_index = merge_price_df.index.droplevel(level=2).drop_duplicates()
        avg_price_df = pd.DataFrame(index=output_index, columns=merge_price_df.columns, dtype=float)

        for col in merge_price_df.columns:
        # Get the 'SubCategory' values from the new index and map them to the averages
            avg_price_df[col] = avg_price_df.index.get_level_values(level=1).map(avt_tmp[col])
        columns_to_drop = [col for col in merge_price_df.columns if '단가' in col[0]]
        
        
        
        map_format = {}
        won_format_string = '₩ {:,.3f}' # Example: $12.3k or $12,345
        usd_format_string = 'USD {:,.3f}' # Example: $12.3k or $12,345
        won_format_string2 = '₩ {:,.0f}' # Example: $12.3k or $12,345
        usd_format_string2 = 'USD {:,.0f}' # Example: $12.3k or $12,345
        percentage_format_string = '{:.2%}' # Example: 12.34%
        mass_format_string = '{:,.2f}' # Example: 12.34%
        
        for col_tuple in merge_price_df.columns:
            if col_tuple[0] == '비중':
                map_format[col_tuple] = percentage_format_string
            elif col_tuple[0] == '원단위[kg/kg]':
                map_format[col_tuple] = mass_format_string
                
            elif col_tuple[0][:4] == '제조원가':
                if int(currency)==1:
                    map_format[col_tuple] = usd_format_string2
                else:
                    map_format[col_tuple] = won_format_string2
            elif int(currency) == 1:
                map_format[col_tuple] = usd_format_string
            else:
                map_format[col_tuple] = won_format_string
        
        sum_price = pd.DataFrame(columns=[''])
        sum_price.loc['Capex'] = [float(capex_cost * currency)]
        sum_price.loc['Capacity [MT]'] = [target_amount/1000]
        sum_price.loc[f"{st.session_state.main_source} 단가 [/MT]"] = [float(st.session_state.chem_data['Price (USD/kg)'][f"{st.session_state.main_source}"])*1000 * currency]
        sum_price.loc['제조 원가 [/MT]'] = float(list(avg_price_df.sum(axis=0))[2])

        avg_price_df = avg_price_df.drop(columns=columns_to_drop)
        st.dataframe(sum_price.style.format(usd_format_string2).map(lambda v: 'font-weight: bold;'))
        st.dataframe(avg_price_df.style.format(map_format))
        

        idx = merge_price_df.index.get_level_values(1).unique().tolist()
        detailed_idx = st.selectbox(label='상세',options=idx,index=None)
        if detailed_idx =='감가비':
            installed_cost = {}
            for i in scaled_system.units:
                if i.installed_cost >0:
                    installed_cost[i.ID] = i.installed_cost
            installed_cost = pd.DataFrame.from_dict(installed_cost,orient='index',columns=['Base Cost USD'])
            detailed_cost = st.dataframe(installed_cost.style.format(usd_format_string))
        elif detailed_idx:
            detailed_cost = st.dataframe(merge_price_df.xs(detailed_idx,level=1).style.format(map_format))
        else:
            detailed_cost = st.dataframe(merge_price_df.xs('유틸리티',level=1).style.format(map_format))

    if 'save_scenario' not in st.session_state:
        st.session_state.save_scenario = {}
        sc_df = {}
    else: 
        sc_name = st.text_input('시나리오 이름', placeholder='시나리오 1', key='sc_name')
        memo = st.text_area("시나리오 설명", placeholder="1T 생산, Titer 1.24",key='sc_memo')
        if st.button('시나리오 비교'):
            sc_df = {}
            sc_df[sc_name] = {'memo':str(memo), '제조원가':0, 'cost':avg_price_df, '유지':True}
            for sc_id in st.session_state.save_scenario:
                if sc_id != sc_name:
                    if st.session_state.save_scenario[sc_id]['유지']:
                        sc_df[sc_id] = st.session_state.save_scenario[sc_id]

            st.session_state.save_scenario = sc_df

    
    st.data_editor(pd.DataFrame(st.session_state.save_scenario),
                   column_config={
                       
                       "유지": st.column_config.CheckboxColumn("유지", help="시나리오 유지 여부", default=True,)
                   },
                   use_container_width=True)


        

            #st.session_state.save_scenario[sc_name] = sc_df
        #st.data_editor(pd.DataFrame.from_dict(st.session_state.save_scenario))
        



            
            


print(f"=== PYTHON SCRIPT FULLY DONE at {time.strftime('%H:%M:%S')} ===", flush=True)
