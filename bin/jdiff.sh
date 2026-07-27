#!/usr/bin/env bash

meld <(jq . "$1") <(jq . "$2")
