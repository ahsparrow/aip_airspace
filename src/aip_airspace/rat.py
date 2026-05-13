from geopandas import GeoDataFrame

from aip_airspace.boundary import boundary_polygon
from aip_airspace.util import parse_level


def make_rat(rat: dict, geometry: dict) -> dict:
    upper = parse_level(geometry["upper"])
    lower = parse_level(geometry["lower"])

    return {
        "rat_name": rat["name"],
        "name": geometry.get("name", rat["name"]),
        "stype:": "P",
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

    return gdf
