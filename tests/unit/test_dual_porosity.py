"""A mobile and an immobile domain exchanging mass.

The schema has carried dual porosity since the beginning and nothing wrote it,
which is the worst state for a feature to be in: the control accepts a value,
the project saves it, and the deck that runs has one porosity in it.

Where MT3DMS puts this is not obvious and is the reason these tests check the
written file rather than the call. Dual porosity is not part of BTN — it is a
mode of the reaction package, and the field named "porosity" there is the
immobile one while BTN's stays mobile.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.schema.common import (
    ConstantSeries,
    StressPeriod,
    TimeDiscretisation,
    ZoneField,
    constant,
)
from mupstudio.schema.flow import ConstantHeadPackage, FlowModel, HeadEntry, WellEntry, WellPackage
from mupstudio.schema.grid import column_grid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.selection import CellRange
from mupstudio.schema.transport import Dispersion, DualPorosity, TransportModel
from mupstudio.schema.zones import PropertyZone


def project(**overrides: object) -> Project:
    """A column with an inflow and an outflow, so the deck is complete."""
    defaults: dict[str, object] = {
        "meta": ProjectMeta(name="dual", engine="pht3d"),
        "grid": column_grid(ncells=10, length=1.0),
        "time": TimeDiscretisation(periods=[StressPeriod(perlen=1.0, nstp=10)]),
        "flow": FlowModel(
            packages=[
                WellPackage(
                    id="inflow",
                    entries=[
                        WellEntry(
                            cells=CellRange(layers=[1], rows=[1], columns=[1]),
                            rate=ConstantSeries(value=0.1),
                        )
                    ],
                ),
                ConstantHeadPackage(
                    id="outflow",
                    entries=[
                        HeadEntry(
                            cells=CellRange(layers=[1], rows=[1], columns=[10]),
                            head=ConstantSeries(value=0.0),
                        )
                    ],
                ),
            ]
        ),
    }
    return Project(**{**defaults, **overrides})  # type: ignore[arg-type]


def dual(immobile: float = 0.08, transfer: float = 0.002) -> TransportModel:
    return TransportModel(
        porosity=constant(0.25),
        dispersion=Dispersion(longitudinal=constant(0.01)),
        dual_porosity=DualPorosity(
            immobile_porosity=constant(immobile), transfer_rate=constant(transfer)
        ),
    )


def build(tmp_path: Path, transport: TransportModel) -> tuple[Path, object]:
    """Write a complete MT3D deck, and hand back where it went."""
    import numpy as np

    from mupstudio.engines.pht3d.ordering import Group, order_components
    from mupstudio.engines.pht3d.transport import write_transport

    model = compile_project(project(transport=transport))
    workdir = tmp_path / "deck"
    workdir.mkdir(exist_ok=True)

    # One aqueous species is enough for a deck; pH and pe come with it.
    components = order_components({Group.AQUEOUS: ["Cl"]})
    initial = {
        component.name: np.full(model.grid.shape, 1e-9 if component.name == "Cl" else 7.0)
        for component in components
    }
    boundary = {
        package.id: dict.fromkeys((c.name for c in components), 0.0)
        for package in model.project.flow.packages
    }

    result = write_transport(
        model, workdir, components=components, initial=initial, boundary=boundary, ftl="flow.ftl"
    )
    return workdir, result


def write_deck(tmp_path: Path, transport: TransportModel) -> str:
    """The reaction package as written, or "" when there is not one."""
    workdir, _ = build(tmp_path, transport)
    rct = next(iter(workdir.glob("*.rct")), None)
    return rct.read_text() if rct else ""


class TestCompiledFields:
    def test_both_fields_are_resolved_like_any_other_property(self) -> None:
        model = compile_project(project(transport=dual()))

        assert model.properties["immobile_porosity"].shape == model.grid.shape
        assert model.properties["immobile_porosity"][0, 0, 0] == 0.08
        assert model.properties["transfer_rate"][0, 0, 0] == 0.002

    def test_they_are_absent_when_dual_porosity_is_off(self) -> None:
        model = compile_project(project())

        assert "immobile_porosity" not in model.properties

    def test_the_immobile_porosity_can_vary_by_zone(self) -> None:
        """The immobile fraction is a property of the material, like any other."""
        model = compile_project(
            project(
                zones=[PropertyZone(id="clay", cells=CellRange(layers=[1], rows=[1], columns=[5]))],
                transport=TransportModel(
                    dispersion=Dispersion(longitudinal=constant(0.01)),
                    dual_porosity=DualPorosity(
                        immobile_porosity=ZoneField(default=0.02, values={"clay": 0.30}),
                        transfer_rate=constant(0.001),
                    ),
                ),
            )
        )

        assert model.properties["immobile_porosity"][0, 0, 4] == 0.30
        assert model.properties["immobile_porosity"][0, 0, 0] == 0.02


class TestWrittenDeck:
    def test_no_reaction_package_without_dual_porosity(self, tmp_path: Path) -> None:
        assert write_deck(tmp_path, TransportModel(dispersion=Dispersion())) == ""

    def test_the_package_asks_for_dual_domain_transfer(self, tmp_path: Path) -> None:
        """isothm=5 is dual-domain mass transfer without sorption.

        Not 6: PHT3D does its chemistry through pht3d_ph.dat, and a sorption
        isotherm on top of an exchange assemblage counts the same process twice.
        """
        # Record 1 is ISOTHM IREACT IRCTOP IGETSC, in that order.
        isothm, ireact, _irctop, igetsc = write_deck(tmp_path, dual()).splitlines()[0].split()

        assert int(isothm) == 5  # dual-domain mass transfer, without sorption
        assert int(ireact) == 0  # no kinetic decay; the chemistry is PHREEQC's
        assert int(igetsc) == 0  # immobile concentrations not read separately

    def test_the_immobile_porosity_reaches_the_file(self, tmp_path: Path) -> None:
        written = write_deck(tmp_path, dual(immobile=0.08))

        assert any("0.08" in line and "prsity2" in line for line in written.splitlines())

    def test_every_species_gets_the_transfer_rate(self, tmp_path: Path) -> None:
        """FloPy fills species it is not given with zero.

        One value passed leaves a single component exchanging between the
        domains and every other one sealed into the mobile pore space — which
        runs, and is wrong in a way nothing reports.
        """
        written = write_deck(tmp_path, dual(transfer=0.002))
        rates = [line for line in written.splitlines() if "#sp2" in line]

        # Cl, pH and pe: three components, three transfer rates, none of them 0.
        assert len(rates) == 3
        assert all("0.002" in line for line in rates)

    def test_the_mobile_porosity_stays_in_the_basic_package(self, tmp_path: Path) -> None:
        """Two separate pore spaces. Giving both the total doubles the water."""
        workdir, _ = build(tmp_path, dual(immobile=0.08))

        btn = next(iter(workdir.glob("*.btn"))).read_text()

        assert "0.25" in btn
        assert "0.08" not in btn


class TestWarnings:
    def test_a_zero_transfer_rate_is_called_out(self, tmp_path: Path) -> None:
        """The model would run and the immobile domain would never see anything."""
        _, result = build(tmp_path, dual(transfer=0.0))

        assert any("never exchanges" in warning for warning in result.warnings)  # type: ignore[attr-defined]


class TestEngineSupport:
    def test_mf6rtm_still_refuses_it_rather_than_writing_half_of_it(self) -> None:
        with pytest.raises(ValueError, match="not supported by MF6RTM"):
            project(meta=ProjectMeta(name="dual", engine="mf6rtm"), transport=dual())
