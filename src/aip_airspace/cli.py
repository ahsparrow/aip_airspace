import datetime
import json
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import requests
from geopandas import read_file
import yaml

from aip_airspace.airspace import make_airspace_gdf
from aip_airspace.loa import make_loa_gdf
from aip_airspace.loadaip import fix_up, airac_date
from aip_airspace.obstacle import make_obstacle_gdf
from aip_airspace.openair import make_openair, parse_openair
from aip_airspace.overlay import overlay
from aip_airspace.sporting import parse_sporting
from aip_airspace.rat import make_rat_gdf
from aip_airspace.util import next_airac_date


def remote_aip() -> None:
    parser = ArgumentParser()
    parser.add_argument("geojson_filename")
    parser.add_argument("--prev", action="store_true", help="use previous AIRAC date")
    parser.add_argument("--config_file", default="config.yaml")
    args = parser.parse_args()

    with open(args.config_file, "rt") as f:
        config = yaml.safe_load(f.read())

    airac_date = next_airac_date()
    if args.prev:
        airac_date += datetime.timedelta(days=-28)
    airac_date_str = airac_date.strftime("%Y%m%d")

    # Download zip archive from NATS and extract AIP XML data
    url = f"https://nats-uk.ead-it.com/cms-nats/export/sites/default/en/Publications/digital-datasets/ICAO_AIP/EG_AIP_DS_{airac_date_str}_XML.zip"

    print("Downloading AIP dataset...")
    response = requests.get(url)
    response.raise_for_status()

    print("Extracting XML...")
    zip_data = BytesIO(response.content)
    with ZipFile(zip_data) as archive:
        xml_data = archive.read(f"EG_AIP_DS_FULL_{airac_date_str}.xml")

    root = ET.fromstring(xml_data)

    # Fix "issues" in XML
    fix_up(root)

    aip_to_geojson(root, config, args.geojson_filename)


def local_aip() -> None:
    parser = ArgumentParser()
    parser.add_argument("aip_filename")
    parser.add_argument("geojson_filename")
    parser.add_argument("--config_file", default="config.yaml")
    args = parser.parse_args()

    with open(args.config_file, "rt") as f:
        config = yaml.safe_load(f.read())

    print("Loading AIP")
    tree = ET.parse(args.aip_filename)
    root = tree.getroot()

    # Fix "problems" in raw XML data
    fix_up(root)

    aip_to_geojson(root, config, args.geojson_filename)


def aip_to_geojson(root: ET.Element, config, geojson_filename) -> None:
    aip_bytes = ET.tostring(root)

    # Data from AIP
    print("Loading data frames...")
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

    airspace_gdf.reset_index(inplace=True)
    geo_dict = airspace_gdf.to_geo_dict(drop_id=True)
    geo_dict["airac_date"] = airac_date(root)
    with open(geojson_filename, "wt") as f:
        json.dump(geo_dict, f)


def fixup_aip() -> None:
    parser = ArgumentParser()
    parser.add_argument("aip_filename")
    parser.add_argument("fixup_filename")
    args = parser.parse_args()

    # Parse the XML
    tree = ET.parse(args.aip_filename)
    root = tree.getroot()

    # Fix "problems" in raw XML data
    fix_up(root)

    tree.write(args.fixup_filename)


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

    # Use GeoJSON 2018
    rat_gdf.to_file(Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES")


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

    # Use GeoJSON 2018
    loa_gdf.to_file(Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES")


def sporting_to_geojson() -> None:
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

    # Use GeoJSON 2018
    gdf.to_file(Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES")


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

    # Use GeoJSON 2018
    gdf.to_file(Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES")


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
        # Use GeoJSON 2018
        gdf.to_file(Path(args.output_filename), driver="GeoJSON", RFC7946="YES")
    else:
        with open(args.airspace_filename) as f:
            airspace = json.load(f)

        oa = make_openair(gdf)
        with open(args.output_filename, "wt") as f:
            f.write(
                f"*\n* Altitude Overlay {args.max_alt}ALT{' ATZ/DZ' if args.atzdz else ''} ({airspace['airac_date']})\n*\n"
            )
            f.write(oa)


def openair_to_geojson():
    parser = ArgumentParser()
    parser.add_argument("openair_filename")
    parser.add_argument("geojson_filename")
    args = parser.parse_args()

    with open(args.openair_filename) as f:
        gdf = parse_openair(f.read())

    # Use GeoJSON 2018
    gdf.to_file(Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES")
