from importlib.resources import files
from math import sqrt
from pathlib import Path

from freetype import Face, FT_LOAD_DEFAULT, FT_LOAD_NO_BITMAP
from geopandas import GeoDataFrame, GeoSeries
import numpy as np
import pandas
from shapely import (
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    minimum_bounding_radius,
    polygonize,
)
from shapely.affinity import scale, skew, translate
from shapely.ops import polylabel
from sklearn.cluster import KMeans

TEXT_SIZE = 3000
SPLIT_RADIUS = 22500


def norm_lower_limit(row):
    if row.lowerLimitReference == "SFC":
        return 0
    elif row.lowerLimitReference == "STD":
        return row.lowerLimit * 100
    else:
        return row.lowerLimit


# Get character glyphs from TTF file
def get_glyphs(font, chars):
    # Set font face
    face = Face(font)
    face.set_char_size(1000)

    glyphs = {"normal": {}, "slanted": {}}
    for char in chars:
        face.load_char(char, FT_LOAD_DEFAULT | FT_LOAD_NO_BITMAP)
        outline = face.glyph.outline

        # List of contour slices
        contours = [0] + [c + 1 for c in outline.contours]
        slices = [slice(contours[i], contours[i + 1]) for i in range(len(contours) - 1)]

        # Polygons for glyph
        mp = MultiPolygon([Polygon(outline.points[s]) for s in slices])
        glyphs["normal"][char] = mp
        glyphs["slanted"][char] = skew(mp, 25)

    return glyphs


# Create a Mulitpolygon representation of text
def make_string(glyphs, text, style="normal"):
    offset = 0
    result = MultiPolygon()

    for char in text:
        poly = glyphs[style][char]
        minx, miny, maxx, maxy = poly.bounds

        poly = translate(poly, offset)
        result = result.union(poly)

        offset += maxx + 50

    return result


def annotation_polys(glyphs, point, clearance, annotation, style="normal"):
    # Create annotation polgons
    txt = make_string(glyphs, annotation, style)
    minx, miny, maxx, maxy = txt.bounds

    # Scale to fit space available
    scl = 2 * min(clearance, TEXT_SIZE) / sqrt((maxx - minx) ** 2 + (maxy - miny) ** 2)
    txt = scale(txt, scl, scl)
    minx, miny, maxx, maxy = txt.bounds

    # Translate to correct postion
    xoff = point.x - (minx + maxx) / 2
    yoff = point.y - (miny + maxy) / 2
    txt = translate(txt, xoff, yoff)

    return txt


# Guess best position for annotation
def get_position(polys):
    pos = []
    dist = []
    for p in polys:
        poi = polylabel(p, tolerance=100)
        poi_dist = poi.distance(p.boundary)

        centroid = p.centroid
        centroid_dist = centroid.distance(p.boundary)

        if p.contains(centroid) and centroid_dist > min(TEXT_SIZE, (poi_dist * 0.90)):
            pos.append(centroid)
            dist.append(centroid_dist)
        else:
            pos.append(poi)
            dist.append(poi_dist)

    return pos, dist


# Recursively cluster points
def cluster_points(out, points, max_size):
    if minimum_bounding_radius(points) < max_size:
        out.append(points)
    else:
        # Split points into two clusters using k-means clustering
        kmeans = KMeans(n_clusters=2, random_state=0, n_init="auto")
        cluster = kmeans.fit_predict([(p.x, p.y) for p in points.geoms])

        c1 = MultiPoint(np.array(points.geoms)[cluster == 0])
        cluster_points(out, c1, max_size)

        c2 = MultiPoint(np.array(points.geoms)[cluster == 1])
        cluster_points(out, c2, max_size)


