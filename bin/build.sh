#!/usr/bin/env bash

echo "Sporting"
uv run sporting build/sporting.geojson

echo -e "\nAirspace"
uv run airspace build/airspace.geojson

echo -e "\nLOA"
uv run loa assets/loa.yaml build/airspace.geojson build/loa.geojson

echo -e "\nRA(T)"
uv run rat assets/rat.yaml build/rat.geojson

echo -e "\nObstacles"
uv run obstacle build/airspace.geojson build/obstacle.geojson

echo -e "\nOverlays"
uv run overlay --max_alt 10400 build/airspace.geojson build/overlay_105.geojson build/overlay_105.txt &
uv run overlay --max_alt 19400 build/airspace.geojson build/overlay_195.geojson build/overlay_195.txt &
uv run overlay --max_alt 10400 build/airspace.geojson build/overlay_atzdz.geojson build/overlay_atzdz.txt --atzdz &

echo "working..."
wait -n
echo "done one"
wait -n
echo "done two"
wait -n
echo "all done"
