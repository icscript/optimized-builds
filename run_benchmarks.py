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
# Both directories are hard-coded so change this in the code
# below if needed.
#
# Beware that benchmarking takes a while!
# It is advisable to run the script in a screen session.
#
# NOTE: Only the main 'polkadot' binary is used for benchmarking.
# The worker binaries (polkadot-prepare-worker, polkadot-execute-worker)
# are only needed when running an actual node, not for benchmarks.

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


def perform_benchmark(binary, NB_RUNS, nb_build, processed_dir):
    for i in range(NB_RUNS):
        print("Performing benchmark run {} for polkadot build {}".format(i, nb_build))

        pct_before = psutil.cpu_percent(interval=2)
        bench = subprocess.run([binary, "benchmark", "machine", "--disk-duration", "30"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = bench.stdout.decode("utf-8")
        pct_after = psutil.cpu_percent(interval=2)

        with open(processed_dir + "/bench_{}_run_{}.txt".format(nb_build, i), "w") as text_file:
            text_file.write("CPU utilization at start: {}\n".format(pct_before))
            text_file.write(out)
            text_file.write("CPU utilization at end: {}\n".format(pct_after))

    # Extrinsic benchmark (added in v0.9.27)
    # NOTE: Changed from '--chain polkadot-dev' to '--dev' for polkadot-sdk compatibility
    # The polkadot-dev chain was removed when native runtime was removed from the node
    # Number of extrinsic runs is 1/5 of machine benchmark runs
    extrinsic_runs = max(4, NB_RUNS // 5)
    for i in range(extrinsic_runs):
        print("Performing extrinsic benchmark run {} for polkadot build {}".format(i, nb_build))

        pct_before = psutil.cpu_percent(interval=2)
        bench = subprocess.run([binary, 'benchmark', 'extrinsic', '--pallet', 'system', '--extrinsic', 'remark', '--dev'],
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

    if not list_of_files:
        print("ERROR: No polkadot binaries found in {}".format(bin_dir))
        print("Make sure you've run compile.py first with version = '{}'".format(version))
        sys.exit(1)

    # Prepare output directory
    host = socket.gethostname()
    now = datetime.now().strftime("%Y-%b-%d_%Hh%M")
    processed_dir = 'output/' + version + "/" + host + "/" + now
    if not os.path.isdir(processed_dir):
        os.makedirs(processed_dir)

    print("Found {} compiled binaries to benchmark".format(len(list_of_files)))
    print("Output will be saved to: {}".format(processed_dir))
    print("")

    # Run all numbered binaries polkadot_NB.bin
    # NOTE: Only the main polkadot binary is benchmarked. The worker binaries
    # (polkadot-prepare-worker_NB.bin, polkadot-execute-worker_NB.bin) are
    # only needed for running an actual validator node, not for benchmarking.
    for binary in list_of_files:
        # Use raw string for regex to avoid escape sequence warning
        nb = int(re.findall(r"_\d+.bin", binary)[0][1:-4])
        perform_benchmark(binary, NB_RUNS, nb, processed_dir)
        # Copy json build file
        orig_json = binary[:-4] + '.json'
        new_json = processed_dir + '/bench_{}.json'.format(nb)
        shutil.copy2(orig_json, new_json)

    # Run official binary for comparison
    # Downloads from GitHub releases if not already present
    binary = bin_dir + '/official_polkadot.bin'
    if not os.path.exists(binary):
        print("")
        print("Downloading official polkadot binary for comparison...")
        # Download URL for polkadot-sdk releases
        url = "https://github.com/paritytech/polkadot-sdk/releases/download/polkadot-{}/polkadot".format(version)
        print("URL: {}".format(url))
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code != 200:
                print("WARNING: Failed to download official binary (HTTP {}).".format(resp.status_code))
                print("Skipping official benchmark. You can download manually from:")
                print("  https://github.com/paritytech/polkadot-sdk/releases/tag/polkadot-{}".format(version))
                binary = None
            else:
                with open(binary, "wb") as f:
                    f.write(resp.content)
                print("Downloaded successfully.")
        except requests.exceptions.RequestException as e:
            print("WARNING: Failed to download official binary: {}".format(e))
            print("Skipping official benchmark.")
            binary = None

    if binary and os.path.exists(binary):
        if not os.access(binary, os.X_OK):
            print("Setting executable permission for official_polkadot.bin.")
            os.chmod(binary, stat.S_IXUSR)
        perform_benchmark(binary, NB_RUNS, "official", processed_dir)

    print("")
    print("Benchmarking complete!")
    print("Results saved to: {}".format(processed_dir))
    print("Run parse_benchmarks.py to analyze results.")


if __name__=="__main__":
    # ==========================================================================
    # CONFIGURATION - Update these values as needed
    # ==========================================================================

    # Polkadot version to benchmark
    # This should match the version used in compile.py
    # Format: "stable2509-2" (corresponds to polkadot v1.20.2)
    # See releases at: https://github.com/paritytech/polkadot-sdk/releases
    version = "stable2509-2"

    # Number of benchmark runs per binary (more runs = more accurate results)
    # Each run takes ~30-60 seconds, so 20 runs ≈ 10-20 minutes per binary
    NB_RUNS = 20
    # For quick testing:
    # NB_RUNS = 2

    # ==========================================================================

    run(version, NB_RUNS)
