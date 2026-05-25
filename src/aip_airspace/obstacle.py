from geopandas import GeoDataFrame
from shapely import MultiPolygon

KEEP_COLUMNS = ["identifier", "type", "elevation", "elevation_uom", "geometry"]


def make_obstacle_gdf(
    obstacle_gdf: GeoDataFrame, airspace_gdf: GeoDataFrame, coast_gdf: GeoDataFrame
) -> GeoDataFrame:
    # Swap lat/long and set CRS
    obstacle_gdf.geometry = obstacle_gdf.affine_transform([0, 1, 1, 0, 0, 0])
    obstacle_gdf.set_crs(epsg=4326, inplace=True)

    # Filter by vertical extent
    obstacle_gdf = obstacle_gdf[obstacle_gdf.verticalExtent > 600]

    # Filter on-shore only
    coast_gdf.to_crs(epsg=32630, inplace=True)
    coast_gdf.geometry = coast_gdf.buffer(100)
    coast_gdf.to_crs(epsg=4326, inplace=True)
    coast_gdf.set_index("name", inplace=True)
    gdf = obstacle_gdf[obstacle_gdf.within(coast_gdf.loc["uk_coast", "geometry"])]

    # Filter low airspace
    a = MultiPolygon(
        airspace_gdf[
            (airspace_gdf.stype == "CTR")
            | (
                ((airspace_gdf.stype == "CTA") | (airspace_gdf.stype == "TMA"))
                & (
                    (airspace_gdf.lowerLimitReference == "MSL")
                    & (airspace_gdf.lowerLimit < 2000)
                )
            )
        ].geometry
    )
    gdf = gdf[~gdf.within(a)]

    # Delete unused columns
    gdf.drop(columns=[c for c in gdf.columns if c not in KEEP_COLUMNS], inplace=True)
    gdf.rename(
        {"type": "name", "elevation": "upperLimit", "elevation_uom": "upperLimit_uom"},
        axis=1,
        inplace=True,
    )
    gdf["upperLimitReference"] = "MSL"
    gdf["lowerLimit"] = 0
    gdf["lowerLimit_uom"] = "FT"
    gdf["lowerLimitReference"] = "SFC"
    gdf["stype"] = "OBST"

    return gdf
