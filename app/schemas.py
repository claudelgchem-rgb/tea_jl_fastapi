"""Pydantic request models for the API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HeatUtilityRow(BaseModel):
    utility: str
    price: float = Field(0.0, alias="price [USD/kg]")

    class Config:
        populate_by_name = True


class ConfigRequest(BaseModel):
    main_product: str
    main_source: str
    target_amount: float
    operating_hours: float = 7920
    gmp: bool = True
    od_to_dcw: float = 0.22
    electricity_price: float = 0.128
    currency: float = 1500
    heat_utility: Optional[Dict[str, float]] = None


class ChemicalRow(BaseModel):
    Name: str
    Formula: str = ""
    Price: float = Field(0.0, alias="Price (USD/kg)")
    Phase: str = "l"

    class Config:
        populate_by_name = True


class ChemicalsRequest(BaseModel):
    chemicals: List[ChemicalRow]


class SolutionRow(BaseModel):
    Name: str
    concentration: float = Field(0.0, alias="Concentration [g/L]")

    class Config:
        populate_by_name = True


class SolutionItem(BaseModel):
    name: str
    autoclave: bool = True
    rows: List[SolutionRow] = []


class SolutionsRequest(BaseModel):
    solutions: List[SolutionItem]


class AddNodeRequest(BaseModel):
    node_type: str


class DeleteNodeRequest(BaseModel):
    node_id: str


class AddEdgeRequest(BaseModel):
    source: str
    target: str


class DeleteEdgeRequest(BaseModel):
    edge_id: str


class MoveNodeRequest(BaseModel):
    node_id: str
    x: float
    y: float


class EditNodeRequest(BaseModel):
    name: str
    value: Dict[str, Any]


class ScenarioRequest(BaseModel):
    name: str
