#!/bin/bash

CONTAINER_CMD=$(which podman || which docker)

$CONTAINER_CMD build -t localhost/hackspace-mgmt:latest -f Dockerfile

