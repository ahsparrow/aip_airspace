import re

# Latitude/longitude regex
# Pattern is: [D]DDMMSS[.s[s[s]]]H
DMS_PATTERN = "(?P<d>[0-9]{2}|[01][0-9]{2})(?P<m>[0-5][0-9])(?P<s>[0-5][0-9](.[0-9]{1,3})?)(?P<h>[NESW])"
DMS_RE = re.compile(DMS_PATTERN)

# Conversion factor
NM_TO_DEGREES = 1 / 60


# Convert latitude or longitude string to floating point degrees
def parse_deg(deg_str: str) -> float:
    m = DMS_RE.match(deg_str)
    if m is None:
        return 0.0

    deg = int(m.group("d")) + int(m.group("m")) / 60 + float(m.group("s")) / 3600
    if m.group("h") in "SW":
        deg = -deg
    return deg


# Convert latlon string to pair of floats
def parse_latlon(latlon_str: str) -> tuple[float, float]:
    lat, lon = [parse_deg(d) for d in latlon_str.split()]
    return lat, lon


def parse_level(level: str) -> dict:
    if level.startswith("FL"):
        limit = int(level[2:])
        uom = "FL"
        ref = "STD"
    elif level == "SFC":
        limit = 0
        uom = "FT"
        ref = "SFC"
    else:
        limit = int(level.split()[0])
        uom = "FT"
        ref = "MSL"

    return {"limit": limit, "uom": uom, "reference": ref}
