"""Starting points for a new project.

A column with no boundary conditions has no flow, so nothing moves and every
output is zero. That is correct but useless as a starting point, so a new
project comes with the boundaries a column benchmark always has: water and
solute entering one end, water leaving the other.
"""

from __future__ import annotations

from mupstudio.schema.common import ConstantSeries, StressPeriod, TimeDiscretisation, constant
from mupstudio.schema.flow import (
    BoundaryPackage,
    CellRange,
    ConstantHeadPackage,
    FlowModel,
    FlowProperties,
    WellPackage,
)
from mupstudio.schema.grid import column_grid
from mupstudio.schema.project import Engine, Project, ProjectMeta
from mupstudio.schema.transport import Dispersion, TransportModel

# Defaults chosen so a fresh project runs and shows something: a sand-like
# conductivity and porosity, and a dispersivity of a few cell lengths.
DEFAULT_K = 1.0
DEFAULT_POROSITY = 0.32
DISPERSIVITY_FRACTION = 0.013


def starter_column(
    name: str,
    *,
    engine: Engine = "mf6rtm",
    cells: int = 50,
    length: float = 0.5,
    perlen: float = 1.0,
    nstp: int = 10,
    pore_volumes: float = 1.0,
    inflow_concentration: float = 1.0,
    with_boundaries: bool = True,
) -> Project:
    """A 1D column that runs as soon as it is created.

    The inflow rate is set to push ``pore_volumes`` through the column over the
    simulated time, so the tracer sweeps a visible distance rather than barely
    entering the first cell.
    """
    grid = column_grid(ncells=cells, length=length)
    total_time = perlen

    packages: list[BoundaryPackage] = []
    if with_boundaries:
        pore_volume = length * DEFAULT_POROSITY  # unit width and thickness
        rate = pore_volumes * pore_volume / total_time
        packages = [
            WellPackage(
                id="inflow",
                cells=CellRange(layers=[1], rows=[1], columns=[1]),
                rate=ConstantSeries(value=rate),
                concentration=ConstantSeries(value=inflow_concentration),
            ),
            ConstantHeadPackage(
                id="outflow",
                cells=CellRange(layers=[1], rows=[1], columns=[cells]),
                head=ConstantSeries(value=0.0),
            ),
        ]

    return Project(
        meta=ProjectMeta(
            name=name,
            engine=engine,
            description="A 1D column: water and solute enter one end and leave the other.",
        ),
        grid=grid,
        time=TimeDiscretisation(periods=[StressPeriod(perlen=perlen, nstp=nstp)]),
        flow=FlowModel(
            properties=FlowProperties(
                k=constant(DEFAULT_K),
                porosity=constant(DEFAULT_POROSITY),
                starting_head=constant(0.0),
            ),
            packages=packages,
        ),
        transport=TransportModel(
            dispersion=Dispersion(longitudinal=constant(length * DISPERSIVITY_FRACTION))
        ),
    )
