import datetime
import json
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import requests
import yaml
from geopandas import read_file

from aip_airspace.airspace import make_airspace_gdf
from aip_airspace.license import license
from aip_airspace.loa import make_loa_gdf
from aip_airspace.loadaip import airac_date, fix_up
from aip_airspace.obstacle import make_obstacle_gdf
from aip_airspace.openair import make_openair, parse_openair
from aip_airspace.overlay import overlay
from aip_airspace.rat import make_rat_gdf
from aip_airspace.sporting import parse_sporting
from aip_airspace.util import next_airac_date


def airspace_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("geojson_filename")
    parser.add_argument("--aip_filename", help="local AIP xml file")
    parser.add_argument("--prev", action="store_true", help="use previous AIRAC date")
    parser.add_argument("--config_file", default="config.yaml")
    args = parser.parse_args()

    with open(args.config_file, "rt") as f:
        config = yaml.safe_load(f.read())

    if args.aip_filename:
        print("Loading AIP")
        tree = ET.parse(args.aip_filename)
        root = tree.getroot()
    else:
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


def aip_to_geojson(root: ET.Element, config, geojson_filename) -> None:
    aip_bytes = ET.tostring(root)

    # Data from AIP
    print("Loading data frames...")
    airspace_gdf = read_file(aip_bytes, layer="Airspace")
    rwy_centreline_pt_gdf = read_file(aip_bytes, layer="RunwayCentrelinePoint")
    rwy_dirn_df = read_file(aip_bytes, layer="RunwayDirection")
    air_traffic_control_df = read_file(aip_bytes, layer="AirTrafficControlService")
    air_traffic_management_df = read_file(
        aip_bytes, layer="AirTrafficManagementService"
    )
    info_service_df = read_file(aip_bytes, layer="InformationService")
    radio_comm_channel_df = read_file(aip_bytes, layer="RadioCommunicationChannel")

    # Coast data
    coast_gdf = read_file(config["files"]["coast"])

    # ILS runway centreline points
    with open(config["files"]["ils"]) as ils_file:
        ils_rwy_centreline_pt_ids = yaml.safe_load(ils_file)

    # MATZ configurations
    with open(config["files"]["matz"]) as matz_file:
        matz_data = yaml.safe_load(matz_file)

    # Sporting activities
    sporting_activity_gdf = read_file(config["files"]["sporting_activity"])

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

    # Use GeoJSON 2018
    airspace_gdf.to_file(
        Path(geojson_filename),
        driver="GeoJSON",
        RFC7946="YES",
        FOREIGN_MEMBERS_COLLECTION=json.dumps(
            {"airac_date": f"{airac_date(root)}", "license": license}
        ),
        ID_FIELD="id",
    )


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
    rat_gdf.to_file(
        Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES", ID_FIELD="id"
    )


def loa_to_geojson() -> None:
    parser = ArgumentParser()
    parser.add_argument("loa_filename")
    parser.add_argument("airspace_filename")
    parser.add_argument("geojson_filename")
    args = parser.parse_args()

    with open(args.loa_filename) as f:
        loa_list = yaml.safe_load(f.read())

    airspace_gdf = read_file(args.airspace_filename)

    loa_gdf = make_loa_gdf(loa_list, airspace_gdf)

    # Final validity check
    if loa_gdf.geometry.is_valid.all():
        print("Geometry Valid: OK")
    else:
        print("WARNING: Invalid geometry")

    # Use GeoJSON 2018
    loa_gdf.to_file(
        Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES", ID_FIELD="id"
    )


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
    gdf.to_file(
        Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES", ID_FIELD="id"
    )


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
    gdf.to_file(
        Path(args.geojson_filename), driver="GeoJSON", RFC7946="YES", ID_FIELD="id"
    )


def make_overlay() -> None:
    parser = ArgumentParser()
    parser.add_argument("airspace_filename")
    parser.add_argument(
        "output_filename", nargs="+", help="GeoJSON (.geojson) or OpenAir (.txt)"
    )
    parser.add_argument(
        "--max_alt", type=int, default=10400, help="maximum base altitude"
    )
    parser.add_argument(
        "--atzdz", action="store_true", help="add ATZ upper limits and DZ"
    )
    args = parser.parse_args()

    airspace_gdf = read_file(args.airspace_filename)

    gdf = overlay(airspace_gdf, args.max_alt, args.atzdz)

    for fname in args.output_filename:
        if Path(fname).suffix == ".geojson":
            # Use GeoJSON 2018
            gdf.to_file(Path(fname), driver="GeoJSON", RFC7946="YES")
        else:
            with open(args.airspace_filename) as f:
                airspace = json.load(f)

            oa = make_openair(gdf)
            with open(fname, "wt") as f:
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
