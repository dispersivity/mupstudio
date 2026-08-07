"""Starting points for a new project.

A column with no boundary conditions has no flow, so nothing moves and every
output is zero. That is correct but useless as a starting point, so a new
project comes with the boundaries a column benchmark always has: water and
solute entering one end, water leaving the other.
"""

from __future__ import annotations

from mupstudio.schema.chemistry import (
    ChemistryModel,
    Composition,
    DatabaseRef,
    EquilibriumPhases,
    PhaseTarget,
    SelectedOutput,
    Solution,
)
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


def starter_chemistry(database: str = "phreeqc.dat") -> ChemistryModel:
    """The calcite and dolomite column, ready to run.

    This is Appelo's cation exchange column stripped to its simplest reactive
    form, and it is the benchmark every reactive transport code is checked
    against: a calcite-bearing sand initially in equilibrium with its own pore
    water, flushed with a magnesium chloride solution. Calcite dissolves,
    dolomite precipitates, and the fronts arrive in a known order.

    It exists so the Chemistry step opens with something a chemist recognises
    and can edit, rather than with empty tables.
    """
    return ChemistryModel(
        enabled=True,
        database=DatabaseRef(name=database),
        solutions=[
            Solution(
                id="background",
                label="Pore water, calcite equilibrated",
                ph=9.91,
                pe=4.0,
                concentrations={"C(+4)": 1.23e-4, "Ca": 1.23e-4, "Cl": 0.0, "Mg": 0.0},
            ),
            Solution(
                id="inflow",
                label="Magnesium chloride",
                ph=7.0,
                pe=4.0,
                concentrations={"C(+4)": 0.0, "Ca": 0.0, "Cl": 2e-3, "Mg": 1e-3},
            ),
        ],
        equilibrium_phases=[
            EquilibriumPhases(
                id="calcite_sand",
                label="Calcite sand",
                phases=[
                    # Calcite is present and can dissolve; dolomite starts at
                    # nothing and can only precipitate, which is what makes the
                    # second front appear.
                    PhaseTarget(phase="Calcite", saturation_index=0.0, moles=1.220625e-4),
                    PhaseTarget(phase="Dolomite", saturation_index=0.0, moles=0.0),
                ],
            )
        ],
        compositions=[
            Composition(
                id="sand",
                label="Calcite sand",
                colour="#c8b48a",
                solution="background",
                equilibrium_phases="calcite_sand",
            )
        ],
        background="sand",
        boundary_solutions={"inflow": "inflow"},
        selected_output=SelectedOutput(
            totals=["Ca", "Cl", "Mg", "C"],
            equilibrium_phases=["Calcite", "Dolomite"],
        ),
    )