# Split polygons into smaller parts
def poly_splitter(poly, max_size, grid=500):
    if minimum_bounding_radius(poly) < max_size:
        return [poly]

    # Create array of points inside polygon
    minx, miny, maxx, maxy = poly.bounds
    nx = int((maxx - minx) // grid + 1)
    ny = int((maxy - miny) // grid + 1)

    pts = MultiPoint([Point(x * grid, y * grid) for x in range(nx) for y in range(ny)])

    pts = translate(pts, minx, miny)
    pts = poly.intersection(pts)

    # Split points into clusters
    out = []
    cluster_points(out, pts, max_size)

    # Convert point arrays back to polygons
    return [p.buffer(grid * 0.501, cap_style="square").intersection(poly) for p in out]


def overlay(airspace_gdf: GeoDataFrame, max_alt: int, atzdz: bool) -> GeoDataFrame:
    # Character glyphs for annotation
    glyphs = get_glyphs(
        files("aip_airspace").joinpath("data").joinpath("asselect.ttf").open("rb"),
        "0123456789DZ",
    )

    airspace_gdf = airspace_gdf.to_crs(epsg=32630)

    # Convert points to polygons
    point_gdf = airspace_gdf[airspace_gdf.geom_type == "Point"]
    point_gdf.geometry = point_gdf.buffer(point_gdf.radius)
    airspace_gdf.update(point_gdf)

    airspace_gdf = airspace_gdf.assign(
        normlower=airspace_gdf.apply(norm_lower_limit, axis=1)
    )

    # Filter CTA, etc. and limit base level
    cta_gdf = airspace_gdf[
        airspace_gdf.atype.isin(["CTA", "CTR", "TMA"])
        & (airspace_gdf.normlower <= max_alt)
        & (airspace_gdf.name != "BRIZE NORTON CTR")
    ]
    cta_gdf.to_file(Path("overlay.geojson"), driver="GeoJSON")

    # Create polygons from union of CTA geometries
    cta_union = cta_gdf.geometry.exterior.unary_union
    cta_polys = GeoSeries(polygonize(cta_union.geoms), crs="EPSG:32630")

    # Remove slivers between not-quite adjacent airspace
    cta_polys = cta_polys.buffer(-300).buffer(299)

    # Convert multipolygon into polygons
    cta_polys = cta_polys.explode(ignore_index=True)

    # Remove empty polygon
    cta_polys = cta_polys[~cta_polys.is_empty]

    # Remove polygons exterior to CTA
    cta_polys = cta_polys[
        [cta_gdf.geometry.contains(p).any() for p in cta_polys.representative_point()]
    ]

    # Merge to single multipolygon
    cta_multipoly = MultiPolygon([p for p in cta_polys if not p.is_empty])

    # Remove ATZ and DZ geometrys for HG/PG overlay
    if atzdz:
        # ATZs (with exceptions)
        atz_gdf = airspace_gdf[
            (
                (airspace_gdf.atype == "ATZ")
                & ~airspace_gdf.name.isin(
                    [
                        "BARTON ATZ",
                        "BIGGIN HILL ATZ",
                        "DENHAM ATZ",
                        "DERBY ATZ",
                        "ELSTREE ATZ",
                        "FAIROAKS ATZ",
                        "ODIHAM ATZ",
                        "REDHILL ATZ",
                        "ROCHESTER ATZ",
                        "STAPLEFORD ATZ",
                        "WHITE WALTHAM ATZ",
                    ]
                )
            )
        ]

        # Dropzones
        dz_gdf = airspace_gdf[(airspace_gdf.atype == "DZ")]

        # Update cta_multipoly by removing ATZs and dropzones
        cta_multipoly = cta_multipoly.difference(
            pandas.concat([atz_gdf.geometry, dz_gdf.geometry]).unary_union
        )

    # Split bigger polygons
    polys = [poly_splitter(p, SPLIT_RADIUS) for p in cta_multipoly.geoms]
    polys = [poly for sublist in polys for poly in sublist]

    # Convert any multipolygons to polygons
    polys = GeoSeries(polys, crs="EPSG:32630").explode(ignore_index=True).geometry

    # Get label positions and distance to edge
    poi, dist = get_position(polys)

    # Create annotation
    annotation = GeoDataFrame({"geometry": []}, crs="EPSG:32630")
    for pos, clearance in zip(poi, dist):
        # Find lowest airspace at point p
        ctas = cta_gdf.cx[pos.x : pos.x + 1, pos.y : pos.y + 1]
        min_ind = ctas["normlower"].argmin()
        lowest_cta = ctas.iloc[min_ind]

        # Skip if base at surface or clearance is too small
        if lowest_cta["normlower"] == 0 or clearance < 750:
            continue

        # Use slanted glyphs for flight levels, upright for altitude
        style = "slanted" if lowest_cta.lowerLimitReference == "STD" else "normal"

        # Convert height text to polygons
        txt = annotation_polys(
            glyphs, pos, clearance, str(lowest_cta["normlower"] // 100), style
        )

        data = {
            "geometry": txt,
            "name": [lowest_cta["name"]],
            "lowerLimit": [lowest_cta.lowerLimit],
            "lowerLimit_uom": [lowest_cta.lowerLimit_uom],
            "lowerLimitReference": [lowest_cta.lowerLimitReference],
            "upperLimit": [lowest_cta.upperLimit],
            "upperLimit_uom": [lowest_cta.upperLimit_uom],
            "upperLimitReference": [lowest_cta.upperLimitReference],
        }
        annotation = pandas.concat(
            [annotation, GeoDataFrame(data, crs="EPSG:32630")], ignore_index=False
        )

    # Annotate ATZ and DZ for HG/PG overlay
    if atzdz:
        # DZ annotation
        for _, dz in dz_gdf.iterrows():
            pos = dz.geometry.centroid
            clearance = minimum_bounding_radius(dz.geometry) * 0.75
            txt = annotation_polys(glyphs, pos, clearance, "DZ")

            data = {
                "geometry": txt,
                "name": [dz["name"]],
                "lowerLimit": [0],
                "lowerLimit_uom": ["FT"],
                "lowerLimitReference": ["SFC"],
                "upperLimit": [dz.upperLimit],
                "upperLimit_uom": [dz.upperLimit_uom],
                "upperLimitReference": [dz.upperLimitReference],
            }
            annotation = pandas.concat(
                [annotation, GeoDataFrame(data, crs="EPSG:32630")], ignore_index=False
            )

        # ATZ annotation
        for _, atz in atz_gdf.iterrows():
            pos = atz.geometry.centroid
            if not dz_gdf.geometry.contains(pos).any():
                clearance = minimum_bounding_radius(atz.geometry)
                txt = annotation_polys(glyphs, pos, clearance, str(atz.upperLimit))

                data = {
                    "geometry": txt,
                    "name": [atz["name"]],
                    "lowerLimit": [0],
                    "lowerLimit_uom": ["FT"],
                    "lowerLimitReference": ["SFC"],
                    "upperLimit": [atz.upperLimit],
                    "upperLimit_uom": [atz.upperLimit_uom],
                    "upperLimitReference": [atz.upperLimitReference],
                }
                annotation = pandas.concat(
                    [annotation, GeoDataFrame(data, crs="EPSG:32630")],
                    ignore_index=False,
                )

    # Convert to WGS84
    return annotation.to_crs(epsg=4326)
