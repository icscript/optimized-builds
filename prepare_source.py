#!/usr/bin/env python3

# Copyright 2024
# GNU General Public License
#
# Script to prepare polkadot-sdk source with BLAKE2 SIMD patches.
#
# USAGE:
#   # Download and patch latest stable version
#   python prepare_source.py --version stable2509-2
#
#   # Download without patching (for comparison builds)
#   python prepare_source.py --version stable2509-2 --no-patch
#
#   # Force re-download and re-patch
#   python prepare_source.py --version stable2509-2 --force
#
# WHAT THIS DOES:
#   1. Downloads polkadot-sdk source tarball from GitHub
#   2. Copies blake2b_simd and blake2s_simd to polkadot-sdk/patched-crates/
#   3. Applies OnceLock patches (preserves hand-tuned SIMD with target-cpu=native)
#   4. Adds [patch.crates-io] section to Cargo.toml
#   5. Creates .source-info marker file with metadata
#
# AFTER RUNNING:
#   Run compile.py to build with various optimization options.

import subprocess
import os
import sys
import shutil
import json
import argparse
from datetime import datetime
from pathlib import Path

try:
    import tomlkit
except ImportError:
    print("ERROR: tomlkit not installed. Run: pip install tomlkit")
    sys.exit(1)


def prompt_yes_no(question, default=False):
    """Prompt user for yes/no answer."""
    suffix = " [y/N]: " if not default else " [Y/n]: "
    while True:
        answer = input(question + suffix).strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'")


def run_cmd(cmd, cwd=None, check=True):
    """Run a shell command."""
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ERROR: Command failed: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result


def download_source(version, base_dir, force=False):
    """Download polkadot-sdk source tarball."""
    sdk_dir = os.path.join(base_dir, "polkadot-sdk")

    # Check if already exists
    if os.path.isdir(sdk_dir):
        if force:
            print(f"Removing existing source directory: {sdk_dir}")
            shutil.rmtree(sdk_dir)
        else:
            print(f"Source directory already exists: {sdk_dir}")
            if not prompt_yes_no("Overwrite existing source?", default=False):
                print("Using existing source.")
                return sdk_dir
            shutil.rmtree(sdk_dir)

    print(f"\nDownloading polkadot-sdk version {version}...")

    # Download tarball
    tarball_url = f"https://github.com/paritytech/polkadot-sdk/archive/refs/tags/polkadot-{version}.tar.gz"
    tarball_file = os.path.join(base_dir, f"polkadot-{version}.tar.gz")

    run_cmd(f"curl -L -o {tarball_file} {tarball_url}", cwd=base_dir)

    # Extract
    print("Extracting...")
    run_cmd(f"tar -xzf {tarball_file}", cwd=base_dir)

    # Rename to polkadot-sdk
    extracted_dir = os.path.join(base_dir, f"polkadot-sdk-polkadot-{version}")
    if os.path.isdir(extracted_dir):
        shutil.move(extracted_dir, sdk_dir)
    else:
        print(f"ERROR: Expected directory not found: {extracted_dir}")
        sys.exit(1)

    # Clean up tarball
    os.remove(tarball_file)

    print(f"Source downloaded to: {sdk_dir}")
    return sdk_dir


def setup_patched_crates(sdk_dir, patches_dir):
    """Copy pre-patched blake2 crates to polkadot-sdk."""
    patched_crates_src = os.path.join(patches_dir, "blake2-patched-crates")
    patched_crates_dst = os.path.join(sdk_dir, "patched-crates")

    if not os.path.isdir(patched_crates_src):
        print(f"ERROR: Patched crates not found: {patched_crates_src}")
        print("Make sure patches/blake2-patched-crates/ exists with patched blake2b_simd and blake2s_simd")
        sys.exit(1)

    # Copy patched crates
    if os.path.isdir(patched_crates_dst):
        shutil.rmtree(patched_crates_dst)

    print(f"\nCopying patched crates to: {patched_crates_dst}")
    shutil.copytree(patched_crates_src, patched_crates_dst)

    return patched_crates_dst


def update_cargo_toml(sdk_dir):
    """Add [patch.crates-io] section to Cargo.toml."""
    cargo_toml_path = os.path.join(sdk_dir, "Cargo.toml")

    print(f"\nUpdating Cargo.toml with patch configuration...")

    # Read existing Cargo.toml
    with open(cargo_toml_path, "r") as f:
        config = tomlkit.load(f)

    # Add patch section
    if "patch" not in config:
        config["patch"] = {}
    if "crates-io" not in config["patch"]:
        config["patch"]["crates-io"] = {}

    # Add blake2 patches with relative paths
    config["patch"]["crates-io"]["blake2b_simd"] = {
        "path": "patched-crates/blake2b_simd-1.0.2"
    }
    config["patch"]["crates-io"]["blake2s_simd"] = {
        "path": "patched-crates/blake2s_simd-1.0.1"
    }

    # Write back
    with open(cargo_toml_path, "w") as f:
        tomlkit.dump(config, f)

    print("  Added [patch.crates-io] for blake2b_simd and blake2s_simd")


def create_source_info(sdk_dir, version, patched):
    """Create .source-info marker file with metadata."""
    info = {
        "version": version,
        "patched": patched,
        "patch_type": "oncelock" if patched else None,
        "prepared_at": datetime.now().isoformat(),
        "patches_applied": [
            "blake2b_simd-1.0.2 (OnceLock function pointer dispatch)",
            "blake2s_simd-1.0.1 (OnceLock function pointer dispatch)"
        ] if patched else []
    }

    info_path = os.path.join(sdk_dir, ".source-info")
    with open(info_path, "w") as f:
        json.dump(info, f, indent=2)

    print(f"\nCreated source info: {info_path}")
    return info


