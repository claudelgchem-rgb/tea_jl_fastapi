"""Server-side session state.

The original application stored everything in Streamlit's ``st.session_state``,
a per-browser-tab dict-like object that persisted across reruns.  FastAPI is
stateless, so we recreate the same idea explicitly: every browser gets a
session id (stored in a signed cookie) and we keep one :class:`SessionState`
per id in an in-memory store.

``SessionState`` deliberately mimics ``st.session_state`` so the ported
``flow_tabs`` modules can keep using ``state.foo`` / ``state.get('foo')`` /
``'foo' in state`` / ``state['foo']`` exactly as the Streamlit code did.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, Iterator


class SessionState:
    """A dict-like namespace, attribute- and item-accessible.

    Mirrors the subset of the ``st.session_state`` API used by the app:
    attribute access, item access, ``in``, ``.get()`` and ``.setdefault()``.
    """

    def __init__(self) -> None:
        # Use object.__setattr__ to avoid recursing through our __setattr__.
        object.__setattr__(self, "_data", {})

    # -- attribute access -------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, "_data")[name]
        except KeyError as exc:  # pragma: no cover - parity with Streamlit
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self._data[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self._data[name]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(name) from exc

    # -- item access ------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    # -- dict helpers -----------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        return self._data.setdefault(key, default)

    def update(self, other: Dict[str, Any]) -> None:
        self._data.update(other)

    def to_dict(self) -> Dict[str, Any]:
        return self._data


class SessionStore:
    """Thread-safe in-memory registry of :class:`SessionState` objects."""

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def get_or_create(self, session_id: str | None) -> tuple[str, SessionState]:
        with self._lock:
            if session_id and session_id in self._sessions:
                return session_id, self._sessions[session_id]
            new_id = session_id or self.new_id()
            state = SessionState()
            self._sessions[new_id] = state
            return new_id, state

    def reset(self, session_id: str) -> SessionState:
        with self._lock:
            state = SessionState()
            self._sessions[session_id] = state
            return state


# Single process-wide store (mirrors Streamlit's single-process model).
store = SessionStore()
