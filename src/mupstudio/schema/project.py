"""What a project is.

One project targets one engine, chosen when it is created. The model itself is
engine-agnostic — the same grid, flow and transport definitions feed either
writer — but which engine a project is for decides what it may contain, since
PHT3D and MF6RTM do not support the same things.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from mupstudio.schema.chemistry import ChemistryModel
from mupstudio.schema.common import Id, LengthUnit, TimeDiscretisation, TimeUnit
from mupstudio.schema.flow import PACKAGE_NAMES, SOLUTE_CARRYING, FlowModel
from mupstudio.schema.gis import DataModel
from mupstudio.schema.grid import GridSpec, StructuredGrid
from mupstudio.schema.selection import out_of_range
from mupstudio.schema.transport import TransportModel
from mupstudio.schema.zones import PropertyZone


def _where(package_id: str, entry: object, position: int) -> str:
    """Name the offending entry the way the screen shows it."""
    label = getattr(entry, "label", "") or f"entry {position}"
    return f"package {package_id!r} ({label})"


# Bumped when a change cannot be read by the previous version. Migrations live
# in schema/migrate.py and run on load.
SCHEMA_VERSION = 1

Engine = Literal["mf6rtm", "pht3d"]


class ProjectMeta(BaseModel):
    """Identity and units."""

    name: str = Field(min_length=1, max_length=200)
    engine: Engine
    schema_version: int = SCHEMA_VERSION
    description: str = ""
    length_unit: LengthUnit = "meters"
    time_unit: TimeUnit = "days"
    crs: str | None = Field(
        default=None, description="EPSG code; absent for a model with no real-world location"
    )
    created: str | None = None
    modified: str | None = None


class RunOptions(BaseModel):
    """How to run, as opposed to what to run."""

    reactive: bool = True
    nthreads: int = Field(default=1, ge=1, le=256)
    executable: str | None = Field(
        default=None, description="Overrides the engine executable from settings"
    )


class Project(BaseModel):
    """A complete model definition.

    Validation here is the one place cross-references are checked, so a project
    that loads is a project whose parts refer to things that exist.
    """

    meta: ProjectMeta
    grid: GridSpec
    time: TimeDiscretisation
    data: DataModel = Field(default_factory=DataModel)
    flow: FlowModel = Field(default_factory=FlowModel)
    transport: TransportModel = Field(default_factory=TransportModel)
    chemistry: ChemistryModel = Field(default_factory=ChemistryModel)
    run: RunOptions = Field(default_factory=RunOptions)
    zones: list[PropertyZone] = Field(
        default_factory=list,
        description="Named regions of the grid, shared by flow and transport properties",
    )

    @model_validator(mode="after")
    def _check_references(self) -> Project:
        self._check_engine_supports_grid()
        self._check_package_ids_are_unique()
        self._check_cells_are_inside_the_grid()
        self._check_series_match_the_stress_periods()
        self._check_zone_references_resolve()
        self._check_engine_supports_features()
        self._check_chemistry_matches_the_model()
        return self

    def _check_engine_supports_grid(self) -> None:
        if self.meta.engine == "pht3d" and not isinstance(self.grid, StructuredGrid):
            raise ValueError(
                "PHT3D runs on structured grids only; this project uses "
                f"a {self.grid.kind} grid. Convert it to MF6RTM to keep the grid."
            )

    def _check_package_ids_are_unique(self) -> None:
        seen: set[str] = set()
        for package in self.flow.packages:
            if package.id in seen:
                raise ValueError(f"two boundary packages share the id {package.id!r}")
            seen.add(package.id)

    def _check_cells_are_inside_the_grid(self) -> None:
        """Catch an index typo here rather than in a MODFLOW listing file."""
        if not isinstance(self.grid, StructuredGrid):
            return

        bounds = {"nlay": self.grid.nlay, "nrow": self.grid.nrow, "ncol": self.grid.ncol}

        for package in self.flow.packages:
            for position, entry in enumerate(package.entries, start=1):
                bad = out_of_range(entry.cells, **bounds)
                if bad:
                    raise ValueError(f"{_where(package.id, entry, position)} refers to {bad}")

        for zone in self.zones:
            bad = out_of_range(zone.cells, **bounds)
            if bad:
                raise ValueError(f"zone {zone.id!r} refers to {bad}")

    def _check_series_match_the_stress_periods(self) -> None:
        nper = self.time.nper
        for package in self.flow.packages:
            for position, entry in enumerate(package.entries, start=1):
                for name in ("rate", "head", "stage", "elevation", "conductance", "bottom"):
                    series = getattr(entry, name, None)
                    if series is None or series.kind != "per_period":
                        continue
                    if len(series.values) != nper:
                        raise ValueError(
                            f"{_where(package.id, entry, position)} gives "
                            f"{len(series.values)} values for {name}, but the model has "
                            f"{nper} stress {'period' if nper == 1 else 'periods'}"
                        )

    def _check_zone_references_resolve(self) -> None:
        """A property keyed by zone has to name zones this project has."""
        known = {zone.id for zone in self.zones}
        sources = [
            *((f"flow.{name}", field) for name, field in self.flow.properties.zoned_fields()),
            *((f"transport.{name}", field) for name, field in self.transport.zoned_fields()),
        ]

        for label, field in sources:
            for zone_id in field.values:
                if zone_id not in known:
                    have = ", ".join(sorted(known)) or "none"
                    raise ValueError(
                        f"{label} gives a value for the zone {zone_id!r}, which this "
                        f"project does not have (it has: {have})"
                    )

        if not known:
            return
        for zone in self.zones:
            if zone.cells.kind == "shape" and zone.cells.source not in {
                source.id for source in self.data.sources
            }:
                raise ValueError(
                    f"zone {zone.id!r} is drawn from the data source "
                    f"{zone.cells.source!r}, which this project does not have"
                )

    def _check_engine_supports_features(self) -> None:
        if self.transport.dual_porosity is not None and self.meta.engine == "mf6rtm":
            raise ValueError(
                "dual porosity is not supported by MF6RTM yet; it writes for PHT3D only"
            )

    def _check_chemistry_matches_the_model(self) -> None:
        """Chemistry refers to the grid and to the flow boundaries.

        The chemistry model validates its own internal references; what it
        cannot see is whether the cells it zones exist, or whether the packages
        it assigns water to are packages this project has.
        """
        chemistry = self.chemistry
        if not chemistry.enabled:
            return

        if chemistry.compositions and chemistry.background is None:
            raise ValueError(
                "chemistry needs a background composition, so that cells no zone "
                "covers still have water in them"
            )

        if isinstance(self.grid, StructuredGrid):
            for zone in chemistry.zones:
                bad = out_of_range(
                    zone.cells, nlay=self.grid.nlay, nrow=self.grid.nrow, ncol=self.grid.ncol
                )
                if bad:
                    raise ValueError(f"chemistry zone {zone.id!r} refers to {bad}")

        by_id = {package.id: package for package in self.flow.packages}
        for package_id in chemistry.boundary_solutions:
            package = by_id.get(package_id)
            if package is None:
                known = ", ".join(sorted(by_id)) or "none"
                raise ValueError(
                    f"chemistry assigns water to the boundary {package_id!r}, which this "
                    f"project does not have (it has: {known})"
                )
            # A drain only takes water out, so giving it an inflow chemistry is
            # a mistake worth catching rather than quietly ignoring.
            if package.kind not in SOLUTE_CARRYING:
                raise ValueError(
                    f"boundary {package_id!r} is a {PACKAGE_NAMES[package.kind]}, which only "
                    "removes water, so it cannot carry an inflow solution"
                )

    @property
    def package_ids(self) -> list[Id]:
        return [package.id for package in self.flow.packages]

    def describe(self) -> str:
        """A one-line summary, for logs and the run list."""
        grid = self.grid
        shape = (
            f"{grid.nlay}x{grid.nrow}x{grid.ncol}"
            if isinstance(grid, StructuredGrid)
            else f"{grid.kind}"
        )
        return (
            f"{self.meta.name}: {self.meta.engine}, {shape} "
            f"({grid.ncells:,} cells), {self.time.nper} stress "
            f"{'period' if self.time.nper == 1 else 'periods'}"
        )
