"""The MT3DMS deck PHT3D transports with, and the SSM file FloPy cannot write.

The SSM tests read against the published Engesgaard deck at
``mf6rtm/benchmark/ex1/pht3d/Pht3d.ssm``, which PHT3D has actually run. Its
records are the specification: what goes in each column, and — the part that is
easy to get wrong — which components appear and which are zero.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.engines.pht3d.ordering import Group, order_components
from mupstudio.engines.pht3d.transport import TRACE, Pht3dTransportError, write_ssm
from mupstudio.schema.common import ConstantSeries, StressPeriod, TimeDiscretisation, constant
from mupstudio.schema.flow import (
    CellRange,
    ConstantHeadPackage,
    DrainPackage,
    FlowModel,
    FlowProperties,
    WellPackage,
)
from mupstudio.schema.grid import column_grid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.templates import starter_column

# A deck PHT3D has run, kept in the repo so this is checked everywhere and not
# only where the mf6rtm benchmark suite happens to be installed.
GOLDEN = Path(__file__).parent.parent / "fixtures" / "pht3d_golden" / "ex1"
GOLDEN_SSM = GOLDEN / "Pht3d.ssm"
GOLDEN_BTN = GOLDEN / "Pht3d.btn"

# The Engesgaard column: four aqueous components, two minerals, pH and pe.
ENGESGAARD = {
    Group.AQUEOUS: ["C(+4)", "Ca", "Cl", "Mg"],
    Group.MINERAL: ["Calcite", "Dolomite"],
}


@pytest.fixture
def components():  # type: ignore[no-untyped-def]
    return order_components(ENGESGAARD)


def ssm_lines(tmp_path: Path, model, components, boundary) -> list[str]:  # type: ignore[no-untyped-def]
    path = tmp_path / "trans.ssm"
    write_ssm(path, model, components, boundary)
    return path.read_text().splitlines()


def test_the_header_flags_the_packages_present(tmp_path: Path, components) -> None:  # type: ignore[no-untyped-def]
    """MT3DMS reads six flags, in its own order, and skips the ones set false."""
    model = compile_project(starter_column("c", engine="pht3d", cells=5))

    lines = ssm_lines(tmp_path, model, components, {})

    # A well is present; drain, recharge, evapotranspiration, river and general
    # head are not. Constant head is not among the flags: MT3DMS reads it from
    # the flow link file rather than from a flag.
    assert lines[0].split() == ["T", "F", "F", "F", "F", "F"]


def test_the_inflow_water_carries_its_ph_and_pe(tmp_path: Path, components) -> None:  # type: ignore[no-untyped-def]
    """The distinction the published deck makes, and the easy one to get wrong.

    pH and pe are not transported, but they are properties of the water
    arriving and PHT3D needs them to speciate it. Minerals are not something
    water can carry, so those are zero. Writing pH as zero instead would inject
    an impossibly acidic solution at every boundary cell.
    """
    model = compile_project(starter_column("c", engine="pht3d", cells=5))
    boundary = {"inflow": {"Cl": 2e-3, "Mg": 1e-3, "pH": 7.0, "pe": 4.0}}

    record = ssm_lines(tmp_path, model, components, boundary)[3]
    values = [float(item) for item in record.split()[5:]]

    assert values == pytest.approx([TRACE, TRACE, 2e-3, 1e-3, 7.0, 4.0, 0.0, 0.0])


def test_it_matches_the_published_deck(tmp_path: Path, components) -> None:
    """Read against the record PHT3D itself was run on.

    Same problem, same chemistry: the numbers on our record should be the
    numbers on theirs. Compared as values rather than as text, because column
    widths are ours to choose and the values are not.
    """
    published = [float(item) for item in GOLDEN_SSM.read_text().splitlines()[3].split()[5:]]

    model = compile_project(starter_column("c", engine="pht3d", cells=50))
    boundary = {"inflow": {"Cl": 2e-3, "Mg": 1e-3, "pH": 7.0, "pe": 4.0}}
    ours = [float(item) for item in ssm_lines(tmp_path, model, components, boundary)[3].split()[5:]]

    assert ours == pytest.approx(published)


def test_the_component_count_matches_the_published_deck(components) -> None:  # type: ignore[no-untyped-def]
    """The deck declares eight components of which four move.

    Six aqueous names and four mobile ones is the whole of the pH and pe rule,
    stated by a file PHT3D accepted.
    """
    from mupstudio.engines.pht3d.ordering import mobile_count

    header = GOLDEN_BTN.read_text().splitlines()[2].split()
    ncomp, mcomp = int(header[4]), int(header[5])

    assert len(components) == ncomp
    assert mobile_count(components) == mcomp


def test_the_published_deck_names_the_components_in_our_order(components) -> None:  # type: ignore[no-untyped-def]
    """Its BTN comments each starting concentration with the component's name."""
    named = [
        line.split("#", 1)[1].strip()
        for line in GOLDEN_BTN.read_text().splitlines()
        if "#" in line and not line.startswith("#")
    ]
    # The deck truncates names to six characters in those comments.
    ours = [component.name[:6] for component in components]

    assert [name for name in named if name in ours] == ours


