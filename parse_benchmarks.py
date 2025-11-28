#!/usr/bin/env python3

# Copyright 2022 https://www.math-crypto.com
# GNU General Public License
#
# Updated 2024 for polkadot-sdk compatibility

# Script to parse the benchmark files that were generated
# by run_benchmarks.py. It will read all the files in
#   ~/polkadot-optimized/output/VERSION/HOSTNAME/DATE_TIME/
# For each combination of VERSION, HOSTNAME, DATE_TIME a
# pandas dataframe is constructed and stored in
#   ~/polkadot-optimized/processed/todo/
# as a feather object and
#   ~/polkadot-optimized/processed/csv/
# as a csv file. Processed files are then moved to
#   ~/polkadot-optimized/processed/old/
#
# NOTE: This script only processes benchmark results from the main
# polkadot binary. The worker binaries (polkadot-prepare-worker,
# polkadot-execute-worker) don't produce benchmark output.


import re
import pandas as pd
import os
from glob import glob
import shutil
import json
# pip install pyarrow
from datetime import datetime
from pathlib import Path

def convert_to_MiB(score_string):
    # MODIFIED: Use raw string for regex pattern
    raw_nb = float(re.findall(r"[+-]?\d+\.\d+", score_string)[0])
    # Handle both old format (KiB/s, MiB/s, GiB/s) and new format (KiBs, MiBs, GiBs)
    if 'KiB' in score_string:
        nb = raw_nb / 1000
    elif 'MiB' in score_string:
        nb = raw_nb
    elif 'GiB' in score_string:
        nb = raw_nb * 1000
    else:
        # Fallback: assume MiB if unit not recognized
        print("WARNING: Unrecognized unit in score string: {}".format(score_string))
        nb = raw_nb
    return nb

def get_cpu_pct(bench):
    cpu_start = -1
    cpu_end = -1
    for line in filter(None, bench.split('\n')):

        if not line.startswith('CPU'):
            continue
        if cpu_start==-1:
            cpu_start = float(line.split(':')[-1])
        else:
            cpu_end = float(line.split(':')[-1])
    return max(cpu_start, cpu_end)

# https://stackoverflow.com/questions/19127704/how-to-read-ascii-formatted-table-in-python
def get_scores(ascii_table):
    header = []
    scores = []
    for line in filter(None, ascii_table.split('\n')):
        if not line.startswith('|'):
            continue
        if '-+-' in line or '===' in line:
            continue
        if not header:
            header = line.split('|')[1:-1]
            continue
        splitted_line = line.split('|')[1:-1]
        score_string = splitted_line[2]
        scores.append( convert_to_MiB(score_string) )
    return scores

def get_extrinsic_times(output_text):
    """Parse extrinsic benchmark output. Returns None if parsing fails."""
    times = {}

    # Helper function to safely extract a value
    def safe_extract(pattern, text):
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
        return None

    # Try to extract all values
    times['tot'] = safe_extract(r'Total:\s*(\d+)', output_text)
    times['min'] = safe_extract(r'Min:\s*(\d+)', output_text)
    times['max'] = safe_extract(r'Max:\s*(\d+)', output_text)
    times['avg'] = safe_extract(r'Average:\s*(\d+)', output_text)
    times['med'] = safe_extract(r'Median:\s*(\d+)', output_text)
    times['std'] = safe_extract(r'Stddev:\s*(\d+)', output_text)

    # Check if we got the essential values
    if times['tot'] is None or times['avg'] is None:
        # Parsing failed - output format may have changed
        return None

    # Try to extract percentiles (optional)
    pct_match = re.search(r'Percentiles 99th, 95th, 75th:\s*(\d+),\s*(\d+),\s*(\d+)', output_text)
    if pct_match:
        times['pct99'] = float(pct_match.group(1))
        times['pct95'] = float(pct_match.group(2))
        times['pct75'] = float(pct_match.group(3))
    else:
        times['pct99'] = None
        times['pct95'] = None
        times['pct75'] = None

    return times


