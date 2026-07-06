from argparse import ArgumentParser
from pathlib import Path
import json

from geopandas import read_file
import yaml

from aip_airspace.airspace import make_airspace_gdf
from aip_airspace.loa import make_loa_gdf
from aip_airspace.loadaip import fix_up
from aip_airspace.obstacle import make_obstacle_gdf
from aip_airspace.openair import make_openair
from aip_airspace.overlay import overlay
from aip_airspace.sporting import parse_sporting
from aip_airspace.rat import make_rat_gdf


def aip_fixup() -> None:
    parser = ArgumentParser()
    parser.add_argument("aip_filename")
    parser.add_argument("fixup_filename")
    args = parser.parse_args()

    with open(args.aip_filename, "rt") as aip_file:
        aip_str = aip_file.read()

    # Fix "problems" in raw XML data
    aip_bytes, _ = fix_up(aip_str)

    with open(args.fixup_filename, "wb") as fixup_file:
        fixup_file.write(aip_bytes)


def aip_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("aip_filename")
    parser.add_argument("geojson_filename")
    parser.add_argument("--config_file", default="config.yaml")
    args = parser.parse_args()

    with open(args.config_file, "rt") as f:
        config = yaml.safe_load(f.read())

    print("Loading AIP")
    with open(args.aip_filename, "rt") as aip_file:
        aip_str = aip_file.read()

    # Fix "problems" in raw XML data
    aip_bytes, airac_date = fix_up(aip_str)

    # Data from AIP
    print("Loading data frames")
    airspace_gdf = read_file(aip_bytes, layer="Airspace")
    airspace_gdf.set_index("identifier", inplace=True)
    airspace_gdf.set_crs(epsg=4326, inplace=True)

    rwy_centreline_pt_gdf = read_file(aip_bytes, layer="RunwayCentrelinePoint")
    rwy_centreline_pt_gdf.set_crs(epsg=4326, inplace=True)
    rwy_centreline_pt_gdf.set_index("identifier", inplace=True)

    rwy_dirn_df = read_file(aip_bytes, layer="RunwayDirection")
    rwy_dirn_df.set_index("identifier", inplace=True)

    air_traffic_control_df = read_file(aip_bytes, layer="AirTrafficControlService")
    air_traffic_control_df.set_index("identifier", inplace=True)

    air_traffic_management_df = read_file(
        aip_bytes, layer="AirTrafficManagementService"
    )
    air_traffic_management_df.set_index("identifier", inplace=True)

    info_service_df = read_file(aip_bytes, layer="InformationService")
    info_service_df.set_index("identifier", inplace=True)

    radio_comm_channel_df = read_file(aip_bytes, layer="RadioCommunicationChannel")
    radio_comm_channel_df.set_index("identifier", inplace=True)

    # Coast data
    coast_gdf = read_file(config["files"]["coast"])
    coast_gdf.set_crs(epsg=4326, inplace=True)

    # ILS runway centreline points
    with open(config["files"]["ils"]) as ils_file:
        ils_rwy_centreline_pt_ids = yaml.safe_load(ils_file)

    # MATZ configurations
    with open(config["files"]["matz"]) as matz_file:
        matz_data = yaml.safe_load(matz_file)

    # Sporting activities
    sporting_activity_gdf = read_file(config["files"]["sporting_activity"])
    sporting_activity_gdf.set_crs(epsg=4326, inplace=True)
    sporting_activity_gdf.set_index("identifier", inplace=True)

    print("Making airspace")
    airspace_gdf = make_airspace_gdf(
        airspace_gdf,
        rwy_centreline_pt_gdf,
        air_traffic_control_df,
        air_traffic_management_df,
        info_service_df,
        radio_comm_channel_df,
        rwy_dirn_df,
        coast_gdf,
        config["exclude_ids"],
        config["service_overrides"],
        ils_rwy_centreline_pt_ids,
        matz_data,
        sporting_activity_gdf,
        config["overrides"],
    )

    # Final validity check
    if airspace_gdf.geometry.is_valid.all():
        print("Geometry Valid: OK")
    else:
        print("WARNING: Invalid geometry")
    airspace_gdf.to_file(Path("foo.geojson"), driver="GeoJSON")

    airspace_gdf.reset_index(inplace=True)
    geo_dict = airspace_gdf.to_geo_dict(drop_id=True)
    geo_dict["airac_date"] = airac_date
    with open(args.geojson_filename, "wt") as f:
        json.dump(geo_dict, f)


