"""The MODFLOW-2005 flow twin PHT3D transports through.

PHT3D cannot read a MODFLOW 6 solution, so the flow is solved again by
MODFLOW-2005. That makes this the one place two engines could quietly disagree
about the same project: same grid, same boundaries, different solvers, and
nothing downstream compares them.

So these tests do compare them. If the heads match, the difference between an
MF6RTM run and a PHT3D run of the same project is chemistry, which is what a
modeller wants to be able to assume.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.doctor import find_executable
from mupstudio.engines.mf6rtm.writer import write_mf6
from mupstudio.engines.pht3d.flow import FTL_NAME, write_flow
from mupstudio.schema.common import ConstantSeries, StressPeriod, TimeDiscretisation, constant
from mupstudio.schema.flow import (
    CellRange,
    ConstantHeadPackage,
    FlowModel,
    FlowProperties,
    RechargePackage,
    WellPackage,
)
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.templates import starter_column

MF2005 = find_executable("mf2005")
MF6 = find_executable("mf6")

pytestmark = pytest.mark.skipif(
    MF2005 is None, reason="mf2005 not installed; run: mupstudio get-engines"
)


def run_mf2005(workdir: Path, name: str = "flow") -> subprocess.CompletedProcess[str]:
    assert MF2005 is not None
    return subprocess.run(
        [str(MF2005)],
        cwd=workdir,
        input=f"{name}.nam\n",
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_the_flow_twin_runs(tmp_path: Path) -> None:
    project = starter_column("column", engine="pht3d", cells=50, perlen=0.24, nstp=24)
    write_flow(compile_project(project), tmp_path)

    result = run_mf2005(tmp_path)

    assert "Normal termination" in result.stdout, result.stdout[-2000:]


def test_it_writes_the_link_file_transport_reads(tmp_path: Path) -> None:
    """The FTL is the whole point of the flow twin.

    MT3DMS and PHT3D take cell face flows from it rather than solving flow
    themselves, so a model written without one runs MODFLOW and then has
    nothing to transport.
    """
    project = starter_column("column", engine="pht3d", cells=50)
    write_flow(compile_project(project), tmp_path)
    run_mf2005(tmp_path)

    link = tmp_path / FTL_NAME
    assert link.is_file()
    assert link.stat().st_size > 0


def test_every_boundary_kind_survives_the_crossing(tmp_path: Path) -> None:
    """MODFLOW-2005 spells these differently, and one is an array not a list."""
    grid = StructuredGrid(
        columns=AxisSpacing(ncells=10, total_length=100.0),
        rows=AxisSpacing(ncells=4, total_length=40.0),
        top=10.0,
        layers=[LayerSpec(bottom=0.0)],
    )
    project = Project(
        meta=ProjectMeta(name="mixed", engine="pht3d"),
        grid=grid,
        time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0, nstp=1, steady=True)]),
        flow=FlowModel(
            properties=FlowProperties(k=constant(10.0), starting_head=constant(9.0)),
            packages=[
                WellPackage(
                    id="pump",
                    cells=CellRange(layers=[1], rows=[2], columns=[5]),
                    rate=ConstantSeries(value=-50.0),
                ),
                ConstantHeadPackage(
                    id="east",
                    cells=CellRange(layers=[1], rows=[1, 2, 3, 4], columns=[10]),
                    head=ConstantSeries(value=9.0),
                ),
                RechargePackage(id="rain", rate=ConstantSeries(value=1e-4)),
            ],
        ),
    )

    twin = write_flow(compile_project(project), tmp_path)
    result = run_mf2005(tmp_path)

    assert "Normal termination" in result.stdout, result.stdout[-2000:]
    assert twin.warnings == []
    # A constant head takes two values in MODFLOW-2005 where MF6 takes one.
    assert {"flow.wel", "flow.chd", "flow.rch"} <= set(twin.files)


@pytest.mark.skipif(MF6 is None, reason="mf6 not installed")
def test_both_engines_solve_the_same_flow(tmp_path: Path) -> None:
    """The check that makes a cross-engine comparison meaningful.

    Written from one compiled model into two solvers. Heads should agree to
    within their convergence tolerances; anything larger means the two decks
    describe different problems, and every chemistry difference downstream
    would be attributed to the wrong cause.
    """
    import flopy

    project = starter_column("column", engine="pht3d", cells=50, perlen=0.24, nstp=24)
    model = compile_project(project)

    old = tmp_path / "mf2005"
    new = tmp_path / "mf6"
    write_flow(model, old)
    write_mf6(model, new)

    assert "Normal termination" in run_mf2005(old).stdout
    assert MF6 is not None
    modern = subprocess.run([str(MF6)], cwd=new, capture_output=True, text=True, timeout=600)
    assert modern.returncode == 0, modern.stdout[-2000:]

    old_heads = flopy.utils.HeadFile(str(old / "flow.hds")).get_data()
    new_heads = flopy.utils.HeadFile(str(next(new.glob("*.hds")))).get_data()

    np.testing.assert_allclose(old_heads, new_heads, atol=1e-4)


def test_the_flow_twin_ignores_chemistry(tmp_path: Path) -> None:
    """Chemistry changes nothing about the flow, so it must change no file.

    Worth pinning: the same compiled model carries chemistry, and a writer that
    let it leak into the flow would make the reactive and conservative runs
    solve different flow fields.
    """
    from mupstudio.schema.templates import starter_chemistry

    plain = starter_column("column", engine="pht3d", cells=20)
    reactive = Project.model_validate(
        {**plain.model_dump(), "chemistry": starter_chemistry().model_dump()}
    )

    write_flow(compile_project(plain), tmp_path / "plain")
    write_flow(compile_project(reactive), tmp_path / "reactive")

    for name in ("flow.dis", "flow.lpf", "flow.wel", "flow.chd", "flow.bas"):
        assert (tmp_path / "plain" / name).read_bytes() == (
            tmp_path / "reactive" / name
        ).read_bytes(), f"{name} differs"
