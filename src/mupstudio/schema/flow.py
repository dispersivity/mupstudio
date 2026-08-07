"""Flow: aquifer properties and boundary conditions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from mupstudio.schema.common import Id, PropertyField, TimeSeries, constant


class FlowProperties(BaseModel):
    """What the aquifer is made of."""

    k: PropertyField = Field(default_factory=lambda: constant(1.0), description="Horizontal K")
    k33: PropertyField | None = Field(default=None, description="Vertical K; defaults to k")
    porosity: PropertyField = Field(default_factory=lambda: constant(0.25))
    specific_storage: PropertyField = Field(default_factory=lambda: constant(1e-5))
    specific_yield: PropertyField = Field(default_factory=lambda: constant(0.15))
    starting_head: PropertyField = Field(default_factory=lambda: constant(0.0))
    icelltype: int = Field(
        default=0,
        description="0 confined, 1 convertible. Confined is the usual choice for a column.",
    )


class CellRange(BaseModel):
    """Cells named by index, for grids drawn by hand rather than from GIS.

    Indices are 1-based to match how MODFLOW input reads, since anyone checking
    this against a listing file is counting from one.
    """

    kind: Literal["cells"] = "cells"
    layers: list[int] = Field(min_length=1)
    rows: list[int] = Field(min_length=1)
    columns: list[int] = Field(min_length=1)


CellSelection = Annotated[CellRange, Field(discriminator="kind")]


class WellPackage(BaseModel):
    """Injection or extraction at cells. Negative rate extracts."""

    kind: Literal["well"] = "well"
    id: Id
    cells: CellSelection
    rate: TimeSeries


class ConstantHeadPackage(BaseModel):
    """Head held fixed. The usual inflow boundary for a column."""

    kind: Literal["chd"] = "chd"
    id: Id
    cells: CellSelection
    head: TimeSeries


class RechargePackage(BaseModel):
    """Areally distributed inflow at the top."""

    kind: Literal["recharge"] = "recharge"
    id: Id
    rate: TimeSeries
    cells: CellSelection | None = Field(
        default=None, description="Where it applies; the whole top layer if omitted"
    )


BoundaryPackage = Annotated[
    WellPackage | ConstantHeadPackage | RechargePackage,
    Field(discriminator="kind"),
]


class SolverOptions(BaseModel):
    """How hard to push the linear solve."""

    outer_maximum: int = Field(default=50, ge=1)
    inner_maximum: int = Field(default=100, ge=1)
    outer_dvclose: float = Field(default=1e-6, gt=0)
    inner_dvclose: float = Field(default=1e-6, gt=0)
    complexity: Literal["simple", "moderate", "complex"] = "moderate"


class FlowModel(BaseModel):
    """The flow half of a model."""

    properties: FlowProperties = Field(default_factory=FlowProperties)
    packages: list[BoundaryPackage] = Field(default_factory=list)
    solver: SolverOptions = Field(default_factory=SolverOptions)

    def package(self, package_id: str) -> BoundaryPackage:
        for package in self.packages:
            if package.id == package_id:
                return package
        known = ", ".join(item.id for item in self.packages) or "none"
        raise KeyError(f"no boundary package {package_id!r} (have: {known})")
