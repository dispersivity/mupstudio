"""Chemistry: the databases, and checking a project against one.

The database is what turns the chemistry editor from free text into a set of
choices, so these endpoints exist mainly to feed pickers: which databases are
installed, and what is in the one selected.

Indexes are sent whole rather than paged. llnl.dat is the worst case at about
three thousand entries, which is a few hundred kilobytes of JSON and is fetched
once per database — cheaper than paging a list people search rather than scroll.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from mupstudio.chemdb import cache, validate
from mupstudio.chemdb.parser import DatabaseIndex
from mupstudio.schema.chemistry import ChemistryModel
from mupstudio.server.routers.projects import load_project

log = logging.getLogger(__name__)
router = APIRouter(tags=["chemistry"])


@router.get("/databases")
def list_databases() -> dict[str, Any]:
    """Every database found, with a summary of what is in it.

    Parsing them all to summarise is what makes the picker useful: a modeller
    chooses between phreeqc.dat and pht3d_datab.dat by what they contain, not by
    their names.
    """
    entries: list[dict[str, Any]] = []
    for path in cache.available():
        try:
            index = cache.load(path)
        except Exception as error:  # a malformed database should not hide the rest
            log.warning("could not parse %s: %s", path, error)
            entries.append({"name": path.name, "path": str(path), "error": str(error)})
            continue
        entries.append(
            {
                "name": path.name,
                "path": str(path),
                "sha256": index.sha256,
                "summary": index.summary(),
            }
        )
    return {"databases": entries}


@router.get("/databases/{name}/index")
def database_index(name: str) -> dict[str, Any]:
    """Everything in one database that the chemistry editor can offer."""
    return _serialise(_load_database(name))


@router.get("/databases/{name}/rates/{rate}")
def rate_detail(name: str, rate: str) -> dict[str, Any]:
    """One rate law's parameters, each with the BASIC lines that use it.

    A rate law's parameters are positional and unnamed, so the only statement of
    what PARM(2) means is the line of BASIC that reads it. Showing those lines
    beside the input is the difference between an editable rate and a guess.
    """
    index = _load_database(name)
    found = index.rate(rate)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no rate law {rate!r} in {name}")

    return {
        "name": found.name,
        "parmCount": found.parm_count,
        "basic": found.basic,
        "isMineral": index.phase(found.name) is not None,
        "parms": [
            {"index": number, "lines": found.parm_lines(number)}
            for number in range(1, found.parm_count + 1)
        ],
    }


@router.post("/chemistry/check")
def check_chemistry(chemistry: ChemistryModel, database: str | None = None) -> dict[str, Any]:
    """Check chemistry against a database without saving anything.

    Takes the chemistry directly rather than a project path so the editor can
    check as it is edited, before the change has been written to disk.
    """
    index = _load_database(database or chemistry.database.name)
    problems = validate.check(chemistry, index)

    return {
        "database": index.name,
        "problems": [
            {
                "severity": problem.severity,
                "where": problem.where,
                "message": problem.message,
                "suggestion": problem.suggestion,
            }
            for problem in problems
        ],
        "errors": sum(1 for problem in problems if problem.severity == "error"),
        "warnings": sum(1 for problem in problems if problem.severity == "warning"),
    }


@router.get("/projects/chemistry/check")
def check_project_chemistry(path: str) -> dict[str, Any]:
    """The same check, for the chemistry a saved project holds."""
    project = load_project(path)
    return check_chemistry(project.chemistry)


def _load_database(name: str) -> DatabaseIndex:
    try:
        return cache.load_by_name(name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"could not read {name}: {error}") from error


def _serialise(index: DatabaseIndex) -> dict[str, Any]:
    """The index, as the shapes the editor's pickers want.

    Master species are grouped by element so redox states appear as children of
    the element rather than as a flat list of names nobody can scan.
    """
    elements: dict[str, list[dict[str, Any]]] = {}
    for item in index.solution_species:
        elements.setdefault(item.element, []).append(
            {
                "name": item.name,
                "redox": item.redox_state,
                "species": item.species,
                "gramFormulaWeight": item.gram_formula_weight,
            }
        )

    return {
        "name": index.name,
        "path": index.path,
        "sha256": index.sha256,
        "summary": index.summary(),
        "elements": [
            {"element": element, "states": states} for element, states in sorted(elements.items())
        ],
        "phases": [
            {"name": phase.name, "reaction": phase.reaction, "logK": phase.log_k}
            for phase in index.minerals
        ],
        "gases": [
            {"name": phase.name, "reaction": phase.reaction, "logK": phase.log_k}
            for phase in index.gases
        ],
        "exchangeSpecies": index.exchange_species,
        "exchangeSites": index.exchange_sites,
        "surfaceSites": index.surface_sites,
        "rates": [
            {
                "name": rate.name,
                "parmCount": rate.parm_count,
                "isMineral": index.phase(rate.name) is not None,
            }
            for rate in index.rates
        ],
        "kineticMinerals": index.kinetic_minerals,
    }
