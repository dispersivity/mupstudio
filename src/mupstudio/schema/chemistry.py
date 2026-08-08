"""Chemistry: what is in the water and what it can react with.

PHREEQC organises chemistry into numbered assemblages — solution 1, equilibrium
phases 2, exchange 1 — and a cell is assigned one of each. ORTi3D packed that
tuple into a single integer per cell, which is dense and breaks past nine
assemblages. Here the tuple is a named Composition, so a cell is assigned
"leachate" rather than 2101.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from mupstudio.schema.common import Id

# CellRange is re-exported: chemistry used to define its own, and a zone is
# still written as one in the common case.
from mupstudio.schema.selection import CellRange as CellRange
from mupstudio.schema.selection import CellSelection

# Rows that describe the solution itself rather than a dissolved species.
SOLUTION_META = ("pH", "pe", "temperature", "density", "water")


class DatabaseRef(BaseModel):
    """Which PHREEQC database the chemistry is written against.

    The hash is recorded so a project opened later can tell whether the
    database it was built against is the one now on disk.
    """

    name: str = "phreeqc.dat"
    path: str | None = Field(default=None, description="Absolute path; searched by name if unset")
    sha256: str | None = None


class Solution(BaseModel):
    """A water composition.

    Concentrations are keyed by master species, so the keys are whatever the
    database defines: ``Ca``, ``C(+4)``, ``Fe(+2)``.
    """

    id: Id
    label: str = ""
    ph: float = 7.0
    pe: float = 4.0
    temperature: float = 25.0
    units: Literal["mol/kgw", "mmol/kgw", "umol/kgw", "mg/l", "ug/l"] = "mol/kgw"
    concentrations: dict[str, float] = Field(default_factory=dict)
    charge_balance: str | None = Field(
        default=None,
        description="Master species adjusted to balance charge, if any",
    )

    @model_validator(mode="after")
    def _charge_balance_species_must_be_present(self) -> Solution:
        if self.charge_balance and self.charge_balance not in self.concentrations:
            raise ValueError(
                f"solution {self.id!r} balances charge on {self.charge_balance!r}, "
                "which it does not contain"
            )
        return self


class PhaseTarget(BaseModel):
    """One mineral in an equilibrium assemblage."""

    phase: str
    saturation_index: float = 0.0
    moles: float = Field(
        default=0.0, ge=0, description="Available amount; 0 allows dissolution only"
    )


class EquilibriumPhases(BaseModel):
    """Minerals a solution equilibrates with."""

    id: Id
    label: str = ""
    phases: list[PhaseTarget] = Field(default_factory=list)


class ExchangeAssemblage(BaseModel):
    """Cation exchange capacity, by exchange species."""

    id: Id
    label: str = ""
    sites: dict[str, float] = Field(default_factory=dict)
    equilibrate_with: Id | None = Field(
        default=None,
        description="Solution the exchanger starts in equilibrium with",
    )


class SurfaceSite(BaseModel):
    """One sorption site type."""

    site: str
    moles: float = Field(ge=0)
    specific_area: float = Field(default=0.0, ge=0, description="m2/g")
    mass: float = Field(default=0.0, ge=0, description="g")


class SurfaceAssemblage(BaseModel):
    """Sorption sites, and how the electrical double layer is treated."""

    id: Id
    label: str = ""
    sites: list[SurfaceSite] = Field(default_factory=list)
    edl_model: Literal["no_edl", "diffuse_layer", "donnan"] = "no_edl"
    donnan_thickness: float | None = None
    equilibrate_with: Id | None = None


class KineticReaction(BaseModel):
    """One rate law and its parameters.

    Parameters are positional, as PHREEQC defines them: ``parms[0]`` is
    ``PARM(1)``. The database says how many a law expects, and validation
    checks the count rather than leaving it to fail at run time.
    """

    rate: str = Field(description="Name of a RATES entry in the database")
    initial_moles: float = Field(default=0.0, ge=0, alias="m0")
    parms: list[float] = Field(default_factory=list)
    formula: str | None = Field(default=None, description="Overrides the rate's own stoichiometry")
    steps: list[float] | None = None

    model_config = {"populate_by_name": True}


class KineticAssemblage(BaseModel):
    """A set of kinetic reactions acting together."""

    id: Id
    label: str = ""
    reactions: list[KineticReaction] = Field(default_factory=list)


class GasPhaseAssemblage(BaseModel):
    """A gas phase, fixed pressure or fixed volume."""

    id: Id
    label: str = ""
    partial_pressures: dict[str, float] = Field(default_factory=dict)
    fixed_pressure: bool = True
    total_pressure: float = 1.0
    volume: float = 1.0


class Composition(BaseModel):
    """What one part of the model is made of, chemically.

    The tuple PHREEQC needs, named. A cell gets a composition, not six
    independent assemblage numbers.
    """

    id: Id
    label: str = ""
    colour: str | None = Field(default=None, description="Hex colour used in the viewport legend")
    solution: Id
    equilibrium_phases: Id | None = None
    exchange: Id | None = None
    surface: Id | None = None
    kinetics: Id | None = None
    gas_phase: Id | None = None


# Chemistry points at cells the same way everything else does. A composition
# painted over an imported polygon is the same operation as a conductivity zone
# over that polygon, and there is no reason for two spellings of it.
ChemSelection = CellSelection


class ChemZone(BaseModel):
    """A composition applied to part of the grid."""

    id: Id
    composition: Id
    cells: ChemSelection


class SelectedOutput(BaseModel):
    """What PHREEQC is asked to report.

    This decides what can be visualised afterwards: a species not selected here
    is not written, and the run has to be repeated to get it.
    """

    totals: list[str] = Field(default_factory=list)
    molalities: list[str] = Field(default_factory=list)
    saturation_indices: list[str] = Field(default_factory=list)
    equilibrium_phases: list[str] = Field(default_factory=list)
    kinetic_reactants: list[str] = Field(default_factory=list)
    gases: list[str] = Field(default_factory=list)
    ph: bool = True
    pe: bool = True

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.totals,
                self.molalities,
                self.saturation_indices,
                self.equilibrium_phases,
                self.kinetic_reactants,
                self.gases,
            ]
        )


class ChemistryModel(BaseModel):
    """The chemistry half of a model."""

    enabled: bool = False
    database: DatabaseRef = Field(default_factory=DatabaseRef)

    solutions: list[Solution] = Field(default_factory=list)
    equilibrium_phases: list[EquilibriumPhases] = Field(default_factory=list)
    exchange: list[ExchangeAssemblage] = Field(default_factory=list)
    surface: list[SurfaceAssemblage] = Field(default_factory=list)
    kinetics: list[KineticAssemblage] = Field(default_factory=list)
    gas_phases: list[GasPhaseAssemblage] = Field(default_factory=list)

    compositions: list[Composition] = Field(default_factory=list)
    background: Id | None = Field(default=None, description="Composition for cells no zone covers")
    zones: list[ChemZone] = Field(default_factory=list)

    boundary_solutions: dict[str, Id] = Field(
        default_factory=dict,
        description="Flow package id to the solution its inflow carries",
    )
    selected_output: SelectedOutput = Field(default_factory=SelectedOutput)

    @model_validator(mode="after")
    def _check_internal_references(self) -> ChemistryModel:
        """Every name a composition or zone mentions must exist.

        Checked here rather than at write time so a dangling reference is
        reported while it is still being edited.
        """
        if not self.enabled:
            return self

        pools: dict[str, set[str]] = {
            "solution": {item.id for item in self.solutions},
            "equilibrium_phases": {item.id for item in self.equilibrium_phases},
            "exchange": {item.id for item in self.exchange},
            "surface": {item.id for item in self.surface},
            "kinetics": {item.id for item in self.kinetics},
            "gas_phase": {item.id for item in self.gas_phases},
        }

        for composition in self.compositions:
            for slot, available in pools.items():
                referenced = getattr(composition, slot)
                if referenced is not None and referenced not in available:
                    raise ValueError(
                        f"composition {composition.id!r} uses {slot} {referenced!r}, "
                        f"which does not exist"
                    )

        names = {item.id for item in self.compositions}
        if self.background is not None and self.background not in names:
            raise ValueError(f"the background composition {self.background!r} does not exist")

        for zone in self.zones:
            if zone.composition not in names:
                raise ValueError(
                    f"zone {zone.id!r} uses composition {zone.composition!r}, which does not exist"
                )

        solutions = pools["solution"]
        for package, solution in self.boundary_solutions.items():
            if solution not in solutions:
                raise ValueError(
                    f"boundary {package!r} carries solution {solution!r}, which does not exist"
                )

        # Equilibrating against a solution that is not defined would fail deep
        # inside PhreeqcRM, so it is caught here. Exchange and surface
        # assemblages are walked separately because they are different types
        # that happen to share this one field.
        equilibrating: list[tuple[str, str | None]] = [
            *((item.id, item.equilibrate_with) for item in self.exchange),
            *((item.id, item.equilibrate_with) for item in self.surface),
        ]
        for assemblage_id, target in equilibrating:
            if target is not None and target not in solutions:
                raise ValueError(
                    f"{assemblage_id!r} equilibrates with solution {target!r}, which does not exist"
                )

        return self

    def composition(self, composition_id: str) -> Composition:
        for item in self.compositions:
            if item.id == composition_id:
                return item
        raise KeyError(f"no composition {composition_id!r}")

    def solution(self, solution_id: str) -> Solution:
        for item in self.solutions:
            if item.id == solution_id:
                return item
        raise KeyError(f"no solution {solution_id!r}")
