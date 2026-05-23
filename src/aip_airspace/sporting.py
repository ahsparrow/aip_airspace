import re

from geopandas import GeoDataFrame
from lxml import html
from shapely import Point

from aip_airspace.util import parse_latlon

NAME_RE = re.compile(r"(.+) (GLIDER SITE|MICROLIGHT SITE|TRAINING AERODROME)")
ELEVATION_RE = re.compile(r"Site elevation: (\d+ FT AMSL|SL)", flags=re.IGNORECASE)
UPPER_LIMIT_RE = re.compile(r"Upper limit: (\d+) FT AGL")
CHANNEL_RE = re.compile(r"(?:Freq|Channel): (\d{3}\.\d{3})")


def parse_sporting(text: str) -> GeoDataFrame:
    root = html.fromstring(text)

    # Drop hidden content
    for element in root.xpath("//*[@style='display: none;']"):
        element.drop_tree()

    names = []
    geoms = []
    stypes = []
    upper_limits = []
    channels = []

    name_tags = root.xpath("//tbody/tr/td[1]/p[1]")
    for tag in name_tags:
        txt = tag.text_content().strip()

        if name_match := NAME_RE.match(txt):
            names.append(name_match.group(1))

            match name_match.group(2):
                case "GLIDER SITE":
                    stypes.append("GLIDER")
                case "MICROLIGHT SITE":
                    stypes.append("MICROLIGHT")
                case "TRAINING AERODROME":
                    stypes.append("TRAINING")

            # Lat/lon
            lat_lon = tag.xpath("following-sibling::p")[0].text_content()
            lat, lon = parse_latlon(lat_lon)
            geoms.append(Point(lon, lat))

            # Elevation
            elev_channel_tag = tag.xpath("../following-sibling::td[3]/p[1]")[0]
            elev_match = ELEVATION_RE.search(elev_channel_tag.text_content())
            if (elev_str := elev_match.group(1)) == "SL":
                elevation = 0
            else:
                elevation = int(elev_str.split()[0])

            # Channel
            channel_match = CHANNEL_RE.search(elev_channel_tag.text_content())
            if channel_match:
                channels.append(channel_match.group(1))
            else:
                channels.append(None)

            # Upper limit
            if upper_limit_tag := tag.xpath("../following-sibling::td[1]/p[1]"):
                upper_match = UPPER_LIMIT_RE.match(upper_limit_tag[0].text_content())
                upper_limit = int(upper_match.group(1)) + elevation
            else:
                upper_limit = elevation + 1000
            upper_limits.append(upper_limit)

    gdf = GeoDataFrame(
        {
            "name": names,
            "stype": stypes,
            "upperLimit": upper_limits,
            "upperLimit_uom": "FT",
            "upperLimitReference": "MSL",
            "lowerLimit": 0,
            "lowerLimit_uom": "FT",
            "lowerLimitReference": "SFC",
            "channel": channels,
            "geometry": geoms,
        },
        crs="EPSG:4326",
    )
    return gdf


if __name__ == "__main__":
    import requests

    request = requests.get(
        "https://www.aurora.nats.co.uk/htmlAIP/Publications/2026-06-11-AIRAC/html/eAIP/EG-ENR-5.5-en-GB.html#ENR-5.5"
    )

    parse_sporting(request.content)
