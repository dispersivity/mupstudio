"""Reading and writing project directories.

The TOML files are a supported place to work — hand-edited, or generated in bulk
by a script — so the round trip has to be exact and the errors have to point at
the file and field that need fixing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mupstudio.schema.common import (
    ConstantSeries,
    PerPeriodSeries,
    StressPeriod,
    TimeDiscretisation,
    ZoneField,
    constant,
)
from mupstudio.schema.flow import CellRange, ConstantHeadPackage, FlowModel, WellPackage
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid, column_grid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.transport import Dispersion, TransportModel
from mupstudio.store import projectstore, toml_io


def simple() -> Project:
    return Project(
        meta=ProjectMeta(name="Engesgaard column", engine="mf6rtm"),
        grid=column_grid(ncells=50, length=0.5),
        time=TimeDiscretisation(periods=[StressPeriod(perlen=0.24, nstp=24)]),
        flow=FlowModel(
            packages=[
                ConstantHeadPackage(
                    id="inflow",
                    cells=CellRange(layers=[1], rows=[1], columns=[1]),
                    head=ConstantSeries(value=0.0),
                )
            ]
        ),
    )


def elaborate() -> Project:
    """Exercises every shape the writer has to handle."""
    return Project(
        meta=ProjectMeta(
            name='Tricky "quoted" name',
            engine="pht3d",
            description="line one\nline two\ttabbed",
            crs="EPSG:32719",
        ),
        grid=StructuredGrid(
            origin_x=1234.5,
            origin_y=-9876.25,
            rotation=13.5,
            columns=AxisSpacing(widths=[0.1, 0.25, 1e-3, 1e5]),
            rows=AxisSpacing(ncells=3, total_length=30.0),
            top=100.0,
            layers=[LayerSpec(name="upper", bottom=50.0, sublayers=2), LayerSpec(bottom=-1e-8)],
        ),
        time=TimeDiscretisation(
            periods=[
                StressPeriod(perlen=1.0, steady=True),
                StressPeriod(perlen=365.25, nstp=100, tsmult=1.2),
            ],
            start_datetime="2026-01-01",
        ),
        flow=FlowModel(
            packages=[
                WellPackage(
                    id="injector",
                    cells=CellRange(layers=[1, 2], rows=[1], columns=[2, 3]),
                    rate=PerPeriodSeries(values=[0.0, -12.5]),
                )
            ]
        ),
        transport=TransportModel(
            porosity=ZoneField(default=0.3, values={"sand": 0.35, "clay": 0.05}),
            dispersion=Dispersion(longitudinal=constant(0.01), diffusion=constant(1e-9)),
            advection_scheme="upstream",
        ),
    )


class TestRoundTrip:
    def test_saves_one_file_per_section(self, tmp_path: Path) -> None:
        projectstore.save(tmp_path / "p.mup", simple())

        written = sorted(path.name for path in (tmp_path / "p.mup").iterdir())

        assert written == [
            ".gitignore",
            "flow.toml",
            "grid.toml",
            "project.toml",
            "run.toml",
            "transport.toml",
        ]

    def test_a_saved_project_loads_back_identically(self, tmp_path: Path) -> None:
        original = simple()
        projectstore.save(tmp_path / "p.mup", original, touch_modified=False)

        loaded = projectstore.load(tmp_path / "p.mup")

        assert loaded.model_dump() == original.model_dump()

    def test_every_field_shape_survives_the_round_trip(self, tmp_path: Path) -> None:
        original = elaborate()
        projectstore.save(tmp_path / "p.mup", original, touch_modified=False)

        loaded = projectstore.load(tmp_path / "p.mup")

        assert loaded.model_dump() == original.model_dump()

    @pytest.mark.parametrize("build", [simple, elaborate], ids=["simple", "elaborate"])
    def test_saving_twice_writes_identical_bytes(self, tmp_path: Path, build) -> None:
        """An unchanged project must not churn version control."""
        directory = tmp_path / "p.mup"
        projectstore.save(directory, build(), touch_modified=False)
        before = {path.name: path.read_bytes() for path in directory.iterdir()}

        projectstore.save(directory, projectstore.load(directory), touch_modified=False)
        after = {path.name: path.read_bytes() for path in directory.iterdir()}

        assert after == before

    def test_floats_do_not_drift(self, tmp_path: Path) -> None:
        original = elaborate()
        projectstore.save(tmp_path / "p.mup", original, touch_modified=False)

        loaded = projectstore.load(tmp_path / "p.mup")

        assert loaded.grid.columns.widths == original.grid.columns.widths
        assert loaded.grid.layers[-1].bottom == original.grid.layers[-1].bottom

    def test_gitignore_keeps_derived_directories_out(self, tmp_path: Path) -> None:
        projectstore.save(tmp_path / "p.mup", simple())

        ignored = (tmp_path / "p.mup" / ".gitignore").read_text()

        assert "cache/" in ignored
        assert "runs/" in ignored


class TestHandEditing:
    def test_a_hand_edited_value_is_read_back(self, tmp_path: Path) -> None:
        """Editing the TOML in a text editor is a supported way to work."""
        directory = tmp_path / "p.mup"
        projectstore.save(directory, simple())

        grid = (directory / "grid.toml").read_text().replace("ncells = 50", "ncells = 80")
        (directory / "grid.toml").write_text(grid)

        assert projectstore.load(directory).grid.ncol == 80

    def test_an_omitted_optional_field_falls_back_to_its_default(self, tmp_path: Path) -> None:
        directory = tmp_path / "p.mup"
        projectstore.save(directory, simple())

        content = toml_io.read(directory / "project.toml")
        del content["meta"]["length_unit"]
        toml_io.write(directory / "project.toml", content)

        assert projectstore.load(directory).meta.length_unit == "meters"

    def test_a_missing_optional_file_is_tolerated(self, tmp_path: Path) -> None:
        directory = tmp_path / "p.mup"
        projectstore.save(directory, simple())
        (directory / "transport.toml").unlink()

        loaded = projectstore.load(directory)

        assert loaded.transport.advection_scheme == "tvd"


class TestErrors:
    def test_a_directory_that_is_not_a_project(self, tmp_path: Path) -> None:
        with pytest.raises(projectstore.ProjectError, match=r"no project\.toml"):
            projectstore.load(tmp_path)

    def test_malformed_toml_names_the_file(self, tmp_path: Path) -> None:
        directory = tmp_path / "p.mup"
        projectstore.save(directory, simple())
        (directory / "grid.toml").write_text("this is not [ valid toml")

        with pytest.raises(projectstore.ProjectError, match=r"grid\.toml is not valid TOML"):
            projectstore.load(directory)

    def test_a_validation_failure_names_the_file_and_the_field(self, tmp_path: Path) -> None:
        directory = tmp_path / "p.mup"
        projectstore.save(directory, simple())
        grid = (directory / "grid.toml").read_text().replace("ncells = 50", "ncells = -3")
        (directory / "grid.toml").write_text(grid)

        with pytest.raises(projectstore.ProjectError) as caught:
            projectstore.load(directory)

        assert "grid.toml" in str(caught.value)
        assert "grid" in str(caught.value)

    def test_a_section_in_the_wrong_file_is_reported(self, tmp_path: Path) -> None:
        directory = tmp_path / "p.mup"
        projectstore.save(directory, simple())
        content = toml_io.read(directory / "grid.toml")
        content["flow"] = {"properties": {}}
        toml_io.write(directory / "grid.toml", content)

        with pytest.raises(projectstore.ProjectError, match="unexpected section"):
            projectstore.load(directory)

    def test_a_newer_schema_version_is_refused_clearly(self, tmp_path: Path) -> None:
        directory = tmp_path / "p.mup"
        projectstore.save(directory, simple())
        content = toml_io.read(directory / "project.toml")
        content["meta"]["schema_version"] = 99
        toml_io.write(directory / "project.toml", content)

        with pytest.raises(projectstore.ProjectError, match="newer mupstudio"):
            projectstore.load(directory)

    def test_create_refuses_to_overwrite(self, tmp_path: Path) -> None:
        projectstore.create(tmp_path, "column", simple())

        with pytest.raises(projectstore.ProjectError, match="already exists"):
            projectstore.create(tmp_path, "column", simple())


class TestTomlWriter:
    def test_omits_a_table_whose_fields_are_all_unset(self) -> None:
        text = toml_io.dumps({"outer": {"unset": None, "items": [{"a": 1}]}})

        assert "[outer]" not in text
        assert "[[outer.items]]" in text

    def test_keeps_a_float_a_float(self) -> None:
        assert toml_io.loads(toml_io.dumps({"x": 1.0}))["x"] == 1.0
        assert isinstance(toml_io.loads(toml_io.dumps({"x": 1.0}))["x"], float)

    def test_round_trips_awkward_numbers(self) -> None:
        values = {"tiny": 1e-30, "huge": 1e30, "precise": 0.1 + 0.2, "negative": -1.5e-7}

        assert toml_io.loads(toml_io.dumps(values)) == values

    def test_escapes_strings_that_would_break_the_file(self) -> None:
        values = {"quoted": 'he said "hi"', "multiline": "one\ntwo", "tabbed": "a\tb"}

        assert toml_io.loads(toml_io.dumps(values)) == values

    def test_refuses_values_toml_cannot_hold(self) -> None:
        for bad in (float("nan"), float("inf")):
            with pytest.raises(toml_io.TomlWriteError, match="no representation"):
                toml_io.dumps({"x": bad})

    def test_writes_a_zone_map_as_an_inline_table(self) -> None:
        text = toml_io.dumps({"values": {"sand": 0.35, "clay": 0.05}})

        assert toml_io.loads(text)["values"] == {"sand": 0.35, "clay": 0.05}
