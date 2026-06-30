import streamlit as st
import numpy as np, pandas as pd, sys, os, json, copy, string, pickle, math
from uuid import uuid4
from chempy import Substance
import biosteam as bst
import thermosteam as tmo
from scipy.optimize import fsolve

#========================================================================
# --- Base variables ---
hd = ['Name', 'Formula', 'Price (USD/kg)', 'Phase']
      #, 'Cp (J/g/K)', 'Density (kg/m3)', 'MW', 'Hf (J/mol)', 'Tm (K)', 'Tb (K)', 'Tt (K)','Pt (Pa)']
optional_col = {'Tm (K)':273.15,'Tb (K)':373.12, 'Tt (K)':273.16, 'Pt (Pa)':611.65 ,'Cp (J/g/K)':4.1806, 'Hf (J/mol)':-2.8582e5, 'Density (kg/m3)':1000, 'Phase':'s'}
hd2 = {'ID':'Name', 'formula':'Formula', 'Cp':'Cp (J/g/K)', 'Phase':'Phase', 'rho':'Density (kg/m3)', 'MW':'MW', 'Hf':'Hf (J/mol)', 'Tm':'Tm (K)', 'Tb':'Tb (K)', 'Tt':'Tt (K)','Pt':'Pt (Pa)'}

# Aux utility function
def data_editor_to_dataframe(data_old, data_new):
    if data_new["deleted_rows"]:
        data_old = data_old.drop(data_new["deleted_rows"])
        data_old = data_old.reset_index(drop=True)
    if data_new["added_rows"]:
        #for index, changes in data_new["added_rows"].items():
        #    for column, value in changes.items():
        added_df = pd.DataFrame(data_new["added_rows"])
        data_old = pd.concat([data_old, added_df], ignore_index=True)
    if data_new["edited_rows"]:
        for index, changes in data_new["edited_rows"].items():
            for column, value in changes.items():
                if column not in data_old.columns:
                     data_old[column] = np.nan # Or appropriate default value
                data_old.loc[index, column] = value
    data_new = data_old.drop_duplicates()
    data_new.reset_index(inplace=True)
    return data_new

