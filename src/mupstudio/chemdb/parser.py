"""Reading a PHREEQC database.

The database is what makes a chemistry editor possible: it says which species
exist, which minerals can precipitate, and what parameters a rate law expects.
Without it every field is free text and every mistake surfaces as a PHREEQC
error three minutes into a run.

These files are hand-maintained and inconsistent — comments anywhere, blocks in
any order, blank lines and continuations — so the parser is deliberately
forgiving about layout and strict only about the block keywords.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# The blocks worth reading. Anything else is skipped rather than rejected: a
# database may carry blocks this build does not use, and that is not an error.
KNOWN_BLOCKS = frozenset(
    {
        "SOLUTION_MASTER_SPECIES",
        "SOLUTION_SPECIES",
        "PHASES",
        "EXCHANGE_MASTER_SPECIES",
        "EXCHANGE_SPECIES",
        "SURFACE_MASTER_SPECIES",
        "SURFACE_SPECIES",
        "RATES",
        "END",
    }
)

_BLOCK = re.compile(r"^([A-Z][A-Z_0-9]*)\s*$")
_PARM = re.compile(r"\bPARM\s*\(\s*(\d+)\s*\)", re.IGNORECASE)
# An element with a redox state, as in C(+4) or Fe(+2).
_REDOX = re.compile(r"^([A-Za-z][A-Za-z]*)\(([-+]?\d+(?:\.\d+)?)\)$")

# Species the chemistry editor should not offer as things to set: they are
# derived, or they are the solvent.
HIDDEN_MASTER_SPECIES = frozenset({"E", "H2O", "Alkalinity"})


@dataclass(frozen=True)
class MasterSpecies:
    """One row of SOLUTION_MASTER_SPECIES."""

    name: str
    species: str
    alkalinity: float
    gram_formula_weight: float | None
    element_weight: float | None

    @property
    def element(self) -> str:
        """The element, with any redox state stripped: C(+4) is carbon."""
        match = _REDOX.match(self.name)
        return match.group(1) if match else self.name

    @property
    def redox_state(self) -> str | None:
        match = _REDOX.match(self.name)
        return match.group(2) if match else None


@dataclass(frozen=True)
class Phase:
    """A mineral or a gas, from PHASES."""

    name: str
    reaction: str
    log_k: float | None

    @property
    def is_gas(self) -> bool:
        """PHREEQC marks gases by the suffix in the phase name."""
        return "(g)" in self.name.lower()


@dataclass(frozen=True)
class Rate:
    """A kinetic rate law, from RATES."""

    name: str
    basic: str
    parm_count: int

    def parm_lines(self, index: int) -> list[str]:
        """BASIC lines mentioning PARM(index).

        Shown in the editor next to the parameter, because a rate law's
        parameters are positional and otherwise unnamed: the only statement of
        what parm(2) means is the line that uses it.
        """
        wanted = re.compile(rf"\bPARM\s*\(\s*{index}\s*\)", re.IGNORECASE)
        return [line.strip() for line in self.basic.splitlines() if wanted.search(line)]


@dataclass
class DatabaseIndex:
    """Everything the chemistry editor needs from a database."""

    name: str
    path: str
    sha256: str
    master_species: list[MasterSpecies] = field(default_factory=list)
    aqueous_species: list[str] = field(default_factory=list)
    phases: list[Phase] = field(default_factory=list)
    exchange_species: list[str] = field(default_factory=list)
    exchange_sites: list[str] = field(default_factory=list)
    surface_sites: list[str] = field(default_factory=list)
    rates: list[Rate] = field(default_factory=list)

    @property
    def minerals(self) -> list[Phase]:
        return [phase for phase in self.phases if not phase.is_gas]

    @property
    def gases(self) -> list[Phase]:
        return [phase for phase in self.phases if phase.is_gas]

    @property
    def solution_species(self) -> list[MasterSpecies]:
        """Master species a user would set a concentration for.

        Where an element has redox states, PHREEQC lists both the element and
        each state. The bare element is dropped, because setting both it and its
        states is contradictory.
        """
        with_redox = {item.element for item in self.master_species if item.redox_state}
        return [
            item
            for item in self.master_species
            if item.name not in HIDDEN_MASTER_SPECIES
            and not (item.name in with_redox and item.redox_state is None)
        ]

    @property
    def kinetic_minerals(self) -> list[str]:
        """Rates that name a phase, so they consume or produce a mineral."""
        phase_names = {phase.name for phase in self.phases}
        return sorted(rate.name for rate in self.rates if rate.name in phase_names)

    def rate(self, name: str) -> Rate | None:
        return next((item for item in self.rates if item.name == name), None)

    def phase(self, name: str) -> Phase | None:
        return next((item for item in self.phases if item.name == name), None)

    def summary(self) -> dict[str, int]:
        return {
            "masterSpecies": len(self.solution_species),
            "phases": len(self.minerals),
            "gases": len(self.gases),
            "exchangeSpecies": len(self.exchange_species),
            "surfaceSites": len(self.surface_sites),
            "rates": len(self.rates),
        }


def strip_comment(line: str) -> str:
    """Remove a trailing comment. PHREEQC uses both # and !."""
    for marker in ("#", "!"):
        position = line.find(marker)
        if position >= 0:
            line = line[:position]
    return line.rstrip()


