from geopandas import read_file, GeoDataFrame

KEEP_COLUMNS = [
    "gml_id",
    "identifier",
    "name",
    "classification",
    "upperLimit",
    "upperLimit_uom",
    "upperLimitReference",
    "lowerLimit",
    "lowerLimit_uom",
    "lowerLimitReference",
    "geometry",
    "stype",
]


def simple_type(row):
    if row["type"] in ["CTA", "CTR", "TMA", "D", "P"]:
        return row["type"]
    elif row["type"] == "R" and row["timeSlice|AirspaceTimeSlice|localType"] not in [
        "RPZ",
        "FRZ",
    ]:
        return "R"
    elif row["timeSlice|AirspaceTimeSlice|localType"] == "ATZ":
        return "ATZ"
    elif row["timeSlice|AirspaceTimeSlice|localType"] == "RMZ":
        return "RMZ"
    elif row["timeSlice|AirspaceTimeSlice|localType"] == "TMZ":
        return "TMZ"
    elif row["timeSlice|AirspaceTimeSlice|localType"] == "TRAG":
        return "TRAG"
    elif row["activity"] == "PARACHUTE":
        return "DZ"
    elif row["activity"] == "LASER":
        return "LASER"
    elif row["activity"] == "HI_RADIO":
        return "HIRTA"
    elif row["activity"] == "GAS":
        return "GVS"
    elif row["name"].startswith("NSGA"):
        return "NSGA"
    else:
        return None


def remove_offshore(gdf, buffer=10000):
    coast = geopandas.read_file("coast.geojson")
    coast.to_crs(epsg=27700, inplace=True)
    coast["geometry"] = coast.buffer(buffer)
    coast.to_crs(epsg=4326, inplace=True)

    mp = shapely.MultiPolygon(coast.geometry)

    return gdf[gdf.overlaps(mp) | gdf.within(mp)]


def airspace(as_gdf: GeoDataFrame) -> GeoDataFrame:
    as_gdf["stype"] = as_gdf.apply(simple_type, axis=1)

    # Drop unknown types
    gdf = as_gdf.dropna(subset=["stype"])

    # Drop above FL195 (except TRAG)
    gdf = gdf[
        (gdf.lowerLimit_uom != "FL") | (gdf.lowerLimit < 195) | (gdf.stype == "TRAG")
    ]

    # Remove anything wholely inside a CTR
    ctr_poly = shapely.MultiPolygon(gdf[gdf["stype"] == "CTR"].geometry)
    gdf = gdf[~gdf.within(ctr_poly) | (gdf["stype"] == "CTR")]

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
