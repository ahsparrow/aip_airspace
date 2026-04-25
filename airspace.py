import shapely
from geopandas import read_file, GeoDataFrame
from pandas import DataFrame, merge
from uuid import UUID

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


def add_frequency(
    as_gdf: GeoDataFrame,
    ats_gdf: GeoDataFrame,
    is_gdf: GeoDataFrame,
    rcc_gdf: GeoDataFrame,
) -> GeoDataFrame:
    as_gdf = as_gdf.set_index("identifier")
    rcc_gdf = rcc_gdf.set_index("identifier")

    # Emtpy dictionary of services
    service_dict = {
        k: v for k, v in zip(as_gdf.index, [[] for _ in range(len(as_gdf.index))])
    }

    # Loop over ATC services
    for _, row in ats_gdf.iterrows():
        if row.clientAirspace_href is not None:
            for href in row.clientAirspace_href:
                uuid = str(UUID(href))
                if uuid in as_gdf.index:
                    # Ignore class A and C
                    if len(set(as_gdf.loc[uuid].classification) & set(["A", "C"])) == 0:
                        service_dict[uuid].append(row)

    # Loop over Information services
    for _, row in is_gdf.iterrows():
        if row.clientAirspace_href is not None:
            for href in row.clientAirspace_href:
                uuid = str(UUID(href))
                if uuid in as_gdf.index:
                    service_dict[uuid].append(row)

    # Channel list
    channel = {
        k: v for k, v in zip(as_gdf.index, ["" for _ in range(len(as_gdf.index))])
    }
    call_sign = {
        k: v for k, v in zip(as_gdf.index, ["" for _ in range(len(as_gdf.index))])
    }

    # Find services for airspaces
    for uuid, services in service_dict.items():
        service = None
        if len(services) == 1:
            # Just one service
            service = services[0]
        elif len(services) > 1:
            asrvc = [s for s in services if "APPROACH" in str(s.callSign)]
            if len(asrvc) == 1:
                service = asrvc[0]
            elif len(asrvc) == 0:
                rsrvc = [s for s in services if "RADAR" in str(s.callSign)]
                if len(rsrvc) == 1:
                    service = rsrvc[0]
                elif len(rsrvc) > 1:
                    channel[uuid] = "Multiple RADAR"
                else:
                    channel[uuid] = "No APPROACH/RADAR"
            else:
                channel[uuid] = "Multiple APPROACH"

        # Get frequency for service
        if service is not None:
            href = service.radioCommunication_href
            if len(href) == 1:
                # Just one frequency
                channel[uuid] = str(
                    rcc_gdf.loc[str(UUID(href[0]))].frequencyTransmission
                )
                call_sign[uuid] = service.callSign[0]
            else:
                # More than one frequency
                channel[uuid] = "Multiple frequency"

    df = DataFrame.from_dict(channel, orient="index", columns=["channel"])
    gdf = merge(as_gdf, df, left_index=True, right_index=True)

    df = DataFrame.from_dict(call_sign, orient="index", columns=["call_sign"])
    gdf = merge(gdf, df, left_index=True, right_index=True)

    return gdf


if __name__ == "__main__":
    from loadaip import load_aip
    from pathlib import Path
    import geopandas

    print("Load AIP")
    aip = load_aip("data/EG_AIP_DS_FULL_20260416.xml")

    print("Load Airspace layer")
    airspace_gdf = read_file(aip, layer="Airspace")
    airspace_gdf.set_crs(epsg=4326, inplace=True)

    airspace_gdf = remove_offshore(airspace_gdf)
    airspace_gdf = airspace(airspace_gdf)

    print("Load ATC Service layer")
    ats_gdf = read_file(aip, layer="AirTrafficControlService")

    print("Load Information Service layer")
    is_gdf = read_file(aip, layer="InformationService")

    print("Load Radio Communication Channel layer")
    rcc_gdf = read_file(aip, layer="RadioCommunicationChannel")

    output_gdf = add_frequency(airspace_gdf, ats_gdf, is_gdf, rcc_gdf)

    output_gdf.to_file(Path("airspace.geojson"), driver="GeoJSON")