def parse():
    output_dir = Path("output")
    processed_dir = Path("processed")
    os.makedirs(processed_dir, exist_ok=True)
    os.makedirs(processed_dir / "csv", exist_ok=True)
    os.makedirs(processed_dir / "todo", exist_ok=True)
    os.makedirs(processed_dir / "old", exist_ok=True)

    path_version_date_host = output_dir.glob("*/*/*")
    for p in path_version_date_host:
        version = p.parts[1]
        host = p.parts[2]
        date = p.parts[3]

        # read all build json files
        build_info = {}
        for f in p.glob('bench_*.json'):
            nb_build = f.stem.split("_")[1]
            with open(f, "r") as text_file:
                build_info[nb_build] = json.load(text_file)['build_options']
                # Booleans are not stored in pyarrow -- ugly translation to string
                for key, value in build_info[nb_build].items():
                    if key=='lto' and value==False:
                        build_info[nb_build]['lto'] = 'False'
        # [profile.release]
        # # Polkadot runtime requires unwinding.
        # panic = "unwind"
        # opt-level = 3
        # https://doc.rust-lang.org/rustc/codegen-options/index.html#codegen-units
        # The default value, if not specified, is 16 for non-incremental builds.
        # https://doc.rust-lang.org/rustc/codegen-options/index.html#lto
        # If -C lto is not specified, then the compiler will attempt to perform "thin local LTO"
        # which performs "thin" LTO on the local crate only across its codegen units.
        # Official binaries from polkadot-sdk releases use the production profile
        # Default production profile: lto=true, codegen-units=1, opt-level=3
        # We use approximate values here for comparison purposes
        build_info['official'] = { "toolchain": "unknown", "arch": "unknown", "codegen-units": 1,
                                    "lto": "true", "opt-level": 3 }

        # read the benchmarks
        all_data = []
        for f in p.glob('bench_*.txt'):
            nb_build = f.stem.split("_")[1]
            nb_run = int(f.stem.split("_")[3])
            ts = int(os.path.getmtime(f))
            # date = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d_%Hh%Mm')

            with open(f, "r") as text_file:
                bench = text_file.read()
                scores = get_scores(bench)

                if not scores:
                    # no benchmark table (arch not supported probably)
                    continue

                data = {"host": host, "date": date,
                    "ver": version,
                    "nb_run": nb_run, "nb_build": nb_build,
                    "cpu": get_cpu_pct(bench),
                    "BLAKE2-256": scores[0], "SR25519-Verify": scores[1],
                    "Copy": scores[2],
                    "Seq_Write": scores[3], "Rnd_Write": scores[4]}
                data.update(build_info[nb_build])

                if not all_data:
                    all_data = [data]
                else:
                    all_data.append(data)

        # save as dataframe
        df = pd.DataFrame(all_data).reset_index()
        df.to_csv(processed_dir / "csv" / "{}_{}_{}.csv".format(version, host, date), index=False)
        df.to_feather(processed_dir / "todo" / "{}_{}_{}.feather".format(version, host, date))
        print(df)

        # read the signing extrinsic
        all_data = []
        for f in p.glob('new_bench_*.txt'):
            nb_build = f.stem.split("_")[2]
            nb_run = int(f.stem.split("_")[4])
            ts = int(os.path.getmtime(f))
            # date = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d_%Hh%Mm')

            with open(f, "r") as text_file:
                bench = text_file.read()
                times = get_extrinsic_times(bench)

                if not times:
                    # Parsing failed - output format may have changed or benchmark failed
                    print("WARNING: Could not parse extrinsic benchmark: {}".format(f.name))
                    continue

                data = {"host": host, "date": date,
                    "ver": version,
                    "nb_run": nb_run, "nb_build": nb_build,
                    "cpu": get_cpu_pct(bench)}
                data.update(times)
                data.update(build_info[nb_build])

                if not all_data:
                    all_data = [data]
                else:
                    all_data.append(data)

        # save as dataframe
        df = pd.DataFrame(all_data).reset_index()
        df.to_csv(processed_dir / "csv" / "extrinsic_{}_{}_{}.csv".format(version, host, date), index=False)
        df.to_feather(processed_dir / "todo" / "extrinsic_{}_{}_{}.feather".format(version, host, date))
        print(df)

        shutil.move(p, processed_dir / "old" / version / host / date)

        # TODO remove dir if empty with bench



if __name__=="__main__":
    parse()


