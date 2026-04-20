from shapely import LineString, Point
import geopandas
import xml.etree.ElementTree as ET

ns = {
    "aixm": "http://www.aixm.aero/schema/5.1",
    "gml": "http://www.opengis.net/gml/3.2",
    "message": "http://www.aixm.aero/schema/5.1/message",
    "xlink": "http://www.w3.org/1999/xlink",
}
for name in ns:
    ET.register_namespace(name, ns[name])

TOLERANCE = 0.001


# From shapely user manual
def cut(line, distance):
    # Cuts a line in two at a distance from its starting point
    if distance <= TOLERANCE or distance >= (line.length - TOLERANCE):
        return [LineString(line)]
    coords = list(line.coords)
    for i, p in enumerate(coords):
        pd = line.project(Point(p))
        if pd >= (distance - TOLERANCE):
            return [LineString(coords[: i + 1]), LineString(coords[i:])]


def fix_links(et, borders_df):
    # Find gml:Rings with xlink-ed gml:curveMembers
    rings = et.findall(".//gml:Ring/gml:curveMember[@xlink:href]/..", ns)
    for ring in rings:
        curve_members = ring.findall("gml:curveMember", ns)

        for n, cm in enumerate(curve_members):
            href = cm.attrib.get(f"{{{ns['xlink']}}}href")
            if href:
                identifier = href.split(":")[-1]
                border_segment = et.find(f".//gml:identifier[.='{identifier}']", ns)

                # Get previous and next positions
                prev = curve_members[(n - 1) % len(ring)].findall(".//gml:pos", ns)
                prev = Point([float(x) for x in prev[-1].text.split()][::-1])

                next = curve_members[(n + 1) % len(ring)].findall(".//gml:pos", ns)
                next = Point([float(x) for x in next[0].text.split()][::-1])

                # Find border geometry
                border = borders_df[borders_df["identifier"] == identifier][
                    "geometry"
                ].iloc[0]

                # Trim border geometry to match positions
                border = cut(border, border.project(prev))[-1]
                border = cut(border, border.project(next))[0]

                # Clear linked curve member
                cm.clear()
                cm.attrib = {"xlink:type": "simple"}

                # Add linked points
                curve = ET.SubElement(cm, "gml:Curve")
                segments = ET.SubElement(curve, "gml:segments")
                geo_str = ET.SubElement(
                    segments, "gml:GeodesicString", attrib={"interpolation": "geodesic"}
                )
                for p in [prev.coords[-1]] + border.coords[1:-1:] + [next.coords[0]]:
                    point_prop = ET.SubElement(
                        geo_str, "gml:pointProperty", attrib={"xlink:type": "simple"}
                    )
                    aixm_point = ET.SubElement(
                        point_prop,
                        "aixm:Point",
                        attrib={"srsName": "urn:ogc:def:crs:EPSG::4326"},
                    )
                    pos = ET.SubElement(
                        aixm_point,
                        "gml:pos",
                        attrib={"srsName": "urn:ogc:def:crs::EPSG:4326"},
                    )
                    pos.text = f"{p[1]} {p[0]}"


def fix_units(et):
    ft_i = et.findall(".//gml:radius[@uom='[ft_i]']", ns)
    for el in ft_i:
        el.set("uom", "FT")


def load_aip(aip):
    et = ET.parse(aip)

    # Replace "[ft_i]" with "FT"
    fix_units(et)

    # Fix border links in the airspace
    borders = geopandas.read_file(ET.tostring(et.getroot()), layer="GeoBorder")
    fix_links(et, borders)

    return ET.tostring(et.getroot())


if __name__ == "__main__":
    from zipfile import ZipFile

    with ZipFile("data/EG_AIP_DS_20260416_XML.zip") as zf:
        aip = zf.open("EG_AIP_DS_FULL_20260416.xml")

    aip = load_aip(aip)

    et = ET.ElementTree(ET.fromstring(aip))
    ET.indent(et, "   ")
    et.write("tmp.xml", encoding="unicode")
