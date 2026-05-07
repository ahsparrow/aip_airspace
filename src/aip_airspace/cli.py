from aip_airspace.airspace import (
    airspace,
    add_frequency,
    override,
    override_ats,
    remove_excluded,
    remove_offshore,
)
from aip_airspace.ils import ils
from aip_airspace.loadaip import load
from aip_airspace.matz import matz

from argparse import ArgumentParser
from pathlib import Path

from geopandas import GeoDataFrame, read_file
from pandas import DataFrame, concat, merge
import yaml


def aip_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("aip_filename")
    parser.add_argument("geojson_filename")
    args = parser.parse_args()

    config = yaml.safe_load(open("config.yaml"))

    print("Load AIP")
    aip = load(args.aip_filename).encode()

    print("Load Airspace layer")
    airspace_gdf = read_file(aip, layer="Airspace")
    airspace_gdf.set_crs(epsg=4326, inplace=True)
    airspace_gdf.set_index("identifier", inplace=True)

    coast_gdf = read_file(config["files"]["coastline"])
    airspace_gdf = remove_offshore(airspace_gdf, coast_gdf)

    airspace_gdf = remove_excluded(airspace_gdf, config["exclude"])
    airspace_gdf = airspace(airspace_gdf)

    print("Load ATC Service layer")
    ats_df = read_file(aip, layer="AirTrafficControlService")

    # Service overrides
    ats_df = override_ats(ats_df, config["service_override"])

    # Get radio comms data
    print("Load Information Service layer")
    is_df = read_file(aip, layer="InformationService")

    print("Load Radio Communication Channel layer")
    rcc_df = read_file(aip, layer="RadioCommunicationChannel")

    # Add frequencies
    airspace_gdf = add_frequency(airspace_gdf, ats_df, is_df, rcc_df)

    # Get runway data for ILS
    print("Load Runway Centreline Point layer")
    rcp_gdf = read_file(aip, layer="RunwayCentrelinePoint")

    print("Load Runway Direction layer")
    rd_df = read_file(aip, layer="RunwayDirection")

    # Add ILS
    print("Add ILS")
    atz_gdf = airspace_gdf[airspace_gdf["stype"] == "ATZ"]
    with open(config["files"]["ils"]) as file:
        data = yaml.safe_load(file)
    ils_gdf = ils(data["runway_centre_points"], atz_gdf, rcp_gdf, rd_df)

    # Add MATZ
    print("Add MATZ")
    with open(config["files"]["matz"]) as matz_file:
        data = yaml.safe_load(matz_file)
    matz_gdf, channel_df = matz(data["matz"], airspace_gdf)

    # Set military ATZ channels
    airspace_gdf.update(channel_df)

    # Gliding sites (with 1 nm buffer)
    print("Add gliding sites")
    with open(config["files"]["gliding_site"]) as file:
        data = yaml.safe_load(file)

    gliding_gdf = GeoDataFrame.from_features(data)
    gliding_gdf.set_crs(epsg=4326, inplace=True)

    gliding_gdf.to_crs(epsg=27700, inplace=True)
    gliding_gdf.geometry = gliding_gdf.geometry.buffer(1852)
    gliding_gdf.to_crs(epsg=4326, inplace=True)

    merged_gdf = concat((airspace_gdf, ils_gdf, matz_gdf, gliding_gdf))

    # Override attributes
    override(merged_gdf, config["override"])

    # Fix up geometries and snap to 1 second grid
    merged_gdf.geometry = merged_gdf.geometry.make_valid()
    merged_gdf.geometry = merged_gdf.geometry.set_precision(grid_size=1 / 3600)

    # Discard any sliver polygons created by the fix up
    gdf = merged_gdf[merged_gdf.geometry.geom_type == "MultiPolygon"]
    gdf.geometry = gdf.geometry.apply(lambda g: max(g.geoms, key=lambda x: x.area))
    merged_gdf.update(gdf)

    # Reduce size of output file
    merged_gdf.geometry = merged_gdf.geometry.set_precision(grid_size=0.000001)

    # Final validity check
    if merged_gdf.geometry.is_valid.all():
        print("Geometry Valid: OK")
    else:
        print("WARNING: Invalid geometry")

    merged_gdf.to_file(Path(args.geojson_filename), driver="GeoJSON")
