"""Named regions of the grid, shared by every property that varies over it.

A modeller does not think "conductivity 12 here, porosity 0.3 here, dispersivity
1 m here" as three independent maps. They think "this is the sand and that is
the clay", and then give the sand and the clay their properties. Zones are that
idea: the region is named and drawn once, and each property says what its value
is per zone.

This is why zones live at the project level rather than under flow or transport.
The sand is the sand for hydraulic conductivity and for porosity alike, and two
copies of its outline would be two things to keep in step.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mupstudio.schema.common import Id
from mupstudio.schema.selection import CellSelection


class PropertyZone(BaseModel):
    """A named region, however it was picked out."""

    id: Id
    label: str = Field(default="", description="What the region is: 'sand', 'weathered'")
    cells: CellSelection
    color: str | None = Field(
        default=None,
        description="Hex colour for the legend. Assigned by the app when left unset.",
    )


def paint_order(zones: list[PropertyZone]) -> list[PropertyZone]:
    """Zones in the order they are applied, later ones winning where they overlap.

    List order is the answer everywhere in the app: it is what a layer list
    means in every GIS, and it is the only rule a person can predict without
    reading documentation. Overlap is allowed on purpose — painting a small
    lens inside a large unit is easier than cutting a hole in the large one.
    """
    return list(zones)
