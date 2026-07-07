"""Root entry point — bridges to the FastAPI application in ``app/main.py``.

The original Streamlit single-script app that used to live here has been
converted to FastAPI (see ``app/main.py`` and the ``app`` package).  This module
re-exports the FastAPI ``app`` so the server can be launched from the repo root:

    uvicorn main_app:app --host 0.0.0.0 --port 8000

which is equivalent to ``uvicorn app.main:app``.
"""

from app.main import app  # noqa: F401  (re-exported for uvicorn main_app:app)
