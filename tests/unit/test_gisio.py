"""Importing spatial data, and getting it onto a map.

Written against real files rather than mocks. The whole point of this path is to
cope with what shapefiles and CSVs are actually like — sidecars, missing
projections, columns named whatever the person felt like — and a mock would only
prove the code agrees with my idea of those.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mupstudio.gisio import ingest, preview
from mupstudio.schema.gis import DataModel, PointTableSource, RasterSource, VectorSource

# UTM 19S: metres, southern hemisphere, and what a Chilean model is built in.
# Chosen over a metre-less system because a projected CRS is what reprojection
# actually has to handle.
UTM19S = "EPSG:32719"


@pytest.fixture
def catchment(tmp_path: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import Polygon

    path = tmp_path / "source" / "catchment.shp"
    path.parent.mkdir(parents=True, exist_ok=True)
    shape = Polygon([(340000, 6280000), (360000, 6280000), (362000, 6300000), (338000, 6298000)])
    gpd.GeoDataFrame({"name": ["basin"]}, geometry=[shape], crs=UTM19S).to_file(path)
    return path


@pytest.fixture
def wells(tmp_path: Path) -> Path:
    import pandas as pd

    path = tmp_path / "source" / "wells.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "id": ["W1", "W2"],
            "easting": [345000, 350000],
            "northing": [6285000, 6290000],
            "rate": [-500, -300],
        }
    ).to_csv(path, index=False)
    return path


@pytest.fixture
def terrain(tmp_path: Path) -> Path:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "source" / "dem.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=40,
        width=50,
        count=1,
        dtype="float32",
        crs=UTM19S,
        transform=from_origin(338000, 6300000, 480, 500),
    ) as target:
        target.write(np.linspace(500, 2500, 50 * 40).reshape(40, 50).astype("float32"), 1)
    return path


def project(tmp_path: Path) -> Path:
    directory = tmp_path / "model.mup"
    directory.mkdir(exist_ok=True)
    return directory


# --- reading files ----------------------------------------------------------


def test_a_shapefile_reports_what_it_holds(catchment: Path, tmp_path: Path) -> None:
    imported = ingest.import_file(catchment, project(tmp_path), source_id="catchment")
    source = imported.source

    assert isinstance(source, VectorSource)
    assert source.geometry == "polygon"
    assert source.feature_count == 1
    assert source.crs == UTM19S
    assert "name" in source.fields
    assert imported.warnings == []


def test_a_shapefile_brings_its_sidecars(catchment: Path, tmp_path: Path) -> None:
    """A .shp without its .dbf is unreadable, so copying one file is not enough."""
    directory = project(tmp_path)
    ingest.import_file(catchment, directory, source_id="catchment")

    copied = {path.suffix for path in (directory / ingest.GIS_DIR).iterdir()}
    assert {".shp", ".shx", ".dbf"} <= copied


def test_a_zipped_shapefile_is_unpacked(catchment: Path, tmp_path: Path) -> None:
    """Which is how shapefiles are actually shared."""
    archive = tmp_path / "catchment.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for part in catchment.parent.glob("catchment.*"):
            bundle.write(part, part.name)

    imported = ingest.import_file(archive, project(tmp_path), source_id="catchment")

    assert isinstance(imported.source, VectorSource)
    assert imported.source.feature_count == 1


def test_a_zip_of_nothing_useful_says_so(tmp_path: Path) -> None:
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", "nothing here")

    with pytest.raises(ingest.ImportError_, match="holds no shapefile"):
        ingest.import_file(archive, project(tmp_path), source_id="x")


def test_a_csv_guesses_its_coordinate_columns(wells: Path, tmp_path: Path) -> None:
    """The usual names are few, and a wrong guess is visible immediately: the
    points land somewhere absurd."""
    imported = ingest.import_file(wells, project(tmp_path), source_id="wells", crs=UTM19S)
    source = imported.source

    assert isinstance(source, PointTableSource)
    assert (source.x_column, source.y_column) == ("easting", "northing")
    assert source.row_count == 2
    assert any("easting" in warning for warning in imported.warnings)


def test_a_csv_with_unguessable_columns_lists_what_it_has(tmp_path: Path) -> None:
    import pandas as pd

    path = tmp_path / "odd.csv"
    pd.DataFrame({"across": [1.0], "along": [2.0]}).to_csv(path, index=False)

    with pytest.raises(ingest.ImportError_, match="across, along"):
        ingest.import_file(path, project(tmp_path), source_id="odd")


def test_named_columns_beat_the_guess(tmp_path: Path) -> None:
    import pandas as pd

    path = tmp_path / "odd.csv"
    pd.DataFrame({"across": [345000.0], "along": [6285000.0]}).to_csv(path, index=False)

    imported = ingest.import_file(
        path,
        project(tmp_path),
        source_id="odd",
        x_column="across",
        y_column="along",
        crs=UTM19S,
    )

    assert isinstance(imported.source, PointTableSource)
    assert imported.source.x_column == "across"


def test_a_raster_reports_its_shape(terrain: Path, tmp_path: Path) -> None:
    imported = ingest.import_file(terrain, project(tmp_path), source_id="dem")
    source = imported.source

    assert isinstance(source, RasterSource)
    assert (source.width, source.height, source.band_count) == (50, 40, 1)
    assert source.crs == UTM19S


def test_a_file_it_does_not_read_says_what_it_does(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_bytes(b"nope")

    with pytest.raises(ingest.ImportError_, match=r"\.shp"):
        ingest.import_file(path, project(tmp_path), source_id="x")


def test_importing_a_file_already_in_the_project_does_not_copy_it_over_itself(
    catchment: Path, tmp_path: Path
) -> None:
    directory = project(tmp_path)
    first = ingest.import_file(catchment, directory, source_id="a")
    inside = directory / ingest.GIS_DIR / first.source.path

    again = ingest.import_file(inside, directory, source_id="b")

    assert again.source.path == first.source.path


# --- getting it onto a map --------------------------------------------------


def test_a_layer_comes_back_in_longitude_and_latitude(catchment: Path, tmp_path: Path) -> None:
    """The map draws in degrees; the model works in metres. Something has to
    convert, and doing it on the server means doing it once."""
    directory = project(tmp_path)
    source = ingest.import_file(catchment, directory, source_id="catchment").source

    geojson = preview.geojson_for(directory, source, project_crs=UTM19S)
    ring = geojson["features"][0]["geometry"]["coordinates"][0]

    # Santiago: about 70 degrees west, 33 degrees south.
    assert all(-71 < point[0] < -70 for point in ring)
    assert all(-34 < point[1] < -33 for point in ring)


def test_points_from_a_csv_become_real_geometry(wells: Path, tmp_path: Path) -> None:
    directory = project(tmp_path)
    source = ingest.import_file(wells, directory, source_id="wells", crs=UTM19S).source

    geojson = preview.geojson_for(directory, source, project_crs=UTM19S)

    assert len(geojson["features"]) == 2
    assert geojson["features"][0]["geometry"]["type"] == "Point"


def test_a_raster_is_shown_as_its_footprint(terrain: Path, tmp_path: Path) -> None:
    """The pixels are not sent. On this step the question is where it covers;
    reading values out of it belongs to the grid."""
    directory = project(tmp_path)
    source = ingest.import_file(terrain, directory, source_id="dem").source

    geojson = preview.geojson_for(directory, source, project_crs=UTM19S)

    assert len(geojson["features"]) == 1
    assert geojson["features"][0]["geometry"]["type"] == "Polygon"
    assert geojson["features"][0]["properties"]["width"] == 50


def test_a_layer_with_no_crs_anywhere_says_why_it_cannot_be_drawn(
    terrain: Path, tmp_path: Path
) -> None:
    directory = project(tmp_path)
    source = ingest.import_file(terrain, directory, source_id="dem").source
    stateless = source.model_copy(update={"crs": None})

    with pytest.raises(preview.PreviewError, match="no coordinate system"):
        preview.geojson_for(directory, stateless, project_crs=None)


def test_a_missing_file_is_reported_rather_than_crashing(
    catchment: Path, tmp_path: Path
) -> None:
    directory = project(tmp_path)
    source = ingest.import_file(catchment, directory, source_id="catchment").source
    (directory / ingest.GIS_DIR / source.path).unlink()

    with pytest.raises(preview.PreviewError, match="not in the project"):
        preview.geojson_for(directory, source, project_crs=UTM19S)


def test_the_extent_covers_everything_imported(
    catchment: Path, wells: Path, tmp_path: Path
) -> None:
    """So the map can open looking at the data rather than at the Atlantic."""
    directory = project(tmp_path)
    sources = [
        ingest.import_file(catchment, directory, source_id="catchment").source,
        ingest.import_file(wells, directory, source_id="wells", crs=UTM19S).source,
    ]

    west, south, east, north = preview.extent_of(sources, UTM19S)  # type: ignore[misc]

    assert -71 < west < east < -70
    assert -34 < south < north < -33


def test_the_extent_of_nothing_is_nothing(tmp_path: Path) -> None:
    assert preview.extent_of([], UTM19S) is None


def test_geometry_is_simplified_for_the_screen(tmp_path: Path) -> None:
    """A surveyed boundary carries vertices a pixel apart; a browser gains
    nothing from them and a large layer becomes slow to draw."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Polygon

    path = tmp_path / "source" / "detailed.shp"
    path.parent.mkdir(parents=True, exist_ok=True)
    angles = np.linspace(0, 2 * np.pi, 5000)
    ring = [(350000 + 10000 * np.cos(a), 6290000 + 10000 * np.sin(a)) for a in angles]
    gpd.GeoDataFrame({"n": [1]}, geometry=[Polygon(ring)], crs=UTM19S).to_file(path)

    directory = project(tmp_path)
    source = ingest.import_file(path, directory, source_id="detailed").source

    simplified = preview.geojson_for(directory, source, project_crs=UTM19S)
    whole = preview.geojson_for(directory, source, project_crs=UTM19S, simplify=False)

    kept = len(simplified["features"][0]["geometry"]["coordinates"][0])
    original = len(whole["features"][0]["geometry"]["coordinates"][0])
    assert kept < original


