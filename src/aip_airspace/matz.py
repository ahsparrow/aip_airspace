from geopandas import GeoDataFrame
from pandas import DataFrame, concat
from shapely import affinity, box, union_all, Point

NM_M = 1852


def get_channels(matz_list):
    data = [
        [m["atz_identifier"], m["channel"], m["callsign"]]
        for m in matz_list
        if "channel" in m
    ]
    data = [list(x) for x in zip(*data[:])]

    df = DataFrame({"id": data[0], "channel": data[1], "callsign": data[2]})
    df.set_index("id", inplace=True)

    return df


def create_matz(
    matz_list: list[dict], atz_gdf: GeoDataFrame
) -> tuple[GeoDataFrame, DataFrame]:
    # ATS DataFrame with cartesian coordiates
    catz_gdf = atz_gdf.to_crs(epsg=27700)

    # Filter MATZ ATZs
    atz_ids = [m["atz_identifier"] for m in matz_list]
    catz_gdf = catz_gdf.loc[atz_ids]

    # Trim " ATZ" from end of name
    catz_gdf["name"] = [n[:-4] for n in catz_gdf["name"]]

    # Store ATZ centroids
    catz_gdf["centroid"] = catz_gdf["geometry"].centroid

    # Create MATZ core geometries
    geom = []
    for md in matz_list:
        centroid = catz_gdf.loc[md["atz_identifier"]].centroid

        matz = centroid.buffer(md.get("radius", 5) * NM_M)

        # WARTON is a special case
        if md["name"] == "WARTON":
            width = md["stubs"][0]["width"]
            offset = md["stubs"][0]["offset"]
            heading = md["stubs"][0]["heading"]
            radius = md.get("radius", 5)

            stub = box(
                -(width / 2 + offset) * NM_M,
                -2 * radius * NM_M,
                (width / 2 - offset) * NM_M,
                2 * radius * NM_M,
            )
            stub = affinity.rotate(stub, -heading, Point(0, 0))
            stub = affinity.translate(stub, centroid.x, centroid.y)
            matz = matz.intersection(stub.buffer(1))

        geom.append(matz)

    # Union of overlapping cores
    core_union = union_all(geom)
    geom = core_union.geoms

    # Merge ATZ attribues
    names = []
    uppers = []
    for core in geom:
        # Get (maybe list) ATZs inside the MATZ
        atzs = catz_gdf[catz_gdf.centroid.within(core)]

        # Alphabetically sorted names
        ns = atzs.name.sort_values()
        names.append(f"{'/'.join(ns)} {'CMATZ' if len(ns) > 1 else 'MATZ'}")

        # Maximum upper limit
        uppers.append(atzs.upperLimit.max())

    # Create GeoDataFrame of MATZ cores
    core_gdf = GeoDataFrame(
        {
            "stype": ["MATZ"] * len(geom),
            "name": names,
            "upperLimit": uppers,
            "upperLimit_uom": ["FT"] * len(geom),
            "upperLimitReference": "MSL",
            "lowerLimit": 0,
            "lowerLimit_uom": ["FT"] * len(geom),
            "lowerLimitReference": "SFC",
            "geometry": geom,
        },
        crs="EPSG:27700",
    )

    # Stubs
    geom = []
    names = []
    uppers = []
    for md in matz_list:
        catz = catz_gdf.loc[md["atz_identifier"]]

        for n, sd in enumerate(md["stubs"]):
            width = sd.get("width", 4)
            offset = sd.get("offset", 0)
            stub = box(
                (-width / 2 + offset) * NM_M,
                0,
                (width / 2 + offset) * NM_M,
                (md.get("radius", 5) + sd.get("distance", 5)) * NM_M,
            )
            stub = affinity.rotate(stub, -(sd["heading"] + 180), Point(0, 0))
            stub = affinity.translate(stub, catz.centroid.x, catz.centroid.y)

            # Remove intersections with MATZ cores
            stub = stub.difference(core_union)

            geom.append(stub)

            name = f"{catz["name"]} STUB" + (
                "" if len(md["stubs"]) != 2 else f" {n + 1}"
            )
            names.append(name)

            # Upper limit is 1000' above ATZ upper limit
            uppers.append(catz.upperLimit + 1000)

    stub_gdf = GeoDataFrame(
        {
            "stype": ["MATZ"] * len(geom),
            "name": names,
            "upperLimit": uppers,
            "upperLimit_uom": ["FT"] * len(geom),
            "upperLimitReference": "MSL",
            "lowerLimit": [u - 2000 for u in uppers],
            "lowerLimit_uom": ["FT"] * len(geom),
            "lowerLimitReference": "MSL",
            "geometry": geom,
        },
        crs="EPSG:27700",
    )

    # Concatenate cores and stubs and convert to WGS84
    matz_gdf = GeoDataFrame(concat([core_gdf, stub_gdf]), crs="EPSG:27700")
    matz_gdf.to_crs(epsg=4326, inplace=True)

    channel_df = get_channels(matz_list)

    return matz_gdf, channel_df
