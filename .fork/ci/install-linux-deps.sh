#!/usr/bin/env bash
# Installs the system packages a Linux CI row needs on a stock ubuntu-24.04 or
# ubuntu-24.04-arm runner (#5). Libraries come from the dependency provider,
# so only what can't be built from source belongs here.
set -euo pipefail

packages=(
    ninja-build
    # Avahi is loaded at runtime, not linked. The workflow starts the daemon
    # for wpinet's mDNS tests.
    avahi-daemon
    # TEMPORARY: remove once the OpenCV recipe lands (#33).
    libopencv-dev
)

sudo apt-get update
sudo apt-get install -y "${packages[@]}"
