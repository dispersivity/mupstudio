"""What a project is.

One project targets one engine, chosen when it is created. The model itself is
engine-agnostic — the same grid, flow and transport definitions feed either
writer — but which engine a project is for decides what it may contain, since
PHT3D and MF6RTM do not support the same things.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from mupstudio.schema.common import Id, LengthUnit, TimeDiscretisation, TimeUnit
from mupstudio.schema.flow import FlowModel
from mupstudio.schema.grid import GridSpec, StructuredGrid
from mupstudio.schema.transport import TransportModel

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
    flow: FlowModel = Field(default_factory=FlowModel)
    transport: TransportModel = Field(default_factory=TransportModel)
    run: RunOptions = Field(default_factory=RunOptions)

    @model_validator(mode="after")
    def _check_references(self) -> Project:
        self._check_engine_supports_grid()
        self._check_package_ids_are_unique()
        self._check_cells_are_inside_the_grid()
        self._check_series_match_the_stress_periods()
        self._check_engine_supports_features()
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

        limits = {"layers": self.grid.nlay, "rows": self.grid.nrow, "columns": self.grid.ncol}
        for package in self.flow.packages:
            selection = getattr(package, "cells", None)
            if selection is None:
                continue
            for axis, limit in limits.items():
                for index in getattr(selection, axis):
                    if not 1 <= index <= limit:
                        raise ValueError(
                            f"package {package.id!r} refers to {axis[:-1]} {index}, "
                            f"but the grid has {limit} (indices start at 1)"
                        )

    def _check_series_match_the_stress_periods(self) -> None:
        nper = self.time.nper
        for package in self.flow.packages:
            for name in ("rate", "head"):
                series = getattr(package, name, None)
                if series is None or series.kind != "per_period":
                    continue
                if len(series.values) != nper:
                    raise ValueError(
                        f"package {package.id!r} gives {len(series.values)} values for "
                        f"{name}, but the model has {nper} stress "
                        f"{'period' if nper == 1 else 'periods'}"
                    )

    def _check_engine_supports_features(self) -> None:
        if self.transport.dual_porosity is not None and self.meta.engine == "mf6rtm":
            raise ValueError(
                "dual porosity is not supported by MF6RTM yet; it writes for PHT3D only"
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
