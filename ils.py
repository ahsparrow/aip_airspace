from geopandas import GeoDataFrame
from math import sin, cos
from shapely import Polygon
from shapely.affinity import rotate, translate
from uuid import UUID


def ils(runway_centrepoint_refs, atz_gdf, runway_centrepoint_gdf, runway_dirn_df):
    # Set runway centre point index
    rcp_gdf = runway_centrepoint_gdf.set_index("identifier")

    # Filter and convert to cartesian geometry
    rcp_gdf = rcp_gdf.loc[runway_centrepoint_refs]
    rcp_gdf.to_crs(epsg=27700, inplace=True)

    # Set runway direction index
    rd_df = runway_dirn_df.set_index("identifier")

    # Convert ATZ to cartesian geometry
    atz_gdf = atz_gdf.to_crs(epsg=27700)

    # Calculate ATZ centre and size, and set centre as geometry
    atz_gdf["centroid"] = atz_gdf.geometry.centroid
    atz_gdf.set_geometry(atz_gdf.geometry.centroid)
    atz_gdf["radius"] = atz_gdf.geometry.minimum_bounding_radius()

    # Get nearast ATZ for each runway centrepoint
    atc_rcp_gdf = rcp_gdf.sjoin_nearest(atz_gdf, how="left")

    ils_data = {"name": [], "upperLimit": [], "lowerLimit": [], "geometry": []}
    for _, atc_rcp in atc_rcp_gdf.iterrows():
        atz_radius = atc_rcp["radius"]
        x1 = atz_radius * sin(0.05)
        y1 = atz_radius * cos(0.05)
        x2 = 8 * 1852 * sin(0.05)
        y2 = 8 * 1852 * cos(0.05)

        rd = rd_df.loc[str(UUID(atc_rcp.onRunway_href))]
        bearing = float(rd.trueBearing)

        # Calculate ILS feathers
        ils_poly = Polygon(
            ((-x1, y1), (-x2, y2), (0, y2 - 1000), (x2, y2), (x1, y1), (-x1, y1))
        )
        ils_poly = rotate(ils_poly, -bearing + 180, origin=(0, 0))
        ils_poly = translate(ils_poly, atc_rcp.centroid.x, atc_rcp.centroid.y)

        # ILS data
        ils_data["geometry"].append(ils_poly)
        ils_data["name"].append(atc_rcp["name"].replace("ATZ", "ILS"))
        ils_data["upperLimit"].append(atc_rcp.upperLimit)
        ils_data["lowerLimit"].append(atc_rcp.upperLimit - 1000)

    # Build ILS GeoDataFrame
    ils_gdf = GeoDataFrame(ils_data, crs="EPSG:27700")
    ils_gdf.to_crs(epsg=4326, inplace=True)

    ils_gdf = ils_gdf.assign(stype="ILS")
    ils_gdf = ils_gdf.assign(upperLimit_uom="FT")
    ils_gdf = ils_gdf.assign(upperLimitReference="MSL")
    ils_gdf = ils_gdf.assign(lowerLimit_uom="FT")
    ils_gdf = ils_gdf.assign(lowerLimitReference="MSL")

    return ils_gdf
