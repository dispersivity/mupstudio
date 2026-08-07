"""Shared field types.

The recurring problem in a model definition is that almost any property can be
given as one number, as different numbers per zone, or as an array someone
calibrated elsewhere. Rather than three shapes of every field, there is one
tagged union used everywhere, so a writer handles the three cases once.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

# Identifiers are used as TOML table keys and in cross-references, so they are
# restricted to what stays readable in both a file and a URL.
ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def validate_id(value: str) -> str:
    if not ID_PATTERN.match(value):
        raise ValueError(
            f"{value!r} is not a valid id: start with a letter, then letters, digits, "
            "hyphens or underscores, up to 64 characters"
        )
    return value


Id = Annotated[str, Field(pattern=ID_PATTERN.pattern)]

LengthUnit = Literal["meters", "feet", "centimeters", "unknown"]
TimeUnit = Literal["seconds", "minutes", "hours", "days", "years", "unknown"]


class ConstantField(BaseModel):
    """One value everywhere."""

    kind: Literal["constant"] = "constant"
    value: float


class ZoneField(BaseModel):
    """A value per zone, with a fallback for cells no zone covers."""

    kind: Literal["zones"] = "zones"
    default: float
    values: dict[str, float] = Field(default_factory=dict)


class ArrayField(BaseModel):
    """An array on disk, relative to the project directory.

    For fields nobody wants to retype: a calibrated conductivity field, a
    measured porosity distribution.
    """

    kind: Literal["array"] = "array"
    path: str


PropertyField = Annotated[
    ConstantField | ZoneField | ArrayField,
    Field(discriminator="kind"),
]


class ConstantSeries(BaseModel):
    """Unchanging through time."""

    kind: Literal["constant"] = "constant"
    value: float


class PerPeriodSeries(BaseModel):
    """One value per stress period."""

    kind: Literal["per_period"] = "per_period"
    values: list[float]


TimeSeries = Annotated[
    ConstantSeries | PerPeriodSeries,
    Field(discriminator="kind"),
]


def constant(value: float) -> ConstantField:
    """Shorthand, since most properties start life as one number."""
    return ConstantField(value=value)


class StressPeriod(BaseModel):
    """One period of the simulation, as MODFLOW divides time."""

    perlen: float = Field(gt=0, description="Length of the period")
    nstp: int = Field(default=1, ge=1, description="Time steps within it")
    tsmult: float = Field(default=1.0, gt=0, description="Time step multiplier")
    steady: bool = Field(default=False, description="Solve flow as steady state")


class TimeDiscretisation(BaseModel):
    """The simulation's time axis."""

    periods: list[StressPeriod] = Field(min_length=1)
    start_datetime: str | None = Field(
        default=None, description="ISO date the run starts, for labelling output"
    )

    @field_validator("periods")
    @classmethod
    def _reject_zero_length(cls, periods: list[StressPeriod]) -> list[StressPeriod]:
        for index, period in enumerate(periods):
            if period.perlen <= 0:
                raise ValueError(f"stress period {index + 1} has no length")
        return periods

    @property
    def nper(self) -> int:
        return len(self.periods)

    @property
    def total_time(self) -> float:
        return sum(period.perlen for period in self.periods)
