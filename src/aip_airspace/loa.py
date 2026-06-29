from typing import cast

from geopandas import GeoDataFrame
from pandas import concat

from aip_airspace.boundary import boundary_polygon
from aip_airspace.util import parse_level


def make_loa_add(loa: dict, feature: dict, volume: dict) -> dict:
    upper = parse_level(volume["upper"])
    lower = parse_level(volume["lower"])

    return {
        "loa_name": loa["name"],
        "name": volume.get("name", feature.get("name", loa["name"])),
        "atype:": feature["type"],
        "classification": feature.get("class"),
        "upperLimit": upper["limit"],
        "upperLimit_uom": upper["uom"],
        "upperLimitReference": upper["reference"],
        "lowerLimit": lower["limit"],
        "lowerLimit_uom": lower["uom"],
        "lowerLimitReference": lower["reference"],
        "geometry": boundary_polygon(volume["boundary"], resolution=15),
    }


def make_loa_replace(
    loa: dict, feature: dict, volume: dict, airspace_gdf: GeoDataFrame
) -> dict:
    upper = parse_level(volume["upper"])
    lower = parse_level(volume["lower"])

    airspace = airspace_gdf.loc[feature["aref"]]

    return {
        "loa_name": loa["name"],
        "aref": feature["aref"],
        "name": volume.get("name", feature.get("name", airspace["name"])),
        "atype:": airspace["atype"],
        "classification": airspace.get("classification"),
        "upperLimit": upper["limit"],
        "upperLimit_uom": upper["uom"],
        "upperLimitReference": upper["reference"],
        "lowerLimit": lower["limit"],
        "lowerLimit_uom": lower["uom"],
        "lowerLimitReference": lower["reference"],
        "geometry": boundary_polygon(volume["boundary"], resolution=15),
    }


def make_loa_gdf(loa_list: list[dict], airspace_gdf: GeoDataFrame) -> GeoDataFrame:
    data = [
        make_loa_add(loa, feature, volume)
        for loa in loa_list
        for feature in loa["add"]
        for volume in feature["geometry"]
    ]

    add_gdf = GeoDataFrame(data)
    add_gdf.set_crs(epsg=4326, inplace=True)

    data = [
        make_loa_replace(loa, feature, volume, airspace_gdf)
        for loa in loa_list
        for feature in loa["replace"]
        for volume in feature["geometry"]
    ]
    replace_gdf = GeoDataFrame(data)
    replace_gdf.set_crs(epsg=4326, inplace=True)

    merged_gdf = concat([add_gdf, replace_gdf])
    merged_gdf = cast(GeoDataFrame, merged_gdf)

    return merged_gdf
