#!/usr/bin/env python3
"""
Simple benchmark analysis script - no complex dependencies needed.
Just needs: pandas, pyarrow (for feather files)

Usage:
    python3 analyze_simple.py processed/todo/stable2509-2_fernando-bue_2025-Nov-28_08h03.feather
"""

import sys
import pandas as pd

def analyze(feather_path):
    print(f"\n{'='*60}")
    print(f"Analyzing: {feather_path}")
    print(f"{'='*60}\n")

    # Load the data
    df = pd.read_feather(feather_path)

    # Benchmark scores (higher is better for all)
    scores = ['BLAKE2-256', 'SR25519-Verify', 'Copy', 'Seq_Write', 'Rnd_Write']

    # Get unique builds
    builds = df['nb_build'].unique()
    print(f"Found {len(builds)} builds: {sorted(builds)}")
    print(f"Runs per build: {df.groupby('nb_build').size().iloc[0]}")
    print()

    # Calculate median scores per build
    summary = df.groupby('nb_build')[scores].median()

    # Add build configuration info
    config_cols = ['toolchain', 'lto', 'codegen-units', 'opt-level', 'arch']
    available_cols = [c for c in config_cols if c in df.columns]
    config = df.groupby('nb_build')[available_cols].first()

    results = pd.concat([config, summary], axis=1)

    # Calculate composite score (average of normalized scores)
    for score in scores:
        results[f'{score}_norm'] = results[score] / results[score].max() * 100

    norm_cols = [f'{s}_norm' for s in scores]
    results['composite'] = results[norm_cols].mean(axis=1)

    # Sort by composite score
    results = results.sort_values('composite', ascending=False)

    print("="*60)
    print("RESULTS - Sorted by Overall Performance (Higher = Better)")
    print("="*60)
    print()

    # Print configuration and scores for each build
    for idx, row in results.iterrows():
        print(f"Build: {idx}")
        if 'toolchain' in row:
            print(f"  Config: {row.get('toolchain', '?')}, lto={row.get('lto', '?')}, "
                  f"codegen-units={row.get('codegen-units', '?')}, opt-level={row.get('opt-level', '?')}")
        print(f"  Composite Score: {row['composite']:.1f}%")
        print(f"  BLAKE2-256:     {row['BLAKE2-256']:.1f} MiB/s")
        print(f"  SR25519-Verify: {row['SR25519-Verify']:.1f} MiB/s")
        print(f"  Copy:           {row['Copy']:.1f} MiB/s")
        print(f"  Seq_Write:      {row['Seq_Write']:.1f} MiB/s")
        print(f"  Rnd_Write:      {row['Rnd_Write']:.1f} MiB/s")
        print()

    # Compare to official
    if 'official' in results.index:
        print("="*60)
        print("IMPROVEMENT OVER OFFICIAL BUILD")
        print("="*60)
        print()
        official = results.loc['official']
        for idx, row in results.iterrows():
            if idx != 'official':
                improvements = []
                for score in scores:
                    pct = (row[score] - official[score]) / official[score] * 100
                    improvements.append(f"{score}: {pct:+.1f}%")
                print(f"Build {idx}: {', '.join(improvements)}")
        print()

    # Recommendation
    print("="*60)
    print("RECOMMENDATION")
    print("="*60)
    best = results.index[0]
    print(f"\nBest overall build: {best}")
    if best in results.index:
        row = results.loc[best]
        if 'toolchain' in row:
            print(f"Configuration: {row.get('toolchain', '?')}, lto={row.get('lto', '?')}, "
                  f"codegen-units={row.get('codegen-units', '?')}, opt-level={row.get('opt-level', '?')}")
    print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default path
        import glob
        feathers = glob.glob('processed/todo/*.feather')
        feathers = [f for f in feathers if not f.startswith('processed/todo/extrinsic')]
        if feathers:
            # Use most recent
            feathers.sort()
            path = feathers[-1]
            print(f"Using: {path}")
        else:
            print("Usage: python3 analyze_simple.py <path_to_feather_file>")
            print("Example: python3 analyze_simple.py processed/todo/stable2509-2_host_2025-Nov-28.feather")
            sys.exit(1)
    else:
        path = sys.argv[1]

    analyze(path)
