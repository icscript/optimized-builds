#!/usr/bin/env python3

# Copyright 2022 https://www.math-crypto.com
# GNU General Public License
#
# Updated 2024 for polkadot-sdk compatibility

# Script to benchmark many different polkadot binaries that were
# compiled using compile.py. Version needs to be specified in
# the code below. Binaries are expected to placed in
#     ~/polkadot-optimized/bin/VERSION
# The output of the benchmarks are placed in
#     ~/polkadot-optimized/output/VERSION/HOSTNAME/DATE_TIME
# Both directories are hard-codes so change this in the code
# below if needed.
#
# Beware that benchmarking takes a while!
# It is advisable to run the script in a screen session.
#
# NOTE: Only the main 'polkadot' binary is used for benchmarking.
# The worker binaries (polkadot-prepare-worker, polkadot-execute-worker)
# are only needed when running an actual node, not for benchmarks.
#
# Docker needs to be runnable without sudo privileges!

import subprocess
import sys
import os, stat
import socket
from datetime import datetime
import psutil # pip install psutil
import glob
import re
import shutil
from pathlib import Path
import requests


def perform_benchmark(binary, NB_RUNS, nb_build, processed_dir, docker=False, version=None):
    for i in range(NB_RUNS):
        print("Performing benchmark run {} for polkadot build {}".format(i, nb_build))

        pct_before = psutil.cpu_percent(interval=2)
        if not docker:
            bench = subprocess.run([binary, "benchmark", "machine", "--disk-duration", "30"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        else:
            # MODIFIED: Updated docker image reference for polkadot-sdk
            # Old format: parity/polkadot:v0.9.27
            # New format: parity/polkadot:polkadot-stable2509-2 (or use version variable)
            bench = subprocess.run(['docker', 'run', '--rm', '-it', 'parity/polkadot:polkadot-{}'.format(version),
                                    'benchmark', 'machine', '--disk-duration', '30'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = bench.stdout.decode("utf-8")
        pct_after = psutil.cpu_percent(interval=2)

        with open(processed_dir + "/bench_{}_run_{}.txt".format(nb_build, i), "w") as text_file:
            text_file.write("CPU utilization at start: {}\n".format(pct_before))
            text_file.write(out)
            text_file.write("CPU utilization at end: {}\n".format(pct_after))

    # TODO test for version >= 0.9.27
    # TODO number of tests i hard coded (idea: take 1/5 of NB_RUNS)
    for i in range(4):
        print("Performing extrinsic benchmark run {} for polkadot build {}".format(i, nb_build))

        pct_before = psutil.cpu_percent(interval=2)
        if not docker:
            bench = subprocess.run([binary, 'benchmark', 'extrinsic', '--pallet', 'system', '--extrinsic', 'remark', '--chain', 'polkadot-dev'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        else:
            # MODIFIED: Updated docker image reference for polkadot-sdk
            bench = subprocess.run(['docker', 'run', '--rm', '-it', 'parity/polkadot:polkadot-{}'.format(version),
                                    'benchmark', 'extrinsic', '--pallet', 'system', '--extrinsic', 'remark', '--chain', 'polkadot-dev'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = bench.stdout.decode("utf-8")
        pct_after = psutil.cpu_percent(interval=2)

        with open(processed_dir + "/new_bench_{}_run_{}.txt".format(nb_build, i), "w") as text_file:
            text_file.write("CPU utilization at start: {}\n".format(pct_before))
            text_file.write(out)
            text_file.write("CPU utilization at end: {}\n".format(pct_after))

def run(version, NB_RUNS = 5):
    os.chdir(os.path.expanduser('~/polkadot-optimized'))
    bin_dir = 'bin/' + version
    list_of_files = glob.glob(bin_dir + '/polkadot_*.bin')

    # Prepare output directory
    host = socket.gethostname()
    now = datetime.now().strftime("%Y-%b-%d_%Hh%M")
    processed_dir = 'output/' + version + "/" + host + "/" + now
    if not os.path.isdir(processed_dir):
        os.makedirs(processed_dir)

    # Run all numbered binaries polkadot_NB.bin
    # NOTE: Only the main polkadot binary is benchmarked. The worker binaries
    # (polkadot-prepare-worker_NB.bin, polkadot-execute-worker_NB.bin) are
    # only needed for running an actual validator node, not for benchmarking.
    for binary in list_of_files:
        # MODIFIED: Use raw string for regex to avoid escape sequence warning
        nb = int(re.findall(r"_\d+.bin", binary)[0][1:-4])
        perform_benchmark(binary, NB_RUNS, nb, processed_dir, version=version)
        # Copy json build file
        orig_json = binary[:-4] + '.json'
        new_json = processed_dir + '/bench_{}.json'.format(nb)
        shutil.copy2(orig_json, new_json)

    # Run official binary
    binary = bin_dir + '/official_polkadot.bin'
    if not os.path.exists(binary):
        print("Downloading polkadot binary since official_polkadot.bin not found.")
        # MODIFIED: Updated download URL for polkadot-sdk releases
        # Old URL: https://github.com/paritytech/polkadot/releases/download/v{version}/polkadot
        # New URL: https://github.com/paritytech/polkadot-sdk/releases/download/polkadot-{version}/polkadot
        url = "https://github.com/paritytech/polkadot-sdk/releases/download/polkadot-{}/polkadot".format(version)
        print("Downloading from: {}".format(url))
        resp = requests.get(url)
        if resp.status_code != 200:
            print("WARNING: Failed to download official binary (status {}). Skipping official benchmark.".format(resp.status_code))
            print("You may need to download it manually from the releases page.")
        else:
            with open(binary, "wb") as f: # opening a file handler to create new file
                f.write(resp.content)

    if os.path.exists(binary):
        if not os.access(binary, os.X_OK):
            print("Setting executable permission for official_polkadot.bin.")
            os.chmod(binary, stat.S_IXUSR)
        perform_benchmark(binary, NB_RUNS, "official", processed_dir, version=version)
    else:
        print("Skipping official binary benchmark - file not found.")

    # Run in Docker
    # MODIFIED: Docker image tags now use polkadot-{version} format
    # Note: Docker benchmarks may not be available for all versions
    # Check https://hub.docker.com/r/parity/polkadot/tags for available tags
    print("Attempting Docker benchmark (may fail if image not available)...")
    try:
        perform_benchmark(None, NB_RUNS, "docker", processed_dir, docker=True, version=version)
    except Exception as e:
        print("Docker benchmark failed: {}".format(e))
        print("This is expected if the Docker image is not available for this version.")
    # sudo docker run --rm -it parity/polkadot:vVER benchmark machine --disk-duration 30





if __name__=="__main__":
    # MODIFIED: Updated version format for polkadot-sdk
    # Old format: "0.9.27"
    # New format: "stable2509-2" (corresponds to v1.20.2)
    version = "stable2509-2"
    NB_RUNS = 20
    # For testing:
    # NB_RUNS = 2
    run(version, NB_RUNS)


