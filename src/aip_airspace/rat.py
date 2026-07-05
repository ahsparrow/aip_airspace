from geopandas import GeoDataFrame
from uuid import NAMESPACE_URL, uuid5

from aip_airspace.boundary import boundary_polygon
from aip_airspace.util import parse_level


def make_rat(rat: dict, geometry: dict) -> dict:
    upper = parse_level(geometry["upper"])
    lower = parse_level(geometry["lower"])

    return {
        "identifier": uuid5(NAMESPACE_URL, f"asselect.uk/rat/{geometry['name']}"),
        "rat_name": rat["name"],
        "name": geometry["name"],
        "atype": rat["type"],
        "classification": rat.get("class"),
        "upperLimit": upper["limit"],
        "upperLimit_uom": upper["uom"],
        "upperLimitReference": upper["reference"],
        "lowerLimit": lower["limit"],
        "lowerLimit_uom": lower["uom"],
        "lowerLimitReference": lower["reference"],
        "geometry": boundary_polygon(geometry["boundary"], resolution=15),
    }


def make_rat_gdf(rat_list: list[dict]) -> GeoDataFrame:
    data = [make_rat(rat, geometry) for rat in rat_list for geometry in rat["geometry"]]
    gdf = GeoDataFrame(data)
    gdf.set_crs(epsg=4326, inplace=True)
    gdf.geometry = gdf.geometry.set_precision(grid_size=0.000001)

    return gdf

