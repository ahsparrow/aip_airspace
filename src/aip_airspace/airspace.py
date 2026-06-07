from typing import cast

from shapely import MultiPolygon
from geopandas import GeoDataFrame
from pandas import DataFrame, Series, StringDtype, concat
from uuid import UUID

from aip_airspace.ils import calculate_ils
from aip_airspace.matz import create_matz

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


def simple_type(row: Series) -> str | None:
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


def rename(row: Series) -> str:
    if row.stype in ["D", "P", "R"]:
        return f"{row.designator[2:]} {row['name']}"
    else:
        return row["name"]


def remove_offshore(
    gdf: GeoDataFrame, coast_gdf: GeoDataFrame, buffer: int = 10000
) -> GeoDataFrame:
    coast_gdf.to_crs(epsg=32630, inplace=True)
    coast_gdf.geometry = coast_gdf.buffer(buffer)
    coast_gdf.to_crs(epsg=4326, inplace=True)

    geom = coast_gdf.unary_union
    return gdf[gdf.overlaps(geom) | gdf.within(geom)]


def remove_excluded(gdf: GeoDataFrame, exclude: list[str]) -> GeoDataFrame:
    return gdf.loc[gdf.index.difference(exclude)]


def asselect_airspace(as_gdf: GeoDataFrame) -> GeoDataFrame:
    as_gdf["stype"] = as_gdf.apply(simple_type, axis=1)

    # Drop unknown types
    gdf = as_gdf.dropna(subset=["stype"])

    # Drop above FL195 (except TRAG)
    gdf = gdf[
        (gdf.lowerLimit_uom != "FL") | (gdf.lowerLimit < 195) | (gdf.stype == "TRAG")
    ]

    # Remove anything wholly inside a CTR
    ctr_poly = MultiPolygon(gdf[gdf["stype"] == "CTR"].geometry)
    gdf = gdf[~gdf.within(ctr_poly) | (gdf["stype"] == "CTR")]

    # Rename danger, prohibited and restricted areas
    gdf["name"] = gdf.apply(rename, axis=1)

    # Remove unused columns
    gdf.drop(columns=[c for c in gdf.columns if c not in KEEP_COLUMNS], inplace=True)

    # Convert classification from array to scalar
    gc = gdf["classification"]
    gc[gc.notna()] = gc[gc.notna()].apply(lambda x: x[0])

    # Remove ATZ classification and all class G
    gc[gdf["stype"] == "ATZ"] = None
    gc[gc == "G"] = None

    gdf["classification"] = gc.astype(str)

    # Remove CTAs and CTRs duplicated by TMZs
    gdf.sort_values(by="stype", inplace=True)
    out_gdf = gdf[
        ~(
            (gdf[["geometry", "upperLimit", "lowerLimit"]].duplicated(keep="last"))
            & ((gdf["stype"] == "CTA") | (gdf["stype"] == "CTR"))
        )
    ]

    return out_gdf


# Override callsign/frequency in ATC service
def override_ats(ats_df: DataFrame, override: list[dict]) -> DataFrame:
    ats_df = ats_df.set_index("identifier")

    for svc in override:
        ats_df.loc[svc["identifier"], "callSign"] = [svc["callsign"]]
        ats_df.loc[svc["identifier"], "radioCommunication_href"] = [svc["rcc_href"]]

    return ats_df


def get_services(df: DataFrame, uuid_services: dict):
    # Ignore services without client airspace, call sign and radio comms
    for _, row in df[
        df.clientAirspace_href.notna()
        & df.callSign.notna()
        & df.radioCommunication_href.notna()
    ].iterrows():
        for href in row.clientAirspace_href:
            uuid = str(UUID(href))

            # Call sign and radio comms can be either string or array of strings
            callsign = (
                [row.callSign]
                if type(df.dtypes.callSign) is StringDtype
                else row.callSign
            )
            rc_href = (
                [row.radioCommunication_href]
                if type(df.dtypes.radioCommunication_href) is StringDtype
                else row.radioCommunication_href
            )

            # Ignore services without 1:1 call sign/radio channel
            if len(callsign) == len(rc_href):
                uuid_services[uuid] = uuid_services.get(uuid, []) + [
                    {"callsign": callsign, "rc_href": rc_href}
                ]