def parse_database(path: Path) -> DatabaseIndex:
    """Read a .dat file into an index."""
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    index = DatabaseIndex(
        name=path.stem,
        path=str(path),
        sha256=hashlib.sha256(raw).hexdigest(),
    )

    for block, lines in _split_blocks(text):
        if block == "SOLUTION_MASTER_SPECIES":
            index.master_species.extend(_parse_master_species(lines))
        elif block == "SOLUTION_SPECIES":
            index.aqueous_species.extend(_parse_species_names(lines))
        elif block == "PHASES":
            index.phases.extend(_parse_phases(lines))
        elif block == "EXCHANGE_MASTER_SPECIES":
            index.exchange_sites.extend(_parse_first_column(lines))
        elif block == "EXCHANGE_SPECIES":
            index.exchange_species.extend(_parse_species_names(lines))
        elif block == "SURFACE_MASTER_SPECIES":
            index.surface_sites.extend(_parse_first_column(lines))
        elif block == "RATES":
            index.rates.extend(_parse_rates(lines))

    return index


def _split_blocks(text: str) -> list[tuple[str, list[str]]]:
    """Group lines under the block keyword that introduced them."""
    blocks: list[tuple[str, list[str]]] = []
    current: str | None = None
    lines: list[str] = []

    for raw in text.splitlines():
        candidate = strip_comment(raw).strip()
        match = _BLOCK.match(candidate)
        if match and match.group(1) in KNOWN_BLOCKS:
            if current is not None:
                blocks.append((current, lines))
            current, lines = match.group(1), []
            continue
        if current is not None:
            # RATES needs its original text, so raw lines are kept and
            # comments stripped per-parser instead of here.
            lines.append(raw)

    if current is not None:
        blocks.append((current, lines))
    return blocks


def _parse_master_species(lines: list[str]) -> list[MasterSpecies]:
    found: list[MasterSpecies] = []
    for raw in lines:
        parts = strip_comment(raw).split()
        if len(parts) < 3:
            continue
        try:
            alkalinity = float(parts[2])
        except ValueError:
            continue
        found.append(
            MasterSpecies(
                name=parts[0],
                species=parts[1],
                alkalinity=alkalinity,
                gram_formula_weight=_maybe_float(parts, 3),
                element_weight=_maybe_float(parts, 4),
            )
        )
    return found


def _parse_species_names(lines: list[str]) -> list[str]:
    """Species defined by a reaction: the product on the right of the equals.

    Reaction lines are indented in some blocks and not in others, so
    indentation is not the signal. What distinguishes a reaction from the
    keywords that follow it is the equals sign and the absence of a leading
    dash.
    """
    names: list[str] = []
    for raw in lines:
        line = strip_comment(raw).strip()
        if not line or "=" not in line or line.startswith("-"):
            continue
        if line.split()[0].lower() in {"log_k", "delta_h", "analytical_expression"}:
            continue

        right = line.split("=", 1)[1].strip()
        # Products are separated by " + "; the species is the first one, with
        # any stoichiometric coefficient in front of it removed.
        first = right.split(" + ")[0].strip()
        stripped = first.lstrip("0123456789. ")
        if stripped:
            names.append(stripped)

    # A database repeats species across sub-blocks; order is kept but the
    # duplicates are not.
    return list(dict.fromkeys(names))


def _parse_first_column(lines: list[str]) -> list[str]:
    names: list[str] = []
    for raw in lines:
        parts = strip_comment(raw).split()
        if parts:
            names.append(parts[0])
    return names


def _parse_phases(lines: list[str]) -> list[Phase]:
    """A phase is a name on its own line, then its reaction and keywords."""
    phases: list[Phase] = []
    name: str | None = None
    reaction = ""
    log_k: float | None = None

    def flush() -> None:
        nonlocal name, reaction, log_k
        if name:
            phases.append(Phase(name=name, reaction=reaction.strip(), log_k=log_k))
        name, reaction, log_k = None, "", None

    for raw in lines:
        line = strip_comment(raw)
        if not line.strip():
            continue

        if not line[0].isspace():
            # An unindented line starts a new phase.
            flush()
            name = line.strip().split()[0]
            continue

        body = line.strip()
        lowered = body.lower()
        if lowered.startswith(("log_k", "-log_k")):
            log_k = _first_float(body)
        elif not body.startswith("-") and "=" in body and not reaction:
            reaction = body

    flush()
    return phases


def _parse_rates(lines: list[str]) -> list[Rate]:
    """A rate is a name, then BASIC between -start and -end."""
    rates: list[Rate] = []
    name: str | None = None
    body: list[str] = []
    inside = False

    for raw in lines:
        stripped = raw.strip()
        lowered = strip_comment(raw).strip().lower()

        if lowered == "-start":
            inside = True
            body = []
            continue
        if lowered == "-end":
            if name:
                text = "\n".join(body)
                rates.append(Rate(name=name, basic=text, parm_count=_count_parms(text)))
            inside, name, body = False, None, []
            continue

        if inside:
            body.append(raw)
        elif stripped and not raw[0].isspace() and not stripped.startswith("#"):
            name = strip_comment(raw).strip().split()[0] or None

    return rates


def _count_parms(basic: str) -> int:
    """How many parameters a rate law expects.

    Taken as the highest PARM index it references, since the parameters are
    positional and a law using PARM(1) and PARM(3) still needs three values.
    """
    indices = [int(match) for match in _PARM.findall(basic)]
    return max(indices) if indices else 0


def _maybe_float(parts: list[str], index: int) -> float | None:
    if index >= len(parts):
        return None
    try:
        return float(parts[index])
    except ValueError:
        return None


def _first_float(text: str) -> float | None:
    for token in text.split()[1:]:
        try:
            return float(token)
        except ValueError:
            continue
    return None
