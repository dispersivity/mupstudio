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
    concentration: TimeSeries | None = Field(
        default=None,
        description=(
            "Solute concentration of the inflow. Used for a conservative tracer run; "
            "a reactive run takes it from the boundary chemistry instead."
        ),
    )


class ConstantHeadPackage(BaseModel):
    """Head held fixed. The usual inflow boundary for a column."""

    kind: Literal["chd"] = "chd"
    id: Id
    cells: CellSelection
    head: TimeSeries
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of water entering here"
    )


class DrainPackage(BaseModel):
    """DRN. Water leaves where head exceeds the drain elevation, never enters.

    Outflow only, so it carries no inflow chemistry.
    """

    kind: Literal["drn"] = "drn"
    id: Id
    cells: CellSelection
    elevation: TimeSeries
    conductance: TimeSeries


class RiverPackage(BaseModel):
    """RIV. Exchanges with a surface water body through a streambed."""

    kind: Literal["riv"] = "riv"
    id: Id
    cells: CellSelection
    stage: TimeSeries
    conductance: TimeSeries
    bottom: TimeSeries = Field(description="Streambed bottom elevation")
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of water entering from the river"
    )


class GeneralHeadPackage(BaseModel):
    """GHB. A head boundary some distance away, reached through a conductance."""

    kind: Literal["ghb"] = "ghb"
    id: Id
    cells: CellSelection
    head: TimeSeries
    conductance: TimeSeries
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of water entering here"
    )


class RechargePackage(BaseModel):
    """Areally distributed inflow at the top."""

    kind: Literal["recharge"] = "recharge"
    id: Id
    rate: TimeSeries
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of the recharge"
    )
    cells: CellSelection | None = Field(
        default=None, description="Where it applies; the whole top layer if omitted"
    )


BoundaryPackage = Annotated[
    WellPackage
    | ConstantHeadPackage
    | RechargePackage
    | DrainPackage
    | RiverPackage
    | GeneralHeadPackage,
    Field(discriminator="kind"),
]

# The MODFLOW package name for each kind. Used wherever a boundary is named to
# a user: modellers think in package names, not in descriptions of them.
PACKAGE_NAMES: dict[str, str] = {
    "well": "WEL",
    "chd": "CHD",
    "rch": "RCH",
    "recharge": "RCH",
    "drn": "DRN",
    "riv": "RIV",
    "ghb": "GHB",
}


class SolverOptions(BaseModel):
    """How hard to push the linear solve."""

    outer_maximum: int = Field(default=50, ge=1)
    inner_maximum: int = Field(default=100, ge=1)
    outer_dvclose: float = Field(default=1e-6, gt=0)
    inner_dvclose: float = Field(default=1e-6, gt=0)
    complexity: Literal["simple", "moderate", "complex"] = "moderate"


# Boundary kinds that can introduce water, and so can introduce solute. DRN is
# absent because a drain only removes water.
SOLUTE_CARRYING = frozenset({"well", "chd", "recharge", "riv", "ghb"})


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
