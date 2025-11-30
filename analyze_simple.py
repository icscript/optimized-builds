#!/usr/bin/env python3
"""
Benchmark analysis script following math-crypto.com methodology.
Focuses on CPU scores (BLAKE2-256, SR25519-Verify) and optionally Extrinsic timing.
Disk/memory scores are ignored as optimization has little impact on them.

Usage:
    python3 analyze_simple.py processed/todo/stable2509-2_fernando-bue_2025-Nov-28_08h03.feather
"""

import sys
import os
import numpy as np
import pandas as pd


def calc_stats(df, score):
    """
    Calculate median with 95% CI error estimate (assuming normality).
    Error on median ≈ 1.25 × error on mean.
    """
    stats = df[["nb_build", score]].groupby("nb_build")[score].agg(['median', 'mean', 'sem'])
    stats['± mean'] = 1.96 * stats['sem']  # 95% CI
    stats['± median'] = 1.25 * stats['± mean']
    return stats[['median', '± median']].rename(
        columns={'median': score, '± median': f'Δ-{score}'}
    )


def analyze(feather_path):
    print(f"\n{'='*70}")
    print(f"Analyzing: {feather_path}")
    print(f"{'='*70}\n")

    # Load the data
    df = pd.read_feather(feather_path)

    # Check for extrinsic data
    extr_path = os.path.join(
        os.path.dirname(feather_path),
        "extrinsic_" + os.path.basename(feather_path)
    )
    has_extrinsic = os.path.exists(extr_path)
    df_ex = None

    if has_extrinsic:
        df_ex = pd.read_feather(extr_path)
        if len(df_ex) == 0 or 'med' not in df_ex.columns:
            has_extrinsic = False
            df_ex = None
            print("✗ Extrinsic file exists but is empty (only CPU scores will be analyzed)")
        else:
            df_ex = df_ex.rename(columns={'med': 'Extr-Remark'})
            print("✓ Extrinsic benchmark data found")
    else:
        print("✗ No extrinsic data (only CPU scores will be analyzed)")
    print()

    # CPU scores only (higher is better) - ignore disk/memory per author's methodology
    cpu_scores = ['BLAKE2-256', 'SR25519-Verify']

    # Get unique builds
    builds = sorted(df['nb_build'].unique())
    runs_per_build = df.groupby('nb_build').size()
    print(f"Found {len(builds)} builds: {builds}")
    print(f"Runs per build: {runs_per_build.iloc[0]}")

    # Check max CPU usage (high values indicate system interference)
    if 'cpu' in df.columns:
        max_cpu = df['cpu'].max()
        print(f"Max CPU interference: {max_cpu*100:.1f}%")
        if max_cpu > 0.5:
            print("  ⚠ WARNING: High CPU usage detected, results may be unreliable")
    print()

    # Calculate statistics with error estimates
    stats_list = [calc_stats(df, s) for s in cpu_scores]
    if has_extrinsic and 'Extr-Remark' in df_ex.columns:
        stats_list.append(calc_stats(df_ex, 'Extr-Remark'))

    medians = pd.concat(stats_list, axis=1)

    # Add build configuration info
    config_cols = ['toolchain', 'lto', 'codegen-units', 'opt-level', 'arch']
    available_cols = [c for c in config_cols if c in df.columns]
    config = df.groupby('nb_build')[available_cols].first()

    results = pd.concat([config, medians], axis=1)

    # Calculate improvement over official
    if 'official' in results.index:
        official = results.loc['official']
        for score in cpu_scores:
            off_val = official[score]
            results[f'{score} vs off'] = (results[score] - off_val) / off_val * 100
        if has_extrinsic and 'Extr-Remark' in results.columns:
            off_val = official['Extr-Remark']
            # For extrinsic, negative is better (less time)
            results['Extr-Remark vs off'] = (results['Extr-Remark'] - off_val) / off_val * 100

    # Sort by BLAKE2-256 performance (primary CPU benchmark)
    results = results.sort_values('BLAKE2-256', ascending=False)

    # Print results
    print("="*70)
    print("CPU BENCHMARK RESULTS (sorted by BLAKE2-256)")
    print("="*70)
    print()
    print("Note: Disk/memory scores ignored per math-crypto.com methodology")
    print("      (optimization has little impact on disk and memory scores)")
    print()

    for idx, row in results.iterrows():
        is_official = idx == 'official'
        marker = " ← baseline" if is_official else ""
        print(f"Build: {idx}{marker}")

        if 'toolchain' in row and pd.notna(row.get('toolchain')):
            print(f"  Config: {row.get('toolchain', '?')}, lto={row.get('lto', '?')}, "
                  f"codegen-units={int(row.get('codegen-units', 0)) if pd.notna(row.get('codegen-units')) else '?'}, "
                  f"opt-level={int(row.get('opt-level', 0)) if pd.notna(row.get('opt-level')) else '?'}")

        # BLAKE2-256
        blake_val = row['BLAKE2-256']
        blake_err = row.get('Δ-BLAKE2-256', 0)
        blake_diff = row.get('BLAKE2-256 vs off', 0)
        if is_official:
            print(f"  BLAKE2-256:     {blake_val:.1f} ± {blake_err:.1f} MiB/s")
        else:
            print(f"  BLAKE2-256:     {blake_val:.1f} ± {blake_err:.1f} MiB/s ({blake_diff:+.1f}%)")

        # SR25519-Verify
        sr_val = row['SR25519-Verify']
        sr_err = row.get('Δ-SR25519-Verify', 0)
        sr_diff = row.get('SR25519-Verify vs off', 0)
        if is_official:
            print(f"  SR25519-Verify: {sr_val:.1f} ± {sr_err:.1f} MiB/s")
        else:
            print(f"  SR25519-Verify: {sr_val:.1f} ± {sr_err:.1f} MiB/s ({sr_diff:+.1f}%)")

        # Extrinsic (if available) - lower is better
        if has_extrinsic and 'Extr-Remark' in row:
            ex_val = row['Extr-Remark']
            ex_err = row.get('Δ-Extr-Remark', 0)
            ex_diff = row.get('Extr-Remark vs off', 0)
            if is_official:
                print(f"  Extr-Remark:    {ex_val:.1f} ± {ex_err:.1f} ns (lower=better)")
            else:
                # Negative diff means faster (better)
                better_worse = "faster" if ex_diff < 0 else "slower"
                print(f"  Extr-Remark:    {ex_val:.1f} ± {ex_err:.1f} ns ({abs(ex_diff):.1f}% {better_worse})")

        print()

    # Summary table
    if 'official' in results.index:
        print("="*70)
        print("SUMMARY: IMPROVEMENT OVER OFFICIAL BUILD")
        print("="*70)
        print()
        print(f"{'Build':<10} {'BLAKE2-256':>12} {'SR25519-Verify':>16}", end="")
        if has_extrinsic and 'Extr-Remark' in results.columns:
            print(f" {'Extr-Remark':>14}")
        else:
            print()
        print("-" * (40 + (16 if has_extrinsic else 0)))

        for idx, row in results.iterrows():
            if idx == 'official':
                continue
            blake_diff = row.get('BLAKE2-256 vs off', 0)
            sr_diff = row.get('SR25519-Verify vs off', 0)
            print(f"{str(idx):<10} {blake_diff:>+11.1f}% {sr_diff:>+15.1f}%", end="")
            if has_extrinsic and 'Extr-Remark vs off' in row:
                ex_diff = row.get('Extr-Remark vs off', 0)
                # Negative is better for extrinsic
                print(f" {ex_diff:>+13.1f}%")
            else:
                print()
        print()
        print("(Positive = better for CPU scores, Negative = better for Extrinsic)")
        print()

    # Find best builds
    print("="*70)
    print("ANALYSIS")
    print("="*70)
    print()

    # Exclude official for ranking
    custom_builds = results[results.index != 'official'].copy() if 'official' in results.index else results.copy()

    if len(custom_builds) > 0:
        # Best for each metric
        best_blake = custom_builds['BLAKE2-256'].idxmax()
        best_sr = custom_builds['SR25519-Verify'].idxmax()

        print(f"Best BLAKE2-256:     Build {best_blake} ({custom_builds.loc[best_blake, 'BLAKE2-256']:.1f} MiB/s)")
        print(f"Best SR25519-Verify: Build {best_sr} ({custom_builds.loc[best_sr, 'SR25519-Verify']:.1f} MiB/s)")

        if has_extrinsic and 'Extr-Remark' in custom_builds.columns:
            best_ex = custom_builds['Extr-Remark'].idxmin()  # Lower is better
            print(f"Best Extr-Remark:    Build {best_ex} ({custom_builds.loc[best_ex, 'Extr-Remark']:.1f} ns)")

        print()

        # Check if any build beats official on CPU scores
        if 'official' in results.index:
            dominated = custom_builds[
                (custom_builds['BLAKE2-256 vs off'] > 0) &
                (custom_builds['SR25519-Verify vs off'] > 0)
            ]
            if len(dominated) > 0:
                print(f"Builds that beat official on BOTH CPU scores: {list(dominated.index)}")
            else:
                # Check individual improvements
                blake_better = custom_builds[custom_builds['BLAKE2-256 vs off'] > 0]
                sr_better = custom_builds[custom_builds['SR25519-Verify vs off'] > 0]
                if len(blake_better) > 0:
                    print(f"Builds better at BLAKE2-256: {list(blake_better.index)}")
                if len(sr_better) > 0:
                    print(f"Builds better at SR25519-Verify: {list(sr_better.index)}")
                if len(blake_better) == 0 and len(sr_better) == 0:
                    print("No builds beat official on CPU scores")
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