def test_a_boundary_with_no_chemistry_injects_the_trace_floor(tmp_path: Path, components) -> None:  # type: ignore[no-untyped-def]
    """Zero is not a concentration PHREEQC can take the logarithm of."""
    model = compile_project(starter_column("c", engine="pht3d", cells=5))

    record = ssm_lines(tmp_path, model, components, {})[3]
    values = [float(item) for item in record.split()[5:]]

    assert values[:6] == [TRACE] * 6
    assert values[6:] == [0.0, 0.0]


def test_each_package_gets_its_own_source_type(tmp_path: Path, components) -> None:  # type: ignore[no-untyped-def]
    """MT3DMS decides what a record means from ITYPE, so it has to be right.

    A well adds mass at a rate; a constant head fixes the concentration. Giving
    a well a constant head's number would hold the aquifer at the injected
    chemistry instead of mixing into it.
    """
    project = Project(
        meta=ProjectMeta(name="mixed", engine="pht3d"),
        grid=column_grid(ncells=6, length=6.0),
        time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0, nstp=1)]),
        flow=FlowModel(
            properties=FlowProperties(k=constant(1.0), starting_head=constant(0.0)),
            packages=[
                WellPackage(
                    id="pump",
                    cells=CellRange(layers=[1], rows=[1], columns=[1]),
                    rate=ConstantSeries(value=1.0),
                ),
                ConstantHeadPackage(
                    id="out",
                    cells=CellRange(layers=[1], rows=[1], columns=[6]),
                    head=ConstantSeries(value=0.0),
                ),
                DrainPackage(
                    id="ditch",
                    cells=CellRange(layers=[1], rows=[1], columns=[3]),
                    elevation=ConstantSeries(value=0.0),
                    conductance=ConstantSeries(value=1.0),
                ),
            ],
        ),
    )
    model = compile_project(project)

    lines = ssm_lines(tmp_path, model, components, {})
    types = sorted(int(line.split()[4]) for line in lines[3:6])

    assert types == [1, 2, 3]  # constant head, well, drain
    assert lines[0].split()[:2] == ["T", "T"]  # a well and a drain are present


def test_the_allocation_covers_the_busiest_period(tmp_path: Path, components) -> None:  # type: ignore[no-untyped-def]
    """MT3DMS allocates from MXSS once, so it has to be the maximum.

    Taking the first period's count would work until a later period added a
    boundary, and then overrun an array in Fortran.
    """
    model = compile_project(starter_column("c", engine="pht3d", cells=5, perlen=2.0, nstp=1))
    lines = ssm_lines(tmp_path, model, components, {})

    counts = [int(line) for line in lines[2:] if len(line.split()) == 1]
    assert int(lines[1]) == max(counts)


def test_a_component_with_no_starting_value_is_refused(tmp_path: Path) -> None:
    """A silent trace floor would look like a real near-zero measurement."""
    from mupstudio.engines.pht3d.transport import _initial_concentrations

    parts = order_components({Group.AQUEOUS: ["Ca", "Cl"]})
    with pytest.raises(Pht3dTransportError, match="Cl"):
        _initial_concentrations(parts, {"Ca": np.zeros(3), "pH": np.zeros(3), "pe": np.zeros(3)})


def test_starting_concentrations_are_floored() -> None:
    from mupstudio.engines.pht3d.transport import _initial_concentrations

    parts = order_components({Group.AQUEOUS: ["Ca"]})
    written = _initial_concentrations(
        parts, {"Ca": np.zeros(4), "pH": np.full(4, 7.0), "pe": np.full(4, 4.0)}
    )

    assert np.all(written["sconc"] == TRACE)
    assert np.all(written["sconc2"] == 7.0)
