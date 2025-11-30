#!/usr/bin/env python3

# Copyright 2022 https://www.math-crypto.com
# GNU General Public License
#
# Updated 2024 for polkadot-sdk compatibility
# Updated 2024-11: Removed source downloading (now handled by prepare_source.py)

# Script to compile polkadot with various optimization options.
#
# PREREQUISITES:
#   Run prepare_source.py first to download and patch the source.
#
# USAGE:
#   python compile.py
#
# The binaries are placed in ~/optimized-builds/bin/VERSION
# Beware that compiling takes a while (about 30 min per set of options).
# It is recommended to run the script in a screen session.

import subprocess
import os
import shutil
import re
import glob
import json
import sys
import datetime
import dateutil.relativedelta
import itertools

import tomlkit
from pathlib import Path


def extract_largest_number(files):
    if len(files) == 0:
        return -1
    else:
        return max([int(re.findall(r"_\d+.bin", f)[0][1:-4]) for f in files])


def hours_minutes(dt1, dt2):
    rd = dateutil.relativedelta.relativedelta(dt2, dt1)
    return "{}H {}M {}S".format(rd.hours, rd.minutes, rd.seconds)


def run(cmd, work_dir, log_file, env=None):
    os.chdir(work_dir)
    with open(log_file, "a+") as log:
        if env is None:
            subprocess.run(cmd, shell=True, check=True, universal_newlines=True, stderr=log)
        else:
            subprocess.run(cmd, shell=True, check=True, universal_newlines=True, stderr=log, env=env)


def verify_binary(binary_path):
    """Verify binary has expected SIMD characteristics.

    Checks for:
    - Hand-tuned BLAKE2 AVX2 code (blake2b_simd::avx2::compress1_loop)
    - Count of zmm (AVX-512) instructions
    - Count of ymm (AVX2) instructions

    Returns dict with verification results.
    """
    results = {
        'has_blake2_avx2': False,
        'blake2_avx2_symbols': [],
        'zmm_count': 0,
        'ymm_count': 0,
        'warnings': [],
    }

    if not os.path.exists(binary_path):
        results['warnings'].append(f"Binary not found: {binary_path}")
        return results

    # Check for hand-tuned BLAKE2 AVX2 symbols
    try:
        objdump_result = subprocess.run(
            ['objdump', '-t', binary_path],
            capture_output=True, text=True, timeout=60
        )
        for line in objdump_result.stdout.split('\n'):
            if 'blake2b_simd' in line and 'avx2' in line.lower():
                results['blake2_avx2_symbols'].append(line.strip().split()[-1])
                results['has_blake2_avx2'] = True
    except Exception as e:
        results['warnings'].append(f"Failed to check symbols: {e}")

    # Count SIMD instructions (zmm = AVX-512, ymm = AVX2)
    # Use grep -c to count lines containing the register (one per instruction)
    try:
        # Count zmm (AVX-512) instructions
        zmm_result = subprocess.run(
            f"objdump -d '{binary_path}' | grep -c zmm",
            shell=True, capture_output=True, text=True, timeout=300
        )
        results['zmm_count'] = int(zmm_result.stdout.strip()) if zmm_result.returncode == 0 else 0

        # Count ymm (AVX2) instructions
        ymm_result = subprocess.run(
            f"objdump -d '{binary_path}' | grep -c ymm",
            shell=True, capture_output=True, text=True, timeout=300
        )
        results['ymm_count'] = int(ymm_result.stdout.strip()) if ymm_result.returncode == 0 else 0
    except Exception as e:
        results['warnings'].append(f"Failed to count instructions: {e}")

    # Reference values from official Parity build
    OFFICIAL_ZMM = 2018
    OFFICIAL_YMM = 15787

    # Add warnings for unexpected values
    if not results['has_blake2_avx2']:
        results['warnings'].append("WARNING: Hand-tuned BLAKE2 AVX2 code NOT found!")

    if results['zmm_count'] > OFFICIAL_ZMM * 10:
        results['warnings'].append(
            f"WARNING: High AVX-512 count ({results['zmm_count']:,} vs {OFFICIAL_ZMM:,} official) - "
            "may indicate excessive auto-vectorization"
        )

    if results['ymm_count'] > OFFICIAL_YMM * 10:
        results['warnings'].append(
            f"WARNING: High AVX2 count ({results['ymm_count']:,} vs {OFFICIAL_YMM:,} official) - "
            "may indicate excessive auto-vectorization"
        )

    return results


