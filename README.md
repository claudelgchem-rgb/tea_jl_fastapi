# TEA – Techno-Economic Analysis (FastAPI)

This project was converted from a **Streamlit** application to a **FastAPI**
web application. It is a techno-economic analysis (TEA) tool for bioprocesses
built on top of [`biosteam`](https://biosteam.readthedocs.io/): the user
registers chemicals, defines media solutions, draws a block-flow diagram of
unit operations, and runs a simulation that produces an OPEX/CAPEX cost
breakdown.

## What changed in the conversion

| Streamlit concept | FastAPI replacement |
|---|---|
| `main_app.py` single script | `app/main.py` JSON API + a single-page frontend (`app/templates`, `app/static`) |
| `st.session_state` | `app/session.py` – per-session server-side state (signed cookie → `SessionState`) |
| `streamlit_flow` React component | a plain SVG flow editor in `app/static/app.js` (drag nodes, drag-to-connect, double-click edge to delete) |
| `st.number_input` / `st.selectbox` / `st.data_editor` widgets | declarative **form schemas** built by `app/flow_tabs/util_bfd.py` and rendered by the browser |
| `st.cache_data` / `st.rerun()` | ordinary functions + stateless request/response |
| `flow_tabs/util_biosteam_Copy1.py` | `app/flow_tabs/util_biosteam.py` (same simulation logic, `st.*` removed) |
| `flow_tabs/util_bfd_Copy4.py` | `app/flow_tabs/util_bfd.py` (node management + `process_*` logic kept; `render_*_widgets` → `*_schema` builders) |
| cost-analysis result block | `app/compute.py` (returns JSON tables instead of styled DataFrames) |

The original Streamlit files are kept under `flow_tabs/` for reference.

## Project layout

```
app/
  main.py            FastAPI routes + frontend serving
  session.py         SessionState / SessionStore (replaces st.session_state)
  flow_models.py     FlowNode / FlowEdge / FlowState (replace streamlit_flow objects)
  data.py            session init, chemical management, scenario save/load
  default_data.py    built-in defaults (replaces the external initial_val.json)
  compute.py         calculation pipeline + OPEX/CAPEX cost tables
  schemas.py         pydantic request models
  flow_tabs/
    util_biosteam.py biosteam simulation core (ported)
    util_bfd.py      node schemas + data processing (ported)
    aux_compat.py    fallback shims for deployment-provided helpers/units
  templates/index.html
  static/app.js, static/style.css
```

## Running

```bash
python3.12 -m venv .venv
.venv/bin/pip install -U pip setuptools wheel
.venv/bin/pip install -r requirements.txt          # web stack
.venv/bin/pip install biosteam thermosteam          # simulation stack
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

> **Python 3.12+ is required** – `thermosteam` uses 3.12 f-string syntax and
> will not import on 3.11.

Scenario files are written to `./data` (override with `TEA_DATA_DIR`). If a real
`initial_val.json` is placed in that directory it overrides the built-in
defaults.

## Custom unit operations (deferred)

Running an actual simulation (`POST /api/calculate`) needs the project's custom
biosteam unit operations (`Custom_fermenter3`, `MVR`, `HIC_Column`, …) from a
`Biosteam_custom_unit` module, plus the real `aux_chemical` helpers. Those were
never part of this repository (the Streamlit app imported them from a
deployment `pages/` path).

Per the current scope these custom units are **deferred**: everything up to and
including chemical/thermo setup and stream construction runs, and `/api/calculate`
returns a clear `503` identifying the missing unit. To enable full calculations,
drop `Biosteam_custom_unit.py` and `aux_chemical.py` into `app/flow_tabs/`
(or install them as importable modules) — they are auto-detected and take
precedence over the fallback shims in `aux_compat.py`.

## API summary

| Method & path | Purpose |
|---|---|
| `GET /api/state` | full UI snapshot |
| `POST /api/chemicals` | register the chemical table |
| `POST /api/config` | set product/source/target/hours/GMP/utilities (the “다음” step) |
| `POST /api/solutions` | define media solutions (fills water, prices them) |
| `POST /api/nodes/add` · `/nodes/delete` · `/nodes/move` | flow node ops |
| `POST /api/edges/add` · `/edges/delete` | flow edge ops |
| `GET /api/nodes/{id}/schema` · `POST /api/nodes/{id}` | node form schema / save edit |
| `POST /api/calculate` | run simulation + cost analysis |
| `GET/POST /api/scenarios*` | list / save / load scenarios |