# --- the record of what a project holds -------------------------------------


def test_layers_cannot_share_an_id() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="share the id"):
        DataModel(
            sources=[
                VectorSource(id="a", path="a.shp"),
                VectorSource(id="a", path="b.shp"),
            ]
        )


def test_each_new_layer_gets_a_colour_of_its_own() -> None:
    """Two layers the same colour on a satellite basemap are one layer."""
    data = DataModel(sources=[VectorSource(id="a", path="a.shp", colour="#38bdf8")])

    assert data.next_colour() != "#38bdf8"


def test_a_layer_is_found_by_id_or_named_in_the_error() -> None:
    data = DataModel(sources=[VectorSource(id="a", path="a.shp")])

    assert data.source("a").path == "a.shp"
    with pytest.raises(KeyError, match="nope"):
        data.source("nope")


def test_a_project_carries_its_data_through_a_save(tmp_path: Path) -> None:
    from mupstudio.schema.project import Project
    from mupstudio.schema.templates import starter_column
    from mupstudio.store import projectstore

    base = starter_column("field", cells=5)
    with_data = Project.model_validate(
        {
            **base.model_dump(),
            "meta": {**base.meta.model_dump(), "crs": UTM19S},
            "data": DataModel(
                sources=[VectorSource(id="catchment", path="catchment.shp", crs=UTM19S)],
                basemap="esri-imagery",
            ).model_dump(),
        }
    )

    projectstore.save(tmp_path / "p.mup", with_data, touch_modified=False)
    loaded = projectstore.load(tmp_path / "p.mup")

    assert (tmp_path / "p.mup" / "data.toml").exists()
    assert loaded.data.basemap == "esri-imagery"
    assert loaded.data.source("catchment").crs == UTM19S
