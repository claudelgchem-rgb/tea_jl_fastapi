import numpy as np, pandas as pd, sys, os, json, copy, string, pickle, math

import streamlit as st
import streamlit_flow
from streamlit_flow.elements import StreamlitFlowNode, StreamlitFlowEdge
from streamlit_flow.state import StreamlitFlowState
from streamlit_flow.layouts import LayeredLayout, ManualLayout
from nanoid import generate as nanoid
import streamlit.components.v1 as components
import time
import base64
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, Callable, Optional


# Assuming aux_chemical.py contains fill_water3 and other necessary functions
from .aux_chemical import * 

_st_flow_func = components.declare_component("streamlit_flow", path='/home/sbf/JLee/test/streamlit-flow/streamlit_flow/frontend/build/')

#============================================================================
# Global Constants
#============================================================================
base_dir ='/home/sbf/JLee/test/data/scenario/'
node_image_dir = '/home/sbf/JLee/test/data/node_image/'

#============================================================================
# StreamlitFlow Core Utilities
#============================================================================
@st.cache_data
def get_image_base64(image_path, node):
    with open(os.path.join(image_path, node + '.jpg'),'rb')as img_file:
        return base64.b64encode(img_file.read()).decode('utf-8').replace("\n", "")

@st.cache_data
def load_node_image(image_path):
    st.session_state.node_image={}
    for node_type in st.session_state.all_unit_defaults['node_style']:
        try:
            st.session_state.node_image[node_type] = get_image_base64(image_path, node_type)
        except:
            st.session_state.node_image[node_type] = get_image_base64(image_path, 'fermenter')
    return st.session_state.node_image


def create_node_content(image_str, label):

    return f"""
    <div style="
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
    ">
        
        <img src="data:image/png;base64,{image_str}" 
             style="width:60px; height:60px; object-fit:contain;" />

        <div style="margin-top:6px; font-size:14px;">
            {label}
        </div>

    </div>
    """

def get_emoji(node_type):
    node_db = {"연속 피드": '⚙️',
        "배치 피드": '⚙️',
        "Product Stream": '⭐',
        "폐기물": '⚙️',
        "발효/정제 분리선": '✅',
        "발효기": '⚗️',
        "믹싱 탱크": '🌀',
        "원심분리기": '✂️',
        "증발기": '💨',
        "동결건조기": '❄️',
        "SMB_Chromatography": '📊',
        "DiaFiltration": '📊',
        "Heater": '🔥',
        "Distillation": '🔃',
        "IEX column": '🪫',
        "HIC column": '🪫',
        "Protease/HCl/NaOH 처리": '🧪',
        "gel_filtration": '🫧',
        'Gypsum filtration':'📊',
        '용액처리기':'🧪',
        "highlight": '⚙️',
        }

    try:
        return node_db[node_type]
    except:
        return '⚙️'



def create_emoji_node_content(emoji, label):
    return f'<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;"><div style="font-size:40px;line-height:1.2;margin-bottom:8px;">{emoji}</div><div style="font-size:14px;font-weight:bold;color:#333333;">{label}</div></div>'


@st.cache_data
def get_node_feature(): # Declare features needed for each unit
    # Access the pre-loaded defaults from session state
    features = copy.deepcopy(st.session_state.all_unit_defaults.get('node_features', {}))
    # Dynamically set Rate In Solid for '원심분리기' if needed, based on current chem_list
    chem_list = st.session_state.get('chemical_list', ['Water', 'Glucose', 'Biomass'])
    for unit in features:
        if "split" in features[unit]:
            features[unit]["split"] = {i:0.2 for i in chem_list}
            
    return features


@st.cache_data
def get_node_style():
    features  = copy.deepcopy(st.session_state.all_unit_defaults.get('node_style', {}))
    return features

def apply_selection_style_old(nodes):
    styles = get_node_style()
    for node in nodes:
        node_type = node.data.get('node_type', 'highlight') # Use 'highlight' as a fallback
        base_style = styles.get(node_type, styles["highlight"]).copy()
        base_style.update({'fontSize':'16px', 'padding':1, 'width': '120px', 'border':'1px solid transparent', 'boxShadow':'none'})
        if node.data['node_type']=='발효/정제 분리선':
            base_style['width'] = '200px'
            base_style['fontSize'] = '32px' # Corrected typo here
        node.style = base_style
    return nodes

    
def apply_selection_style(nodes):
    for node in nodes:
        base_style = {'color': 'black', 'fontSize':'16px', 'padding':1, 'width': '120px', 'border':'1px solid transparent', 'boxShadow':'none'}
        if node.data['node_type']=='발효/정제 분리선':
            base_style['width'] = '300px'
        node.style = base_style
    return nodes


def fast_copy(obj):
    # More robust deep copy for general Python objects and StreamlitFlow* objects
    if hasattr(obj, 'asdict') and callable(obj.asdict):
        return obj.__class__.from_dict(copy.deepcopy(obj.asdict()))
    return copy.deepcopy(obj)

#============================================================================
# StreamlitFlow Management Functions
#============================================================================

def add_node(node_type_input):
    NODE_TYPES = get_node_feature()
    node_data_value = fast_copy(NODE_TYPES.get(node_type_input, {})) 
    count = len(st.session_state.flow_state.nodes)
    node_label = f'{node_type_input} {count + 1}'
    node_id = 'Node_' + node_label + '_' + nanoid(size=4)
    if node_type_input=='발효/정제 분리선':
        node_label = '발효 ➔ 정제'

    #node_content = create_node_content(st.session_state.node_image[node_type_input], node_label)
    emoji_string = get_emoji(node_type_input)
    node_content = create_emoji_node_content(emoji_string, node_label)

        
    new_node = StreamlitFlowNode(id=node_id, pos=(count*5 + 300, count*50+250),
                          node_type="default", 
                          #node_type=node_type_input, 
                          source_position='bottom', target_position='top',
                          data={"content": node_label,
                                "node_type": node_type_input,
                                "Value": node_data_value,
                                'custom_value':node_label,
                                "label": node_content,
                               },
                          )
        
    st.session_state.flow_state.nodes.append(new_node)
    st.session_state.flow_state.timestamp = time.time()
    st.session_state.flow_rev +=1
    st.session_state.proceed3=False


def delete_node(selected_node_id):
    if not selected_node_id: return
    
    st.session_state.flow_state.nodes = [node for node in st.session_state.flow_state.nodes if node.id != selected_node_id]
    st.session_state.flow_state.edges = [edge for edge in st.session_state.flow_state.edges if edge.source != selected_node_id and edge.target != selected_node_id and edge.id != selected_node_id]
    # Clear selection state after deletion
    st.session_state.flow_state.selected_id = None
    st.session_state.selected_id_old = None
    st.session_state.node_select = None # Also clear the sidebar selectbox selection
    st.session_state.flow_state.timestamp = time.time()
    st.session_state.flow_rev +=1
    st.session_state.flow_state = StreamlitFlowState(nodes=st.session_state.flow_state.nodes, edges=st.session_state.flow_state.edges)
    st.session_state.proceed3=False
    st.rerun()


def initialize_flowstate():
    NODE_TYPES = get_node_feature()
    emoji_fermenter = get_emoji('발효기')
    emoji_final = get_emoji('Product Stream')
    emoji_sep = get_emoji('발효/정제 분리선')
    

    node_fermenter = StreamlitFlowNode(id='Node_'+ '메인 발효기_'+nanoid(size=4), pos=(100, 100),
                          node_type="default", source_position='bottom', target_position='top',
                          data={"content": create_emoji_node_content(emoji_fermenter, '메인 발효기'),
                                "node_type": "발효기",
                                'custom_value':'메인 발효기',
                                "Value": fast_copy(NODE_TYPES["발효기"]),},) # Use fast_copy here
    node_final = StreamlitFlowNode(id='Node_'+ 'Product Stream_' + nanoid(size=4), pos=(100, 600),
                          node_type="default", source_position='bottom', target_position='top',
                          data={"content": create_emoji_node_content(emoji_final, '공정 완료'),
                                "node_type": "Product Stream",
                                'custom_value':'공정 완료',
                                "Value": fast_copy(NODE_TYPES["Product Stream"]),},) # Use fast_copy here
    node_sep =  StreamlitFlowNode(id='Node_'+'발효/정제 분리선_' + nanoid(size=4), pos=(10, 300),
                          node_type="default", source_position='bottom', target_position='top',
                          data={"content": create_emoji_node_content(emoji_sep, '발효 ➔ 정제'),
                                "node_type": "발효/정제 분리선",
                                'custom_value':'발효 ➔ 정제',
                                "Value": fast_copy(NODE_TYPES["발효/정제 분리선"]),},) # Use fast_copy here

    nodes = [node_fermenter, node_sep, node_final]
    edges = [StreamlitFlowEdge(f"edge_{node_fermenter.id}_{node_sep.id}", node_fermenter.id, node_sep.id)]
    
    st.session_state.flow_state = StreamlitFlowState(nodes=nodes, edges=edges)
    st.session_state.selected_id_old = None
    st.session_state.flow_state.selected_id = None
    st.session_state.flow_rev = 0 # Reset flow revision
    st.session_state.node_select = None # Reset node selection for sidebar


def sf_tmp(key:str,
        state:StreamlitFlowState, height:int=1000, fit_view:bool=False, show_controls:bool=True, show_minimap:bool=True,
        allow_new_edges:bool=True, animate_new_edges:bool=False, style:dict={}, layout=ManualLayout(), get_node_on_click:bool=True,
        get_edge_on_click:bool=True, pan_on_drag:bool=True, allow_zoom:bool=True, min_zoom:float=0.5,
        enable_pane_menu:bool=True, enable_node_menu:bool=True, enable_edge_menu:bool=True, hide_watermark:bool=True, node_types: Optional[Dict[str, Callable[[Dict], str]]] = None):
    
    # Ensure apply_selection_style is called on a copy or before asdict conversion
    nodes_for_display = apply_selection_style(copy.deepcopy(state.nodes))
    nodes_as_dict = [node.asdict() for node in nodes_for_display]
    edges_as_dict = [edge.asdict() for edge  in state.edges]
    component_value = _st_flow_func(  nodes=nodes_as_dict,
                                        edges=edges_as_dict,
                                        height=height,
                                        showControls=show_controls,
                                        fitView=fit_view,
                                        showMiniMap=show_minimap,
                                        style=style,
                                        animateNewEdges=animate_new_edges,
                                        allowNewEdges=allow_new_edges,
                                        layoutOptions=layout.__to_dict__(),
                                        getNodeOnClick=get_node_on_click,
                                        getEdgeOnClick=get_edge_on_click,
                                        panOnDrag=pan_on_drag,
                                        allowZoom=allow_zoom,
                                        minZoom=min_zoom,
                                        enableNodeMenu=enable_node_menu,
                                        enablePaneMenu=enable_pane_menu,
                                        enableEdgeMenu=enable_edge_menu,
                                        hideWatermark=hide_watermark,
                                        key=key,
                                        timestamp=state.timestamp,
                                        component='streamlit_flow',
                                        nodeTypes=node_types)
    if component_value is None:
        return state
    new_state = StreamlitFlowState(
        nodes=[StreamlitFlowNode.from_dict(node) for node in component_value['nodes']],
        edges=[StreamlitFlowEdge.from_dict(edge) for edge in component_value['edges']],
        selected_id=component_value['selectedId'],
        timestamp=component_value['timestamp'])

    return new_state

    
