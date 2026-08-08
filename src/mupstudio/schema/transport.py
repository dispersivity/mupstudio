"""Transport: how solutes move, before any chemistry acts on them."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mupstudio.schema.common import PropertyField, ZoneField, constant


class Dispersion(BaseModel):
    """Mechanical dispersion and molecular diffusion.

    Transverse dispersivities default to a tenth and a hundredth of the
    longitudinal value, which are the conventional starting ratios.
    """

    longitudinal: PropertyField = Field(default_factory=lambda: constant(0.0))
    transverse_horizontal: PropertyField | None = None
    transverse_vertical: PropertyField | None = None
    diffusion: PropertyField = Field(default_factory=lambda: constant(0.0))

    @property
    def enabled(self) -> bool:
        """Whether dispersion does anything.

        A column benchmark testing pure advection sets everything to zero, and
        MODFLOW would rather the package were absent than present with zeros.
        """
        for field in (self.longitudinal, self.diffusion):
            if not isinstance(field, type(constant(0.0))) or field.value != 0.0:
                return True
        return self.transverse_horizontal is not None or self.transverse_vertical is not None


class DualPorosity(BaseModel):
    """A mobile and an immobile domain exchanging mass.

    PHT3D only for now; the schema carries it so a model does not have to be
    rebuilt when MF6RTM gains support.
    """

    immobile_porosity: PropertyField
    transfer_rate: PropertyField


class TransportModel(BaseModel):
    """The transport half of a model."""

    porosity: PropertyField | None = Field(
        default=None, description="Defaults to the flow model's porosity"
    )
    dispersion: Dispersion = Field(default_factory=Dispersion)
    advection_scheme: Literal["upstream", "central", "tvd"] = "tvd"
    dual_porosity: DualPorosity | None = None

    def zoned_fields(self) -> list[tuple[str, ZoneField]]:
        """The properties given per zone, so their zone names can be checked."""
        return [("porosity", self.porosity)] if isinstance(self.porosity, ZoneField) else []
