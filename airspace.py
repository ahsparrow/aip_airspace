from shapely import MultiPolygon, Point
from geopandas import read_file, GeoDataFrame
from pandas import DataFrame, concat, merge
from uuid import UUID

KEEP_COLUMNS = [
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
    coast = geopandas.read_file("assets/coast.geojson")
    coast.to_crs(epsg=27700, inplace=True)
    coast["geometry"] = coast.buffer(buffer)
    coast.to_crs(epsg=4326, inplace=True)

    mp = MultiPolygon(coast.geometry)

    return gdf[gdf.overlaps(mp) | gdf.within(mp)]


def remove_excluded(gdf, exclude):
    return gdf.loc[gdf.index.difference(exclude)]


def extras(extra_list):
    data = []
    for e in extra_list:
        data.append(
            {
                "name": e["name"],
                "stype": e["stype"],
                "upperLimit": e["upper_ft"],
                "upperLimit_uom": "FT",
                "upperLimitReference": "MSL",
                "lowerLimit": 0,
                "lowerLimit_uom": "FT",
                "lowerLimitReference": "SFC",
                "geometry": Point(e["centre"][0], e["centre"][1]),
            }
        )

    gdf = GeoDataFrame(DataFrame(data), crs="EPSG:4326")
    gdf.to_crs(epsg=27700, inplace=True)

    gdf.geometry = gdf.geometry.buffer([e["radius_nm"] * 1852 for e in extra_list])

    return gdf.to_crs(epsg=4326)


def airspace(as_gdf: GeoDataFrame) -> GeoDataFrame:
    as_gdf["stype"] = as_gdf.apply(simple_type, axis=1)

    # Drop unknown types
    gdf = as_gdf.dropna(subset=["stype"])

    # Drop above FL195 (except TRAG)
    gdf = gdf[
        (gdf.lowerLimit_uom != "FL") | (gdf.lowerLimit < 195) | (gdf.stype == "TRAG")
    ]

    # Remove anything wholely inside a CTR
    ctr_poly = MultiPolygon(gdf[gdf["stype"] == "CTR"].geometry)
    gdf = gdf[~gdf.within(ctr_poly) | (gdf["stype"] == "CTR")]

    # Remove unused columns
    gdf.drop(columns=[c for c in gdf.columns if c not in KEEP_COLUMNS], inplace=True)

    return gdf


# Override callsign/frequency in ATC service
def override_ats(ats_df, override):
    ats_df = ats_df.set_index("identifier")

    for svc in override:
        ats_df.loc[svc["identifier"], "callSign"] = [svc["callsign"]]
        ats_df.loc[svc["identifier"], "radioCommunication_href"] = [svc["rcc_href"]]

    return ats_df


def add_frequency(
    as_gdf: GeoDataFrame,
    ats_df: GeoDataFrame,
    is_df: GeoDataFrame,
    rcc_df: GeoDataFrame,
) -> GeoDataFrame:
    rcc_df = rcc_df.set_index("identifier")

    # list of services for each airspace
    service_dict = {
        k: v for k, v in zip(as_gdf.index, [[] for _ in range(len(as_gdf.index))])
    }

    # channels and call signs for each airspace
    channel = {
        k: v for k, v in zip(as_gdf.index, ["" for _ in range(len(as_gdf.index))])
    }
    callsign = {
        k: v for k, v in zip(as_gdf.index, ["" for _ in range(len(as_gdf.index))])
    }

    # loop over ATC services
    for _, row in ats_df.iterrows():
        if row.clientAirspace_href is not None:
            for href in row.clientAirspace_href:
                uuid = str(UUID(href))

                # check client airspace exists
                if uuid in as_gdf.index:
                    # check missing callsign
                    if row.callSign is not None:
                        # Ignore class A and C
                        if not set(as_gdf.loc[uuid].classification) & {"A", "C"}:
                            # check unambiguous call sign <-> frequency
                            if len(row.callSign) == len(row.radioCommunication_href):
                                service_dict[uuid].append(row)
                            else:
                                callsign[uuid] = "Ambiguous callsign/frequency"
                    else:
                        callsign[uuid] = "Missing callsign"

    # loop over Information services
    for _, row in is_df.iterrows():
        if row.clientAirspace_href is not None:
            for href in row.clientAirspace_href:
                uuid = str(UUID(href))
                if uuid in as_gdf.index:
                    service_dict[uuid].append(row)

    # for each airspace
    for uuid, services in service_dict.items():
        # build flat callsign list
        csign = []
        for n_svc, svc in enumerate(services):
            for n_cs, cs in enumerate(svc.callSign):
                csign.append((n_svc, n_cs, cs))

        # check services names in order of preference
        for svc in ["APPROACH", "RADAR", "INFORMATION", "RADIO"]:
            if callsign[uuid] != "":
                break

            for n_svc, n_cs, cs in csign:
                if cs.endswith(svc):
                    href = services[n_svc].radioCommunication_href[n_cs]
                    rcc_uuid = str(UUID(href))
                    freq = rcc_df.loc[rcc_uuid].frequencyTransmission

                    callsign[uuid] = cs
                    channel[uuid] = freq
                    break

    df = DataFrame.from_dict(channel, orient="index", columns=["channel"])
    gdf = merge(as_gdf, df, left_index=True, right_index=True)

    df = DataFrame.from_dict(callsign, orient="index", columns=["callsign"])
    gdf = merge(gdf, df, left_index=True, right_index=True)

    return gdf


if __name__ == "__main__":
    from gliding import gliding_sites
    from ils import ils
    from loadaip import load_aip
    from matz import matz
    from pathlib import Path
    import argparse
    import geopandas
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("aip_filename")
    parser.add_argument("geojson_filename")
    args = parser.parse_args()

    config = yaml.safe_load(open("config.yaml"))

    print("Load AIP")
    aip = load_aip(args.aip_filename)

    print("Load Airspace layer")
    airspace_gdf = read_file(aip, layer="Airspace")
    airspace_gdf.set_crs(epsg=4326, inplace=True)
    airspace_gdf.set_index("identifier", inplace=True)

    airspace_gdf = remove_offshore(airspace_gdf)
    airspace_gdf = remove_excluded(airspace_gdf, config["exclude"])
    airspace_gdf = airspace(airspace_gdf)

    print("Load ATC Service layer")
    ats_df = read_file(aip, layer="AirTrafficControlService")

    # Service overrides
    ats_df = override_ats(ats_df, config["service"])

    print("Load Information Service layer")
    is_df = read_file(aip, layer="InformationService")

    print("Load Radio Communication Channel layer")
    rcc_df = read_file(aip, layer="RadioCommunicationChannel")

    # Add frequencies
    airspace_gdf = add_frequency(airspace_gdf, ats_df, is_df, rcc_df)

    print("Load Runway Centreline Point layer")
    rcp_gdf = read_file(aip, layer="RunwayCentrelinePoint")

    print("Load Runway Direction layer")
    rd_df = read_file(aip, layer="RunwayDirection")

    # Add ILS
    print("Add ILS")
    atz_gdf = airspace_gdf[airspace_gdf["stype"] == "ATZ"]
    ils_gdf = ils(config["ils_rcp"], atz_gdf, rcp_gdf, rd_df)

    # Add MATZ
    print("Add MATZ")
    with open("assets/matz.yaml") as matz_file:
        data = yaml.safe_load(matz_file)
    matz_gdf = matz(data["matz"], airspace_gdf)

    # Gliding sites (with 1 nm buffer)
    print("Add gliding sites")
    with open("assets/gliding.yaml") as gliding_file:
        data = yaml.safe_load(gliding_file)
    gliding_gdf = gliding_sites(data)
    gliding_gdf.to_crs(epsg=27700, inplace=True)
    gliding_gdf.geometry = gliding_gdf.geometry.buffer(1852)
    gliding_gdf.to_crs(epsg=4326, inplace=True)

    output_gdf = concat((airspace_gdf, ils_gdf, matz_gdf, gliding_gdf))

    # Reduce output file size
    output_gdf.geometry = output_gdf.geometry.make_valid()
    output_gdf.geometry = output_gdf.geometry.set_precision(grid_size=0.000001)

    output_gdf.to_file(Path(args.geojson_filename), driver="GeoJSON")
