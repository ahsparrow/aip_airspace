from aip_airspace.airspace import assemble_airspace
from aip_airspace.loadaip import fix_up

from argparse import ArgumentParser
from pathlib import Path

from geopandas import GeoDataFrame, read_file
from pandas import concat
import yaml


def aip_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("aip_filename")
    parser.add_argument("geojson_filename")
    parser.add_argument("--config_file", default="config.yaml")
    args = parser.parse_args()

    with open(args.config_file, "rt") as f:
        config = yaml.safe_load(f.read())

    print("Load AIP")
    with open(args.aip_filename, "rt") as aip_file:
        aip_str = aip_file.read()

    # Fix "problems" in raw XML data
    aip_bytes = fix_up(aip_str).encode()

    # Data from AIP
    print("Load data frames")
    airspace_gdf = read_file(aip_bytes, layer="Airspace")
    rwy_centreline_pt_gdf = read_file(aip_bytes, layer="RunwayCentrelinePoint")
    air_traffic_service_df = read_file(aip_bytes, layer="AirTrafficControlService")
    info_service_df = read_file(aip_bytes, layer="InformationService")
    radio_comm_channel_df = read_file(aip_bytes, layer="RadioCommunicationChannel")
    rwy_dirn_df = read_file(aip_bytes, layer="RunwayDirection")

    # Coastline data
    coastline_gdf = read_file(config["files"]["coastline"])

    # ILS runway centreline points
    with open(config["files"]["ils"]) as ils_file:
        ils_rwy_centreline_pt_ids = yaml.safe_load(ils_file)

    # MATZ configurations
    with open(config["files"]["matz"]) as matz_file:
        matz_data = yaml.safe_load(matz_file)

    # Gliding site data
    with open(config["files"]["gliding_site"]) as gliding_file:
        gliding_data = yaml.safe_load(gliding_file)

    print("Processing...")
    airspace_gdf = assemble_airspace(
        airspace_gdf,
        rwy_centreline_pt_gdf,
        air_traffic_service_df,
        info_service_df,
        radio_comm_channel_df,
        rwy_dirn_df,
        coastline_gdf,
        config["exclude_ids"],
        config["service_overrides"],
        ils_rwy_centreline_pt_ids,
        matz_data,
        gliding_data,
        config["overrides"],
    )

    # Final validity check
    if airspace_gdf.geometry.is_valid.all():
        print("Geometry Valid: OK")
    else:
        print("WARNING: Invalid geometry")

    airspace_gdf.to_file(Path(args.geojson_filename), driver="GeoJSON")