#============================================================================
# General Data Helpers
#============================================================================

def _get_df_from_dict_list2(data_dict_input, columns):
    """
    Converts various dict-like structures (from node.data['Value'] or data_editor)
    into a pandas DataFrame suitable for st.data_editor.
    The 'columns' argument is now consistently used for naming.
    """
    if not data_dict_input:
        return pd.DataFrame(columns=columns)
    elif isinstance(data_dict_input, dict) and all(isinstance(v, list) for v in data_dict_input.values()):
        # Handles {'물질':[], '농도':[]} format - already has column names
        return pd.DataFrame(data_dict_input)
    elif isinstance(data_dict_input, dict):
        # Handles {'ChemicalA': 10.0, 'ChemicalB': 5.0} format
        # Use the provided 'columns' argument for naming
        return pd.DataFrame(list(data_dict_input.items()), columns=columns)
    elif isinstance(data_dict_input, list):
        # Handles [['ChemicalA', 10.0], ['ChemicalB', 5.0]] format
        return pd.DataFrame(data_dict_input, columns=columns)
    return pd.DataFrame(columns=columns)


def _get_df_from_dict_list(data_dict_input, columns):
    """
    Converts various dict-like structures (from node.data['Value'] or data_editor)
    into a pandas DataFrame suitable for st.data_editor.
    The 'columns' argument is now consistently used for naming.
    """
    if not data_dict_input:
        return pd.DataFrame(columns=columns)
    elif isinstance(data_dict_input, dict) and all(isinstance(v, list) for v in data_dict_input.values()):
        # Handles {'물질':[], '농도':[]} format - already has column names
        processed_data = {}
        for k, v in data_dict_input.items():
            # Check if all elements in the list 'v' are themselves lists of length 1
            if v and all(isinstance(x, list) and len(x) == 1 for x in v):
                # If so, flatten them (e.g., [[100.0], [50.0]] becomes [100.0, 50.0])
                processed_data[k] = [x[0] for x in v]
            else:
                processed_data[k] = v
        
        # Ensure processed_data has all expected columns, adding empty lists if missing
        # This handles cases where a column like '용액' might be missing from the original dict.
        # It assumes all lists in processed_data have the same length if not empty.
        num_rows = len(next(iter(processed_data.values()))) if processed_data else 0
        for col in columns:
            if col not in processed_data:
                processed_data[col] = [''] * num_rows # Add empty strings for missing columns
        
        return pd.DataFrame(processed_data)
    elif isinstance(data_dict_input, dict):
        # Handles {'ChemicalA': 10.0, 'ChemicalB': 5.0} format
        # This data intrinsically provides 2 elements per row (key, value).
        # We need to explicitly add default values if 'columns' expects more.
        data_for_df = []
        for material, conc in data_dict_input.items():
            row = [material, conc]
            # If the expected number of columns is greater than the data provided, add defaults
            if len(columns) > len(row):
                row.extend([''] * (len(columns) - len(row))) # Add empty strings for missing columns
            data_for_df.append(row)
        return pd.DataFrame(data_for_df, columns=columns)
    elif isinstance(data_dict_input, list):
        # Handles [['ChemicalA', 10.0], ['ChemicalB', 5.0]] format
        # Similar to the dict of scalars, each inner list intrinsically has 2 elements.
        data_for_df = []
        for row_list in data_dict_input:
            row = list(row_list) # Ensure it's a mutable list
            # If the expected number of columns is greater than the data provided, add defaults
            if len(columns) > len(row):
                row.extend([''] * (len(columns) - len(row))) # Add empty strings for missing columns
            data_for_df.append(row)
        return pd.DataFrame(data_for_df, columns=columns)
    
    return pd.DataFrame(columns=columns)

#============================================================================
# Unit: Fermenter
#============================================================================

