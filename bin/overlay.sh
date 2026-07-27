#!/usr/bin/env bash

echo "Generating overlays..."
if [[ "$#" -eq 1 && "$1" == "geojson" ]]; then
  uv run overlay --max_alt 10400 build/airspace.geojson build/overlay_105.geojson &
  uv run overlay --max_alt 19400 build/airspace.geojson build/overlay_195.geojson &
  uv run overlay --max_alt 10400 build/airspace.geojson build/overlay_atzdz.geojson --atzdz &
else
  uv run overlay --max_alt 10400 build/airspace.geojson build/overlay_105.txt &
  uv run overlay --max_alt 19400 build/airspace.geojson build/overlay_195.txt &
  uv run overlay --max_alt 10400 build/airspace.geojson build/overlay_atzdz.txt --atzdz &
fi

wait -n
echo "Done one"
wait -n
echo "Done two"
wait -n
echo "All done"
