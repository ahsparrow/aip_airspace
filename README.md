# AIP AIRSPACE

aip_airspace is a Python utility for processing UK airspace data from
the NATS ICAO Aeronautical Information Publication (AIP), converting
it into GeoJSON format for use by the asselect.uk aviation platform.
It handles transformation of airspace definitions, obstacles, letters
of agreement, temporary restricted areas, and sporting activities.

## Assets

- config.yaml - Modifications to AIP airspace
- assets/coast.geojson - Coastline data for removing offshore airspace
- assets/ils.yaml - Runway centre points for ILS feathers
- assets/loa.yaml - Letters of Agreement
- assets/matz.yaml - MATZ specifications
- assets/rat.yaml - Temporary restricted areas

## ASSelect file generation

### Sporting activities

Single geometry points are excluded from the AIP dataset, so they have to be scraped
from the HTML version of the AIP

    uv run sporting build/sporting.geojson

### Airspace

Download the current UK ICAO AIP Dataset from
[NATS](https://nats-uk.ead-it.com/cms-nats/opencms/en/Publications/digital-datasets/)
and unpack into the data directory. Then build the airspace file, e.g.

    uv run airspace data/EG_AIP_DS_FULL_20260709.xml dist/airspace.geojson

### Letters of Agreement

    uv run loa assets/loa.yaml dist/airspace.geojson dist/loa.geojson

### Temporary Restricted Areas

    uv run rat assets/rat.yaml dist/rat.geojson

### Obstacles

Download the current UK ICAO Obstacle Dataset from
[NATS](https://nats-uk.ead-it.com/cms-nats/opencms/en/Publications/digital-datasets/)
and unpack into the data directory. Then build the obstacle file, e.g.

    uv run obstacle data/EG_OBS_DS_AREA1_FULL_20260709.xml dist/obstacle.geojson

### Overlays

    uv run overlay --max_alt 10400 dist/airspace.geoson dist/overlay_105.txt
    uv run overlay --max_alt 19400 dist/airspace.geoson dist/overlay_195.txt
    uv run overlay --max_alt 10400 --atzdz dist/airspace.geoson dist/overlay_atzdz.txt