def rat_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("rat_filename")
    parser.add_argument("geojson_filename")
    args = parser.parse_args()

    with open(args.rat_filename) as f:
        rat_list = yaml.safe_load(f.read())

    rat_gdf = make_rat_gdf(rat_list)

    # Final validity check
    if rat_gdf.geometry.is_valid.all():
        print("Geometry Valid: OK")
    else:
        print("WARNING: Invalid geometry")

    rat_gdf.to_file(Path(args.geojson_filename), driver="GeoJSON")


def loa_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("loa_filename")
    parser.add_argument("airspace_filename")
    parser.add_argument("geojson_filename")
    args = parser.parse_args()

    with open(args.loa_filename) as f:
        loa_list = yaml.safe_load(f.read())

    airspace_gdf = read_file(args.airspace_filename)
    airspace_gdf.set_index("identifier", inplace=True)

    loa_gdf = make_loa_gdf(loa_list, airspace_gdf)

    # Final validity check
    if loa_gdf.geometry.is_valid.all():
        print("Geometry Valid: OK")
    else:
        print("WARNING: Invalid geometry")

    loa_gdf.to_file(Path(args.geojson_filename), driver="GeoJSON")


def sporting_to_geojson() -> None:
    import datetime
    import requests

    parser = ArgumentParser()
    parser.add_argument("geojson_filename")
    parser.add_argument("--prev", action="store_true", help="use previous AIRAC date")
    args = parser.parse_args()

    airac_date = datetime.date(2026, 5, 14)
    today = datetime.date.today()
    while airac_date < today:
        airac_date += datetime.timedelta(days=28)

    if args.prev:
        airac_date += datetime.timedelta(days=-28)

    url = f"https://www.aurora.nats.co.uk/htmlAIP/Publications/{airac_date.isoformat()}-AIRAC/html/eAIP/EG-ENR-5.5-en-GB.html#ENR-5.5"
    request = requests.get(url)

    gdf = parse_sporting(request.content)

    gdf.to_file(Path(args.geojson_filename), driver="GeoJSON")


def obstacle_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("obstacle_filename")
    parser.add_argument("airspace_filename")
    parser.add_argument("geojson_filename")
    parser.add_argument("--config_file", default="config.yaml")
    args = parser.parse_args()

    with open(args.config_file, "rt") as f:
        config = yaml.safe_load(f.read())

    obstacle_gdf = read_file(args.obstacle_filename, layer="VerticalStructure")
    airspace_gdf = read_file(args.airspace_filename)
    coast_gdf = read_file(config["files"]["coast"])

    gdf = make_obstacle_gdf(obstacle_gdf, airspace_gdf, coast_gdf)
    gdf.to_file(Path(args.geojson_filename), driver="GeoJSON")


def make_overlay() -> None:
    parser = ArgumentParser()
    parser.add_argument("airspace_filename")
    parser.add_argument("output_filename", help="GeoJSON (.geojson) or OpenAir (.txt)")
    parser.add_argument(
        "--max_alt", type=int, default=10400, help="maximum base altitude"
    )
    parser.add_argument(
        "--atzdz", action="store_true", help="add ATZ upper limits and DZ"
    )
    args = parser.parse_args()

    airspace_gdf = read_file(args.airspace_filename)

    gdf = overlay(airspace_gdf, args.max_alt, args.atzdz)

    if Path(args.output_filename).suffix == ".geojson":
        gdf.to_file(Path(args.output_filename), driver="GeoJSON")
    else:
        with open(args.airspace_filename) as f:
            airspace = json.load(f)

        oa = make_openair(gdf)
        with open(args.output_filename, "wt") as f:
            f.write(
                f"*\n* Height Overlay {args.max_alt}ALT{' ATZ/DZ' if args.atzdz else ''} ({airspace['airac_date']})\n*\n"
            )
            f.write(oa)