def check_existing_source(sdk_dir):
    """Check if source exists and return its info."""
    if not os.path.isdir(sdk_dir):
        return None

    info_path = os.path.join(sdk_dir, ".source-info")
    if os.path.exists(info_path):
        with open(info_path, "r") as f:
            return json.load(f)

    # Check Cargo.toml for patch section
    cargo_toml_path = os.path.join(sdk_dir, "Cargo.toml")
    if os.path.exists(cargo_toml_path):
        with open(cargo_toml_path, "r") as f:
            config = tomlkit.load(f)
        has_patch = "patch" in config and "crates-io" in config.get("patch", {})
        return {"version": "unknown", "patched": has_patch}

    return {"version": "unknown", "patched": False}


def main():
    parser = argparse.ArgumentParser(
        description="Prepare polkadot-sdk source with BLAKE2 SIMD patches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download and patch stable version
  %(prog)s --version stable2509-2

  # Download without patching (for comparison builds)
  %(prog)s --version stable2509-2 --no-patch

  # Force re-download
  %(prog)s --version stable2509-2 --force

  # Use existing source if present (non-interactive)
  %(prog)s --version stable2509-2 --use-existing

Why patch?
  When building with -C target-cpu=native, LTO eliminates hand-tuned BLAKE2
  AVX2 implementations due to compile-time feature detection. The OnceLock
  patch uses indirect function pointers that LTO cannot devirtualize,
  preserving the optimized code paths.

  See patches/README.md for full technical details.
        """
    )

    parser.add_argument('--version', '-v', type=str, required=True,
                        help='Polkadot version (e.g., stable2509-2)')
    parser.add_argument('--no-patch', action='store_true',
                        help='Skip patching (for comparison/baseline builds)')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Force re-download and overwrite existing source')
    parser.add_argument('--use-existing', '-e', action='store_true',
                        help='Use existing source if present (non-interactive)')
    parser.add_argument('--base-dir', type=str,
                        default=os.path.expanduser('~/optimized-builds'),
                        help='Base directory (default: ~/optimized-builds)')

    args = parser.parse_args()

    base_dir = args.base_dir
    sdk_dir = os.path.join(base_dir, "polkadot-sdk")
    patches_dir = os.path.join(base_dir, "patches")

    print("=" * 60)
    print("Polkadot SDK Source Preparation")
    print("=" * 60)
    print(f"Version: {args.version}")
    print(f"Patching: {'NO (--no-patch)' if args.no_patch else 'YES (OnceLock BLAKE2 patches)'}")
    print(f"Base directory: {base_dir}")
    print("=" * 60)

    # Check for existing source
    existing_info = check_existing_source(sdk_dir)
    if existing_info and not args.force:
        print(f"\nExisting source found:")
        print(f"  Version: {existing_info.get('version', 'unknown')}")
        print(f"  Patched: {existing_info.get('patched', False)}")

        if args.use_existing:
            print("Using existing source (--use-existing)")
            if not args.no_patch and not existing_info.get('patched'):
                print("WARNING: Existing source is not patched!")
            return
        else:
            if not prompt_yes_no("Re-download and replace?", default=False):
                print("Using existing source.")
                if not args.no_patch and not existing_info.get('patched'):
                    print("WARNING: Existing source is not patched. Consider re-running with --force")
                return

    # Download source
    sdk_dir = download_source(args.version, base_dir, force=args.force)

    # Apply patches (unless --no-patch)
    if not args.no_patch:
        if not os.path.isdir(patches_dir):
            print(f"ERROR: Patches directory not found: {patches_dir}")
            print("Make sure patches/ directory exists with blake2-patched-crates/")
            sys.exit(1)

        setup_patched_crates(sdk_dir, patches_dir)
        update_cargo_toml(sdk_dir)
    else:
        print("\nSkipping patches (--no-patch)")

    # Create source info marker
    create_source_info(sdk_dir, args.version, patched=not args.no_patch)

    # Setup rust toolchain
    print("\nSetting up Rust toolchain...")
    run_cmd("rustup override set stable", cwd=sdk_dir)
    run_cmd("rustup target add wasm32-unknown-unknown", cwd=sdk_dir)
    run_cmd("rustup component add rust-src", cwd=sdk_dir)

    # Fetch dependencies
    print("\nFetching dependencies (this may take a few minutes)...")
    run_cmd("cargo fetch", cwd=sdk_dir)

    print("\n" + "=" * 60)
    print("Source preparation complete!")
    print("=" * 60)
    print(f"\nSource directory: {sdk_dir}")
    if not args.no_patch:
        print("\nPatches applied:")
        print("  - blake2b_simd: OnceLock function pointer dispatch")
        print("  - blake2s_simd: OnceLock function pointer dispatch")
        print("\nThis preserves hand-tuned AVX2 code when building with -C target-cpu=native")
    else:
        print("\nNo patches applied. Building with -C target-cpu=native will lose")
        print("hand-tuned BLAKE2 AVX2 optimizations due to LTO.")

    print("\nNext steps:")
    print("  1. Run compile.py to build with various optimization options")
    print("  2. Run run_benchmarks.py to benchmark the builds")


if __name__ == "__main__":
    main()
