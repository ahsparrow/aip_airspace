from shapely import MultiPolygon
from geopandas import GeoDataFrame
from pandas import DataFrame, Series
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
        return f"{row.designator[2:]} {row["name"]}"
    else:
        return row["name"]


def remove_offshore(
    gdf: GeoDataFrame, coast_gdf: GeoDataFrame, buffer: int = 10000
) -> GeoDataFrame:
    coast_gdf.to_crs(epsg=27700, inplace=True)
    coast_gdf.geometry = coast_gdf.buffer(buffer)
    coast_gdf.to_crs(epsg=4326, inplace=True)

    mp = MultiPolygon(coast_gdf.geometry)

    return gdf[gdf.overlaps(mp) | gdf.within(mp)]


def remove_excluded(gdf: GeoDataFrame, exclude: list[str]) -> GeoDataFrame:
    return gdf.loc[gdf.index.difference(exclude)]


def airspace(as_gdf: GeoDataFrame) -> GeoDataFrame:
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

    return gdf


# Override callsign/frequency in ATC service
def override_ats(ats_df: DataFrame, override: list[dict]) -> DataFrame:
    ats_df = ats_df.set_index("identifier")

    for svc in override:
        ats_df.loc[svc["identifier"], "callSign"] = [svc["callsign"]]
        ats_df.loc[svc["identifier"], "radioCommunication_href"] = [svc["rcc_href"]]

    return ats_df


def add_frequency(
    as_gdf: GeoDataFrame,
    ats_df: DataFrame,
    is_df: DataFrame,
    rcc_df: DataFrame,
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
    gdf = as_gdf.merge(df, left_index=True, right_index=True)

    df = DataFrame.from_dict(callsign, orient="index", columns=["callsign"])
    gdf = gdf.merge(df, left_index=True, right_index=True)

    return gdf  # type: ignore


def override(airspace_gdf: GeoDataFrame, overrides: list[dict]):
    for o in overrides:
        df = DataFrame({k: [o[k]] for k in o})
        df.set_index("identifier", inplace=True)
        airspace_gdf.update(df)
