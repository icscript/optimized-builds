#!/usr/bin/env python3

# Copyright 2022 https://www.math-crypto.com
# GNU General Public License
#
# Updated 2024 for polkadot-sdk compatibility

# Script to compile a specific release of polkadot with many different
# sets of optimization options (specified in the code down below, look
# for the ##########).
#
# The binaries are placed in
#     ~/polkadot-optimized/bin/VERSION
# (change this in the code below if needed).
# Beware that compiling takes a while (about 30 min per set of options).
# It is recommended to run the script in, for example, a screen session.

from operator import truediv
import subprocess
import os
import shutil
import re
import glob
import json
import logging

import datetime
import dateutil.relativedelta
import itertools

import tomlkit
from pathlib import Path

def extract_largest_number(files):
    if len(files) == 0:
        return -1
    else:
        return max([int(re.findall(r"_\d+.bin",f)[0][1:-4]) for f in files])

def hours_minutes(dt1, dt2):
    rd = dateutil.relativedelta.relativedelta(dt2, dt1)
    return "{}H {}M {}S".format(rd.hours, rd.minutes, rd.seconds)

def run(cmd, work_dir, log_file, env=None):
    os.chdir(work_dir)
    with open(log_file, "a+") as log:
        if env==None:
            subprocess.run(cmd, shell=True, check=True, universal_newlines=True, stderr=log)
        else:
            subprocess.run(cmd, shell=True, check=True, universal_newlines=True, stderr=log, env=env)

