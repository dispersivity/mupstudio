"""Flow: aquifer properties and boundary conditions."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from mupstudio.schema.common import Id, PropertyField, TimeSeries, ZoneField, constant

# CellRange is re-exported because a boundary over a block of cells is still
# how most of them are written, and it reads better next to the packages.
from mupstudio.schema.selection import CellRange as CellRange
from mupstudio.schema.selection import CellSelection


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

    def zoned_fields(self) -> list[tuple[str, ZoneField]]:
        """The properties given per zone, so their zone names can be checked."""
        found = []
        for name in ("k", "k33", "porosity", "specific_storage", "specific_yield", "starting_head"):
            field = getattr(self, name)
            if isinstance(field, ZoneField):
                found.append((name, field))
        return found


class BoundaryEntry(BaseModel):
    """One group of cells inside a package, and the values that apply to them.

    A MODFLOW boundary package is a list of records, not a single condition: a
    WEL file holds every well in the model, each with its own rate, and a CHD
    file can hold a west edge at one head and an east edge at another. A
    package with only one selection and one rate could express neither, so the
    package holds entries and each entry is one selection with its own values.

    One entry over fifty cells writes fifty records sharing a value, which is
    the common case; fifty entries of one cell each writes fifty records with
    fifty values, which is the other one.
    """

    label: str = Field(default="", description="What this is, for the list. Optional.")
    cells: CellSelection


class WellEntry(BoundaryEntry):
    """Injection or extraction. Negative rate extracts."""

    rate: TimeSeries
    concentration: TimeSeries | None = Field(
        default=None,
        description=(
            "Solute concentration of the inflow. Used for a conservative tracer run; "
            "a reactive run takes it from the boundary chemistry instead."
        ),
    )


class HeadEntry(BoundaryEntry):
    """A fixed head."""

    head: TimeSeries
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of water entering here"
    )


class DrainEntry(BoundaryEntry):
    elevation: TimeSeries
    conductance: TimeSeries


class RiverEntry(BoundaryEntry):
    stage: TimeSeries
    conductance: TimeSeries
    bottom: TimeSeries = Field(description="Streambed bottom elevation")
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of water entering from the river"
    )


class GeneralHeadEntry(BoundaryEntry):
    head: TimeSeries
    conductance: TimeSeries
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of water entering here"
    )


class RechargeEntry(BoundaryEntry):
    rate: TimeSeries
    concentration: TimeSeries | None = Field(
        default=None, description="Solute concentration of the recharge"
    )
    # Recharge falls on the whole top of the model unless told otherwise, which
    # is the only boundary where "everywhere" is the sensible default.
    cells: CellSelection | None = None  # type: ignore[assignment]


def _lift_legacy_entry(data: Any, fields: tuple[str, ...]) -> Any:
    """Read a package written before packages held more than one thing.

    Projects are hand-editable TOML that people keep, so an older file has to
    keep opening. The old shape put one selection and one set of values
    directly on the package; that is exactly one entry, so it becomes one.
    """
    if not isinstance(data, dict) or "entries" in data:
        return data

    if not any(field in data for field in ("cells", *fields)):
        return data

    data = dict(data)
    entry = {field: data.pop(field) for field in ("cells", "label", *fields) if field in data}
    data["entries"] = [entry]
    return data


class WellPackage(BaseModel):
    """WEL. Injection and extraction wells, any number of them."""

    kind: Literal["well"] = "well"
    id: Id
    entries: list[WellEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        return _lift_legacy_entry(data, ("rate", "concentration"))


class ConstantHeadPackage(BaseModel):
    """CHD. Cells whose head is held fixed. The usual inflow edge for a column."""

    kind: Literal["chd"] = "chd"
    id: Id
    entries: list[HeadEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        return _lift_legacy_entry(data, ("head", "concentration"))


class DrainPackage(BaseModel):
    """DRN. Water leaves where head exceeds the drain elevation, never enters.

    Outflow only, so it carries no inflow chemistry.
    """

    kind: Literal["drn"] = "drn"
    id: Id
    entries: list[DrainEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        return _lift_legacy_entry(data, ("elevation", "conductance"))


class RiverPackage(BaseModel):
    """RIV. Exchanges with a surface water body through a streambed."""

    kind: Literal["riv"] = "riv"
    id: Id
    entries: list[RiverEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        return _lift_legacy_entry(data, ("stage", "conductance", "bottom", "concentration"))


class GeneralHeadPackage(BaseModel):
    """GHB. A head boundary some distance away, reached through a conductance."""

    kind: Literal["ghb"] = "ghb"
    id: Id
    entries: list[GeneralHeadEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        return _lift_legacy_entry(data, ("head", "conductance", "concentration"))


class RechargePackage(BaseModel):
    """RCH. Areally distributed inflow at the top."""

    kind: Literal["recharge"] = "recharge"
    id: Id
    entries: list[RechargeEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        return _lift_legacy_entry(data, ("rate", "concentration"))


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
