from geopandas import GeoDataFrame
from shapely import Point
import yaml


def make_gdf(gliding_sites, services):
    data = {
        "name": [],
        "stype": "GLIDING",
        "upperLimit": [],
        "upperLimitReference": "MSL",
        "upperLimit_uom": "FT",
        "lowerLimit": 0,
        "lowerLimitReference": "SFC",
        "lowerLimit_uom": "FT",
        "channel": [],
        "callsign": [],
        "geometry": [],
    }

    for gs in gliding_sites:
        data["name"].append(gs["name"])
        data["upperLimit"].append(int(gs["geometry"][0]["upper"].split()[0]))

        centre = gs["geometry"][0]["boundary"][0]["circle"]["centre"]
        lat_str, lon_str = centre.split()

        lat = int(lat_str[0:2]) + int(lat_str[2:4]) / 60 + int(lat_str[4:6]) / 3600
        lon = int(lon_str[0:3]) + int(lon_str[3:5]) / 60 + int(lon_str[5:7]) / 3600
        if lon_str[-1] == "W":
            lon = -lon
        data["geometry"].append(Point((lon, lat)))

        id = gs.get("id")
        callsign = None
        channel = None
        if id:
            service = [s for s in services if id in s["controls"]]
            if service:
                callsign = service[0]["callsign"]
                channel = service[0]["frequency"]

        data["callsign"].append(callsign)
        data["channel"].append(channel)

    gdf = GeoDataFrame(data)
    gdf.set_crs(epsg=4326, inplace=True)

    return gdf


def gliding_sites(data):
    gdf = GeoDataFrame.from_features(data)
    gdf.set_crs(epsg=4326, inplace=True)

    return gdf


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("yaixm_airspace")
    parser.add_argument("yaixm_service")
    parser.add_argument("output")
    args = parser.parse_args()

    yaixm = yaml.safe_load(open(args.yaixm_airspace))

    gliding_sites = [
        a
        for a in yaixm["airspace"]
        if a.get("localtype") == "GLIDER" and a.get("type") == "OTHER"
    ]

    services = yaml.safe_load(open(args.yaixm_service))

    gdf = make_gdf(gliding_sites, services["service"])

    data = gdf.to_geo_dict(drop_id=True)
    with open(args.output, "w") as f:
        yaml.dump(data, f)