def read_file(raw):
    necessary_col = ['Name', 'Formula', 'Price (USD/kg)']
    if raw.name.endswith('.csv'):
        raw_data = pd.read_csv(raw,sep="\t|;|,",engine='python')
    else:
        raw_data = pd.read_excel(raw)
    missing_cols = [col for col in necessary_col if col not in raw_data.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {', '.join(missing_cols)}. Please check the file.")
    return raw_data

def add_property_model(chem,Cp,MW):
    chem.Cn.add_model(Cp*MW, top_priority=True)
    chem.Psat.add_model(1e-20, top_priority=True)
    chem.mu.add_model(0.0035599, top_priority=True)
    return chem

def process_chemical_data(data):
    optional_col = {'Tm (K)':273.15,'Tb (K)':373.12, 'Tt (K)':273.16, 'Pt (Pa)':611.65 ,'Cp (J/g/K)':4.1806, 'Hf (J/mol)':-2.8582e5, 'Density (kg/m3)':1000, 'Phase':'s'}

    data.set_index('Name', inplace=True, drop=False)

    # Fill missing optional columns with default values
    for col, default_val in optional_col.items():
        if col not in data.columns:
            data[col] = default_val
        else:
            data[col].fillna(default_val, inplace=True)
            data[col].replace({0: default_val, '': default_val}, inplace=True)

    # Fetch standard chemical properties but prioritize user-provided data
    chem_list, fetched_data = get_chemicals_and_properties(data)
    processed_data = fetched_data.copy()
    for col, default_val in optional_col.items():
        for idx in processed_data.index:
            user_val = data.loc[idx, col]
            if processed_data.loc[idx, col] != user_val and user_val != default_val:
                processed_data.loc[idx, col] = user_val
    
    return chem_list, processed_data

def get_chemicals_and_properties(data, hd=hd):
    #st.session_state.xx={}
    chemicals_list = [tmo.Chemical('Water')]
    properties_df = data.copy()
    for name, props in data.iterrows():
        try:
            chem = tmo.Chemical(name, search_ID=name)
            if chem.phase_ref == 's':
                chem = tmo.Chemical(name, search_ID=name, phase='s')
                chem = add_property_model(chem, chem.Cp(T=298.15), chem.MW)
            elif chem.phase_ref=='l':
                try:
                    chem.V(phase='l',T=300,P=101325)
                except:
                    chem.rho = 2440
        except:
            custom_props = {
                'phase': props.get('Phase'),
                'rho': props.get('Density (kg/m3)'),
                'Cp': props.get('Cp (J/g/K)'),
                'Hf': props.get('Hf (J/mol)'),
                'formula': props.get('Formula'),
                           }
            custom_props = {k: v for k, v in custom_props.items() if v is not None}
            chem = tmo.Chemical(ID=name, search_db=False, default=True, **custom_props)
            #if chem.phase_ref == 'l' and not chem.Psat.has_model():
            #    chem.Psat.add_model(1e-20, top_priority=True)
            #    chem.mu.add_model(0.001)
        chemicals_list.append(chem)
    chemicals = tmo.Chemicals(chemicals_list)
    #mixture = tmo.IdealMixture.from_chemicals(chemicals)
    bst.settings.set_thermo(chemicals, skip_checks=True, cache=True)
    #bst.settings.set_thermo(chemicals,mixture = mixture, skip_checks=True))

    for chem in chemicals:
        name = chem.ID
        for attr_name, col_name in hd2.items():
            try:
                prop = getattr(chem, attr_name, None)
                if callable(prop):
                    try:
                        value = prop(T=298.15)
                    except:
                        value = prop(T=298.15,P=101325)
                else:
                    value = prop
                properties_df.loc[name, col_name] = value
            except Exception:
                # If a property cannot be calculated for any reason, fill with NaN.
                properties_df.loc[name, col_name] = np.nan
    
    return chemicals, properties_df

@st.fragment
def upload_chemical():
    upload_col1,upload_col2 = st.columns([.85,.15], vertical_alignment='center')
    
    with upload_col1:
        chemical_upload = st.file_uploader(label="Upload chemical information",key=f"uploader_{st.session_state.uploader_key}",type=['csv','xlsx'])
        st.write("""Or manually write information.
        Name, formula and price are necessary. If chemical doesn't exist in PubChem and not given, chemical is assumed to have same property as liquid water""")
        chemical_upload2 = st.data_editor(st.session_state.chem_data,num_rows="dynamic",key='chem_upload2', hide_index=True, 
                column_config={'Name':st.column_config.TextColumn(required=True),
                               'Formula':st.column_config.TextColumn(required=True),
                               'Price (USD/kg)':st.column_config.NumberColumn(required=True),
                               #'Cp (J/g/K)':st.column_config.NumberColumn(), 
                               'Phase':st.column_config.TextColumn(), 
                               #'Density (kg/m3)':st.column_config.NumberColumn(), 
                               #'MW':st.column_config.NumberColumn(), 
                               #'Hf(J/mol)':st.column_config.NumberColumn(), 
                               #'Tm (K)':st.column_config.NumberColumn(), 
                               #'Tb (K)':st.column_config.NumberColumn(), 
                               #'Tt (K)':st.column_config.NumberColumn(),
                               #'Pt (Pa)':st.column_config.NumberColumn()
                              },
                column_order=hd)
    with upload_col2:
        if chemical_upload is not None and st.button('Process file'):
            temp_data = read_file(chemical_upload)
            st.session_state.uploader_key +=1
            st.session_state.chemicals, st.session_state.chem_data = process_chemical_data(temp_data)
            st.rerun()
            
        elif chemical_upload is None and st.button('Process file'):
            st.session_state.chemicals, st.session_state.chem_data = process_chemical_data(chemical_upload2)
            st.rerun()
    try:
        st.session_state.chemical_list = [i.ID for i in st.session_state.chemicals]
    except:
        pass

#===================================================================

def _build_one_chemical(name, props):
    """Build a single tmo.Chemical. Not cached individually because the
    object is mutated (rho / property models); caching it would alias a
    mutated object across reloads."""
    try:
        chem = tmo.Chemical(name, search_ID=name)
        if chem.phase_ref == 's':
            chem = tmo.Chemical(name, search_ID=name, phase='s')
            chem = add_property_model(chem, chem.Cp(T=298.15), chem.MW)
        elif chem.phase_ref == 'l':
            try:
                chem.V(phase='l', T=300, P=101325)
            except:
                chem.rho = 2440
    except:
        custom_props = {
            'phase': props.get('Phase'),
            'rho': props.get('Density (kg/m3)'),
            'Cp': props.get('Cp (J/g/K)'),
            'Hf': props.get('Hf (J/mol)'),
            'formula': props.get('Formula'),
        }
        custom_props = {k: v for k, v in custom_props.items() if v is not None}
        chem = tmo.Chemical(ID=name, search_db=False, default=True, **custom_props)
    return chem


def _chem_signature(data):
    """Hashable signature of a chemical set, used as the cache key."""
    cols = [c for c in _SIG_COLS if c in data.columns]
    return tuple(map(tuple, data[cols].itertuples(index=False)))


@st.cache_resource(ttl=3600)
def _build_chemicals_cached(signature, data_records):
    """Build the tmo.Chemicals object and the extracted-property DataFrame.
    Cached by `signature`; `data_records` carries the rows needed to rebuild
    the chemicals when the cache misses. set_thermo is NOT called here — it
    mutates global state and must run per-active-set in the caller."""
    data = pd.DataFrame(list(data_records))
    data.set_index('Name', inplace=True, drop=False)

    names = set(data.index)
    chemicals_list = []
    if 'Water' not in names:
        chemicals_list.append(_build_one_chemical('Water', {}))
    for name, props in data.iterrows():
        chemicals_list.append(_build_one_chemical(name, props))

    chemicals = tmo.Chemicals(chemicals_list)
    bst.settings.set_thermo(chemicals, skip_checks=True, cache=True)  # needed for property eval below

    properties_df = data.copy()
    for chem in chemicals:
        name = chem.ID
        for attr_name, col_name in hd2.items():
            try:
                prop = getattr(chem, attr_name, None)
                if callable(prop):
                    try:
                        value = prop(T=298.15)
                    except:
                        value = prop(T=298.15, P=101325)
                else:
                    value = prop
                properties_df.loc[name, col_name] = value
            except Exception:
                properties_df.loc[name, col_name] = np.nan

    return chemicals, properties_df


def get_chemicals_and_properties2(data, hd=hd):
    """Thin wrapper kept for backward compatibility."""
    sig = _chem_signature(data)
    records = data.to_dict('records')
    return _build_chemicals_cached(sig, tuple(map(lambda r: tuple(sorted(r.items())), records)) and records)

def process_chemical_data2(data):
    """Fill optional columns, build chemicals (cached), and overlay user
    overrides. Skips the whole rebuild when the active set is unchanged."""
    data = data.copy()
    data.set_index('Name', inplace=True, drop=False)

    # Fill missing optional columns with default values
    for col, default_val in optional_col.items():
        if col not in data.columns:
            data[col] = default_val
        else:
            data[col] = data[col].fillna(default_val)
            data[col] = data[col].replace({0: default_val, '': default_val})

    sig = _chem_signature(data)

    # Skip if this exact set is already active in this session
    if st.session_state.get('_chem_sig') == sig and 'chemicals' in st.session_state:
        return st.session_state.chemicals, st.session_state.chem_data

    chemicals, fetched_data = _build_chemicals_cached(sig, data.to_dict('records'))

    # Re-register thermo for the active set (cache may have returned a prior set)
    bst.settings.set_thermo(chemicals, skip_checks=True, cache=True)

    # Overlay user-provided values where they differ from defaults
    processed_data = fetched_data.copy()
    for col, default_val in optional_col.items():
        for idx in processed_data.index:
            if col in data.columns and idx in data.index:
                user_val = data.loc[idx, col]
                if processed_data.loc[idx, col] != user_val and user_val != default_val:
                    processed_data.loc[idx, col] = user_val

    st.session_state['_chem_sig'] = sig
    return chemicals, processed_data



@st.fragment
def upload_chemical2():
    upload_col1,upload_col2 = st.columns([.85,.15], vertical_alignment='center')
    
    with upload_col1:
        chemical_upload = st.file_uploader(label="Upload chemical information",key=f"uploader_{st.session_state.uploader_key}",type=['csv','xlsx'])
        st.write("""Or manually write information.
        Name, formula and price are necessary. If chemical doesn't exist in PubChem and not given, chemical is assumed to have same property as liquid water""")
        chemical_upload2 = st.data_editor(st.session_state.chem_data,num_rows="dynamic",key='chem_upload2', hide_index=True, 
                column_config={'Name':st.column_config.TextColumn(required=True),
                               'Formula':st.column_config.TextColumn(required=True),
                               'Price (USD/kg)':st.column_config.NumberColumn(required=True),
                               'Phase':st.column_config.TextColumn(), 
                              },
                column_order=hd)
    with upload_col2:
        if chemical_upload is not None and st.button('Process file'):
            temp_data = read_file(chemical_upload)
            st.session_state.uploader_key +=1
            st.session_state.chemicals, st.session_state.chem_data = process_chemical_data2(temp_data)
            st.rerun()
            
        elif chemical_upload is None and st.button('Process file'):
            st.session_state.chemicals, st.session_state.chem_data = process_chemical_data2(chemical_upload2)
            st.rerun()
    try:
        st.session_state.chemical_list = [i.ID for i in st.session_state.chemicals]
    except:
        pass







def fill_water3(in_mass, vol):
    stream = bst.Stream()
    #st.session_state.xx = {}
    def objective(water_mass):
        stream.empty()
        for chem, mass in in_mass.items():
            try:
                stream.imass[chem] = mass
            except:
                pass
        stream.imass['Water'] = float(water_mass)
        return stream.F_vol - vol 
    refined_water_mass = fsolve(objective, 800)[0]
    in_mass['Water'] = refined_water_mass
    if refined_water_mass<0:
        in_mass['Water']=0
    return in_mass
