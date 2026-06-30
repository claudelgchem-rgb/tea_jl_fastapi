"""Plain data models replacing the ``streamlit_flow`` component objects.

The original code used ``StreamlitFlowNode`` / ``StreamlitFlowEdge`` /
``StreamlitFlowState`` from the third-party ``streamlit_flow`` React component.
Those carried rendering metadata (position, ports, style) plus the application
payload in ``node.data`` (``content``, ``node_type``, ``Value``,
``custom_value``, ``label``).

Here we keep the same shape with lightweight dataclasses so the rest of the
ported logic (which reads ``node.id`` / ``node.data[...]``) is unchanged, and so
the state round-trips cleanly to JSON for the browser-side flow editor.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FlowNode:
    id: str
    data: Dict[str, Any] = field(default_factory=dict)
    pos: Tuple[float, float] = (0.0, 0.0)

    def asdict(self) -> Dict[str, Any]:
        return {"id": self.id, "data": self.data, "pos": list(self.pos)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FlowNode":
        pos = d.get("pos", (0.0, 0.0))
        return cls(id=d["id"], data=d.get("data", {}), pos=tuple(pos))


@dataclass
class FlowEdge:
    id: str
    source: str
    target: str
    data: Dict[str, Any] = field(default_factory=dict)

    def asdict(self) -> Dict[str, Any]:
        return {"id": self.id, "source": self.source, "target": self.target, "data": self.data}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FlowEdge":
        return cls(id=d["id"], source=d["source"], target=d["target"], data=d.get("data", {}))


@dataclass
class FlowState:
    nodes: List[FlowNode] = field(default_factory=list)
    edges: List[FlowEdge] = field(default_factory=list)
    selected_id: Optional[str] = None
    timestamp: float = 0.0
    flow_rev: int = 0

    def asdict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.asdict() for n in self.nodes],
            "edges": [e.asdict() for e in self.edges],
            "selected_id": self.selected_id,
            "timestamp": self.timestamp,
            "flow_rev": self.flow_rev,
        }
