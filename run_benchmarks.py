#!/usr/bin/env python3

# Copyright 2022 https://www.math-crypto.com
# GNU General Public License
#
# Updated 2024 for polkadot-sdk compatibility
# Updated 2024-11 with single binary benchmarking mode

# Script to benchmark polkadot binaries.
#
# USAGE:
#   # Benchmark a single binary (e.g., patched build)
#   python run_benchmarks.py --binary /path/to/polkadot --runs 5
#
#   # Benchmark single binary and compare with official release
#   python run_benchmarks.py --binary /path/to/polkadot --compare-official --runs 5
#
#   # Benchmark all binaries in version directory (original behavior)
#   python run_benchmarks.py --version stable2509-2 --all --runs 20
#
# OUTPUT:
#   Results are saved to ~/optimized-builds/output/{version or 'single'}/{hostname}/{datetime}/
#
# NOTE: Only the main 'polkadot' binary is used for benchmarking.
# The worker binaries are only needed when running an actual node.

import subprocess
import sys
import os
import stat
import socket
import argparse
from datetime import datetime
import psutil  # pip install psutil
import glob
import re
import shutil
from pathlib import Path
import requests


def perform_benchmark(binary, nb_runs, build_label, output_dir, skip_extrinsic=False):
    """Run machine and extrinsic benchmarks for a single binary."""

    print(f"\n{'='*60}")
    print(f"Benchmarking: {build_label}")
    print(f"Binary: {binary}")
    print(f"Runs: {nb_runs}")
    print(f"{'='*60}\n")

    # Machine benchmark
    for i in range(nb_runs):
        print(f"Machine benchmark run {i+1}/{nb_runs} for {build_label}")

        pct_before = psutil.cpu_percent(interval=2)
        bench = subprocess.run(
            [binary, "benchmark", "machine", "--disk-duration", "30"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        out = bench.stdout.decode("utf-8")
        pct_after = psutil.cpu_percent(interval=2)

        output_file = os.path.join(output_dir, f"bench_{build_label}_run_{i}.txt")
        with open(output_file, "w") as f:
            f.write(f"CPU utilization at start: {pct_before}\n")
            f.write(out)
            f.write(f"CPU utilization at end: {pct_after}\n")

    if skip_extrinsic:
        return

    # Extrinsic benchmark (fewer runs, takes longer)
    extrinsic_runs = max(4, nb_runs // 5)
    for i in range(extrinsic_runs):
        print(f"Extrinsic benchmark run {i+1}/{extrinsic_runs} for {build_label}")

        pct_before = psutil.cpu_percent(interval=2)
        bench = subprocess.run(
            [binary, 'benchmark', 'extrinsic', '--pallet', 'system', '--extrinsic', 'remark', '--dev'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        out = bench.stdout.decode("utf-8")
        pct_after = psutil.cpu_percent(interval=2)

        output_file = os.path.join(output_dir, f"extrinsic_{build_label}_run_{i}.txt")
        with open(output_file, "w") as f:
            f.write(f"CPU utilization at start: {pct_before}\n")
            f.write(out)
            f.write(f"CPU utilization at end: {pct_after}\n")


def download_official_binary(version, output_path):
    """Download official Parity binary for comparison."""
    url = f"https://github.com/paritytech/polkadot-sdk/releases/download/polkadot-{version}/polkadot"
    print(f"\nDownloading official binary from:")
    print(f"  {url}")

    try:
        resp = requests.get(url, timeout=120)
        if resp.status_code != 200:
            print(f"WARNING: Failed to download (HTTP {resp.status_code})")
            print(f"Download manually from: https://github.com/paritytech/polkadot-sdk/releases/tag/polkadot-{version}")
            return None

        with open(output_path, "wb") as f:
            f.write(resp.content)
        os.chmod(output_path, stat.S_IRWXU)
        print("Downloaded successfully.")
        return output_path
    except requests.exceptions.RequestException as e:
        print(f"WARNING: Download failed: {e}")
        return None


def benchmark_single(binary_path, nb_runs, output_dir, compare_official=False, version=None, skip_extrinsic=False):
    """Benchmark a single binary, optionally comparing with official."""

    if not os.path.exists(binary_path):
        print(f"ERROR: Binary not found: {binary_path}")
        sys.exit(1)

    if not os.access(binary_path, os.X_OK):
        print(f"Setting executable permission for {binary_path}")
        os.chmod(binary_path, stat.S_IRWXU)

    # Create output directory
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    print(f"Output will be saved to: {output_dir}")

    # Determine build label from path
    build_label = Path(binary_path).stem
    if build_label == "polkadot":
        # Use parent directory name for context
        parent = Path(binary_path).parent.name
        build_label = f"custom_{parent}"

    # Save metadata
    metadata = {
        "binary_path": str(binary_path),
        "build_label": build_label,
        "nb_runs": nb_runs,
        "compare_official": compare_official,
        "version": version,
        "timestamp": datetime.now().isoformat(),
    }
    with open(os.path.join(output_dir, "benchmark_info.json"), "w") as f:
        import json
        json.dump(metadata, f, indent=2)

    # Benchmark the custom binary
    perform_benchmark(binary_path, nb_runs, build_label, output_dir, skip_extrinsic)

    # Optionally benchmark official for comparison
    if compare_official:
        if not version:
            print("WARNING: --version required for --compare-official. Skipping official benchmark.")
        else:
            official_path = os.path.join(output_dir, "official_polkadot")
            if not os.path.exists(official_path):
                official_path = download_official_binary(version, official_path)

            if official_path:
                perform_benchmark(official_path, nb_runs, "official", output_dir, skip_extrinsic)

    print(f"\n{'='*60}")
    print("Benchmarking complete!")
    print(f"Results saved to: {output_dir}")
    print("Run analyze_benchmarks.py to compare results.")
    print(f"{'='*60}")


def benchmark_all(version, nb_runs, base_dir):
    """Benchmark all binaries in version directory (original behavior)."""

    bin_dir = os.path.join(base_dir, 'bin', version)
    list_of_files = glob.glob(os.path.join(bin_dir, 'polkadot_*.bin'))

    if not list_of_files:
        print(f"ERROR: No polkadot binaries found in {bin_dir}")
        print(f"Make sure you've run compile.py first with version = '{version}'")
        sys.exit(1)

    # Prepare output directory
    host = socket.gethostname()
    now = datetime.now().strftime("%Y-%b-%d_%Hh%M")
    output_dir = os.path.join(base_dir, 'output', version, host, now)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    print(f"Found {len(list_of_files)} compiled binaries to benchmark")
    print(f"Output will be saved to: {output_dir}")
    print("")

    # Benchmark all numbered binaries
    for binary in list_of_files:
        nb = int(re.findall(r"_\d+.bin", binary)[0][1:-4])
        perform_benchmark(binary, nb_runs, str(nb), output_dir)

        # Copy json build file
        orig_json = binary[:-4] + '.json'
        if os.path.exists(orig_json):
            new_json = os.path.join(output_dir, f'bench_{nb}.json')
            shutil.copy2(orig_json, new_json)

    # Run official binary for comparison
    official_path = os.path.join(bin_dir, 'official_polkadot.bin')
    if not os.path.exists(official_path):
        official_path = download_official_binary(version, official_path)

    if official_path and os.path.exists(official_path):
        perform_benchmark(official_path, nb_runs, "official", output_dir)

    print("")
    print("Benchmarking complete!")
    print(f"Results saved to: {output_dir}")
    print("Run analyze_benchmarks.py to compare results.")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Polkadot binaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark a single binary (quick test)
  %(prog)s --binary ./polkadot --runs 3

  # Benchmark patched build and compare with official
  %(prog)s --binary ./polkadot --compare-official --version stable2509-2 --runs 5

  # Benchmark all builds in version directory
  %(prog)s --version stable2509-2 --all --runs 20

  # Quick machine-only benchmark (skip extrinsic)
  %(prog)s --binary ./polkadot --runs 3 --skip-extrinsic
        """
    )

    parser.add_argument('--binary', '-b', type=str,
                        help='Path to a single polkadot binary to benchmark')
    parser.add_argument('--version', '-v', type=str, default='stable2509-2',
                        help='Polkadot version (default: stable2509-2)')
    parser.add_argument('--runs', '-r', type=int, default=5,
                        help='Number of benchmark runs (default: 5)')
    parser.add_argument('--all', '-a', action='store_true',
                        help='Benchmark all binaries in version directory')
    parser.add_argument('--compare-official', '-c', action='store_true',
                        help='Also benchmark official Parity binary for comparison')
    parser.add_argument('--skip-extrinsic', '-s', action='store_true',
                        help='Skip extrinsic benchmarks (faster, machine benchmark only)')
    parser.add_argument('--output-dir', '-o', type=str,
                        help='Custom output directory (default: auto-generated)')
    parser.add_argument('--base-dir', type=str,
                        default=os.path.expanduser('~/optimized-builds'),
                        help='Base directory for builds (default: ~/optimized-builds)')

    args = parser.parse_args()

    # Validate arguments
    if args.binary and args.all:
        parser.error("Cannot use both --binary and --all")

    if not args.binary and not args.all:
        parser.error("Must specify either --binary or --all")

    if args.binary:
        # Single binary mode
        if args.output_dir:
            output_dir = args.output_dir
        else:
            host = socket.gethostname()
            now = datetime.now().strftime("%Y-%b-%d_%Hh%M")
            output_dir = os.path.join(args.base_dir, 'output', 'single', host, now)

        benchmark_single(
            args.binary,
            args.runs,
            output_dir,
            compare_official=args.compare_official,
            version=args.version,
            skip_extrinsic=args.skip_extrinsic
        )
    else:
        # All binaries mode
        benchmark_all(args.version, args.runs, args.base_dir)


if __name__ == "__main__":
    main()
