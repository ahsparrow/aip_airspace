from geopandas import read_file, GeoDataFrame

KEEP_COLUMNS = [
    "geometry",
    "astype",
    "gml_id",
    "identifier",
    "type",
    "name",
    "classification",
    "upperLimit",
    "upperLimit_uom",
    "upperLimitReference",
    "lowerLimit",
    "lowerLimit_uom",
    "lowerLimitReference",
]


def as_type(row):
    if row["type"] in ["CTA", "CTR", "TMA", "D"]:
        return row["type"]
    elif row["timeSlice|AirspaceTimeSlice|localType"] == "ATZ":
        return "ATZ"
    elif row["activity"] == "PARACHUTE":
        return "DZ"
    else:
        return None


def remove_offshore(gdf, buffer=20000):
    coast = geopandas.read_file("coast.geojson")
    coast.to_crs(epsg=27700, inplace=True)
    coast["geometry"] = coast.buffer(buffer)
    coast.to_crs(epsg=4326, inplace=True)

    mp = shapely.MultiPolygon(coast.geometry)

    return gdf[gdf.overlaps(mp) | gdf.within(mp)]


def airspace(as_gdf: GeoDataFrame) -> GeoDataFrame:
    as_gdf["astype"] = as_gdf.apply(as_type, axis=1)

    # Drop unknown types
    gdf = as_gdf.dropna(subset=["astype"])

    # Drop above FL195
    gdf = gdf[(gdf["lowerLimit_uom"] != "FL") | (gdf["lowerLimit"] < 195)]

    # Remove unused columns
    gdf.drop(columns=[c for c in gdf.columns if c not in KEEP_COLUMNS], inplace=True)

    return gdf


if __name__ == "__main__":
    from loadaip import load_aip
    from pathlib import Path
    import geopandas
    import shapely

    aip = load_aip("data/EG_AIP_DS_FULL_20260416.xml")

    gdf = read_file(aip, layer="Airspace")
    gdf.set_crs(epsg=4326, inplace=True)

    gdf = remove_offshore(gdf)

    as_gdf = airspace(gdf)
    as_gdf.to_file(Path("airspace.geojson"), driver="GeoJSON")
