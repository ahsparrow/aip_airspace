from functools import lru_cache

import numpy as np
from pyproj import Transformer
from pyproj.enums import TransformDirection
from shapely import Polygon

from aip_airspace.util import parse_latlon

TransformerFromCrs = lru_cache(Transformer.from_crs)


def do_line(line):
    return np.array([parse_latlon(p) for p in line])


def do_circle(circle, resolution):
    transformer = TransformerFromCrs(4326, 32630)

    centre_x, centre_y = transformer.transform(*parse_latlon(circle["centre"]))

    # Get radius (assume in nm)
    radius_str = circle["radius"]
    radius = float(radius_str.split()[0]) * 1852

    # Calculate points on circumference
    angle = np.linspace(0, 2 * np.pi, resolution * 4 + 1)

    x = centre_x + radius * np.cos(angle)
    y = centre_y + radius * np.sin(angle)
    pts = transformer.transform(x, y, direction=TransformDirection.INVERSE)

    return np.array(pts).T


def do_arc(arc, from_latlon, resolution):
    transformer = TransformerFromCrs(4326, 32630)

    from_x, from_y = transformer.transform(*from_latlon)
    to_x, to_y = transformer.transform(*parse_latlon(arc["to"]))
    centre_x, centre_y = transformer.transform(*parse_latlon(arc["centre"]))

    # Get radius, either property or calculated
    if radius_str := arc.get("radius"):
        # assume in nm
        radius = float(radius_str.split()[0]) * 1852
    else:
        radius = np.sqrt((to_x - centre_x) ** 2 + (to_y - centre_y) ** 2)

    # Angle is zero for due East, and increase anticlockwise
    angle_from = np.arctan2(from_y - centre_y, from_x - centre_x)
    angle_to = np.arctan2(to_y - centre_y, to_x - centre_x)

    if arc["dir"] == "ccw":
        if angle_to < angle_from:
            angle_to += 2 * np.pi

        angle = np.linspace(-np.pi, 3 * np.pi, resolution * 8 + 1)
        angle = angle[(angle > angle_from) & (angle < angle_to)]
    else:
        if angle_to > angle_from:
            angle_from += 2 * np.pi

        angle = np.linspace(3 * np.pi, -np.pi, resolution * 8 + 1)
        angle = angle[(angle < angle_from) & (angle > angle_to)]

    x = centre_x + radius * np.cos(angle)
    y = centre_y + radius * np.sin(angle)
    x = np.append(x, to_x)
    y = np.append(y, to_y)

    pts = transformer.transform(x, y, direction=TransformDirection.INVERSE)

    return np.array(pts).T


def boundary_polygon(boundary, resolution):
    line_strs = []
    for segment in boundary:
        match segment:
            case {"circle": circle}:
                line_str = do_circle(circle, resolution)
            case {"line": line}:
                line_str = do_line(line)
            case {"arc": arc}:
                line_str = do_arc(arc, line_str[-1], resolution)

        line_strs.append(line_str)

    return Polygon(np.fliplr(np.concatenate(line_strs)))
