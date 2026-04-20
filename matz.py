from geopandas import read_file, GeoDataFrame
import pandas
import yaml
from shapely import affinity, box, union_all, Point

NM_M = 1852


def matz(matz_list: dict, atz_gdf: GeoDataFrame) -> GeoDataFrame:
    # ATS DataFrame with cartesian coordiates
    catz_gdf = atz_gdf.to_crs(epsg=27700)

    # Filter MATZ ATZs
    atz_ids = [m["atz_identifier"] for m in matz_list]
    catz_gdf = catz_gdf[catz_gdf["identifier"].isin(atz_ids)]

    # Trim " ATZ" from end of name
    catz_gdf["name"] = [n[:-4] for n in catz_gdf["name"]]

    # Store ATZ centroids
    catz_gdf["centroid"] = catz_gdf["geometry"].centroid

    # Create MATZ core geometries
    geom = []
    for md in matz_list:
        centroid = (
            catz_gdf[catz_gdf["identifier"] == md["atz_identifier"]].iloc[0].centroid
        )

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
            "localType": ["MATZ"] * len(geom),
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
        catz = catz_gdf[catz_gdf["identifier"] == md["atz_identifier"]].iloc[0]

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
            "localType": ["MATZ"] * len(geom),
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
    matz_gdf = GeoDataFrame(pandas.concat([core_gdf, stub_gdf]), crs="EPSG:27700")
    matz_gdf.to_crs(epsg=4326, inplace=True)

    return matz_gdf


if __name__ == "__main__":
    from loadaip import load_aip
    from pathlib import Path

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    aip = load_aip("data/EG_AIP_DS_FULL_20260416.xml")

    gdf = read_file(aip, layer="Airspace")
    gdf.set_crs(epsg=4326, inplace=True)
    atz_gdf = gdf[gdf["timeSlice|AirspaceTimeSlice|localType"] == "ATZ"]

    matz_gdf = matz(config["matz"], atz_gdf)
    matz_gdf.to_file(Path("matz.geojson"), driver="GeoJSON")