def print_verification(results):
    """Print binary verification results."""
    print("\n" + "-" * 60)
    print("Binary Verification:")
    print("-" * 60)

    # BLAKE2 AVX2 status
    if results['has_blake2_avx2']:
        print(f"  Hand-tuned BLAKE2 AVX2: YES ✓")
        for sym in results['blake2_avx2_symbols'][:3]:
            print(f"    - {sym}")
    else:
        print(f"  Hand-tuned BLAKE2 AVX2: NO ✗")

    # Instruction counts
    print(f"  AVX-512 (zmm) instructions: {results['zmm_count']:,}")
    print(f"  AVX2 (ymm) instructions:    {results['ymm_count']:,}")
    print(f"  (Official reference: zmm=2,018  ymm=15,787)")

    # Warnings
    if results['warnings']:
        print("")
        for warning in results['warnings']:
            print(f"  {warning}")


def check_source(base_dir):
    """Check if polkadot-sdk source exists and is properly set up."""
    sdk_dir = os.path.join(base_dir, "polkadot-sdk")

    if not os.path.isdir(sdk_dir):
        return None, "not_found"

    # Check for .source-info marker
    info_path = os.path.join(sdk_dir, ".source-info")
    if os.path.exists(info_path):
        with open(info_path, "r") as f:
            info = json.load(f)
        return info, "ready"

    # Check Cargo.toml for patch section (legacy check)
    cargo_toml = os.path.join(sdk_dir, "Cargo.toml")
    if os.path.exists(cargo_toml):
        with open(cargo_toml, "r") as f:
            config = tomlkit.load(f)
        has_patch = "patch" in config and "crates-io" in config.get("patch", {})
        return {"version": "unknown", "patched": has_patch}, "legacy"

    return {"version": "unknown", "patched": False}, "unknown"


