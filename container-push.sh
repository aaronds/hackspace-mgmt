#!/bin/bash

CONTAINER_CMD=$(which podman || which docker)

$CONTAINER_CMD tag localhost/hackspace-mgmt:latest registry.bristolhackspace.org/hackspace-mgmt:latest

$CONTAINER_CMD push registry.bristolhackspace.org/hackspace-mgmt:latest