def compile(version, opts):
    print(" === STARTING COMPILATION === ")
    print(opts)
    print(version)

    # Prepare build directory
    os.chdir(os.path.expanduser('~/polkadot-optimized'))
    bin_dir = 'bin/' + version
    if not os.path.isdir(bin_dir):
        os.makedirs(bin_dir)

    # Check if opts was not compiled before
    list_of_files = glob.glob(bin_dir + '/polkadot_*.json')
    for f in list_of_files:
        with open(f, "r") as file:
            json_dict = json.load(file)
            if json_dict['build_options']==opts:
                return

    # Get number of new polkadot build, set filenames
    list_of_files = glob.glob(bin_dir + '/polkadot_*.bin')
    nb = extract_largest_number(list_of_files) + 1

    new_filename_root = bin_dir + '/polkadot_{}'.format(nb)
    log_file = os.path.expanduser('~/polkadot-optimized/' + new_filename_root + ".log")

    # MODIFIED: Changed from 'polkadot' to 'polkadot-sdk' for new repo structure
    if os.path.isdir('polkadot-sdk'):
        shutil.rmtree('polkadot-sdk')

    # Download and extract release tarball
    work_dir = os.path.expanduser('~/polkadot-optimized')

    # Download the official release tarball instead of git clone
    # Release tarballs often have better vendored dependencies than git clones
    # MODIFIED: Changed from git clone to tarball download for better compatibility
    tarball_url = "https://github.com/paritytech/polkadot-sdk/archive/refs/tags/polkadot-{}.tar.gz".format(version)
    tarball_file = "polkadot-{}.tar.gz".format(version)

    run("curl -L -o {} {}".format(tarball_file, tarball_url), work_dir, log_file)
    run("tar -xzf {}".format(tarball_file), work_dir, log_file)
    run("rm {}".format(tarball_file), work_dir, log_file)

    # Rename extracted directory to polkadot-sdk for consistency
    # GitHub tarballs extract to polkadot-sdk-polkadot-{version} format
    extracted_dir = "polkadot-sdk-polkadot-{}".format(version)
    run("mv {} polkadot-sdk".format(extracted_dir), work_dir, log_file)

    # MODIFIED: Updated work_dir path from 'polkadot' to 'polkadot-sdk'
    work_dir = os.path.expanduser('~/polkadot-optimized/polkadot-sdk')

    # MODIFIED: REMOVED init.sh call - polkadot-sdk is a monorepo and doesn't need/have init.sh
    # The old paritytech/polkadot repo required: run("./scripts/init.sh", work_dir, log_file)
    # This is no longer needed in the new polkadot-sdk structure

    # Set build options
    if opts['toolchain'] == 'stable':
        run("rustup override set stable", work_dir, log_file)
    else:
        run("rustup override set nightly", work_dir, log_file)
        # subprocess.Popen("rustup override set nightly", shell=True, check=True, universal_newlines=True)

    run("cargo fetch", work_dir, log_file)

    ## OLD CODE WITH RUSTFLAGS
    # RUSTFLAGS = "-C opt-level=3"
    # if not opts['arch'] == None:
    #     RUSTFLAGS = RUSTFLAGS + " -C target-cpu={}".format(opts['arch'])
    # if opts['codegen']:
    #     RUSTFLAGS = RUSTFLAGS + " -C codegen-units=1"
    # if opts['lto_ldd']:
    #     RUSTFLAGS = RUSTFLAGS + " -C linker-plugin-lto -C linker=clang -C link-arg=-fuse-ld=lld"
    # # Does not work
    # #if opts['lto']:
    # #    RUSTFLAGS = RUSTFLAGS + " -C embed-bitcode -C lto=fat"

    # # Start building
    # cargo_build_opts = ' --profile={} --locked --target=x86_64-unknown-linux-gnu'.format(opts['profile'])

    ## NEW CODE AS CUSTOM PROFILE (
    # It overwrites the production profile -- otherwise still build errors.
    # NOTE: In polkadot-sdk, the Cargo.toml with profiles is in the root directory
    config = tomlkit.loads(Path(work_dir + "/Cargo.toml").read_text())
    profile = {}
    # TODO test if arch can be set here
    # if not opts['arch'] == None:
    #     profile['arch'] = opts['arch']
    profile['inherits'] = 'release'
    profile['codegen-units'] = opts['codegen-units']
    profile['lto'] = opts['lto']
    profile['opt-level'] = opts['opt-level']

    config['profile']['production'] = profile
    with Path(work_dir + "/Cargo.toml").open("w") as fout:
        fout.write(tomlkit.dumps(config))

    RUSTFLAGS = ""
    # TODO test if arch can be set in profile
    if not opts['arch'] == None:
        RUSTFLAGS = RUSTFLAGS + " -C target-cpu={}".format(opts['arch'])

    # Start building
    # MODIFIED: Added -p polkadot to build only the polkadot package (and its dependencies)
    # This builds all 3 binaries: polkadot, polkadot-execute-worker, polkadot-prepare-worker
    cargo_build_opts = ' -p polkadot --profile=production --locked --target=x86_64-unknown-linux-gnu'

    if opts['toolchain'] == 'nightly':
        cargo_build_opts = cargo_build_opts + ' -Z unstable-options'

    cargo_cmd = 'cargo build ' + cargo_build_opts
    env = os.environ.copy()
    env["RUSTFLAGS"] =  RUSTFLAGS

    # Generate custom version suffix from build options for tracking
    # Format: {toolchain}-{arch}-cu{codegen-units}-{lto}-opt{opt-level}-bld{build_number}
    # Example: stb-native-cu1-fat-opt3-bld0
    # This is more useful than git hash for performance comparison
    toolchain_abbr = 'stb' if opts['toolchain'] == 'stable' else 'nightly'
    arch_abbr = opts['arch'] if opts['arch'] else 'default'
    version_suffix = f"{toolchain_abbr}-{arch_abbr}-cu{opts['codegen-units']}-{opts['lto']}-opt{opts['opt-level']}-bld{nb}"
    env["SUBSTRATE_CLI_GIT_COMMIT_HASH"] = version_suffix
    print(f"Version suffix: {version_suffix}")

    # Compiler selection for C/C++ dependencies (RocksDB, etc.)
    # Polkadot SDK docs recommend clang: https://docs.polkadot.com/develop/parachains/install-polkadot-sdk/
    # However, newer compilers have compatibility issues:
    # - GCC 15+ and clang 19+ have stricter type checking that breaks RocksDB's headers
    # - On bleeding-edge distros (Arch), even clang-18 links against GCC 15's libstdc++, causing failures
    # Solution: Prefer gcc-14 (provides both compatible compiler + libstdc++)
    # Falls back to clang-18 on stable distros (Ubuntu) where it links to older GCC stdlib
    # You can override by setting CC/CXX environment variables before running this script
    if "CC" not in env or "CXX" not in env:
        cc_found = None
        cxx_found = None

        # Try compatible compilers in order of preference
        # clang-18 and gcc-14 are known to work with RocksDB in polkadot-stable2509
        # On Arch, clang18 package installs to /usr/lib/llvm18/bin/
        # On Arch, gcc14 installs to /usr/bin/gcc-14 and /usr/bin/g++-14
        # IMPORTANT: Even clang-18 uses the system libstdc++, so on Arch with GCC 15
        #            we need GCC 14 to get compatible libstdc++
        for cc_candidate, cxx_candidate in [
            ("gcc-14", "g++-14"),                                            # Prefer GCC 14 on Arch
            ("/usr/bin/gcc-14", "/usr/bin/g++-14"),                        # Explicit Arch path
            ("/usr/lib/llvm18/bin/clang", "/usr/lib/llvm18/bin/clang++"),  # Arch clang18 path
            ("clang-18", "clang++-18"),                                     # Ubuntu/Debian clang18
            ("clang", "clang++"),
        ]:
            cc_path = shutil.which(cc_candidate)
            cxx_path = shutil.which(cxx_candidate)
            if cc_path and cxx_path:
                cc_found = cc_candidate
                cxx_found = cxx_candidate
                print(f"Using {cc_candidate}/{cxx_candidate} for C/C++ compilation")
                break

        if not cc_found:
            print("ERROR: No compatible C/C++ compiler found!")
            print("Polkadot SDK requires clang for building.")
            print("However, newer compilers (clang 19+, GCC 15+) have compatibility issues with RocksDB.")
            print("")
            print("Please install a compatible compiler:")
            print("  Arch/CachyOS: sudo pacman -S clang18")
            print("  Or:           sudo pacman -S gcc14")
            print("")
            print("See official requirements:")
            print("  https://docs.polkadot.com/develop/parachains/install-polkadot-sdk/")
            raise RuntimeError("No compatible C/C++ compiler found")

        if "CC" not in env:
            env["CC"] = cc_found
        if "CXX" not in env:
            env["CXX"] = cxx_found

    dt1 = datetime.datetime.now()
    run(cargo_cmd, work_dir, log_file, env=env)
    dt2 = datetime.datetime.now()

    ## Copy new polkadot files
    os.chdir(os.path.expanduser('~/polkadot-optimized'))

    # MODIFIED: Updated path from 'polkadot/' to 'polkadot-sdk/'
    target_dir = 'polkadot-sdk/target/x86_64-unknown-linux-gnu/production'

    # MODIFIED: Now copying all 3 required binaries instead of just 1
    # polkadot-sdk produces 3 binaries that all need to be deployed together:
    # - polkadot: main node binary
    # - polkadot-prepare-worker: PVF preparation worker
    # - polkadot-execute-worker: PVF execution worker
    binaries = ['polkadot', 'polkadot-prepare-worker', 'polkadot-execute-worker']

    for binary in binaries:
        orig_filename = '{}/{}'.format(target_dir, binary)
        if binary == 'polkadot':
            # Main binary keeps the numbered naming for benchmark compatibility
            shutil.copy2(orig_filename, new_filename_root + ".bin")
        else:
            # Worker binaries use their original names with build number suffix
            shutil.copy2(orig_filename, bin_dir + '/{}_{}.bin'.format(binary, nb))

    json_dict = {}
    json_dict['build_options'] = opts
    json_dict['build_time'] = hours_minutes(dt1, dt2)
    json_dict['RUSTFLAGS'] = RUSTFLAGS
    json_dict['build_command'] = cargo_cmd
    # MODIFIED: Added list of binaries to JSON for reference
    json_dict['binaries'] = binaries

    json_object = json.dumps(json_dict, indent=4)
    with open(new_filename_root + ".json", "w") as outfile:
        outfile.write(json_object)