def add_frequency(
    as_gdf: GeoDataFrame,
    atc_df: DataFrame,
    atm_df: DataFrame,
    is_df: DataFrame,
    rcc_df: DataFrame,
) -> GeoDataFrame:
    rcc_df = rcc_df.set_index("identifier")

    # Get service information from various data frames
    uuid_services = {}
    get_services(atc_df, uuid_services)
    get_services(atm_df, uuid_services)
    get_services(is_df, uuid_services)

    channel = {}
    callsign = {}

    # for each airspace
    for uuid, services in uuid_services.items():
        if uuid in as_gdf.index and as_gdf.loc[uuid].classification not in ["A", "C"]:
            # build flat callsign list
            csign = []
            for n_svc, svc in enumerate(services):
                for n_cs, cs in enumerate(svc["callsign"]):
                    csign.append((n_svc, n_cs, cs))

            # check services names in order of preference
            for svc in ["APPROACH", "RADAR", "INFORMATION", "RADIO"]:
                for n_svc, n_cs, cs in csign:
                    if cs.endswith(svc):
                        href = services[n_svc]["rc_href"][n_cs]
                        rcc_uuid = str(UUID(href))
                        freq = f"{rcc_df.loc[rcc_uuid].frequencyTransmission:.3f}"

                        callsign[uuid] = cs
                        channel[uuid] = freq
                        break

    df = DataFrame.from_dict(channel, orient="index", columns=["channel"])
    gdf = as_gdf.merge(df, how="left", left_index=True, right_index=True)

    df = DataFrame.from_dict(callsign, orient="index", columns=["callsign"])
    gdf = gdf.merge(df, how="left", left_index=True, right_index=True)

    return gdf  # type: ignore


def override(airspace_gdf: GeoDataFrame, overrides: list[dict]):
    for o in overrides:
        df = DataFrame({k: [o[k]] for k in o})
        df.set_index("identifier", inplace=True)
        airspace_gdf.update(df)


def make_airspace_gdf(
    airspace_gdf: GeoDataFrame,
    rwy_centreline_pt_gdf: GeoDataFrame,
    air_traffic_control_df: DataFrame,
    air_traffic_management_df: DataFrame,
    info_service_df: DataFrame,
    radio_comm_channel_df: DataFrame,
    rwy_dirn_df: DataFrame,
    coast_gdf: GeoDataFrame,
    exclude_ids: list[str],
    service_overrides: list[dict],
    ils_rwy_centreline_pt_ids: list[str],
    matz_data: list[dict],
    sporting_activity_gdf: GeoDataFrame,
    override_data: list[dict],
) -> GeoDataFrame:
    # Set CRS and set AIXM identifier as index
    airspace_gdf.set_crs(epsg=4326, inplace=True)
    airspace_gdf.set_index("identifier", inplace=True)

    # Remove offshore airspace
    airspace_gdf = remove_offshore(airspace_gdf, coast_gdf)

    # Remove other excluded airspace
    airspace_gdf = remove_excluded(airspace_gdf, exclude_ids)

    # Adjust for airspace for ASSelect
    airspace_gdf = asselect_airspace(airspace_gdf)

    # Service overrides
    atc_df = override_ats(air_traffic_control_df, service_overrides)
    atm_df = override_ats(air_traffic_management_df, service_overrides)

    # Add frequencies
    airspace_gdf = add_frequency(
        airspace_gdf, atc_df, atm_df, info_service_df, radio_comm_channel_df
    )

    # Calculate ILS feathers
    atz_gdf = airspace_gdf[airspace_gdf["stype"] == "ATZ"]
    ils_gdf = calculate_ils(
        ils_rwy_centreline_pt_ids, atz_gdf, rwy_centreline_pt_gdf, rwy_dirn_df
    )

    # Calculate MATZ's and get military ATZ frequencies
    matz_gdf = create_matz(matz_data, airspace_gdf)

    # Sporting activities (with 1 nm buffer)
    sporting_activity_gdf.set_index("identifier", inplace=True)
    sporting_activity_gdf.to_crs(epsg=32630, inplace=True)
    sporting_activity_gdf["geometry"] = sporting_activity_gdf["geometry"].buffer(1852)
    sporting_activity_gdf.to_crs(epsg=4326, inplace=True)

    # Merge airspace, ILS, MATZ and gliding
    merged_gdf = concat([airspace_gdf, ils_gdf, matz_gdf, sporting_activity_gdf])
    merged_gdf = cast(GeoDataFrame, merged_gdf)

    # Override attributes
    override(merged_gdf, override_data)

    # Sort by stype then name
    merged_gdf.sort_values(["stype", "name"], inplace=True)

    # Fix up geometries and snap to 1 second grid
    merged_gdf.geometry = merged_gdf.geometry.make_valid()
    merged_gdf.geometry = merged_gdf.geometry.set_precision(grid_size=1 / 3600)

    # Discard any sliver polygons created by the fix up
    gdf = merged_gdf[merged_gdf.geometry.geom_type == "MultiPolygon"]
    gdf.geometry = gdf.geometry.apply(lambda g: max(g.geoms, key=lambda x: x.area))
    merged_gdf.update(gdf)

    # Reduce size of output file
    merged_gdf.geometry = merged_gdf.geometry.set_precision(grid_size=0.000001)

    return merged_gdf
