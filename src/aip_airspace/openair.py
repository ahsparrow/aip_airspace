from geopandas import GeoDataFrame

LATLON_FMT = (
    "{0[d]:02d}:{0[m]:02d}:{0[s]:02d} {0[ns]} {1[d]:03d}:{1[m]:02d}:{1[s]:02d} {1[ew]}"
)


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