def render_fermenter_widgets(current_node_data: dict, node_id: str):
    default_fermenter_data = copy.deepcopy(st.session_state.all_unit_defaults.get('fermenter_default', {}))
    default_fermenter_data['Main reactant'] = st.session_state.main_source

    edited_values = {**default_fermenter_data, **current_node_data} # Merge defaults and existing data

    solution_list = list(st.session_state.get('solutions', {}).keys())
    chem_list = st.session_state.get('chemical_list', [])
    main_source_index = chem_list.index(edited_values['Main reactant']) if edited_values['Main reactant'] in chem_list else 0

    with st.expander('고급 설정'):
        edited_values['P'] = float(st.number_input('압력 [Pa]', value=float(edited_values.get('P', 0)), key=f"{node_id}_P"))
        edited_values['V_wf'] = float(st.number_input('Working Volume [%]', value=float(edited_values.get('V_wf', 0)), key=f"{node_id}_V_wf"))
        edited_values['V_max'] = float(st.number_input('발효기 최대 부피 [m3]', value=float(edited_values.get('V_max', 0)), key=f"{node_id}_V_max"))
        edited_values['tau_add'] = float(st.number_input('투입시간 [hr]', value=float(edited_values.get('tau_add', 0)), key=f"{node_id}_tau_add"))
        edited_values['tau_cool'] = float(st.number_input('추가 cooling [hr]', value=float(edited_values.get('tau_cool', 0)), key=f"{node_id}_tau_cool"))
        edited_values['tau_sip'] = float(st.number_input('SIP 시간 [hr]', value=float(edited_values.get('tau_sip', 0)), key=f"{node_id}_tau_sip"))
        edited_values['tau_cip'] = float(st.number_input('CIP 시간 [hr]', value=float(edited_values.get('tau_cip', 0)), key=f"{node_id}_tau_cip"))
        edited_values['sip_stream_rate'] = float(st.number_input('스팀 속도 [kg/hr/m3]', value=float(edited_values.get('sip_stream_rate', 0)), key=f"{node_id}_sip_stream_rate"))
        edited_values['agitation_efficiency'] = float(st.number_input('Agigator 효율', value=float(edited_values.get('agitation_efficiency', 0)), key=f"{node_id}_agitation_efficiency"))
        edited_values['P_drop'] = float(st.number_input('Pressure drop [Pa]', value=float(edited_values.get('P_drop', 0)), key=f"{node_id}_P_drop"))
        edited_values['compressor_isentropic_efficiency'] = float(st.number_input('컴프레서 효율', value=float(edited_values.get('compressor_isentropic_efficiency', 0)), key=f"{node_id}_compressor_isentropic_efficiency"))
        edited_values['motor_efficiency'] = float(st.number_input('모터 효율', value=float(edited_values.get('motor_efficiency', 0)), key=f"{node_id}_motor_efficiency"))
        edited_values['chill_to_cool_ratio'] = float(st.number_input('Chilled_water ratio', value=float(edited_values.get('chill_to_cool_ratio', 0)), key=f"{node_id}_chiling_to_cooling_ratio"))
        edited_values['Main reactant'] = st.selectbox('주 탄소원', options=chem_list, index=main_source_index, key=f"{node_id}_main_reactant")

    st.subheader("옵션")
    edited_values['tau'] = float(st.number_input('발효 시간', value=float(edited_values.get('tau', 0)), key=f"{node_id}_tau"))
    edited_values['T'] = float(st.number_input('발효 온도 [C]', value=float(edited_values.get('T', 0)), key=f"{node_id}_T"))
    edited_values['vvm'] = float(st.number_input('공기 투입량 [vvm]', value=float(edited_values.get('vvm', 0)), key=f"{node_id}_vvm"))
    edited_values['init_OD'] = float(st.number_input('시작 OD', value=float(edited_values.get('init_OD', 0)), key=f"{node_id}_init_OD"))
    edited_values['final_OD'] = float(st.number_input('최종 OD', value=float(edited_values.get('final_OD', 0)), key=f"{node_id}_final_OD"))
    
    edited_values['initial_vol'] = float(st.number_input('Lab 기준 시작 투입량 [L]', value=float(edited_values.get('initial_vol', 0)), key=f"{node_id}_initial_vol"))
    st.write('시작 투입 농도 [g/L]')
    initial_conc_df = _get_df_from_dict_list(edited_values.get('initial_conc', {}), ['물질','농도 [g/L]','용액'])
    edited_values['_initial_conc_df'] = st.data_editor(initial_conc_df, num_rows="dynamic", key=f"{node_id}_initial_conc_ui",
                hide_index=True, column_config={
                    '물질': st.column_config.SelectboxColumn(options=chem_list, required=True),
                    '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001),
                    '용액': st.column_config.SelectboxColumn(options=solution_list, required=True)}
            )

    edited_values['feed_vol'] = float(st.number_input('Lab 기준 총 피드 투입량 [L]', value=float(edited_values.get('feed_vol', 0)), key=f"{node_id}_feed_vol"))
    st.write('피드 투입 농도 [g/L]')
    feed_conc_df = _get_df_from_dict_list(edited_values.get('feed_conc', {}), ['물질','농도 [g/L]','용액'])
    edited_values['_feed_conc_df'] = st.data_editor(feed_conc_df, num_rows="dynamic", key=f"{node_id}_feed_conc_ui",
                hide_index=True, column_config={
                    '물질': st.column_config.SelectboxColumn(options=chem_list, required=True),
                    '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001),
                    '용액': st.column_config.SelectboxColumn(options=solution_list, required=True)}
            )

    edited_values['final_vol'] = float(st.number_input('Lab 기준 최종 부피 [L]', value=float(edited_values.get('final_vol', 0)), key=f"{node_id}_final_vol"))
    st.write('최종 농도 [g/L]')
    final_conc_df = _get_df_from_dict_list(edited_values.get('final_conc', {}), ['물질','농도 [g/L]'])
    edited_values['_final_conc_df'] = st.data_editor(final_conc_df, num_rows="dynamic", key=f"{node_id}_final_conc_ui", hide_index=True,
                                   column_config={
                                       '물질': st.column_config.SelectboxColumn(options=chem_list, required=True),
                                       '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)}
            )
    
    return edited_values

def process_fermenter_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    
    # Safely get chem_list and solution_list
    chem_list = st.session_state.get('chemical_list', [])
    solution_list = list(st.session_state.get('solutions', {}).keys())

    # Retrieve the processed DataFrame outputs
    initial_conc_df = processed_values.pop('_initial_conc_df')
    feed_conc_df = processed_values.pop('_feed_conc_df')
    final_conc_df = processed_values.pop('_final_conc_df')

    # Convert DataFrames back to dicts (for storage)
    # Ensure the dictionary format is consistent (e.g., {'물질': [...], '농도 [g/L]': [...]})
    processed_values['initial_conc'] = initial_conc_df.to_dict('list')
    processed_values['feed_conc'] = feed_conc_df.to_dict('list')
    processed_values['final_conc'] = final_conc_df.to_dict('list')

    # Perform calculations
    in_mass = {c:0. for c in chem_list} # Initialize with floats
    out_mass = {c:0. for c in chem_list}

    total_in_vol = (processed_values['initial_vol'] + processed_values['feed_vol']) / 1000
    for _, row in initial_conc_df.iterrows():
        if row['물질'] in in_mass:
            in_mass[row['물질']] += float(row['농도 [g/L]']) * processed_values['initial_vol'] / 1000
    for _, row in feed_conc_df.iterrows():
        if row['물질'] in in_mass:
            in_mass[row['물질']] += float(row['농도 [g/L]']) * processed_values['feed_vol'] / 1000
    in_mass = fill_water3(in_mass, total_in_vol)

    for _, row in final_conc_df.iterrows():
        if row['물질'] in out_mass:
            out_mass[row['물질']] = float(row['농도 [g/L]']) * processed_values['final_vol'] / 1000
    out_mass = fill_water3(out_mass, processed_values['final_vol'] / 1000)

    # Stream composition logic
    # Concatenate and ensure '용액' column exists before grouping
    all_conc_df = pd.concat([initial_conc_df, feed_conc_df])
    if '용액' in all_conc_df.columns:
        # Filter out rows where '용액' is NaN or empty string before grouping
        valid_solutions_df = all_conc_df[all_conc_df['용액'].notna() & (all_conc_df['용액'] != '')]
        stream_composition = valid_solutions_df.groupby('용액')['물질'].unique().apply(list).to_dict()
    else:
        stream_composition = {} # No solutions defined

    stream_flow = {s:{} for s in solution_list}
    water_mass_remaining = in_mass.get('Water', 0.0)

    for s in stream_composition:
        if s in st.session_state.get('solutions', {}):
            if len(stream_composition[s]) > 1: st.warning(f"Solution {s} represents multiple chemicals {stream_composition[s]}.")
            chem = stream_composition[s][0]
            if chem in in_mass and chem in st.session_state['solutions'][s]:
                if st.session_state['solutions'][s][chem] != 0:
                    vol_req = in_mass[chem] / (st.session_state['solutions'][s][chem])
                    stream_flow[s] = {j: mass * vol_req for j,mass in st.session_state['solutions'][s].items()}
                    water_mass_remaining -= vol_req * st.session_state['solutions'][s].get('Water', 0.0)
    stream_flow['Water'] = {'Water': max(0.0, water_mass_remaining)} # Ensure water mass is not negative

    processed_values['stream_flow'] = stream_flow
    processed_values['in_mass'] = in_mass
    processed_values['out_mass'] = out_mass
    
    return processed_values

#============================================================================
# Unit: MVR (Mechanical Vapor Recompression)
#============================================================================

def render_MVR_widgets(current_node_data: dict, node_id: str):
    default_mvr_data = copy.deepcopy(st.session_state.all_unit_defaults.get('mvr_default', {}))
    edited_values = {**default_mvr_data, **current_node_data}

    with st.expander('고급 설정'):
        edited_values['U_overall'] = float(st.number_input('U_overall [kW/m.K]', value=float(edited_values.get('U_overall', 0)), key=f"{node_id}_U_overall"))
        edited_values['motor_efficiency'] = float(st.number_input('Motor Efficiency', value=float(edited_values.get('motor_efficiency', 0)), key=f"{node_id}_motor_efficiency"))
        edited_values['compressor_isentropic_efficiency'] = float(st.number_input('compressor_isentropic_efficiency', value=float(edited_values.get('compressor_isentropic_efficiency', 0)), key=f"{node_id}_compressor_isentropic_efficiency"))
        edited_values['pump_efficiency'] = float(st.number_input('Pump Efficiency', value=float(edited_values.get('pump_efficiency', 0)), key=f"{node_id}_pump_efficiency"))
        edited_values['pump_head'] = float(st.number_input('Pump head', value=float(edited_values.get('pump_head', 0)), key=f"{node_id}_pump_head"))
        edited_values['P_drop'] = float(st.number_input('Pressure drop [Pa]', value=float(edited_values.get('P_drop', 0)), key=f"{node_id}_P_drop"))
        edited_values['chemical'] = st.text_input('증류 chemical', value=edited_values.get('chemical', 'Water'), key=f"{node_id}_chemical")
    
    edited_values['T'] = float(st.number_input('온도 [C]', value=float(edited_values.get('T', 0)), key=f"{node_id}_T"))
    edited_values['V'] = float(st.number_input('증발 비율 [%]', value=float(edited_values.get('V', 40)), key=f"{node_id}_V"))
    return edited_values

def process_MVR_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    # No complex data_editor processing or fill_water3 for MVR in your example,
    # so simply return the collected widget data.
    return processed_values

#============================================================================
# Unit: HIC (Hydrophobic Interaction Chromatography)
#============================================================================

def render_HIC_widgets(current_node_data: dict, node_id: str):
    default_hic_data = copy.deepcopy(st.session_state.all_unit_defaults.get('hic_default', {}))
    edited_values = {**default_hic_data, **current_node_data}

    chem_list = st.session_state.get('chemical_list', [])
    util_list = list(st.session_state.get('heat_utility', {}).keys())
    edited_values['binding_material'] = edited_values.get('binding_material', st.session_state.main_product)
    
    chem_index = chem_list.index(edited_values['binding_material'])
    resin_index = util_list.index(edited_values['resin_id']) if edited_values['resin_id'] in util_list else 0
    wastewater_index = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0

    with st.expander('고급 설정'):
        edited_values['column_price'] = float(st.number_input('Empty column 가격 [USD/L resin]', value=float(edited_values.get('column_price', 7000.0)), key=f"{node_id}_HIC_column_price"))
        edited_values['P_drop'] = float(st.number_input('Pressure drop [Pa]', value=float(edited_values.get('P_drop', 0)), key=f"{node_id}_HIC_P_drop"))
        edited_values['motor_efficiency'] = float(st.number_input('Motor Efficiency', value=float(edited_values.get('motor_efficiency', 0)), key=f"{node_id}_HIC_motor_efficiency"))
        edited_values['compressor_isentropic_efficiency'] = float(st.number_input('compressor_isentropic_efficiency', value=float(edited_values.get('compressor_isentropic_efficiency', 0)), key=f"{node_id}_HIC_comp_eff"))
        edited_values['pump_efficiency'] = float(st.number_input('Pump Efficiency', value=float(edited_values.get('pump_efficiency', 0)), key=f"{node_id}_HIC_pump_eff"))
        edited_values['wastewater_id'] = st.selectbox('Wastewater 종류', options=util_list, index=wastewater_index, key=f"{node_id}_HIC_wastewater_id")

    st.write("레진 정보")
    edited_values['resin_id'] = st.selectbox('Resin 종류', options=util_list, index=resin_index, key=f"{node_id}_HIC_resin_id")
    try:
       edited_values['resin_price'] = float(st.number_input('Resin 가격 [USD/L]', value = float(st.session_state.get('heat_utility', {}).get(edited_values['resin_id'], 0.0)), key=f"{node_id}_HIC_resin_price"))
    except ValueError:
        st.write(':red[레진이 등록되지 않음. 수동 입력 또는 화학물질 목록 확인.]')
        edited_values['resin_price'] = float(st.number_input('Resin 가격 [USD/L]', value=float(edited_values.get('resin_price', 0.0)), key=f"{node_id}_HIC_resin_price_manual"))

    edited_values['binding_material'] = st.selectbox('Binding Chemical', options=chem_list, index=chem_index, key=f"{node_id}_binding_material")
    edited_values['binding_capacity'] = float(st.number_input('Binding Capacity [g/L]', value=float(edited_values.get('binding_capacity', 20.0)), key=f"{node_id}_binding_capacity"))
    edited_values['resin_lifetime_cycle'] = float(st.number_input('레진 수명 [cycle]', value=float(edited_values.get('resin_lifetime_cycle', 0)), key=f"{node_id}_HIC_resin_lifetime_cycle"))

    col_conc = ['물질','농도 [g/L]']
    st.subheader("용액 투입량")

    st.write("Loading 정보")
    edited_values['tau_loading'] = float(st.number_input('로딩 시간 [h]', value=float(edited_values.get('tau_loading', 0)), key=f"{node_id}_HIC_tau_loading"))

    st.write("Wash 정보")
    edited_values['flowrate_wash'] = float(st.number_input('wash volume [BV/hr]', value=float(edited_values.get('flowrate_wash', 0)), key=f"{node_id}_HIC_flowrate_wash"))
    edited_values['tau_wash'] = float(st.number_input('wash 시간 [h]', value=float(edited_values.get('tau_wash', 0)), key=f"{node_id}_HIC_tau_wash"))
    st.write('wash 농도 [g/L]')
    wash_conc_df = _get_df_from_dict_list(edited_values.get('conc_wash', {}), columns=col_conc)
    edited_values['_conc_wash_df'] = st.data_editor(wash_conc_df, num_rows="dynamic", key=f"{node_id}_HIC_wash_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Equilibration 정보")
    edited_values['flowrate_equilibrate'] = float(st.number_input('equilibrate volume [BV/hr]', value=float(edited_values.get('flowrate_equilibrate', 0)), key=f"{node_id}_HIC_flowrate_equilibrate"))
    edited_values['tau_equilibrate'] = float(st.number_input('equilibrate 시간 [h]', value=float(edited_values.get('tau_equilibrate', 0)), key=f"{node_id}_HIC_tau_equilibrate"))
    st.write('equilibrate 농도 [g/L]')
    equilibrate_conc_df = _get_df_from_dict_list(edited_values.get('conc_equilibrate', {}), columns=col_conc)
    edited_values['_conc_equilibrate_df'] = st.data_editor(equilibrate_conc_df, num_rows="dynamic", key=f"{node_id}_HIC_equilibrate_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Elution 정보")
    edited_values['flowrate_elute'] = float(st.number_input('elute volume [BV/hr]', value=float(edited_values.get('flowrate_elute', 0)), key=f"{node_id}_HIC_flowrate_elute"))
    edited_values['tau_elute'] = float(st.number_input('elute 시간 [h]', value=float(edited_values.get('tau_elute', 0)), key=f"{node_id}_HIC_tau_elute"))
    st.write('elute 농도 [g/L]')
    elute_conc_df = _get_df_from_dict_list(edited_values.get('conc_elute', {}), columns=col_conc)
    edited_values['_conc_elute_df'] = st.data_editor(elute_conc_df, num_rows="dynamic", key=f"{node_id}_HIC_elute_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Rinse 정보")
    edited_values['flowrate_rinse'] = float(st.number_input('rinse volume [BV/hr]', value=float(edited_values.get('flowrate_rinse', 0)), key=f"{node_id}_HIC_flowrate_rinse"))
    edited_values['tau_rinse'] = float(st.number_input('rinse 시간 [h]', value=float(edited_values.get('tau_rinse', 0)), key=f"{node_id}_HIC_tau_rinse"))
    st.write('rinse 농도 [g/L]')
    rinse_conc_df = _get_df_from_dict_list(edited_values.get('conc_rinse', {}), columns=col_conc)
    edited_values['_conc_rinse_df'] = st.data_editor(rinse_conc_df, num_rows="dynamic", key=f"{node_id}_HIC_rinse_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Regeneration 정보")
    edited_values['flowrate_regenerate'] = float(st.number_input('regenerate volume [BV/hr]', value=float(edited_values.get('flowrate_regenerate', 0)), key=f"{node_id}_HIC_flowrate_regenerate"))
    edited_values['tau_regenerate'] = float(st.number_input('regenerate 시간 [h]', value=float(edited_values.get('tau_regenerate', 0)), key=f"{node_id}_HIC_tau_regenerate"))
    st.write('Regenerate 농도 [g/L]')
    regenerate_conc_df = _get_df_from_dict_list(edited_values.get('conc_regenerate', {}), columns=col_conc)
    edited_values['_conc_regenerate_df'] = st.data_editor(regenerate_conc_df, num_rows="dynamic", key=f"{node_id}_HIC_regenerate_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Product 정보")
    edited_values['volume_product'] = float(st.number_input('Product Volume / Elute volume', value=float(edited_values.get('volume_product', 0)), key=f"{node_id}_HIC_volume_product"))
    st.write('product 농도 [g/L]')
    product_conc_df = _get_df_from_dict_list(edited_values.get('conc_product', {}), columns=col_conc)
    edited_values['_conc_product_df'] = st.data_editor(product_conc_df, num_rows="dynamic", key=f"{node_id}_HIC_product_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    return edited_values

def process_HIC_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    
    # Retrieve the processed DataFrame outputs and apply fill_water3
    # The column name for concentration is '농도 [g/L]' as defined in col_conc
    processed_values['conc_wash'] = fill_water3(processed_values.pop('_conc_wash_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_equilibrate'] = fill_water3(processed_values.pop('_conc_equilibrate_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_elute'] = fill_water3(processed_values.pop('_conc_elute_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_rinse'] = fill_water3(processed_values.pop('_conc_rinse_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_regenerate'] = fill_water3(processed_values.pop('_conc_regenerate_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_product'] = fill_water3(processed_values.pop('_conc_product_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)

    # Update resin price from heat_utility if applicable
    resin_id = processed_values.get('resin_id')
    if resin_id and resin_id in st.session_state.get('heat_utility', {}):
        processed_values['resin_price'] = float(st.session_state['heat_utility'][resin_id])

    return processed_values

#============================================================================
# Unit: IEX (Ion Exchange Chromatography)
#============================================================================

def render_IEX_widgets(current_node_data: dict, node_id: str):
    default_iex_data = copy.deepcopy(st.session_state.all_unit_defaults.get('iex_default', {}))
    edited_values = {**default_iex_data, **current_node_data}

    chem_list = st.session_state.get('chemical_list', [])
    util_list = list(st.session_state.get('heat_utility', {}).keys())
    edited_values['binding_material'] = edited_values.get('binding_material', st.session_state.main_product)
    
    chem_index = chem_list.index(edited_values['binding_material'])
    resin_index = util_list.index(edited_values['resin_id']) if edited_values['resin_id'] in util_list else 0
    wastewater_index = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0

    with st.expander('고급 설정'):
        edited_values['column_price'] = float(st.number_input('Empty column 가격 [USD/L resin]', value=float(edited_values.get('column_price', 7000.0)), key=f"{node_id}_iex_column_price"))
        edited_values['P_drop'] = float(st.number_input('Pressure drop [Pa]', value=float(edited_values.get('P_drop', 0)), key=f"{node_id}_IEX_P_drop"))
        edited_values['motor_efficiency'] = float(st.number_input('Motor Efficiency', value=float(edited_values.get('motor_efficiency', 0)), key=f"{node_id}_IEX_motor_efficiency"))
        edited_values['compressor_isentropic_efficiency'] = float(st.number_input('compressor_isentropic_efficiency', value=float(edited_values.get('compressor_isentropic_efficiency', 0)), key=f"{node_id}_IEX_comp_eff"))
        edited_values['pump_efficiency'] = float(st.number_input('Pump Efficiency', value=float(edited_values.get('pump_efficiency', 0)), key=f"{node_id}_IEX_pump_eff"))
        edited_values['wastewater_id'] = st.selectbox('Wastewater 종류', options=util_list, index=wastewater_index, key=f"{node_id}_IEX_wastewater_id")

    st.write("레진 정보")
    edited_values['resin_id'] = st.selectbox('Resin 종류', options=util_list, index=resin_index, key=f"{node_id}_IEX_resin_id")
    
    try:
       edited_values['resin_price'] = float(st.number_input('Resin 가격 [USD/L]', value = float(st.session_state.get('heat_utility', {}).get(edited_values['resin_id'], 0.0)), key=f"{node_id}_IEX_resin_price"))
    except ValueError:
        st.info(':red[레진이 등록되지 않음. 수동 입력 또는 화학물질 목록 확인.]')
        edited_values['resin_price'] = float(st.number_input('Resin 가격 [USD/L]', value=float(edited_values.get('resin_price', 0.0)), key=f"{node_id}_IEX_resin_price_manual"))

    edited_values['binding_material'] = st.selectbox('Binding Chemical', options=chem_list, index=chem_index, key=f"{node_id}_binding_material")
    edited_values['binding_capacity'] = float(st.number_input('Binding Capacity [g/L]', value=float(edited_values.get('binding_capacity', 20.0)), key=f"{node_id}_IEX_binding_capacity"))
    edited_values['resin_lifetime_cycle'] = float(st.number_input('레진 수명 [cycle]', value=float(edited_values.get('resin_lifetime_cycle', 0)), key=f"{node_id}_IEX_resin_lifetime_cycle"))

    col_conc = ['물질','농도 [g/L]']
    st.subheader("용액 투입량")

    st.write("Loading 정보")
    edited_values['tau_loading'] = float(st.number_input('로딩 시간 [h]', value=float(edited_values.get('tau_loading', 0)), key=f"{node_id}_IEX_tau_loading"))

    st.write("Wash-1 정보")
    edited_values['flowrate_wash1'] = float(st.number_input('wash-1 volume [BV/hr]', value=float(edited_values.get('flowrate_wash1', 0)), key=f"{node_id}_IEX_flowrate_wash1"))
    edited_values['tau_wash1'] = float(st.number_input('wash-1 시간 [h]', value=float(edited_values.get('tau_wash1', 0)), key=f"{node_id}_IEX_tau_wash1"))
    st.write('wash-1 농도 [g/L]')
    wash_conc1_df = _get_df_from_dict_list(edited_values.get('conc_wash1', {'':0.0}), columns=col_conc)
    edited_values['_conc_wash1_df'] = st.data_editor(wash_conc1_df, num_rows="dynamic", key=f"{node_id}_IEX_wash1_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Wash-2 정보")
    edited_values['flowrate_wash2'] = float(st.number_input('wash-2 volume [BV/hr]', value=float(edited_values.get('flowrate_wash2', 0)), key=f"{node_id}_IEX_flowrate_wash2"))
    edited_values['tau_wash2'] = float(st.number_input('wash-2 시간 [h]', value=float(edited_values.get('tau_wash2', 0)), key=f"{node_id}_IEX_tau_wash2"))
    st.write('wash-2 농도 [g/L]')
    wash_conc2_df = _get_df_from_dict_list(edited_values.get('conc_wash2', {'':0.0}), columns=col_conc)
    edited_values['_conc_wash2_df'] = st.data_editor(wash_conc2_df, num_rows="dynamic", key=f"{node_id}_IEX_wash2_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Elution 정보")
    edited_values['flowrate_elute'] = float(st.number_input('elute volume [BV/hr]', value=float(edited_values.get('flowrate_elute', 0)), key=f"{node_id}_IEX_flowrate_elute"))
    edited_values['tau_elute'] = float(st.number_input('elute 시간 [h]', value=float(edited_values.get('tau_elute', 0)), key=f"{node_id}_IEX_tau_elute"))
    st.write('elute 농도 [g/L]')
    elute_conc_df = _get_df_from_dict_list(edited_values.get('conc_elute', {'':0.0}), columns=col_conc)
    edited_values['_conc_elute_df'] = st.data_editor(elute_conc_df, num_rows="dynamic", key=f"{node_id}_IEX_elute_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Regeneration 정보")
    edited_values['flowrate_regenerate'] = float(st.number_input('regenerate volume [BV/hr]', value=float(edited_values.get('flowrate_regenerate', 0)), key=f"{node_id}_IEX_flowrate_regenerate"))
    edited_values['tau_regenerate'] = float(st.number_input('regenerate 시간 [h]', value=float(edited_values.get('tau_regenerate', 0)), key=f"{node_id}_IEX_tau_regenerate"))
    st.write('Regenerate 농도 [g/L]')
    regenerate_conc_df = _get_df_from_dict_list(edited_values.get('conc_regenerate', {'':0.0}), columns=col_conc)
    edited_values['_conc_regenerate_df'] = st.data_editor(regenerate_conc_df, num_rows="dynamic", key=f"{node_id}_IEX_regenerate_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Product 정보")
    edited_values['volume_product'] = float(st.number_input('Product volume / Elute volume', value=float(edited_values.get('volume_product', 0)), key=f"{node_id}_IEX_volume_product"))
    st.write('product 농도 [g/L]')
    product_conc_df = _get_df_from_dict_list(edited_values.get('conc_product', {'':0.0}), columns=col_conc)
    edited_values['_conc_product_df'] = st.data_editor(product_conc_df, num_rows="dynamic", key=f"{node_id}_IEX_product_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    return edited_values

def process_IEX_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    
    # Retrieve the processed DataFrame outputs and apply fill_water3
    processed_values['conc_wash1'] = fill_water3(processed_values.pop('_conc_wash1_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_wash2'] = fill_water3(processed_values.pop('_conc_wash2_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_elute'] = fill_water3(processed_values.pop('_conc_elute_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_regenerate'] = fill_water3(processed_values.pop('_conc_regenerate_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_product'] = fill_water3(processed_values.pop('_conc_product_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)

    # Update resin price from heat_utility if applicable
    resin_id = processed_values.get('resin_id')
    if resin_id and resin_id in st.session_state.get('heat_utility', {'':0.0}):
        processed_values['resin_price'] = float(st.session_state['heat_utility'][resin_id])
    
    return processed_values


#============================================================================
# Unit: Gel Filtration
#============================================================================

def render_gel_filtration_widgets(current_node_data: dict, node_id: str):
    default_hic_data = copy.deepcopy(st.session_state.all_unit_defaults.get('gel_filtration_default', {}))
    edited_values = {**default_hic_data, **current_node_data}

    chem_list = st.session_state.get('chemical_list', [])
    util_list = list(st.session_state.get('heat_utility', {}).keys())
    edited_values['binding_material'] = edited_values.get('binding_material', st.session_state.main_product)

    chem_index = chem_list.index(edited_values['binding_material'])
    resin_index = util_list.index(edited_values['resin_id']) if edited_values['resin_id'] in util_list else 0
    wastewater_index = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0

    with st.expander('고급 설정'):
        edited_values['column_price'] = float(st.number_input('Empty column 가격 [USD/L resin]', value=float(edited_values.get('column_price', 7000.0)), key=f"{node_id}_column_price"))
        edited_values['P_drop'] = float(st.number_input('Pressure drop [Pa]', value=float(edited_values.get('P_drop', 0)), key=f"{node_id}_P_drop"))
        edited_values['motor_efficiency'] = float(st.number_input('Motor Efficiency', value=float(edited_values.get('motor_efficiency', 0)), key=f"{node_id}_motor_efficiency"))
        edited_values['compressor_isentropic_efficiency'] = float(st.number_input('compressor_isentropic_efficiency', value=float(edited_values.get('compressor_isentropic_efficiency', 0)), key=f"{node_id}_comp_eff"))
        edited_values['pump_efficiency'] = float(st.number_input('Pump Efficiency', value=float(edited_values.get('pump_efficiency', 0)), key=f"{node_id}_pump_eff"))
        edited_values['wastewater_id'] = st.selectbox('Wastewater 종류', options=util_list, index=wastewater_index, key=f"{node_id}_wastewater_id")

    st.write("레진 정보")
    edited_values['resin_id'] = st.selectbox('Resin 종류', options=util_list, index=resin_index, key=f"{node_id}_resin_id")
    try:
       edited_values['resin_price'] = float(st.number_input('Resin 가격 [USD/L]', value = float(st.session_state.get('heat_utility', {}).get(edited_values['resin_id'], 0.0)), key=f"{node_id}_resin_price"))
    except ValueError:
        st.write(':red[레진이 등록되지 않음. 수동 입력 또는 화학물질 목록 확인.]')
        edited_values['resin_price'] = float(st.number_input('Resin 가격 [USD/L]', value=float(edited_values.get('resin_price', 0.0)), key=f"{node_id}_resin_price_manual"))

    edited_values['binding_material'] = st.selectbox('Binding Chemical', options=chem_list, index=chem_index, key=f"{node_id}_binding_material")
    edited_values['binding_capacity'] = float(st.number_input('Binding Capacity [g/L]', value=float(edited_values.get('binding_capacity', 20.0)), key=f"{node_id}_binding_capacity"))
    edited_values['resin_lifetime_cycle'] = float(st.number_input('레진 수명 [cycle]', value=float(edited_values.get('resin_lifetime_cycle', 0)), key=f"{node_id}_resin_lifetime_cycle"))

    col_conc = ['물질','농도 [g/L]']
    st.subheader("용액 투입량")

    st.write("Loading 정보")
    edited_values['tau_loading'] = float(st.number_input('로딩 시간 [h]', value=float(edited_values.get('tau_loading', 0.0)), key=f"{node_id}_tau_loading"))

    st.write("Wash 정보")
    edited_values['flowrate_wash'] = float(st.number_input('wash volume [BV/hr]', value=float(edited_values.get('flowrate_wash', 0.0)), key=f"{node_id}_flowrate_wash"))
    edited_values['tau_wash'] = float(st.number_input('wash 시간 [h]', value=float(edited_values.get('tau_wash', 0.0)), key=f"{node_id}_tau_wash"))
    st.write('wash 농도 [g/L]')
    wash_conc_df = _get_df_from_dict_list(edited_values.get('conc_wash', {}), columns=col_conc)
    wash_conc_df['농도 [g/L]'] = wash_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_wash_df'] = st.data_editor(wash_conc_df, num_rows="dynamic", key=f"{node_id}_wash_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Equilibration 정보")
    edited_values['flowrate_equilibrate'] = float(st.number_input('equilibrate volume [BV/hr]', value=float(edited_values.get('flowrate_equilibrate', 0)), key=f"{node_id}_flowrate_equilibrate"))
    edited_values['tau_equilibrate'] = float(st.number_input('equilibrate 시간 [h]', value=float(edited_values.get('tau_equilibrate', 0)), key=f"{node_id}_tau_equilibrate"))
    st.write('equilibrate 농도 [g/L]')
    equilibrate_conc_df = _get_df_from_dict_list(edited_values.get('conc_equilibrate', {}), columns=col_conc)
    equilibrate_conc_df['농도 [g/L]'] = equilibrate_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_equilibrate_df'] = st.data_editor(equilibrate_conc_df, num_rows="dynamic", key=f"{node_id}_equilibrate_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Elution 정보")
    edited_values['flowrate_elute'] = float(st.number_input('elute volume [BV/hr]', value=float(edited_values.get('flowrate_elute', 0)), key=f"{node_id}_flowrate_elute"))
    edited_values['tau_elute'] = float(st.number_input('elute 시간 [h]', value=float(edited_values.get('tau_elute', 0)), key=f"{node_id}_tau_elute"))
    st.write('elute 농도 [g/L]')
    elute_conc_df = _get_df_from_dict_list(edited_values.get('conc_elute', {}), columns=col_conc)
    elute_conc_df['농도 [g/L]'] = elute_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_elute_df'] = st.data_editor(elute_conc_df, num_rows="dynamic", key=f"{node_id}_elute_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Product 정보")
    edited_values['volume_product'] = float(st.number_input('Product volume / Elute volume', value=float(edited_values.get('volume_product', 0)), key=f"{node_id}_volume_product"))
    st.write('product 농도 [g/L]')
    product_conc_df = _get_df_from_dict_list(edited_values.get('conc_product', {}), columns=col_conc)
    product_conc_df['농도 [g/L]'] = product_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_product_df'] = st.data_editor(product_conc_df, num_rows="dynamic", key=f"{node_id}_product_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    return edited_values

def process_gel_filtration_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    
    # Retrieve the processed DataFrame outputs and apply fill_water3
    # The column name for concentration is '농도 [g/L]' as defined in col_conc
    processed_values['conc_wash'] = fill_water3(processed_values.pop('_conc_wash_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_equilibrate'] = fill_water3(processed_values.pop('_conc_equilibrate_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_elute'] = fill_water3(processed_values.pop('_conc_elute_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_product'] = fill_water3(processed_values.pop('_conc_product_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)

    # Update resin price from heat_utility if applicable
    resin_id = processed_values.get('resin_id')
    if resin_id and resin_id in st.session_state.get('heat_utility', {}):
        processed_values['resin_price'] = float(st.session_state['heat_utility'][resin_id])

    return processed_values


#============================================================================
# Unit: Diafiltration
#============================================================================

def render_diafiltration_widgets(current_node_data: dict, node_id: str):
    default_df_data = copy.deepcopy(st.session_state.all_unit_defaults.get('diafiltration_default', {}))
    if 'separation' not in default_df_data or not default_df_data['separation']:
        default_df_data['separation'] = {i:0.2 for i in st.session_state.chemical_list}
    edited_values = {**default_df_data, **current_node_data}

    chem_list = st.session_state.get('chemical_list', [])
    util_list = list(st.session_state.get('heat_utility', {}).keys())

    cip_index = util_list.index(edited_values['cip_id']) if edited_values['cip_id'] in util_list else 0
    wastewater_index = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0
    membrane_index = util_list.index(edited_values['membrane_id']) if edited_values['membrane_id'] in util_list else 0

    with st.expander('고급 설정'):
        edited_values['tau_cip'] = float(st.number_input('CIP 시간 [h]', value=float(edited_values.get('tau_cip', 0)), key=f"{node_id}_DF_tau_cip"))
        edited_values['cip_flowrate'] = float(st.number_input('CIP volume [BV/hr]', value=float(edited_values.get('cip_flowrate', 0)), key=f"{node_id}_DF_cip_flowrate"))
        edited_values['n_cip'] = int(st.number_input('CIP Run 횟수', value=int(edited_values.get('n_cip', 0)), key=f"{node_id}_DF_n_cip")) # Changed to int
        edited_values['cip_id'] = st.selectbox('CIP 용액 종류', options=util_list, index=cip_index, key=f"{node_id}_DF_cip_id")
        edited_values['wastewater_id'] = st.selectbox('Wastewater 종류', options=util_list, index=wastewater_index, key=f"{node_id}_DF_wastewater_id")
        

    st.write("Membrane 정보")
    edited_values['membrane_id'] = st.selectbox('Membrane 종류', options=util_list, index=membrane_index, key=f"{node_id}_DF_membrane_id")
    try:
       edited_values['membrane_cost'] = float(st.number_input('Membrane 가격 [USD]', value = float(st.session_state.get('heat_utility', {}).get(edited_values['membrane_id'], 0.0)), key=f"{node_id}_DF_membrane_cost"))
    except ValueError:
        st.write(':red[Membrane이 등록되지 않음. 수동 입력 또는 화학물질 목록 확인.]')
        edited_values['membrane_cost'] = float(st.number_input('Membrane 가격 [USD]', value=float(edited_values.get('membrane_cost', 0.0)), key=f"{node_id}_DF_membrane_cost_manual"))

    edited_values['membrane_life'] = float(st.number_input('membrane 수명 [hr]', value=float(edited_values.get('membrane_life', 0)), key=f"{node_id}_DF_membrane_life"))

    col_conc = ['물질','농도 [g/L]']

    
    edited_values['tau'] = float(st.number_input('시간 [h]', value=float(edited_values.get('tau', 0)), key=f"{node_id}_DF_tau"))
    st.info("각 물질에 대한 분리 효율 (0-1)을 입력하세요. 0는 모두 유출, 1는 모두 고체상으로 분리.")
    separation_df = _get_df_from_dict_list(edited_values.get('split', {}), ['물질', 'Rate In Solids'])
    edited_values['_separation_df'] = st.data_editor(
        separation_df,
        num_rows="dynamic",
        hide_index=True,
        key=f"{node_id}_DF_separation_ui",
        column_config={
            '물질': st.column_config.SelectboxColumn(options=chem_list, required=True),
            # The column name in the DataFrame is now 'Rate In Solids', so use it directly
            'Rate In Solids': st.column_config.NumberColumn(min_value=0.0, max_value=1.0, format="%.3f", required=True, step=0.0001)
        }
    )
    
    return edited_values

def process_diafiltration_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    # Update membrane price from heat_utility if applicable
    membrane_id = processed_values.get('membrane_id')
    if membrane_id and membrane_id in st.session_state.get('heat_utility', {}):
        processed_values['membrane_cost'] = float(st.session_state['heat_utility'][membrane_id])
    separation_df = processed_values.pop('_separation_df')
    processed_values['separation'] = dict(zip(separation_df['물질'], separation_df['Rate In Solids']))

    return processed_values

#============================================================================
# Unit: Freeze Dryer
#============================================================================

def render_freeze_dryer_widgets2(current_node_data: dict, node_id: str):
    default_fd_data = copy.deepcopy(st.session_state.all_unit_defaults.get('freeze_dryer_defaults2', {}))
    edited_values = {**default_fd_data, **current_node_data}
    util_list = list(st.session_state.get('heat_utility', {}).keys())
    # Use hepa filter if GMP
    #if st.session_state.gmp:
    #    edited_values['hu_condenser_id'] = 'hepa_filter'

    heat_idx = util_list.index(edited_values['heat_id']) if edited_values['heat_id'] in util_list else 0
    wastewater_idx = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0

    with st.expander('고급 설정'):
        #edited_values['freeze_T'] = float(st.number_input('Pre-freezer 온도 [C]', value=float(edited_values.get('freeze_T', 0)), key=f"{node_id}_freeze_T"))
        edited_values['steam_specific_amount'] = float(st.number_input('Steam kg / Evap kg', value=float(edited_values.get('steam_specific_amount', 0)), key=f"{node_id}_steam_specific_amount"))
        edited_values['specific_power'] = float(st.number_input('kW / shelf m2', value=float(edited_values.get('specific_power', 0.3)), key=f"{node_id}_specific_power"))
        edited_values['max_area_per_vessel'] = float(st.number_input('Vessel 당 max shelf 넓이 [m2]', value=float(edited_values.get('max_area_per_vessel', 0)), key=f"{node_id}_max_area_per_vessel"))
        edited_values['_SHELF_PACKING_FACTOR'] = float(st.number_input('Vessel 내 tray 집적도', value=float(edited_values.get('_SHELF_PACKING_FACTOR', 0)), key=f"{node_id}_SHELF_PACKING_FACTOR"))
        edited_values['_SAMPLE_PACKING_FACTOR'] = float(st.number_input('Tray 내 Sample 집적도 (m2/m2)', value=float(edited_values.get('_SAMPLE_PACKING_FACTOR', 0.7)), key=f"{node_id}_SAMPLE_PACKING_FACTOR"))

        edited_values['heat_id'] = st.selectbox('Heat source', options=util_list, index=heat_idx, key=f"{node_id}_heat_id")
        edited_values['wastewater_id'] = st.selectbox('폐기물 종류', options=util_list, index=wastewater_idx, key=f"{node_id}_wastewater_id")


    edited_values['target_final_moisture_content'] = float(st.number_input('최종 수분 농도 (%)', value=float(edited_values.get('target_final_moisture_content', 0)), key=f"{node_id}_target_final_moisture_content"))
    edited_values['sample_thickness'] = float(st.number_input('샘플 두께 [m]', value=float(edited_values.get('sample_thickness', 0)), key=f"{node_id}_sample_thickness"))
    edited_values['tau_loading'] = float(st.number_input('setup 시간 [h]', value=float(edited_values.get('tau_loading', 0)), key=f"{node_id}_tau_loading"))
    edited_values['tau_sublimation'] = float(st.number_input('건조 시간 [h]', value=float(edited_values.get('tau_sublimation', 0)), key=f"{node_id}_tau_sublimation"))
    edited_values['tau_etc'] = float(st.number_input('그 외 시간 [h]', value=float(edited_values.get('tau_etc', 0)), key=f"{node_id}_tau_unloading"))
    edited_values['P'] = float(st.number_input('Pressure [Pa]', value=float(edited_values.get('P', 0)), key=f"{node_id}_P"))

    
    return edited_values

def process_freeze_dryer_data2(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    # Update membrane price from heat_utility if applicable

    return processed_values
    

#============================================================================
# Unit: Freeze Dryer
#============================================================================

def render_freeze_dryer_widgets(current_node_data: dict, node_id: str):
    default_fd_data = copy.deepcopy(st.session_state.all_unit_defaults.get('freeze_dryer_defaults', {}))
    edited_values = {**default_fd_data, **current_node_data}
    util_list = list(st.session_state.get('heat_utility', {}).keys())
    # Use hepa filter if GMP
    if st.session_state.gmp:
        edited_values['hu_condenser_id'] = 'hepa_filter'

    air_filter_idx = util_list.index(edited_values['hu_air_filter_id']) if edited_values['hu_air_filter_id'] in util_list else 0
    freeze_idx = util_list.index(edited_values['hu_freeze_id']) if edited_values['hu_freeze_id'] in util_list else 0
    condenser_idx = util_list.index(edited_values['hu_condenser_id']) if edited_values['hu_condenser_id'] in util_list else 0

    with st.expander('고급 설정'):
        edited_values['freeze_T'] = float(st.number_input('Pre-freezer 온도 [C]', value=float(edited_values.get('freeze_T', 0)), key=f"{node_id}_freeze_T"))
        edited_values['sublimation_T'] = float(st.number_input('Sublimation 온도 [C]', value=float(edited_values.get('sublimation_T', 0)), key=f"{node_id}_sublimation_T"))
        edited_values['condenser_T'] = float(st.number_input('Water Condenser 온도 [C]', value=float(edited_values.get('condenser_T', 0)), key=f"{node_id}_condenser_T"))
        edited_values['hu_freeze_id'] = st.selectbox('Pre-Freezer 용액 종류', options=util_list, index=freeze_idx, key=f"{node_id}_hu_freeze_id")
        edited_values['hu_condenser_id'] = st.selectbox('Water Condenser 용액 종류', options=util_list, index=condenser_idx, key=f"{node_id}_hu_condenser_id")
        edited_values['hu_air_filter_id'] = st.selectbox('Air filter 종류', options=util_list, index=air_filter_idx, key=f"{node_id}_hu_air_filter_id")

        edited_values['max_area_per_vessel'] = float(st.number_input('Vessel 당 max shelf Area [m2]', value=float(edited_values.get('max_area_per_vessel', 0)), key=f"{node_id}_max_area_per_vessel"))
        edited_values['sublimation_mass_transfer_coefficient'] = float(st.number_input('sublimation_mass_transfer_coefficient', value=float(edited_values.get('sublimation_mass_transfer_coefficient', 0)), key=f"{node_id}_sublimation_mass_transfer_coefficient"))

    edited_values['target_final_moisture_content'] = float(st.number_input('최종 수분 농도', value=float(edited_values.get('target_final_moisture_content', 0)), key=f"{node_id}_target_final_moisture_content"))
    edited_values['sample_thickness'] = float(st.number_input('샘플 두께 [m]', value=float(edited_values.get('sample_thickness', 0)), key=f"{node_id}_sample_thickness"))
    edited_values['tau_loading'] = float(st.number_input('Loading 시간 [h]', value=float(edited_values.get('tau_loading', 0)), key=f"{node_id}_tau_loading"))
    edited_values['tau_freeze'] = float(st.number_input('선 냉동 시간 [h]', value=float(edited_values.get('tau', 0)), key=f"{node_id}_tau_freeze"))
    edited_values['tau_sublimation'] = float(st.number_input('건조 시간 [h]', value=float(edited_values.get('tau_sublimation', 0)), key=f"{node_id}_tau_sublimation"))
    edited_values['tau_unloading'] = float(st.number_input('샘플 회수 시간 [h]', value=float(edited_values.get('tau_unloading', 0)), key=f"{node_id}_tau_unloading"))
    edited_values['tau_CIP'] = float(st.number_input('청소/defrost 시간 [h]', value=float(edited_values.get('tau_CIP', 0)), key=f"{node_id}_tau_CIP"))
    

    return edited_values

def process_freeze_dryer_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    # Update membrane price from heat_utility if applicable

    return processed_values
    

#============================================================================
# Unit: Centrifuge
#============================================================================

def render_centrifuge_widgets(current_node_data: dict, node_id: str):
    default_centrifuge_data = copy.deepcopy(st.session_state.all_unit_defaults.get('centrifuge_defaults', {}))
    # Ensure separation dict is initialized with all chemicals if not present
    if 'split' not in default_centrifuge_data or not default_centrifuge_data['split']:
        default_centrifuge_data['split'] = {i:0.2 for i in st.session_state.chemical_list}

    edited_values = {**default_centrifuge_data, **current_node_data}
    chem_list = st.session_state.get('chemical_list', [])
    with st.expander('고급 설정'):
        edited_values['base_kW'] = float(st.number_input('기본 전력 소비 (kW)', value=float(edited_values.get('base_kW', 0)), key=f"{node_id}_centrifuge_base_kW"))
        
    st.write("분리 효율")
    st.info("각 물질에 대한 분리 효율 (0-1)을 입력하세요. 0는 모두 유출, 1는 모두 고체상으로 분리.")
    
    # Now _get_df_from_dict_list will correctly name the second column 'Rate In Solids'
    separation_df = _get_df_from_dict_list(edited_values.get('split', {}), ['물질', 'Rate In Solids'])
    edited_values['_separation_df'] = st.data_editor(
        separation_df,
        num_rows="dynamic",
        hide_index=True,
        key=f"{node_id}_centrifuge_separation_ui",
        column_config={
            '물질': st.column_config.SelectboxColumn(options=chem_list, required=True),
            # The column name in the DataFrame is now 'Rate In Solids', so use it directly
            'Rate In Solids': st.column_config.NumberColumn(min_value=0.0, max_value=1.0, format="%.3f", required=True, step=0.0001)
        }
    )

    product_options = ['Liquid', 'Solid']
    product_index = product_options.index(edited_values['Product']) if edited_values['Product'] in product_options else 0
    edited_values['Product'] = st.selectbox('주요 제품상', options=product_options, index=product_index, key=f"{node_id}_centrifuge_product")
    
    return edited_values

def process_centrifuge_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    # Process separation DataFrame
    separation_df = processed_values.pop('_separation_df')
    # Now the DataFrame column is correctly named 'Rate In Solids'
    processed_values['split'] = dict(zip(separation_df['물질'], separation_df['Rate In Solids']))
    
    return processed_values

#============================================================================
# Unit: Solution processor
#============================================================================

def render_sol_processor_widgets(current_node_data: dict, node_id: str):
    default_sp_data = copy.deepcopy(st.session_state.all_unit_defaults.get('sol_processor_default', {}))
    edited_values = {**default_sp_data, **current_node_data}
    col_conc = ['물질','농도 [g/L]']

    chem_list = st.session_state.get('chemical_list', [])
    util_list = list(st.session_state.get('heat_utility', {}).keys())

    wastewater_index = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0

    with st.expander('고급 설정'):
        
        edited_values['kW_per_m3'] = float(st.number_input('Agitator kW [kW/m3]', value=float(edited_values.get('kW_per_m3', 0.0985)), key=f"{node_id}_kW_per_m3"))
        edited_values['V_wf'] = float(st.number_input('Tank void factor', value=float(edited_values.get('V_wf', 0.8)), key=f"{node_id}_V_wf"))
        edited_values['wastewater_id'] = st.selectbox('Wastewater 종류', options=util_list, index=wastewater_index, key=f"{node_id}_wastewater_id")
        
    edited_values['tau'] = float(st.number_input('Mix 시간 [hr]', value=float(edited_values.get('tau', 1)), key=f"{node_id}_tau"))
    edited_values['T'] = float(st.number_input('온도 [C]', value=float(edited_values.get('T', 0)), key=f"{node_id}_T"))
    
    st.write('Process 용액')
    edited_values['sol_vol'] = float(st.number_input('Feed 당 용액양 [L/L feed]', value=float(edited_values.get('sol_vol', 0.2)), key=f"{node_id}_sol_vol"))
    st.write('Process 용액 농도 [g/L]')
    sol_conc_df = _get_df_from_dict_list(edited_values.get('sol_conc', {}), columns=col_conc)
    sol_conc_df['농도 [g/L]'] = sol_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_sol_df'] = st.data_editor(sol_conc_df, num_rows="dynamic", key=f"{node_id}_sol_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    edited_values['waste_vol'] = float(st.number_input('Feed 당 Waste 양 [L/L feed]', value=float(edited_values.get('waste_vol', 0.0)), key=f"{node_id}_waste_vol"))

    return edited_values

def process_sol_processor_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    processed_values['conc_sol'] = fill_water3(processed_values.pop('_conc_sol_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    
    return processed_values

#============================================================================
# Unit: Distillation
#============================================================================

def render_distillation_widgets(current_node_data: dict, node_id: str):
    default_distill_data = copy.deepcopy(st.session_state.all_unit_defaults.get('distillation_defaults', {}))
    edited_values = {**default_distill_data, **current_node_data}
    edited_values['product_idx'] = edited_values.get('product_idx', 0)
    edited_values['wastewater_id'] = edited_values.get('wastewater_id', 'wastewater')

    chem_list = st.session_state.get('chemical_list', [])
    util_list = list(st.session_state.get('heat_utility', {}).keys())

    wastewater_index = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0

    with st.expander('고급 설정'):
        edited_values['P'] = float(st.number_input('Pressure [Pa]', value=float(edited_values.get('P', 101325)), key=f"{node_id}_P"))
        edited_values['tray_efficiency'] = float(st.number_input('Tray 효율 [%]', value=float(edited_values.get('tray_efficiency', 80)), key=f"{node_id}_tray_efficiency"))
        edited_values['tray_spacing'] = float(st.number_input('Tray간 간격[m]', value=float(edited_values.get('tray_spacing', 0.45)), key=f"{node_id}_tray_spacing"))
        edited_values['heat_transfer_efficiency'] = float(st.number_input('Reboiler 효율 [%]', value=float(edited_values.get('heat_transfer_efficiency', 100.0)), key=f"{node_id}_heat_transfer_efficiency"))
        edited_values['condenser_efficiency'] = float(st.number_input('Condenser 효율 [%]', value=float(edited_values.get('cooling_efficiency', 100.0)), key=f"{node_id}_cooling_efficiency"))
        edited_values['wastewater_id'] = st.selectbox('Wastewater 종류', options=util_list, index=wastewater_index, key=f"{node_id}_wastewater_id")

    edited_values['product_phase'] = st.selectbox('Product phase', options=['Distillate','Bottoms'], index=edited_values['product_idx'], key=f"{node_id}_product_phase")
    edited_values['k'] = float(st.number_input('R/Rmin', value=float(edited_values.get('k', 1.2)), key=f"{node_id}_k"))
    alpha_df = _get_df_from_dict_list(edited_values.get('alpha', {}), ['물질', 'Alpha'])
    hvap_df = _get_df_from_dict_list(edited_values.get('H_vap', {}), ['물질', 'Hvap [kJ/kg]'])
    conc_df = _get_df_from_dict_list(edited_values.get('split', {}), ['물질', 'Distillate로 가는 비율[%]'])
    distillation_df = pd.merge(conc_df, alpha_df, on='물질' ,how='outer').merge(hvap_df, on='물질' ,how='outer')
    st.info('Distillate에 대한 정보를 입력하세요. 작성하지 않을 시 전부 Bottoms에 들어가는 것으로 간주. Hvap의 경우 작성하지 않을 시 Pubchem 검색 후 없으면 물과 같다고 간주')
    edited_values['_distill_df'] = st.data_editor(distillation_df, num_rows='dynamic', hide_index=True, key=f"{node_id}_distill_ui",
        column_config={
            '물질': st.column_config.SelectboxColumn(options=chem_list, required=True),
            'Distillate로 가는 비율[%]': st.column_config.NumberColumn(min_value=0.0, max_value=100.0, format="%.3f", required=True, step=0.0001),
            'Alpha': st.column_config.NumberColumn(min_value=0.0, format="%.3f", required=True, step=0.0001),
            'Hvap [kJ/kg]': st.column_config.NumberColumn(min_value=0.0, format="%.3f", required=False, step=0.0001)
            }
        )
    edited_values['T_reboiler'] = float(st.number_input('Reboiler 온도 [C]', value=float(edited_values.get('k', 200.0)), key=f"{node_id}_T_reboiler"))
    edited_values['T_condenser'] = float(st.number_input('Condenser 온도 [C]', value=float(edited_values.get('k', 150.0)), key=f"{node_id}_T_condenser"))
    edited_values['vap_velocity'] = float(st.number_input('Vapor velocity [m/s]', value=float(edited_values.get('val_velocity', 3.0)), key=f"{node_id}_vap_velocity"))

    return edited_values


def process_distillation_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    # Update membrane price from heat_utility if applicable
    separation_df = processed_values.pop('_distill_df')
    processed_values['split'] = dict(zip(separation_df['물질'], separation_df['Distillate로 가는 비율[%]']))
    processed_values['alpha'] = dict(zip(separation_df['물질'], separation_df['Alpha']))
    processed_values['H_vap'] = dict(zip(separation_df['물질'], separation_df['Hvap [kJ/kg]']))

    return processed_values


#============================================================================
# Unit: SMB Chromatography
#============================================================================

def render_smb_widgets(current_node_data: dict, node_id: str):
    default_smb_data = copy.deepcopy(st.session_state.all_unit_defaults.get('smb_defaults', {}))
    edited_values = {**default_smb_data, **current_node_data}
    col_conc = ['물질','농도 [g/L]']

    chem_list = st.session_state.get('chemical_list', [])
    util_list = list(st.session_state.get('heat_utility', {}).keys())
    edited_values['binding_material'] = edited_values.get('binding_material', st.session_state.main_product)

    chem_index = chem_list.index(edited_values['binding_material'])
    resin_index = util_list.index(edited_values['resin_id']) if edited_values['resin_id'] in util_list else 0
    wastewater_index = util_list.index(edited_values['wastewater_id']) if edited_values['wastewater_id'] in util_list else 0

    with st.expander('고급 설정'):
        edited_values['column_price'] = float(st.number_input('Empty column 가격 [USD/L resin]', value=float(edited_values.get('column_price', 7000.0)), key=f"{node_id}_column_price"))
        edited_values['P_drop'] = float(st.number_input('Pressure drop [Pa]', value=float(edited_values.get('P_drop', 0)), key=f"{node_id}_P_drop"))
        edited_values['motor_efficiency'] = float(st.number_input('Motor Efficiency', value=float(edited_values.get('motor_efficiency', 0)), key=f"{node_id}_motor_efficiency"))
        edited_values['compressor_isentropic_efficiency'] = float(st.number_input('compressor_isentropic_efficiency', value=float(edited_values.get('compressor_isentropic_efficiency', 0)), key=f"{node_id}_comp_eff"))
        edited_values['pump_efficiency'] = float(st.number_input('Pump Efficiency', value=float(edited_values.get('pump_efficiency', 0)), key=f"{node_id}_pump_eff"))
        edited_values['wastewater_id'] = st.selectbox('Wastewater 종류', options=util_list, index=wastewater_index, key=f"{node_id}_wastewater_id")

    st.write("레진 정보")
    edited_values['resin_id'] = st.selectbox('Resin 종류', options=util_list, index=resin_index, key=f"{node_id}_resin_id")
    edited_values['binding_material'] = st.selectbox('Binding Chemical', options=chem_list, index=chem_index, key=f"{node_id}_binding_material")
    st.info("SMB는 continuous하기 때문에 Binding capacity 역시 g/hr product per L resin으로 설정. 다른 chromatography와 다름으로 주의 필요")
    edited_values['binding_capacity'] = float(st.number_input('Binding Capacity [g/hr binding_material / L resin]', value=float(edited_values.get('binding_capacity', 2.0)), key=f"{node_id}_binding_capacity"))
    edited_values['N_columns'] = int(st.number_input('Number of columns', value=int(edited_values.get('N_columns', 8)), key=f"{node_id}_N_columns"))
    
    
    st.write('Desorbent 정보')
    edited_values['flowrate_desorbent'] = float(st.number_input('Desorbent flowrate [BV/hr]', value=float(edited_values.get('flowrate_desorbent', 0.02)), key=f"{node_id}_flowrate_desorbent"))
    st.write('Process 용액 농도 [g/L]')
    sol_conc_df = _get_df_from_dict_list(edited_values.get('conc_desorbent', {}), columns=col_conc)
    sol_conc_df['농도 [g/L]'] = sol_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_desorbent_df'] = st.data_editor(sol_conc_df, num_rows="dynamic", key=f"{node_id}_desorbent_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Regenerant 정보")
    edited_values['flowrate_regenerant'] = float(st.number_input('Regenerant flowrate [BV/hr]', value=float(edited_values.get('flowrate_regenerant', 0)), key=f"{node_id}_flowrate_regenerant"))
    st.write('Regenerant 농도 [g/L]')
    regenerant_conc_df = _get_df_from_dict_list(edited_values.get('conc_regenerant', {}), columns=col_conc)
    regenerant_conc_df['농도 [g/L]'] = regenerant_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_regenerant_df'] = st.data_editor(regenerant_conc_df, num_rows="dynamic", key=f"{node_id}_regenerant_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    st.write("Product 정보")
    edited_values['flowrate_product'] = float(st.number_input('Product flowrate / Feed flowrate []', value=float(edited_values.get('volume_product', 0)), key=f"{node_id}_volume_product"))
    st.write('product 농도 [g/L]')
    product_conc_df = _get_df_from_dict_list(edited_values.get('conc_product', {}), columns=col_conc)
    product_conc_df['농도 [g/L]'] = product_conc_df['농도 [g/L]'].astype(float)
    edited_values['_conc_product_df'] = st.data_editor(product_conc_df, num_rows="dynamic", key=f"{node_id}_product_conc_ui", hide_index=True, column_config={'물질': st.column_config.SelectboxColumn(options=chem_list, required=True), '농도 [g/L]': st.column_config.NumberColumn(format="%.2f", required=True, step=0.001)})

    return edited_values


def process_smb_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    
    # Retrieve the processed DataFrame outputs and apply fill_water3
    # The column name for concentration is '농도 [g/L]' as defined in col_conc
    processed_values['conc_desorbent'] = fill_water3(processed_values.pop('_conc_desorbent_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_regenerant'] = fill_water3(processed_values.pop('_conc_regenerant_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)
    processed_values['conc_product'] = fill_water3(processed_values.pop('_conc_product_df').set_index('물질')['농도 [g/L]'].to_dict(), 1)

    # Update resin price from heat_utility if applicable
    resin_id = processed_values.get('resin_id')
    if resin_id and resin_id in st.session_state.get('heat_utility', {}):
        processed_values['resin_price'] = float(st.session_state['heat_utility'][resin_id])

    return processed_values
    

#============================================================================
# Unit: Generic (Fallback for unhandled types)
#============================================================================

def render_generic_widgets(current_node_data: dict, node_id: str):
    edited_values = current_node_data.copy()
    chem_list = st.session_state.get('chemical_list', [])
    
    # Iterate over a list of items/keys (a copy), not the dictionary itself
    for attr, value in list(edited_values.items()): # <--- Using list() to avoid RuntimeError
        if attr in ['Concentration [g/L]', 'Rate In Solid']:
            # Determine column names for this specific data_editor
            if attr == 'Concentration [g/L]':
                data_editor_cols = ['물질', '농도 [g/L]']
            elif attr == 'Rate In Solid':
                data_editor_cols = ['물질', 'Rate In Solid'] # Specific column name
            else:
                data_editor_cols = ['Name', attr] # Generic fallback

            # _get_df_from_dict_list will now use data_editor_cols for naming
            df_to_edit = _get_df_from_dict_list(edited_values.get(attr, {}), data_editor_cols)
            
            # Configure column_config dynamically, using the actual column name
            column_configs = {
                data_editor_cols[0]: st.column_config.SelectboxColumn(options=chem_list),
                data_editor_cols[1]: st.column_config.NumberColumn(default=0.0)
            }
            
            edited_values[f'_{attr}_df'] = st.data_editor(
                df_to_edit,
                num_rows="dynamic",
                hide_index=True,
                key=f"{node_id}_{attr}",
                column_config=column_configs # Use dynamic column_configs
            )
        elif attr in ['Target', 'Product', 'Waste type', 'chemical']:
            options = chem_list if attr == 'Target' else \
                      ['Liquid', 'Solid'] if attr == 'Product' else \
                      ['Liquid', 'Solid', 'Gas'] if attr == 'Waste type' else \
                      chem_list # Fallback for 'chemical'
            current_value = edited_values.get(attr)
            current_index = options.index(current_value) if current_value in options else 0
            edited_values[attr] = st.selectbox(attr, options, index=current_index, key=f"{node_id}_{attr}")
        elif isinstance(value, (int, float)):
            edited_values[attr] = float(st.number_input(attr, value=float(value), key=f"{node_id}_{attr}"))
        elif isinstance(value, dict): # For nested dictionaries that are not data_editor types
            st.subheader(f"Nested Dictionary: {attr}")
            with st.expander(f"Edit {attr}"):
                for sub_attr, sub_value in list(value.items()): # Iterate over copy of sub-dict
                    if isinstance(sub_value, (int, float)):
                        value[sub_attr] = float(st.number_input(f"{sub_attr} ({attr})", value=float(sub_value), key=f"{node_id}_{attr}_{sub_attr}"))
                    else:
                        value[sub_attr] = st.text_input(f"{sub_attr} ({attr})", value=str(sub_value), key=f"{node_id}_{attr}_{sub_attr}")
            edited_values[attr] = value # Update the main dict
        else:
            edited_values[attr] = st.text_input(attr, value=str(value), key=f"{node_id}_{attr}")
    return edited_values

def process_generic_data(submitted_widget_data: dict):
    processed_values = submitted_widget_data.copy()
    for attr, value in list(processed_values.items()): # Iterate on a copy to allow modification
        if attr.startswith('_') and attr.endswith('_df'): # Process temporary data_editor DFs
            original_attr = attr[1:-3] # e.g., '_Concentration [g/L]_df' -> 'Concentration [g/L]'
            if isinstance(value, pd.DataFrame):
                # With the updated _get_df_from_dict_list, original_attr should now be the correct column name
                value_col = original_attr
                processed_values[original_attr] = dict(zip(value['물질'], value[value_col]))
            processed_values.pop(attr) # Remove the temp key
    return processed_values

#============================================================================
# Central Dispatchers for Node Editing
#============================================================================

def get_node_editor_functions(node_type: str):
    """
    Returns a tuple of (widget_renderer_func, data_processor_func) for a given node type.
    """
    # Map node types to their rendering and processing functions
    func_map = {
        "발효기": (render_fermenter_widgets, process_fermenter_data),
        #"MVR": (render_MVR_widgets, process_MVR_data),
        "증발기": (render_MVR_widgets, process_MVR_data),
        "HIC column": (render_HIC_widgets, process_HIC_data),
        "IEX column": (render_IEX_widgets, process_IEX_data),
        "DiaFiltration": (render_diafiltration_widgets, process_diafiltration_data),
        '원심분리기':(render_centrifuge_widgets, process_centrifuge_data),
        'gel_filtration':(render_gel_filtration_widgets, process_gel_filtration_data),
        #'동결건조기':(render_freeze_dryer_widgets, process_freeze_dryer_data)
        '동결건조기':(render_freeze_dryer_widgets2, process_freeze_dryer_data2),
        '용액처리기':(render_sol_processor_widgets, process_sol_processor_data),
        'SMB_Chromatography':(render_smb_widgets, process_smb_data),
        'Distillation':(render_distillation_widgets, process_distillation_data)
        # Add more mappings for other specific node types
    }
    
    # Return the specific functions or a generic fallback
    return func_map.get(node_type, (render_generic_widgets, process_generic_data))


def edit_node(node: StreamlitFlowNode):
    """
    Renders all widgets for a node (common and type-specific).
    Returns a dictionary representing the node.data with raw widget outputs.
    Does NOT contain st.form or st.form_submit_button.
    """
    node_id = node.id # Get node_id from the node object

    # Ensure 'Value' key exists and is a dictionary
    if 'Value' not in node.data or not isinstance(node.data['Value'], dict):
        node.data['Value'] = {}

    # This will hold the collected widget values for node.data['Value']
    edited_node_data_value = node.data['Value'].copy() 

    # Common fields for all nodes (e.g., node 'content'/'label')
    edited_node_data_content = st.text_input('Name', value=node.data.get('custom_value', node_id), key=f"{node_id}_name")
    
    # Get the appropriate rendering function for this node type
    renderer, _ = get_node_editor_functions(node.data.get('node_type', 'Default')) # Default to generic
    
    # Call the renderer to display widgets and collect their values
    edited_node_data_value = renderer(edited_node_data_value, node_id)
    
    # Reconstruct the node.data dictionary with updated content and Value
    updated_node_data = node.data.copy()
    updated_node_data['content'] = edited_node_data_content
    updated_node_data['Value'] = edited_node_data_value
    
    return updated_node_data

#============================================================================
# Edge Editing Functions
#============================================================================

def render_edge_widgets(current_edge_data: dict, edge_id: str):
    """
    Renders widgets for edge properties.
    """
    edited_values = current_edge_data.copy()

    edited_values['label'] = st.text_input("Label", value=edited_values.get('label', edge_id), key=f"edit_edge_label_{edge_id}")
    edited_values['flow_ratio'] = float(st.number_input("Flow Ratio", value=float(edited_values.get('flow_ratio', 1.0)), min_value=0.0, max_value=1.0, key=f"edit_edge_flow_ratio_{edge_id}"))
    
    # Add other edge-specific properties here
    
    return edited_values

def process_edge_data(submitted_widget_data: dict):
    """
    Processes edge data after form submission.
    """
    # For simple edge data, processing might just be returning the submitted data.
    return submitted_widget_data
