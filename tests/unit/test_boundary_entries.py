"""A package holds records, not one condition.

A WEL file holds every well in the model, each with its own rate. A CHD file
can hold a west edge at one head and an east edge at another. The schema has to
be able to say that, and the compiler has to turn it into the records MODFLOW
reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mupstudio.compile.compiler import CompileError, compile_project
from mupstudio.schema.common import (
    ConstantSeries,
    PerPeriodSeries,
    StressPeriod,
    TimeDiscretisation,
)
from mupstudio.schema.flow import (
    ConstantHeadPackage,
    FlowModel,
    HeadEntry,
    WellEntry,
    WellPackage,
)
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.selection import CellList, CellRange


def project(**overrides: object) -> Project:
    defaults: dict[str, object] = {
        "meta": ProjectMeta(name="test", engine="mf6rtm"),
        "grid": StructuredGrid(
            columns=AxisSpacing(ncells=5, total_length=5.0),
            rows=AxisSpacing(ncells=5, total_length=5.0),
            top=0.0,
            layers=[LayerSpec(bottom=-1.0)],
        ),
        "time": TimeDiscretisation(periods=[StressPeriod(perlen=1.0)]),
    }
    return Project(**{**defaults, **overrides})  # type: ignore[arg-type]


def well(label: str, cells: object, rate: float) -> WellEntry:
    return WellEntry(label=label, cells=cells, rate=ConstantSeries(value=rate))  # type: ignore[arg-type]


class TestManyPerPackage:
    def test_each_well_keeps_its_own_rate(self) -> None:
        """The shape a package holding one rate could not express."""
        model = compile_project(
            project(
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="field",
                            entries=[
                                well("shallow", CellList(indices=[(1, 1, 1)]), -10.0),
                                well("deep", CellList(indices=[(1, 3, 3)]), -250.0),
                            ],
                        )
                    ]
                )
            )
        )

        records = model.boundary("field").spd[0]

        assert [record[0] for record in records] == [(0, 0, 0), (0, 2, 2)]
        assert [record[1] for record in records] == [-10.0, -250.0]

    def test_one_entry_over_many_cells_writes_one_record_each(self) -> None:
        """The common case: an edge of cells sharing a head."""
        model = compile_project(
            project(
                flow=FlowModel(
                    packages=[
                        ConstantHeadPackage(
                            id="west",
                            entries=[
                                HeadEntry(
                                    cells=CellRange(layers=[1], rows=[1, 2, 3], columns=[1]),
                                    head=ConstantSeries(value=10.0),
                                )
                            ],
                        )
                    ]
                )
            )
        )

        records = model.boundary("west").spd[0]

        assert len(records) == 3
        assert {record[1] for record in records} == {10.0}

    def test_two_edges_at_two_heads_in_one_package(self) -> None:
        model = compile_project(
            project(
                flow=FlowModel(
                    packages=[
                        ConstantHeadPackage(
                            id="edges",
                            entries=[
                                HeadEntry(
                                    label="west",
                                    cells=CellRange(layers=[1], rows=[1, 2], columns=[1]),
                                    head=ConstantSeries(value=10.0),
                                ),
                                HeadEntry(
                                    label="east",
                                    cells=CellRange(layers=[1], rows=[1, 2], columns=[5]),
                                    head=ConstantSeries(value=2.0),
                                ),
                            ],
                        )
                    ]
                )
            )
        )

        heads = {record[0][2]: record[1] for record in model.boundary("edges").spd[0]}

        assert heads == {0: 10.0, 4: 2.0}

    def test_two_entries_claiming_a_cell_is_refused(self) -> None:
        """MODFLOW sums some packages and rejects others; neither is what was drawn."""
        with pytest.raises(CompileError, match="already has"):
            compile_project(
                project(
                    flow=FlowModel(
                        packages=[
                            WellPackage(
                                id="field",
                                entries=[
                                    well("a", CellList(indices=[(1, 1, 1)]), -1.0),
                                    well("b", CellList(indices=[(1, 1, 1)]), -2.0),
                                ],
                            )
                        ]
                    )
                )
            )

    def test_the_clash_names_the_entry_the_screen_shows(self) -> None:
        with pytest.raises(CompileError, match="second pump"):
            compile_project(
                project(
                    flow=FlowModel(
                        packages=[
                            WellPackage(
                                id="field",
                                entries=[
                                    well("first pump", CellList(indices=[(1, 2, 2)]), -1.0),
                                    well("second pump", CellList(indices=[(1, 2, 2)]), -2.0),
                                ],
                            )
                        ]
                    )
                )
            )

    def test_an_empty_package_writes_nothing_rather_than_failing(self) -> None:
        """A package is created before it is filled in, and that is not an error."""
        model = compile_project(project(flow=FlowModel(packages=[WellPackage(id="planned")])))

        assert model.boundary("planned").spd[0] == []


class TestPerPeriodValues:
    def test_each_entry_follows_its_own_schedule(self) -> None:
        model = compile_project(
            project(
                time=TimeDiscretisation(
                    periods=[StressPeriod(perlen=1.0), StressPeriod(perlen=1.0)]
                ),
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="field",
                            entries=[
                                WellEntry(
                                    cells=CellList(indices=[(1, 1, 1)]),
                                    rate=PerPeriodSeries(values=[-1.0, -5.0]),
                                ),
                                WellEntry(
                                    cells=CellList(indices=[(1, 2, 2)]),
                                    rate=PerPeriodSeries(values=[0.0, -9.0]),
                                ),
                            ],
                        )
                    ]
                ),
            )
        )

        boundary = model.boundary("field")

        assert [record[1] for record in boundary.spd[0]] == [-1.0, 0.0]
        assert [record[1] for record in boundary.spd[1]] == [-5.0, -9.0]

    def test_a_short_schedule_is_refused_by_name(self) -> None:
        with pytest.raises(Exception, match="stress periods"):
            project(
                time=TimeDiscretisation(
                    periods=[StressPeriod(perlen=1.0), StressPeriod(perlen=1.0)]
                ),
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="field",
                            entries=[
                                WellEntry(
                                    label="odd one",
                                    cells=CellList(indices=[(1, 1, 1)]),
                                    rate=PerPeriodSeries(values=[-1.0]),
                                )
                            ],
                        )
                    ]
                ),
            )


class TestOlderProjects:
    """Projects are hand-editable files people keep, so old ones keep opening."""

    def test_a_package_written_flat_becomes_one_entry(self) -> None:
        package = WellPackage.model_validate(
            {
                "kind": "well",
                "id": "inflow",
                "cells": {"kind": "cells", "layers": [1], "rows": [1], "columns": [1]},
                "rate": {"kind": "constant", "value": -5.0},
                "concentration": {"kind": "constant", "value": 1.0},
            }
        )

        assert len(package.entries) == 1
        assert package.entries[0].rate.value == -5.0
        assert package.entries[0].concentration is not None

    def test_a_new_style_package_is_left_alone(self) -> None:
        package = WellPackage.model_validate(
            {
                "kind": "well",
                "id": "field",
                "entries": [
                    {
                        "cells": {"kind": "list", "indices": [[1, 1, 1]]},
                        "rate": {"kind": "constant", "value": -1.0},
                    }
                ],
            }
        )

        assert len(package.entries) == 1

    def test_an_old_project_on_disk_still_opens(self, tmp_path: Path) -> None:
        from mupstudio.store import projectstore

        directory = tmp_path / "old.mup"
        projectstore.save(directory, project())
        (directory / "flow.toml").write_text(
            "[[flow.packages]]\n"
            'kind = "chd"\n'
            'id = "outflow"\n'
            "\n"
            "[flow.packages.cells]\n"
            'kind = "cells"\n'
            "layers = [1]\n"
            "rows = [1]\n"
            "columns = [5]\n"
            "\n"
            "[flow.packages.head]\n"
            'kind = "constant"\n'
            "value = 0.0\n"
        )

        loaded = projectstore.load(directory)

        assert loaded.flow.packages[0].entries[0].head.value == 0.0