# https://stackoverflow.com/questions/5228158/cartesian-product-of-a-dictionary-of-lists
def product_dict(**kwargs):
    keys = kwargs.keys()
    vals = kwargs.values()
    for instance in itertools.product(*vals):
        yield dict(zip(keys, instance))

if __name__ == "__main__":
    # MODIFIED: Updated version format for polkadot-sdk
    # Old format: '0.9.27' (used with v{version} tag)
    # New format: 'stable2509-2' (used with polkadot-{version} tag)
    # This corresponds to polkadot v1.20.2
    # See releases at: https://github.com/paritytech/polkadot-sdk/releases
    version = 'stable2509-2'

    # # All the options tested for analysis on website
    # dict_opts = {'toolchain': ['stable', 'nightly'],
    #             'arch':      [None, 'alderlake'],  # use native if other arch
    #             'codegen-units':   [1, 16],
    #             'lto':       ['off', 'fat', 'thin'],
    #             'opt-level': [2, 3]
    #             }
    # opts = list(product_dict(**dict_opts))

    # Only the good builds after analysis - takes about 4 hours to build
    # SUGGESTION: For initial testing, comment out all but one option to verify
    # the build process works before running all 5 configurations
    # nightly/stable refers to RUST compiler nightly vs stable releases.
    opts = []
    opts.append({'toolchain': 'stable',  'arch': 'native', 'codegen-units': 1,  'lto': 'fat',  'opt-level': 3}) # build 15
    opts.append({'toolchain': 'stable',  'arch': 'native', 'codegen-units': 16, 'lto': 'fat',  'opt-level': 3}) # build 21
    opts.append({'toolchain': 'nightly', 'arch': 'native', 'codegen-units': 1,  'lto': 'fat',  'opt-level': 2}) # build 38
    opts.append({'toolchain': 'nightly', 'arch': 'native', 'codegen-units': 1,  'lto': 'thin', 'opt-level': 2}) # build 40
    opts.append({'toolchain': 'nightly', 'arch': 'native', 'codegen-units': 16, 'lto': 'fat',  'opt-level': 3}) # build 45

    print("Number of different builds: {}".format(len(opts)))
    for opt in opts:
        compile(version, opt)
