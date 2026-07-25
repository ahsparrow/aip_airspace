from geopandas import GeoDataFrame
from lark import Lark, Transformer
from shapely import Point, Polygon
import shapely

LATLON_FMT = (
    "{0[d]:02d}:{0[m]:02d}:{0[s]:02d} {0[ns]} {1[d]:03d}:{1[m]:02d}:{1[s]:02d} {1[ew]}"
)

Grammer = """
    ?start: feature_list
    feature_list: feature+

    feature: airtype airname (freq? upper lower | freq? lower upper | upper lower freq | lower upper freq) boundary

    airtype: "AC" AIRTYPE _NEWLINE
    airname: "AN" NAME_STRING _NEWLINE
    lower: "AL" (ALT | FL | SFC) _NEWLINE
    upper: "AH" (ALT | FL) _NEWLINE
    freq: "AF" FREQ _NEWLINE

    boundary: (line | circle)+

    line: point+
    circle: centre radius

    ?point: "DP" lat_lon _NEWLINE

    centre: "V" _CENT lat_lon _NEWLINE
    radius: "DC" RADIUS _NEWLINE

    _CENT.3: "X="

    ?lat_lon: LAT_LON

    AIRTYPE.2: /\\b(A|B|C|D|E|F|G|P|Q|R|W|CTR|MATZ|OTHER|RMZ|TMZ)\\b/

    NAME_STRING.1: LETTER (NAME_CHAR | " ")~1..40 NAME_CHAR
    NAME_CHAR: (LETTER | DIGIT | "(" | ")" | "/" | "-" | "." | "'")

    ALT.2: DIGIT+ " ft"
    FL.2: "FL" DIGIT+
    SFC.2: "SFC"

    FREQ.2: DIGIT~3 "." DIGIT~3

    RADIUS.1: DIGIT~1..2 ("." DIGIT~1..3)*
    DIRECTION: ("+" | "-")

    LAT_LON.2: LAT " " LON
    LAT: DIGIT~2 ":" DIGIT~2 ":" DIGIT~2 " " LAT_HEMI
    LON: DIGIT~3 ":" DIGIT~2 ":" DIGIT~2 " " LON_HEMI
    LAT_HEMI: ("N" | "S")
    LON_HEMI: ("E" | "W")

    _NEWLINE: NEWLINE

    COMMENT: /\\*[^\\n]*/ NEWLINE
    %ignore COMMENT

    %ignore " "

    %import common.DIGIT
    %import common.LETTER
    %import common.NEWLINE
    %import common.NUMBER
"""


# Return DMS values for floating point degrees
def dms(deg):
    if deg < 0:
        ns = "S"
        ew = "W"
        deg = -deg
    else:
        ns = "N"
        ew = "E"

    secs = round(deg * 3600)
    mins, secs = divmod(secs, 60)
    degs, mins = divmod(mins, 60)
    return {"d": degs, "m": mins, "s": secs, "ns": ns, "ew": ew}


def level(limit, uom, reference):
    if reference == "SFC":
        return "SFC"
    elif reference == "STD":
        return f"FL{limit}"
    else:
        return f"{limit} ft"


def make_openair(annotation: GeoDataFrame) -> str:
    oa = []
    for _, row in annotation.iterrows():
        oa.append("AC B")
        oa.append(f"AN {row['name']}")
        oa.append(
            f"AL {level(row.lowerLimit, row.lowerLimit_uom, row.lowerLimitReference)}"
        )
        oa.append(
            f"AH {level(row.upperLimit, row.upperLimit_uom, row.upperLimitReference)}"
        )
        for coord in row.geometry.exterior.coords:
            latlon = LATLON_FMT.format(dms(coord[1]), dms(coord[0]))
            oa.append(f"DP {latlon}")

    return "\n".join(oa)


class OpenairTransformer(Transformer):
    def LAT_LON(self, latlon):
        t = latlon.replace(":", "").replace(" ", "")

        lat = int(t[:2]) + int(t[2:4]) / 60 + int(t[4:6]) / 3600
        if t[6] == "S":
            lat = -lat

        lon = int(t[7:10]) + int(t[10:12]) / 60 + int(t[12:14]) / 3600
        if t[14] == "W":
            lon = -lon

        return lat, lon

    def DIRECTION(self, dirn):
        return "cw" if dirn == "+" else "ccw"

    def RADIUS(self, r):
        return round(float(r) * 1852)

    def SFC(self, sfc):
        return sfc.value

    def FL(self, fl):
        return fl.value

    def ALT(self, alt):
        return alt[:-3] + " ft"

    def NAME_STRING(self, str):
        return str.value

    def AIRTYPE(self, str):
        return str.value

    def FREQ(self, str):
        return str.value

    def radius(self, tree):
        return tree[0]

    def centre(self, tree):
        return Point(tree[0])

    def circle(self, tree):
        return tree

    def line(self, tree):
        return [Polygon(tree), None]

    def boundary(self, tree):
        return "boundary", tree[0]

    def upper(self, data):
        return "upper", data[0]

    def lower(self, data):
        return "lower", data[0]

    def airname(self, data):
        return "name", data[0]

    def airtype(self, data):
        return "type", data[0]

    def freq(self, data):
        return "freq", data[0]

    feature = dict
    feature_list = list


def parse_openair(data: str) -> GeoDataFrame:
    parser = Lark(Grammer, parser="lalr")
    tree = parser.parse(data)

    d = OpenairTransformer().transform(tree)

    gdf = GeoDataFrame(d)
    gdf["radius"] = gdf.boundary.apply(lambda b: b[1])
    gdf["geom"] = gdf.boundary.apply(lambda b: b[0])
    gdf = gdf.set_geometry("geom").rename_geometry("geometry")

    # Swap lat/lon
    gdf.geometry = gdf.geometry.map(
        lambda p: shapely.ops.transform(lambda x, y: (y, x), p)
    )

    # Create polygons from points
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=32630)
    points = gdf.geometry.geom_type == "Point"
    gdf.loc[points, "geometry"] = gdf.loc[points, "geometry"].buffer(
        gdf.loc[points, "radius"]
    )
    gdf = gdf.to_crs(epsg=4326)

    # Drop radius and boundary columns
    gdf = gdf.drop(["radius", "boundary"], axis=1)

    return gdf