def prompt_yes_no(question, default=True):
    """Prompt user for yes/no answer."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(question + suffix).strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'")


def compile(version, opts, base_dir):
    print("\n" + "=" * 60)
    print(" STARTING COMPILATION ")
    print("=" * 60)
    print(f"Options: {opts}")
    print(f"Version: {version}")

    # Prepare build directory
    os.chdir(base_dir)
    bin_dir = os.path.join('bin', version)
    if not os.path.isdir(bin_dir):
        os.makedirs(bin_dir)

    # Check if opts was not compiled before
    list_of_files = glob.glob(os.path.join(bin_dir, 'polkadot_*.json'))
    for f in list_of_files:
        with open(f, "r") as file:
            json_dict = json.load(file)
            if json_dict.get('build_options') == opts:
                print(f"Build with these options already exists, skipping.")
                return

    # Get number of new polkadot build, set filenames
    list_of_files = glob.glob(os.path.join(bin_dir, 'polkadot_*.bin'))
    nb = extract_largest_number(list_of_files) + 1

    new_filename_root = os.path.join(bin_dir, f'polkadot_{nb}')
    log_file = os.path.join(base_dir, new_filename_root + ".log")

    # Source directory
    work_dir = os.path.join(base_dir, 'polkadot-sdk')

    # Set build options via toolchain
    if opts['toolchain'] == 'stable':
        run("rustup override set stable", work_dir, log_file)
    else:
        run("rustup override set nightly", work_dir, log_file)

    # Update the active toolchain
    run("rustup update", work_dir, log_file)

    # Ensure required targets/components
    run("rustup target add wasm32-unknown-unknown", work_dir, log_file)
    run("rustup component add rust-src", work_dir, log_file)

    # Modify Cargo.toml with build profile settings
    config = tomlkit.loads(Path(os.path.join(work_dir, "Cargo.toml")).read_text())
    profile = {}
    profile['inherits'] = 'release'
    profile['codegen-units'] = opts['codegen-units']
    profile['lto'] = opts['lto']
    profile['opt-level'] = opts['opt-level']

    config['profile']['production'] = profile
    with Path(os.path.join(work_dir, "Cargo.toml")).open("w") as fout:
        fout.write(tomlkit.dumps(config))

    RUSTFLAGS = ""
    if opts['arch'] is not None:
        RUSTFLAGS = f" -C target-cpu={opts['arch']}"

    # Build command
    cargo_build_opts = ' -p polkadot --profile=production --locked --target=x86_64-unknown-linux-gnu'
    if opts['toolchain'] == 'nightly':
        cargo_build_opts += ' -Z unstable-options'

    cargo_cmd = 'cargo build' + cargo_build_opts
    env = os.environ.copy()
    env["RUSTFLAGS"] = RUSTFLAGS

    # Version suffix for tracking
    toolchain_abbr = 'stb' if opts['toolchain'] == 'stable' else 'nightly'
    arch_abbr = opts['arch'] if opts['arch'] else 'default'
    version_suffix = f"{toolchain_abbr}-{arch_abbr}-cu{opts['codegen-units']}-{opts['lto']}-opt{opts['opt-level']}-bld{nb}"
    env["SUBSTRATE_CLI_GIT_COMMIT_HASH"] = version_suffix
    print(f"Version suffix: {version_suffix}")

    # Compiler selection (same logic as before)
    if "CC" not in env or "CXX" not in env:
        cc_found = None
        cxx_found = None

        for cc_candidate, cxx_candidate in [
            ("clang-18", "clang++-18"),
            ("gcc-14", "g++-14"),
            ("/usr/lib/llvm18/bin/clang", "/usr/lib/llvm18/bin/clang++"),
            ("/usr/bin/gcc-14", "/usr/bin/g++-14"),
            ("clang", "clang++"),
        ]:
            cc_path = shutil.which(cc_candidate)
            cxx_path = shutil.which(cxx_candidate)
            if cc_path and cxx_path:
                cc_found = cc_candidate
                cxx_found = cxx_candidate
                print(f"Using {cc_candidate}/{cxx_candidate} for C/C++ compilation")
                if cc_candidate == "clang":
                    print("WARNING: Using system default 'clang' - may have compatibility issues")
                break

        if not cc_found:
            print("ERROR: No compatible C/C++ compiler found!")
            raise RuntimeError("No compatible C/C++ compiler found")

        if "CC" not in env:
            env["CC"] = cc_found
        if "CXX" not in env:
            env["CXX"] = cxx_found

    # Build
    dt1 = datetime.datetime.now()
    run(cargo_cmd, work_dir, log_file, env=env)
    dt2 = datetime.datetime.now()

    # Copy binaries
    os.chdir(base_dir)
    target_dir = 'polkadot-sdk/target/x86_64-unknown-linux-gnu/production'
    binaries = ['polkadot', 'polkadot-prepare-worker', 'polkadot-execute-worker']

    for binary in binaries:
        orig_filename = os.path.join(target_dir, binary)
        if binary == 'polkadot':
            shutil.copy2(orig_filename, new_filename_root + ".bin")
        else:
            shutil.copy2(orig_filename, os.path.join(bin_dir, f'{binary}_{nb}.bin'))

    # Verify the binary
    print("\nVerifying binary...")
    verification = verify_binary(new_filename_root + ".bin")
    print_verification(verification)

    # Save build metadata including verification
    json_dict = {
        'build_options': opts,
        'build_time': hours_minutes(dt1, dt2),
        'RUSTFLAGS': RUSTFLAGS,
        'build_command': cargo_cmd,
        'binaries': binaries,
        'version_suffix': version_suffix,
        'verification': {
            'has_blake2_avx2': verification['has_blake2_avx2'],
            'zmm_count': verification['zmm_count'],
            'ymm_count': verification['ymm_count'],
            'warnings': verification['warnings'],
        }
    }

    with open(new_filename_root + ".json", "w") as outfile:
        json.dump(json_dict, outfile, indent=4)

    print(f"\nBuild complete: {new_filename_root}.bin")
    print(f"Build time: {hours_minutes(dt1, dt2)}")


def product_dict(**kwargs):
    keys = kwargs.keys()
    vals = kwargs.values()
    for instance in itertools.product(*vals):
        yield dict(zip(keys, instance))


if __name__ == "__main__":
    # Configuration
    version = 'stable2509-2'
    base_dir = os.path.expanduser('~/optimized-builds')

    print("=" * 60)
    print("Polkadot Compilation Script")
    print("=" * 60)

    # Check for source
    source_info, status = check_source(base_dir)

    if status == "not_found":
        print("\nERROR: polkadot-sdk source not found!")
        print(f"Expected at: {os.path.join(base_dir, 'polkadot-sdk')}")
        print("\nRun prepare_source.py first:")
        print(f"  python prepare_source.py --version {version}")
        sys.exit(1)

    print(f"\nSource found:")
    print(f"  Version: {source_info.get('version', 'unknown')}")
    print(f"  Patched: {source_info.get('patched', False)}")

    # Build options
    opts = []

    # Recommended build with patches (target-cpu=native now works!)
    opts.append({'toolchain': 'stable', 'arch': 'native', 'codegen-units': 1, 'lto': 'fat', 'opt-level': 3})

    # Check if building with native on unpatched source
    uses_native = any(o.get('arch') == 'native' for o in opts)
    if uses_native and not source_info.get('patched', False):
        print("\n" + "!" * 60)
        print("WARNING: Building with target-cpu=native on UNPATCHED source!")
        print("This will eliminate hand-tuned BLAKE2 AVX2 optimizations.")
        print("!" * 60)
        if not prompt_yes_no("Continue anyway?", default=False):
            print("\nRun prepare_source.py to apply patches:")
            print(f"  python prepare_source.py --version {version} --force")
            sys.exit(1)

    print(f"\nBuilding {len(opts)} configuration(s)...")

    for opt in opts:
        compile(version, opt, base_dir)

    print("\n" + "=" * 60)
    print("All builds complete!")
    print("=" * 60)
    print(f"\nBinaries saved to: {os.path.join(base_dir, 'bin', version)}")
    print("Run run_benchmarks.py to benchmark the builds.")
